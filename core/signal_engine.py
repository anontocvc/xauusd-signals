"""
Signal Engine v4.2
==================
Fixes:
  1. Session hours corrected for BD (UTC+6):
       Tokyo/Early Asia: 18:00–01:00 UTC (12AM–7AM BD)
       Main Asia:        01:00–08:00 UTC (7AM–2PM BD)  
       London:           08:00–12:00 UTC (2PM–6PM BD)
       London/NY Overlap:12:00–13:30 UTC (6PM–7:30PM BD)
       New York:         13:30–20:00 UTC (7:30PM–2AM BD)

  2. HTF bias loosened — 4H + 1H don't need exact agreement.
     4H bearish + 1H ranging_bearish = bearish bias (locked)
     Previously this returned neutral, blocking ALL signals

  3. Phase does NOT block signals — all 4 phases can produce
     signals. Phase is shown for context only. Manipulation
     and accumulation CAN produce valid sweep setups.

  4. Score thresholds lowered slightly (was too strict for
     Yahoo Finance data quality)

  5. ATR minimum lowered (Yahoo data has lower ATR than MT5)
"""

import math, time, logging
from datetime import datetime, timezone
from core.tp_engine import find_structure_tp_levels, select_best_tps

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
ACCOUNT_BALANCE = 1000.0

RISK_PCT_MAP = {
    "sniper":     0.5,
    "high":       1.0,
    "medium":     1.5,
    "low":        0.75,
    "aggressive": 2.0,
}

FLIP_PROTECTION_CYCLES = 4   # reduced from 5 — faster response

# ── Session definitions (UTC) ─────────────────────────────────────────────────
# BD = UTC+6. All times below are UTC.
#
#  Session              UTC range       BD local time
#  ─────────────────────────────────────────────────
#  Tokyo/Early Asia     18:00–01:00     12:00AM–7:00AM  ← best Asia setup window
#  Main Asia            01:00–08:00     7:00AM–2:00PM
#  London               08:00–12:00     2:00PM–6:00PM   ← best signals
#  London/NY Overlap    12:00–13:30     6:00PM–7:30PM   ← highest volatility
#  New York             13:30–20:00     7:30PM–2:00AM   ← best signals
#  Late NY/Off          20:00–22:00     2:00AM–4:00AM   ← low quality, reduced
#  Off-hours            22:00–18:00     4:00AM–12:00AM  ← skip

def _current_session():
    h = datetime.now(timezone.utc).hour
    m = datetime.now(timezone.utc).minute

    # New York extended: 13:30–20:00 UTC
    if h == 13 and m >= 30:  return "New York"
    if 14 <= h < 20:         return "New York"

    # London/NY Overlap: 12:00–13:30 UTC
    if h == 12:              return "London/NY Overlap"
    if h == 13 and m < 30:   return "London/NY Overlap"

    # London: 08:00–12:00 UTC
    if 8 <= h < 12:          return "London"

    # Tokyo/Early Asia: 18:00 UTC previous day to 01:00 UTC
    # i.e. 18, 19, 20, 21, 22, 23 = Tokyo open
    if 18 <= h <= 23:        return "Tokyo/Early Asia"

    # Main Asia: 01:00–08:00 UTC
    if 1 <= h < 8:           return "Asian"

    # 00:00–01:00 = transition / late Tokyo
    if h == 0:               return "Tokyo/Early Asia"

    # Late NY/winding down: 20:00–22:00
    if 20 <= h < 22:         return "Late NY"

    return "Off-hours"   # 22:00–23:59 only


def _session_is_active(session):
    """All sessions except pure Off-hours produce signals."""
    return session != "Off-hours"


def _session_quality(session):
    """
    Returns (score_multiplier, min_confluence_reduction, lot_multiplier)
    Used to adjust thresholds per session.
    """
    quality_map = {
        "London":           (1.0,  0, 1.00),  # best
        "New York":         (1.0,  0, 1.00),  # best
        "London/NY Overlap":(0.95, 0, 1.00),  # very good — slightly tighter entry
        "Tokyo/Early Asia": (0.80, 1, 0.70),  # good — Tokyo institutional moves
        "Asian":            (0.80, 1, 0.70),  # moderate
        "Late NY":          (0.85, 0, 0.80),  # decent — US close moves
        "Off-hours":        (0.50, 3, 0.30),  # poor
    }
    return quality_map.get(session, (0.80, 1, 0.70))


# Score thresholds — base (London/NY). Session multiplier applied on top.
SCORE_THRESHOLDS = {
    "sniper":     8.0,   # was 8.5 — slightly more achievable
    "high":       6.5,   # was 7.0
    "medium":     5.5,   # was 6.0
    "low":        4.5,   # was 5.0
    "aggressive": 3.5,   # was 4.5
}

MIN_CONFLUENCE_BASE = {
    "sniper":     4,     # was 5
    "high":       3,     # was 4
    "medium":     3,
    "low":        2,
    "aggressive": 2,
}

# ── Shared state ───────────────────────────────────────────────────────────────
_state = {
    "htf_bias":         "neutral",
    "htf_bias_cycles":  0,
    "last_direction":   None,
    "direction_cycles": 0,
    "htf_locked_at":    0,
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def _lot_size(bal, risk_pct, sl_pips):
    risk_usd = bal * (risk_pct / 100)
    if sl_pips <= 0: return 0.01
    lot = math.floor((risk_usd / (sl_pips * 100)) * 100) / 100
    return max(0.01, min(lot, 10.0))

def _rr_label(rr):
    if rr >= 5:   return "Exceptional"
    if rr >= 4:   return "Excellent"
    if rr >= 3:   return "Very Good"
    if rr >= 2:   return "Good"
    if rr >= 1.5: return "Acceptable"
    if rr >= 1:   return "Marginal"
    return "Poor — caution"

def _has_high_news(news):
    now = datetime.now(timezone.utc)
    for ev in news:
        if ev.get("impact") != "HIGH": continue
        try:
            t = ev.get("time", "")
            if "UTC" in t:
                h, m   = int(t.split(":")[0]), int(t.split(":")[1].split()[0])
                ev_min  = h * 60 + m
                now_min = now.hour * 60 + now.minute
                if abs(now_min - ev_min) <= 30:
                    return True, ev["event"]
        except: pass
    return False, None


# ── HTF Bias — FIXED: more flexible matching ───────────────────────────────────
def _compute_htf_bias(tfs):
    """
    Determine HTF bias from 4H and 1H.

    FIXED: Previously required BOTH to say exactly 'bullish'/'bearish'.
    Now: if 4H is bearish AND 1H has ANY bearish component → bearish.
    This handles the common case where 4H=bearish, 1H=ranging_bearish.
    """
    b4h = tfs.get("4h", {}).get("bias", "neutral")
    b1h = tfs.get("1h", {}).get("bias", "neutral")
    t4h = tfs.get("4h", {}).get("trend", "neutral")
    t1h = tfs.get("1h", {}).get("trend", "neutral")

    # Strong agreement — both pure bullish
    if "bullish" in b4h and "bullish" in b1h and "bearish" not in b4h:
        return "bullish"

    # Strong agreement — both pure bearish
    if "bearish" in b4h and "bearish" in b1h and "bullish" not in b4h:
        return "bearish"

    # 4H bearish + 1H has bearish anywhere (ranging_bearish counts)
    if "bearish" in b4h and "bear" in b1h:
        return "bearish"

    # 4H bullish + 1H has bullish anywhere
    if "bullish" in b4h and "bull" in b1h:
        return "bullish"

    # Use trend as tiebreaker when bias is mixed
    if "bearish" in b4h and "bear" in t1h:
        return "bearish"
    if "bullish" in b4h and "bull" in t1h:
        return "bullish"

    # 4H strong + 1H neutral → follow 4H with 80% weight
    if "bearish" in b4h and "neutral" in b1h:
        return "bearish_weak"    # new: weak bias — still trades but lower score
    if "bullish" in b4h and "neutral" in b1h:
        return "bullish_weak"

    # Check 15M for confirmation when HTF is mixed
    b15m = tfs.get("15m", {}).get("bias", "neutral")
    if "bearish" in b4h and "bear" in b15m:
        return "bearish"
    if "bullish" in b4h and "bull" in b15m:
        return "bullish"

    return "neutral"


def _update_htf_bias(new_bias):
    global _state
    if new_bias == "neutral":
        return _state["htf_bias"]   # keep last known bias
    if new_bias == _state["htf_bias"]:
        _state["htf_bias_cycles"] += 1
        return _state["htf_bias"]
    _state["htf_bias_cycles"] += 1
    if _state["htf_bias_cycles"] >= 2:
        logger.info(f"HTF bias: {_state['htf_bias']} → {new_bias}")
        _state["htf_bias"]        = new_bias
        _state["htf_bias_cycles"] = 0
        _state["htf_locked_at"]   = time.time()
        _state["last_direction"]  = None
        _state["direction_cycles"]= 0
    return _state["htf_bias"]


# ── Market Phase ───────────────────────────────────────────────────────────────
def _detect_phase(tf1h, tf4h):
    """
    Detects AMD phase for display only.
    DOES NOT BLOCK signals — all phases can produce valid setups.

    accumulation  = price compressing, low ATR
    manipulation  = liquidity sweep detected (stop hunt setup)  ← great entry!
    retracement   = pulling back into OB/FVG after BOS          ← great entry!
    distribution  = strong trend continuation                   ← great entry!
    """
    if not tf1h: return "unknown"
    smc     = tf1h.get("smc", {})
    trend   = tf1h.get("trend", "ranging")
    atr     = tf1h.get("atr", 5)
    current = tf1h.get("current_price", 0)
    sweeps  = smc.get("sweeps", [])
    struct  = smc.get("structure_events", [])
    obs     = smc.get("order_blocks", [])
    fvgs    = smc.get("fvgs", [])
    in_zone = (any(o["low"]<=current<=o["high"] for o in obs) or
               any(f["bottom"]<=current<=f["top"] for f in fvgs))
    recent_sweep = any(s["candle_ago"] <= 3 for s in sweeps)
    has_bos      = any(e["type"]=="BOS"   for e in struct)
    has_choch    = any(e["type"]=="CHoCH" for e in struct)

    # Phase scoring — multiple conditions can be true
    if recent_sweep:               return "manipulation"   # sweep = best entry trigger
    if has_bos and in_zone:        return "retracement"
    if has_choch:                  return "retracement"
    if has_bos:                    return "distribution"
    if "ranging" in trend and atr < 6: return "accumulation"
    return "distribution" if ("strong" in trend or "bull" in trend or "bear" in trend) else "accumulation"


# ── Phase score bonus ──────────────────────────────────────────────────────────
def _phase_score_bonus(phase, direction, sweeps):
    """
    Add bonus score based on phase quality for the direction.
    manipulation + sweep = highest bonus (stop hunt before real move)
    retracement = good (OB/FVG reaction)
    distribution = ok (trend continuation)
    accumulation = small bonus (uncertain)
    """
    if phase == "manipulation":
        # Check if sweep direction matches trade direction
        for sw in sweeps:
            if direction=="BUY"  and sw["type"]=="bullish_sweep": return 1.5
            if direction=="SELL" and sw["type"]=="bearish_sweep": return 1.5
        return 0.5  # manipulation but sweep doesn't match direction yet
    if phase == "retracement":   return 1.0
    if phase == "distribution":  return 0.8
    if phase == "accumulation":  return 0.2
    return 0.0


# ── Confluence Scoring ─────────────────────────────────────────────────────────
def _score(tf_data, htf_bias, direction, phase):
    score = 0.0; confluence = []
    ind     = tf_data.get("indicators", {})
    smc     = tf_data.get("smc", {})
    current = tf_data.get("current_price", 0)
    sweeps  = smc.get("sweeps", [])
    obs     = smc.get("order_blocks", [])
    fvgs    = smc.get("fvgs", [])
    struct  = smc.get("structure_events", [])
    pd_zone = tf_data.get("premium_discount", "equilibrium")
    rsi     = ind.get("rsi", 50)
    mh      = ind.get("macd_hist", 0)
    ema8    = ind.get("ema8", 0)
    ema21   = ind.get("ema21", 0)
    vol     = ind.get("volume_ratio", 1.0)
    stoch   = ind.get("stoch_k", 50)
    willy   = ind.get("williams_r", -50)

    # ── HTF alignment (most important) ───────────────────────────────────────
    # Support weak bias too (bearish_weak / bullish_weak)
    htf_bull = "bullish" in htf_bias
    htf_bear = "bearish" in htf_bias
    htf_weak = "weak" in htf_bias

    if (htf_bull and direction=="BUY") or (htf_bear and direction=="SELL"):
        pts = 1.8 if htf_weak else 2.5   # weak bias = less points
        score += pts
        confluence.append(f"HTF bias {'weakly ' if htf_weak else ''}aligned ({htf_bias})")
    elif htf_bias == "neutral":
        # Allow neutral but very reduced score — need strong LTF to compensate
        score += 0.5
        confluence.append("HTF neutral — LTF setup only")
    else:
        # Counter-trend — heavy penalty
        score -= 2.5
        return round(score, 2), len(confluence), confluence

    # ── Phase bonus ───────────────────────────────────────────────────────────
    phase_bonus = _phase_score_bonus(phase, direction, sweeps)
    if phase_bonus > 0:
        score += phase_bonus
        confluence.append(f"Phase: {phase} (+{phase_bonus:.1f})")

    # ── Liquidity sweep ───────────────────────────────────────────────────────
    for sw in sweeps:
        if direction=="BUY"  and sw["type"]=="bullish_sweep" and sw["candle_ago"]<=3:
            score+=2.0; confluence.append(f"SSL liquidity sweep {sw['candle_ago']}c ago"); break
        if direction=="SELL" and sw["type"]=="bearish_sweep" and sw["candle_ago"]<=3:
            score+=2.0; confluence.append(f"BSL liquidity sweep {sw['candle_ago']}c ago"); break

    # ── Order block ───────────────────────────────────────────────────────────
    for ob in obs:
        in_zone = ob["low"] <= current <= ob["high"]
        near    = abs(current - ob["mid"]) / max(current,1) < 0.006
        if direction=="BUY" and ob["type"]=="bullish_ob":
            if in_zone:  score+=1.5; confluence.append(f"Inside bullish OB {ob['label']}"); break
            elif near:   score+=0.8; confluence.append(f"Near bullish OB {ob['label']}");   break
        if direction=="SELL" and ob["type"]=="bearish_ob":
            if in_zone:  score+=1.5; confluence.append(f"Inside bearish OB {ob['label']}"); break
            elif near:   score+=0.8; confluence.append(f"Near bearish OB {ob['label']}");   break

    # ── FVG ───────────────────────────────────────────────────────────────────
    for fvg in fvgs:
        in_zone = fvg["bottom"] <= current <= fvg["top"]
        if direction=="BUY"  and fvg["type"]=="bullish_fvg" and in_zone:
            score+=1.0; confluence.append(f"Inside bullish FVG {fvg['label']}"); break
        if direction=="SELL" and fvg["type"]=="bearish_fvg" and in_zone:
            score+=1.0; confluence.append(f"Inside bearish FVG {fvg['label']}"); break

    # ── BOS / CHoCH ───────────────────────────────────────────────────────────
    for ev in struct:
        if direction=="BUY" and ev["direction"]=="bullish":
            pts=1.5 if ev["type"]=="BOS" else 1.0
            score+=pts; confluence.append(f"{ev['type']} bullish: {ev.get('desc','')}"); break
        if direction=="SELL" and ev["direction"]=="bearish":
            pts=1.5 if ev["type"]=="BOS" else 1.0
            score+=pts; confluence.append(f"{ev['type']} bearish: {ev.get('desc','')}"); break

    # ── Premium / Discount ────────────────────────────────────────────────────
    if direction=="BUY"  and pd_zone=="discount":
        score+=1.0; confluence.append(f"Discount zone ({tf_data.get('pd_position_pct',0):.0f}%)")
    if direction=="SELL" and pd_zone=="premium":
        score+=1.0; confluence.append(f"Premium zone ({tf_data.get('pd_position_pct',0):.0f}%)")

    # ── Indicators ────────────────────────────────────────────────────────────
    if direction=="BUY"  and rsi < 45:   score+=0.5; confluence.append(f"RSI {rsi:.1f} oversold")
    if direction=="SELL" and rsi > 55:   score+=0.5; confluence.append(f"RSI {rsi:.1f} overbought")
    if direction=="BUY"  and mh > 0:     score+=0.5; confluence.append("MACD hist +")
    if direction=="SELL" and mh < 0:     score+=0.5; confluence.append("MACD hist −")
    if direction=="BUY"  and ema8>ema21: score+=0.5; confluence.append("EMA8 > EMA21 ▲")
    if direction=="SELL" and ema8<ema21: score+=0.5; confluence.append("EMA8 < EMA21 ▼")
    if vol >= 1.20:  score+=0.5; confluence.append(f"Volume {vol:.2f}x avg")   # lowered from 1.25
    if direction=="BUY"  and stoch < 30: score+=0.3; confluence.append(f"Stoch OS {stoch:.0f}")
    if direction=="SELL" and stoch > 70: score+=0.3; confluence.append(f"Stoch OB {stoch:.0f}")
    if direction=="BUY"  and willy < -70: score+=0.3; confluence.append(f"W%R {willy:.0f}")
    if direction=="SELL" and willy > -30: score+=0.3; confluence.append(f"W%R {willy:.0f}")

    return round(min(score, 10.0), 2), len(confluence), confluence


# ── Filter Gate ────────────────────────────────────────────────────────────────
def _apply_filters(tf_data, news, session):
    atr = tf_data.get("atr", 5)
    vol = tf_data.get("indicators", {}).get("volume_ratio", 1.0)

    # Off-hours: skip entirely
    if session == "Off-hours":
        return False, "Off-hours (22:00–00:00 UTC / 4AM–6AM BD)"

    # News filter
    blocked, ev = _has_high_news(news)
    if blocked: return False, f"HIGH news: {ev}"

    # ATR — lowered for Yahoo Finance data (lower ATR than MT5)
    # Tokyo/Asia gets lower minimum
    min_atr = {
        "Tokyo/Early Asia": 1.5,
        "Asian":            2.0,
        "Late NY":          2.0,
        "London":           2.5,
        "New York":         2.5,
        "London/NY Overlap":2.5,
    }.get(session, 2.0)

    if atr < min_atr:
        return False, f"ATR {atr:.2f} too low for {session} (min {min_atr})"

    # Extreme news spike
    if atr > 100:
        return False, f"ATR {atr:.1f} extreme — news spike, wait"

    # Volume — very relaxed for Yahoo Finance data
    min_vol = 0.3 if session in ("Tokyo/Early Asia","Asian") else 0.4
    if vol < min_vol:
        return False, f"Volume {vol:.2f}x too low (min {min_vol}x)"

    return True, "OK"


# ── Signal Builder ─────────────────────────────────────────────────────────────
def _build_signal(direction, tf_label, tf_data, tf_1h, score,
                  setup_type, confluence_list, phase, session, account_bal=1000.0):
    ind     = tf_data.get("indicators", {})
    smc     = tf_data.get("smc", {})
    current = tf_data.get("current_price", 0)
    atr     = tf_data.get("atr", 5.0)
    obs     = smc.get("order_blocks", [])

    # Session lot multiplier
    _, _, lot_mult = _session_quality(session)

    # SL: structural
    sl_mult = 1.2 if session in ("Tokyo/Early Asia","Asian") else 1.5
    atr_sl  = max(atr * sl_mult, 2.0)   # minimum 2 pip SL

    if direction == "BUY":
        ob_lows = [o["low"] for o in obs if o["type"]=="bullish_ob" and o["low"] < current]
        sl = (max(ob_lows) - atr*0.3) if ob_lows else (current - atr_sl)
        sl = min(sl, current - atr_sl)
    else:
        ob_highs = [o["high"] for o in obs if o["type"]=="bearish_ob" and o["high"] > current]
        sl = (min(ob_highs) + atr*0.3) if ob_highs else (current + atr_sl)
        sl = max(sl, current + atr_sl)

    sl      = round(sl, 2)
    sl_pips = round(abs(current - sl), 2)
    if sl_pips < 1.0: sl_pips = round(atr * 1.2, 2)

    # TP: structure-based
    tp_levels = find_structure_tp_levels(
        direction=direction, entry=current, sl=sl,
        tf_data=tf_data, tf_data_htf=tf_1h, session=session,
    )
    min_rr = 0.7 if session in ("Tokyo/Early Asia","Asian") else 1.0
    tp1_d, tp2_d, tp3_d, all_tps = select_best_tps(tp_levels, min_rr=min_rr)

    def tp_price(d, mult):
        if d: return d["price"]
        return round(current + atr*mult, 2) if direction=="BUY" else round(current - atr*mult, 2)

    tp1 = tp_price(tp1_d, 1.5)
    tp2 = tp_price(tp2_d, 2.5)
    tp3 = tp_price(tp3_d, 4.0)
    rr1 = round(abs(tp1-current)/sl_pips, 2) if sl_pips>0 else 0
    rr2 = round(abs(tp2-current)/sl_pips, 2) if sl_pips>0 else 0
    rr3 = round(abs(tp3-current)/sl_pips, 2) if sl_pips>0 else 0

    # Lot size with session multiplier
    risk_pct = round(RISK_PCT_MAP.get(setup_type, 1.0) * lot_mult, 2)
    lot      = _lot_size(account_bal, risk_pct, sl_pips)
    risk_usd = round(lot * sl_pips * 100, 2)

    # Confidence
    base_conf = {"sniper":90,"high":78,"medium":65,"low":52,"aggressive":40}
    conf = base_conf.get(setup_type, 50)
    if "weak" in _state["htf_bias"]:   conf = max(conf - 8, 30)
    if session in ("Tokyo/Early Asia","Asian"): conf = max(conf - 8, 30)

    tp_desc = [{"tp":f"TP{i}","price":d["price"],"rr":d["rr"],
                "source":d["source"],"confidence":d["confidence"],"description":d["description"]}
               for i, d in enumerate([tp1_d,tp2_d,tp3_d], 1) if d]

    sig_id = f"{direction}-{tf_label}-{round(current/5)*5}-{setup_type}"

    return {
        "id": sig_id, "direction": direction, "timeframe": tf_label,
        "setup_type": setup_type, "confidence": conf, "score": score,
        "market_phase": phase, "session": session,
        "entry": round(current,2),
        "entry_zone": f"${round(current-0.8,2)} – ${round(current+0.8,2)}",
        "sl": sl, "sl_pips": sl_pips,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rr1": rr1, "rr2": rr2, "rr3": rr3,
        "rr_label": _rr_label(rr1),
        "tp_details": tp_desc, "all_tp_levels": all_tps,
        "lot_size": lot, "risk_pct": risk_pct, "risk_usd": risk_usd,
        "confluence": confluence_list, "confluence_count": len(confluence_list),
        "indicators": {
            "rsi": ind.get("rsi",0), "macd_hist": ind.get("macd_hist",0),
            "ema8": ind.get("ema8",0), "ema21": ind.get("ema21",0),
            "stoch_k": ind.get("stoch_k",0), "williams_r": ind.get("williams_r",0),
            "volume_ratio": ind.get("volume_ratio",1), "atr": atr,
        },
        "reasons": confluence_list[:6],
        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "valid": True,
    }


# ── Main Engine ────────────────────────────────────────────────────────────────
class SignalEngine:

    def generate_signals(self, analysis, market_data, account_bal=1000.0):
        global _state
        tfs     = analysis.get("timeframes", {})
        news    = analysis.get("news", [])
        session = _current_session()
        _, _, _ = _session_quality(session)

        new_htf  = _compute_htf_bias(tfs)
        htf_bias = _update_htf_bias(new_htf)
        phase    = _detect_phase(tfs.get("1h"), tfs.get("4h"))
        tf_1h    = tfs.get("1h")
        news_blocked, news_reason = _has_high_news(news)

        # Determine candidate directions based on HTF bias
        if "bullish" in htf_bias:   directions_try = ["BUY"]
        elif "bearish" in htf_bias: directions_try = ["SELL"]
        else:                       directions_try = ["BUY","SELL"]  # neutral: try both

        candidates = []
        score_mult, min_conf_reduction, _ = _session_quality(session)

        for tf_label in ["1m","5m","15m"]:
            tf_data = tfs.get(tf_label)
            if not tf_data: continue

            passed, reason = _apply_filters(tf_data, news, session)
            if not passed:
                logger.debug(f"[{tf_label}] filtered: {reason}")
                continue

            for direction in directions_try:
                sc, conf_count, conf_list = _score(tf_data, htf_bias, direction, phase)

                # Apply session score multiplier
                effective_score = round(sc * score_mult, 2)

                # Determine setup type
                setup_type = None
                for stype in ["sniper","high","medium","low","aggressive"]:
                    thresh  = SCORE_THRESHOLDS[stype]
                    min_con = max(1, MIN_CONFLUENCE_BASE[stype] - min_conf_reduction)
                    if effective_score >= thresh and conf_count >= min_con:
                        setup_type = stype; break

                if not setup_type: continue

                # Don't trade aggressive on neutral bias
                if htf_bias == "neutral" and setup_type in ("aggressive","low"): continue

                candidates.append({
                    "direction": direction, "tf": tf_label,
                    "score": effective_score, "raw_score": sc,
                    "conf_count": conf_count, "conf_list": conf_list,
                    "setup_type": setup_type, "tf_data": tf_data,
                })

        # Flip protection
        if candidates:
            buy_sc  = sum(c["score"] for c in candidates if c["direction"]=="BUY")
            sell_sc = sum(c["score"] for c in candidates if c["direction"]=="SELL")
            dominant = "BUY" if buy_sc >= sell_sc else "SELL"

            if _state["last_direction"] and dominant != _state["last_direction"]:
                _state["direction_cycles"] += 1
                if _state["direction_cycles"] < FLIP_PROTECTION_CYCLES:
                    logger.info(f"Flip suppressed ({_state['direction_cycles']}/{FLIP_PROTECTION_CYCLES})")
                    candidates = [c for c in candidates if c["direction"]==_state["last_direction"]]
                else:
                    logger.info(f"Flip confirmed: {_state['last_direction']} → {dominant}")
                    _state["last_direction"]    = dominant
                    _state["direction_cycles"]  = 0
            else:
                _state["last_direction"]    = dominant
                _state["direction_cycles"]  = 0

        # Build signals
        signals = []
        for c in sorted(candidates, key=lambda x: (-x["score"], x["tf"])):
            sig = _build_signal(
                c["direction"], c["tf"], c["tf_data"], tf_1h,
                c["score"], c["setup_type"], c["conf_list"],
                phase, session, account_bal
            )
            if news_blocked:
                sig["news_warning"] = f"⚠ HIGH NEWS: {news_reason}"
            signals.append(sig)

        # Deduplicate same TF+direction
        seen = set(); unique = []
        for s in signals:
            k = f"{s['timeframe']}-{s['direction']}"
            if k not in seen: seen.add(k); unique.append(s)
        signals = unique[:6]

        # No-signal reason
        if not signals:
            if not _session_is_active(session):
                no_sig_reason = f"Off-hours (4AM–6AM BD time) — system resumes at 6AM BD"
            elif news_blocked:
                no_sig_reason = f"HIGH-impact news event: {news_reason}"
            elif htf_bias == "neutral":
                no_sig_reason = "HTF bias neutral — 4H and 1H disagree on direction"
            else:
                no_sig_reason = f"Score below threshold — need OB+FVG+Sweep confluence"
        else:
            no_sig_reason = ""

        best = signals[0] if signals else None
        return {
            "signals": signals,
            "summary": {
                "total_signals":    len(signals),
                "htf_bias":         htf_bias,
                "htf_bias_raw":     new_htf,
                "market_phase":     phase,
                "session":          session,
                "in_killzone":      _session_is_active(session),
                "asia_session":     session in ("Asian","Tokyo/Early Asia"),
                "tokyo_session":    session == "Tokyo/Early Asia",
                "news_blocked":     news_blocked,
                "news_reason":      news_reason or "",
                "no_signal_reason": no_sig_reason,
                "market_condition": self._market_condition(tfs),
                "flip_protection":  _state["direction_cycles"],
                "best_setup": {
                    "direction":  best["direction"], "timeframe": best["timeframe"],
                    "type":       best["setup_type"], "confidence": best["confidence"],
                    "score":      best["score"],
                } if best else None,
            }
        }

    def _market_condition(self, tfs):
        tf5 = tfs.get("5m", {})
        if not tf5: return "unknown"
        atr = tf5.get("atr", 5)
        if atr > 15: return "high_volatility"
        if atr <  3: return "low_volatility"
        trend = tf5.get("trend","ranging")
        if "strong" in trend:  return "trending_strong"
        if "ranging" in trend: return "ranging"
        return "trending"
