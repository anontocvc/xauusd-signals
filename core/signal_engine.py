"""
Signal Engine v5.0 — Multi-Timeframe Independent Signals
=========================================================
Key changes:
  1. Each TF (1M/5M/15M) analyzed independently — can give BUY or SELL
     regardless of HTF. HTF only affects score weight, not blocks direction.
  2. SL is FIXED at market structure level — never recalculated after entry.
     Stored in signal ID so same signal keeps same SL on refresh.
  3. LTF signals can counter HTF when structure is clear.
  4. Rejection Blocks + Breaker Blocks added to scoring.
  5. S/R levels used for TP targeting.
  6. Inducement detection for entry refinement.
  7. 15M uses full AMD model for entry context.
"""

import math, time, logging, hashlib
from datetime import datetime, timezone
from core.tp_engine import find_structure_tp_levels, select_best_tps

logger = logging.getLogger(__name__)

ACCOUNT_BALANCE = 1000.0

RISK_PCT_MAP = {
    "sniper": 0.5, "high": 1.0, "medium": 1.5,
    "low": 0.75,   "aggressive": 2.0,
}

FLIP_PROTECTION_CYCLES = 3   # faster response

# ── Score thresholds ───────────────────────────────────────────────────────────
SCORE_THRESHOLDS = {
    "sniper": 8.0, "high": 6.5, "medium": 5.5,
    "low": 4.5,    "aggressive": 3.5,
}
MIN_CONFLUENCE = {
    "sniper": 4, "high": 3, "medium": 3,
    "low": 2,    "aggressive": 2,
}

# ── Signal cache — keeps SL fixed between refreshes ───────────────────────────
# key = signal_id, value = {"sl": price, "entry": price, "created_at": ts}
_signal_cache = {}
_MAX_CACHE_AGE = 3600   # remove signals older than 1 hour

# ── State ──────────────────────────────────────────────────────────────────────
_state = {
    "htf_bias":         "neutral",
    "htf_bias_cycles":  0,
    "htf_locked_at":    0,
    "last_direction":   None,
    "direction_cycles": 0,
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
    return "Poor"

def _current_session():
    h = datetime.now(timezone.utc).hour
    m = datetime.now(timezone.utc).minute
    if h == 13 and m >= 30: return "New York"
    if 14 <= h < 20:        return "New York"
    if 12 <= h < 13:        return "London/NY Overlap"
    if h == 13 and m < 30:  return "London/NY Overlap"
    if 8  <= h < 12:        return "London"
    if 18 <= h <= 23:       return "Tokyo/Early Asia"
    if 1  <= h < 8:         return "Asian"
    if h == 0:              return "Tokyo/Early Asia"
    if 20 <= h < 22:        return "Late NY"
    return "Off-hours"

def _session_active(session):
    return session != "Off-hours"

def _session_lot_mult(session):
    return {"Tokyo/Early Asia":0.70,"Asian":0.70,"Late NY":0.80}.get(session, 1.0)

def _has_high_news(news):
    now = datetime.now(timezone.utc)
    for ev in news:
        if ev.get("impact") != "HIGH": continue
        try:
            t = ev.get("time","")
            if "UTC" in t:
                h,m   = int(t.split(":")[0]), int(t.split(":")[1].split()[0])
                ev_m  = h*60+m; now_m = now.hour*60+now.minute
                if abs(now_m-ev_m) <= 30: return True, ev["event"]
        except: pass
    return False, None

def _cleanup_cache():
    now = time.time()
    expired = [k for k,v in _signal_cache.items()
               if now - v.get("created_at",0) > _MAX_CACHE_AGE]
    for k in expired: del _signal_cache[k]


# ── HTF Bias ───────────────────────────────────────────────────────────────────
def _compute_htf_bias(tfs):
    b4h = tfs.get("4h",{}).get("bias","neutral")
    b1h = tfs.get("1h",{}).get("bias","neutral")
    t4h = tfs.get("4h",{}).get("trend","neutral")
    t1h = tfs.get("1h",{}).get("trend","neutral")

    if "bullish" in b4h and "bull" in b1h and "bearish" not in b4h:
        return "bullish"
    if "bearish" in b4h and "bear" in b1h and "bullish" not in b4h:
        return "bearish"
    if "bearish" in b4h and "bear" in b1h: return "bearish"
    if "bullish" in b4h and "bull" in b1h: return "bullish"
    if "bearish" in b4h and "bear" in t1h: return "bearish"
    if "bullish" in b4h and "bull" in t1h: return "bullish"
    if "bearish" in b4h and "neutral" in b1h: return "bearish_weak"
    if "bullish" in b4h and "neutral" in b1h: return "bullish_weak"
    b15m = tfs.get("15m",{}).get("bias","neutral")
    if "bearish" in b4h and "bear" in b15m: return "bearish"
    if "bullish" in b4h and "bull" in b15m: return "bullish"
    return "neutral"

def _update_htf_bias(new_bias):
    global _state
    if new_bias == "neutral": return _state["htf_bias"]
    if new_bias == _state["htf_bias"]:
        _state["htf_bias_cycles"] += 1
        return _state["htf_bias"]
    _state["htf_bias_cycles"] += 1
    if _state["htf_bias_cycles"] >= 2:
        logger.info(f"HTF bias locked: {_state['htf_bias']} → {new_bias}")
        _state["htf_bias"]        = new_bias
        _state["htf_bias_cycles"] = 0
        _state["htf_locked_at"]   = time.time()
        _state["last_direction"]  = None
        _state["direction_cycles"]= 0
    return _state["htf_bias"]


# ── AMD Phase per TF ───────────────────────────────────────────────────────────
def _detect_phase(tf_data):
    if not tf_data: return "unknown"
    smc     = tf_data.get("smc",{})
    trend   = tf_data.get("trend","ranging")
    atr     = tf_data.get("atr",5)
    current = tf_data.get("current_price",0)
    sweeps  = smc.get("sweeps",[])
    struct  = smc.get("structure_events",[])
    obs     = smc.get("order_blocks",[])
    fvgs    = smc.get("fvgs",[])
    induce  = smc.get("inducements",[])
    in_zone = (any(o["low"]<=current<=o["high"] for o in obs) or
               any(f["bottom"]<=current<=f["top"] for f in fvgs))
    recent_sweep = any(s["candle_ago"]<=3 for s in sweeps)
    has_bos      = any(e["type"]=="BOS"   for e in struct)
    has_choch    = any(e["type"]=="CHoCH" for e in struct)
    if recent_sweep:              return "manipulation"
    if induce:                    return "inducement"
    if has_bos and in_zone:       return "retracement"
    if has_choch:                 return "retracement"
    if has_bos:                   return "distribution"
    if "ranging" in trend:        return "accumulation"
    return "distribution" if ("strong" in trend or "bull" in trend or "bear" in trend) else "accumulation"


# ── LTF Structural Direction ───────────────────────────────────────────────────
def _ltf_direction(tf_data):
    """
    Determine the LTF-specific directional bias independently of HTF.
    This is what allows 1M/5M to show BUY while 15M shows SELL.
    """
    if not tf_data: return "neutral"
    smc    = tf_data.get("smc",{})
    struct = smc.get("structure_events",[])
    sweeps = smc.get("sweeps",[])
    bias   = tf_data.get("bias","neutral")
    trend  = tf_data.get("trend","neutral")
    ind    = tf_data.get("indicators",{})
    rsi    = ind.get("rsi",50)
    mh     = ind.get("macd_hist",0)
    ema8   = ind.get("ema8",0)
    ema21  = ind.get("ema21",0)

    bull_score = 0; bear_score = 0

    # Structure events (most important)
    for ev in struct:
        if ev["direction"] == "bullish":  bull_score += 3
        if ev["direction"] == "bearish":  bear_score += 3

    # Recent sweeps
    for sw in sweeps:
        if sw["type"] == "bullish_sweep" and sw["candle_ago"] <= 3: bull_score += 3
        if sw["type"] == "bearish_sweep" and sw["candle_ago"] <= 3: bear_score += 3

    # Bias/trend alignment
    if "bull" in bias:  bull_score += 2
    if "bear" in bias:  bear_score += 2
    if "bull" in trend: bull_score += 1
    if "bear" in trend: bear_score += 1

    # Indicators
    if rsi > 55:  bull_score += 1
    if rsi < 45:  bear_score += 1
    if mh > 0:    bull_score += 1
    if mh < 0:    bear_score += 1
    if ema8>ema21: bull_score += 1
    if ema8<ema21: bear_score += 1

    if bull_score > bear_score + 2:   return "bullish"
    if bear_score > bull_score + 2:   return "bearish"
    return "neutral"


# ── Comprehensive Confluence Scoring ──────────────────────────────────────────
def _score_signal(tf_data, htf_bias, direction, phase, ltf_dir, divergence):
    """
    Score a potential signal. Direction driven by LTF structure,
    HTF is a weight modifier not a blocker (except extreme counter-trend).
    """
    score = 0.0; confluence = []
    ind     = tf_data.get("indicators",{})
    smc     = tf_data.get("smc",{})
    current = tf_data.get("current_price",0)
    sweeps  = smc.get("sweeps",[])
    obs     = smc.get("order_blocks",[])
    fvgs    = smc.get("fvgs",[])
    struct  = smc.get("structure_events",[])
    rbs     = smc.get("rejection_blocks",[])
    brkrs   = smc.get("breaker_blocks",[])
    sr_lvls = smc.get("support_resistance",[])
    induce  = smc.get("inducements",[])
    pd_zone = tf_data.get("premium_discount","equilibrium")
    rsi     = ind.get("rsi",50)
    mh      = ind.get("macd_hist",0)
    ema8    = ind.get("ema8",0)
    ema21   = ind.get("ema21",0)
    vol     = ind.get("volume_ratio",1.0)
    stoch   = ind.get("stoch_k",50)
    willy   = ind.get("williams_r",-50)

    htf_bull = "bullish" in htf_bias
    htf_bear = "bearish" in htf_bias
    htf_weak = "weak"    in htf_bias

    # ── HTF alignment modifier (not a blocker) ──────────────────────────────
    if (htf_bull and direction=="BUY") or (htf_bear and direction=="SELL"):
        pts = 1.5 if htf_weak else 2.5
        score += pts
        confluence.append(f"HTF {'weak ' if htf_weak else ''}aligned ({htf_bias})")
    elif htf_bias == "neutral":
        score += 0.3
        confluence.append("HTF neutral (LTF-driven setup)")
    else:
        # Counter-HTF — allowed but heavily discounted
        # Strong LTF structure can still produce counter-HTF signals
        score -= 1.0
        confluence.append(f"Counter-HTF ({htf_bias}) — LTF override")

    # ── LTF direction alignment (key factor for 1M/5M setups) ───────────────
    if (ltf_dir == "bullish" and direction == "BUY") or \
       (ltf_dir == "bearish" and direction == "SELL"):
        score += 2.0
        confluence.append(f"LTF structure aligned ({ltf_dir})")
    elif ltf_dir == "neutral":
        score += 0.2
    else:
        score -= 0.5  # mild penalty for counter-LTF

    # ── Phase bonus ──────────────────────────────────────────────────────────
    phase_bonus = {
        "manipulation": 1.5, "inducement": 1.2,
        "retracement":  1.0, "distribution": 0.8,
        "accumulation": 0.2,
    }.get(phase, 0.0)
    # Manipulation/inducement bonus only if sweep matches direction
    if phase in ("manipulation","inducement"):
        has_matching_sweep = any(
            (direction=="BUY"  and s["type"]=="bullish_sweep") or
            (direction=="SELL" and s["type"]=="bearish_sweep")
            for s in sweeps if s["candle_ago"] <= 3
        )
        if has_matching_sweep:
            score += phase_bonus
            confluence.append(f"Phase: {phase} (+{phase_bonus:.1f})")
        else:
            score += 0.3  # small bonus even without sweep
    else:
        score += phase_bonus
        if phase_bonus > 0:
            confluence.append(f"Phase: {phase} (+{phase_bonus:.1f})")

    # ── Liquidity sweep (strongest signal) ──────────────────────────────────
    for sw in sweeps:
        if direction=="BUY"  and sw["type"]=="bullish_sweep" and sw["candle_ago"]<=3:
            score+=2.0; confluence.append(f"SSL sweep {sw['candle_ago']}c ago"); break
        if direction=="SELL" and sw["type"]=="bearish_sweep" and sw["candle_ago"]<=3:
            score+=2.0; confluence.append(f"BSL sweep {sw['candle_ago']}c ago"); break

    # ── Order block ──────────────────────────────────────────────────────────
    for ob in obs:
        in_zone = ob["low"]<=current<=ob["high"]
        near    = abs(current-ob["mid"])/max(current,1) < 0.006
        if direction=="BUY" and ob["type"]=="bullish_ob":
            if in_zone:  score+=1.5; confluence.append(f"Inside bull OB {ob['label']}"); break
            elif near:   score+=0.8; confluence.append(f"Near bull OB {ob['label']}");   break
        if direction=="SELL" and ob["type"]=="bearish_ob":
            if in_zone:  score+=1.5; confluence.append(f"Inside bear OB {ob['label']}"); break
            elif near:   score+=0.8; confluence.append(f"Near bear OB {ob['label']}");   break

    # ── Rejection Block (NEW) ────────────────────────────────────────────────
    for rb in rbs:
        if direction=="BUY"  and rb["type"]=="bullish_rb":
            if abs(current-rb["level"])/max(current,1) < 0.005:
                score+=1.2; confluence.append(f"Bullish RB {rb['label']}"); break
        if direction=="SELL" and rb["type"]=="bearish_rb":
            if abs(current-rb["level"])/max(current,1) < 0.005:
                score+=1.2; confluence.append(f"Bearish RB {rb['label']}"); break

    # ── Breaker Block (NEW) ──────────────────────────────────────────────────
    for bb in brkrs:
        if direction=="BUY"  and bb["type"]=="bullish_breaker":
            if abs(current-bb["level"])/max(current,1) < 0.008:
                score+=1.3; confluence.append(f"Bullish Breaker {bb['label']}"); break
        if direction=="SELL" and bb["type"]=="bearish_breaker":
            if abs(current-bb["level"])/max(current,1) < 0.008:
                score+=1.3; confluence.append(f"Bearish Breaker {bb['label']}"); break

    # ── FVG ──────────────────────────────────────────────────────────────────
    for fvg in fvgs:
        in_zone = fvg["bottom"]<=current<=fvg["top"]
        if direction=="BUY"  and fvg["type"]=="bullish_fvg" and in_zone:
            score+=1.0; confluence.append(f"Inside bull FVG {fvg['label']}"); break
        if direction=="SELL" and fvg["type"]=="bearish_fvg" and in_zone:
            score+=1.0; confluence.append(f"Inside bear FVG {fvg['label']}"); break

    # ── BOS / CHoCH ──────────────────────────────────────────────────────────
    for ev in struct:
        if direction=="BUY" and ev["direction"]=="bullish":
            pts=1.5 if ev["type"]=="BOS" else 1.2
            score+=pts; confluence.append(f"{ev['type']} bullish: {ev.get('desc','')}"); break
        if direction=="SELL" and ev["direction"]=="bearish":
            pts=1.5 if ev["type"]=="BOS" else 1.2
            score+=pts; confluence.append(f"{ev['type']} bearish: {ev.get('desc','')}"); break

    # ── Support / Resistance (NEW) ───────────────────────────────────────────
    for sr in sr_lvls[:4]:
        if direction=="BUY" and sr["type"] in ("support","bullish_breaker") and sr["side"]=="below":
            if abs(current-sr["level"])/max(current,1) < 0.008:
                score+=0.8; confluence.append(f"S/R support: {sr['label']}"); break
        if direction=="SELL" and sr["type"] in ("resistance","bearish_breaker") and sr["side"]=="above":
            if abs(current-sr["level"])/max(current,1) < 0.008:
                score+=0.8; confluence.append(f"S/R resistance: {sr['label']}"); break

    # ── Inducement (NEW) ─────────────────────────────────────────────────────
    for ind_ev in induce:
        if direction=="BUY"  and ind_ev["type"]=="bullish_inducement":
            score+=0.8; confluence.append(f"Inducement: {ind_ev['label']}"); break
        if direction=="SELL" and ind_ev["type"]=="bearish_inducement":
            score+=0.8; confluence.append(f"Inducement: {ind_ev['label']}"); break

    # ── Premium/Discount ─────────────────────────────────────────────────────
    if direction=="BUY"  and pd_zone=="discount":
        score+=0.8; confluence.append(f"Discount zone ({tf_data.get('pd_position_pct',0):.0f}%)")
    if direction=="SELL" and pd_zone=="premium":
        score+=0.8; confluence.append(f"Premium zone ({tf_data.get('pd_position_pct',0):.0f}%)")

    # ── Indicators ───────────────────────────────────────────────────────────
    if direction=="BUY"  and rsi < 45:   score+=0.5; confluence.append(f"RSI {rsi:.1f} OS")
    if direction=="SELL" and rsi > 55:   score+=0.5; confluence.append(f"RSI {rsi:.1f} OB")
    if direction=="BUY"  and mh > 0:     score+=0.4; confluence.append("MACD hist +")
    if direction=="SELL" and mh < 0:     score+=0.4; confluence.append("MACD hist −")
    if direction=="BUY"  and ema8>ema21: score+=0.4; confluence.append("EMA8 > EMA21")
    if direction=="SELL" and ema8<ema21: score+=0.4; confluence.append("EMA8 < EMA21")
    if vol >= 1.20:  score+=0.4; confluence.append(f"Vol {vol:.2f}x")
    if direction=="BUY"  and stoch<30: score+=0.3; confluence.append(f"Stoch OS {stoch:.0f}")
    if direction=="SELL" and stoch>70: score+=0.3; confluence.append(f"Stoch OB {stoch:.0f}")
    if direction=="BUY"  and willy<-70: score+=0.3; confluence.append(f"W%R {willy:.0f}")
    if direction=="SELL" and willy>-30: score+=0.3; confluence.append(f"W%R {willy:.0f}")

    return round(min(score,10.0),2), len(confluence), confluence


# ── Fixed SL Calculation ───────────────────────────────────────────────────────
def _calculate_fixed_sl(direction, current, tf_data, sig_id):
    """
    Calculate SL ONCE and cache it. On refresh, return the same SL.
    SL is placed at the STRUCTURAL invalidation level:
    - Below the nearest bullish OB low (for BUY)
    - Above the nearest bearish OB high (for SELL)
    - Or at 1.5× ATR if no OB found
    SL NEVER moves once set (until signal expires after 1 hour).
    """
    _cleanup_cache()

    # Return cached SL if this signal was seen before
    if sig_id in _signal_cache:
        cached = _signal_cache[sig_id]
        logger.debug(f"Using cached SL for {sig_id}: ${cached['sl']}")
        return cached["sl"], cached["entry"]

    # Calculate new SL at structural level
    smc  = tf_data.get("smc",{})
    obs  = smc.get("order_blocks",[])
    rbs  = smc.get("rejection_blocks",[])
    atr  = tf_data.get("atr", 5.0)
    sr   = smc.get("support_resistance",[])

    sl_candidates = []

    if direction == "BUY":
        # Below nearest bullish OB
        for ob in obs:
            if ob["type"]=="bullish_ob" and ob["low"] < current:
                sl_candidates.append(round(ob["low"] - atr*0.2, 2))
        # Below nearest S/R support
        for s in sr:
            if s["type"]=="support" and s["level"] < current:
                sl_candidates.append(round(s["level"] - atr*0.15, 2))
        # Below nearest bullish RB
        for rb in rbs:
            if rb["type"]=="bullish_rb" and rb["low"] < current:
                sl_candidates.append(round(rb["low"] - atr*0.15, 2))
        # Default: 1.5× ATR below
        sl_candidates.append(round(current - atr*1.5, 2))
        # Choose: highest SL below current (closest structural invalidation)
        valid = [s for s in sl_candidates if s < current - atr*0.5]
        sl = max(valid) if valid else round(current - atr*1.5, 2)

    else:  # SELL
        for ob in obs:
            if ob["type"]=="bearish_ob" and ob["high"] > current:
                sl_candidates.append(round(ob["high"] + atr*0.2, 2))
        for s in sr:
            if s["type"]=="resistance" and s["level"] > current:
                sl_candidates.append(round(s["level"] + atr*0.15, 2))
        for rb in rbs:
            if rb["type"]=="bearish_rb" and rb["high"] > current:
                sl_candidates.append(round(rb["high"] + atr*0.15, 2))
        sl_candidates.append(round(current + atr*1.5, 2))
        valid = [s for s in sl_candidates if s > current + atr*0.5]
        sl = min(valid) if valid else round(current + atr*1.5, 2)

    # Cache this SL so it never changes during the signal's lifetime
    _signal_cache[sig_id] = {
        "sl":         sl,
        "entry":      round(current, 2),
        "created_at": time.time(),
        "direction":  direction,
    }
    logger.info(f"New signal SL set: {sig_id} → ${sl} (entry ${current:.2f})")
    return sl, round(current, 2)


# ── Build signal ───────────────────────────────────────────────────────────────
def _build_signal(direction, tf_label, tf_data, tf_1h, score,
                  setup_type, confluence_list, phase, session,
                  htf_bias, ltf_dir, account_bal=1000.0):

    ind     = tf_data.get("indicators",{})
    current = tf_data.get("current_price",0)
    atr     = tf_data.get("atr",5.0)

    # Generate stable signal ID (based on entry zone, not exact price)
    # Rounded to nearest $5 — same signal persists through minor price moves
    price_bucket = round(current / 5) * 5
    raw_id  = f"{direction}-{tf_label}-{price_bucket}-{setup_type}"
    sig_id  = hashlib.md5(raw_id.encode()).hexdigest()[:12]

    # Get fixed SL (from cache or new calculation)
    sl, entry_price = _calculate_fixed_sl(direction, current, tf_data, sig_id)
    sl_pips = round(abs(current - sl), 2)
    if sl_pips < 1.0: sl_pips = round(atr * 1.2, 2)

    # TP from structure
    tp_levels = find_structure_tp_levels(
        direction=direction, entry=current, sl=sl,
        tf_data=tf_data, tf_data_htf=tf_1h, session=session,
    )
    min_rr = 0.7 if session in ("Tokyo/Early Asia","Asian") else 1.0
    tp1_d, tp2_d, tp3_d, all_tps = select_best_tps(tp_levels, min_rr=min_rr)

    def tp_p(d, mult):
        if d: return d["price"]
        return round(current+atr*mult,2) if direction=="BUY" else round(current-atr*mult,2)

    tp1=tp_p(tp1_d,1.5); tp2=tp_p(tp2_d,2.5); tp3=tp_p(tp3_d,4.0)
    rr1=round(abs(tp1-current)/sl_pips,2) if sl_pips>0 else 0
    rr2=round(abs(tp2-current)/sl_pips,2) if sl_pips>0 else 0
    rr3=round(abs(tp3-current)/sl_pips,2) if sl_pips>0 else 0

    # Lot size with session multiplier
    lot_mult = _session_lot_mult(session)
    risk_pct = round(RISK_PCT_MAP.get(setup_type,1.0) * lot_mult, 2)
    lot      = _lot_size(account_bal, risk_pct, sl_pips)
    risk_usd = round(lot * sl_pips * 100, 2)

    # Confidence
    base_conf = {"sniper":90,"high":78,"medium":65,"low":52,"aggressive":40}
    conf = base_conf.get(setup_type,50)
    if "weak" in htf_bias:  conf = max(conf-8, 30)
    if session in ("Tokyo/Early Asia","Asian"): conf = max(conf-8, 30)
    # Counter-HTF setups shown with lower confidence
    htf_aligned = ("bull" in htf_bias and direction=="BUY") or \
                  ("bear" in htf_bias and direction=="SELL")
    if not htf_aligned and htf_bias!="neutral":
        conf = max(conf-12, 25)

    tp_desc = [{"tp":f"TP{i}","price":d["price"],"rr":d["rr"],
                "source":d["source"],"confidence":d["confidence"],"description":d["description"]}
               for i,d in enumerate([tp1_d,tp2_d,tp3_d],1) if d]

    return {
        "id":              sig_id,
        "direction":       direction,
        "timeframe":       tf_label,
        "setup_type":      setup_type,
        "confidence":      conf,
        "score":           score,
        "market_phase":    phase,
        "session":         session,
        "htf_bias":        htf_bias,
        "ltf_direction":   ltf_dir,
        "htf_aligned":     htf_aligned,
        "entry":           round(current,2),
        "entry_price_used":entry_price,
        "entry_zone":      f"${round(current-0.8,2)} – ${round(current+0.8,2)}",
        "sl":              sl,
        "sl_pips":         sl_pips,
        "sl_note":         "Fixed at structural level — do not move",
        "tp1":tp1,"tp2":tp2,"tp3":tp3,
        "rr1":rr1,"rr2":rr2,"rr3":rr3,
        "rr_label":        _rr_label(rr1),
        "tp_details":      tp_desc,
        "all_tp_levels":   all_tps,
        "lot_size":        lot,
        "risk_pct":        risk_pct,
        "risk_usd":        risk_usd,
        "confluence":      confluence_list,
        "confluence_count":len(confluence_list),
        "indicators": {
            "rsi":ind.get("rsi",0),"macd_hist":ind.get("macd_hist",0),
            "ema8":ind.get("ema8",0),"ema21":ind.get("ema21",0),
            "stoch_k":ind.get("stoch_k",0),"williams_r":ind.get("williams_r",0),
            "volume_ratio":ind.get("volume_ratio",1),"atr":atr,
        },
        "reasons":   confluence_list[:7],
        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "valid":     True,
    }


# ── Filter ─────────────────────────────────────────────────────────────────────
def _filter(tf_data, news, session):
    atr = tf_data.get("atr",5)
    vol = tf_data.get("indicators",{}).get("volume_ratio",1.0)
    if session == "Off-hours":
        return False, "Off-hours (4AM–6AM BD)"
    blocked, ev = _has_high_news(news)
    if blocked: return False, f"HIGH news: {ev}"
    min_atr = {"Tokyo/Early Asia":1.5,"Asian":2.0,"Late NY":2.0}.get(session,2.0)
    if atr < min_atr: return False, f"ATR {atr:.2f} < {min_atr}"
    if atr > 120: return False, f"ATR {atr:.1f} spike"
    min_vol = 0.3 if session in ("Tokyo/Early Asia","Asian") else 0.35
    if vol < min_vol: return False, f"Vol {vol:.2f}x < {min_vol}x"
    return True, "OK"


# ── Main engine ────────────────────────────────────────────────────────────────
class SignalEngine:

    def generate_signals(self, analysis, market_data, account_bal=1000.0):
        global _state
        tfs        = analysis.get("timeframes",{})
        news       = analysis.get("news",[])
        session    = _current_session()
        divergence = analysis.get("htf_ltf_divergence", False)
        ltf_consensus = analysis.get("ltf_consensus","mixed")

        new_htf  = _compute_htf_bias(tfs)
        htf_bias = _update_htf_bias(new_htf)
        tf_1h    = tfs.get("1h")
        news_blocked, news_reason = _has_high_news(news)

        candidates = []

        for tf_label in ["1m","5m","15m"]:
            tf_data = tfs.get(tf_label)
            if not tf_data: continue

            passed, reason = _filter(tf_data, news, session)
            if not passed:
                logger.debug(f"[{tf_label}] filtered: {reason}")
                continue

            # Get LTF-specific direction
            ltf_dir = _ltf_direction(tf_data)
            phase   = _detect_phase(tf_data)

            # Determine candidate directions for this TF
            # Each TF can independently suggest BUY or SELL
            directions_to_try = []

            if ltf_dir == "bullish":
                directions_to_try = ["BUY"]
            elif ltf_dir == "bearish":
                directions_to_try = ["SELL"]
            else:
                # Neutral LTF — use HTF bias
                if "bullish" in htf_bias:  directions_to_try = ["BUY"]
                elif "bearish" in htf_bias:directions_to_try = ["SELL"]
                else:                      directions_to_try = ["BUY","SELL"]

            # On divergence — try both directions for full picture
            if divergence and tf_label == "15m":
                directions_to_try = ["BUY","SELL"]

            for direction in directions_to_try:
                sc, conf_count, conf_list = _score_signal(
                    tf_data, htf_bias, direction, phase, ltf_dir, divergence
                )

                # Session score multiplier
                sm = {"Tokyo/Early Asia":0.85,"Asian":0.85,"Late NY":0.90}.get(session,1.0)
                effective_sc = round(sc * sm, 2)

                setup_type = None
                for stype in ["sniper","high","medium","low","aggressive"]:
                    if effective_sc >= SCORE_THRESHOLDS[stype] and conf_count >= MIN_CONFLUENCE[stype]:
                        setup_type = stype; break

                if not setup_type: continue

                # On HTF/LTF divergence, cap counter-HTF signals at MEDIUM
                htf_aligned = ("bull" in htf_bias and direction=="BUY") or \
                              ("bear" in htf_bias and direction=="SELL")
                if not htf_aligned and htf_bias != "neutral":
                    if setup_type in ("sniper","high"): setup_type = "medium"

                candidates.append({
                    "direction":  direction, "tf": tf_label,
                    "score":      effective_sc, "raw_score": sc,
                    "conf_count": conf_count, "conf_list": conf_list,
                    "setup_type": setup_type, "tf_data": tf_data,
                    "phase":      phase, "ltf_dir": ltf_dir,
                    "htf_aligned":htf_aligned,
                })

        # Flip protection (only for HTF-aligned signals)
        htf_cands = [c for c in candidates if c["htf_aligned"]]
        if htf_cands:
            buy_sc  = sum(c["score"] for c in htf_cands if c["direction"]=="BUY")
            sell_sc = sum(c["score"] for c in htf_cands if c["direction"]=="SELL")
            dominant = "BUY" if buy_sc >= sell_sc else "SELL"
            if _state["last_direction"] and dominant != _state["last_direction"]:
                _state["direction_cycles"] += 1
                if _state["direction_cycles"] < FLIP_PROTECTION_CYCLES:
                    logger.info(f"Flip suppressed ({_state['direction_cycles']}/{FLIP_PROTECTION_CYCLES})")
                else:
                    logger.info(f"Flip confirmed: {_state['last_direction']} → {dominant}")
                    _state["last_direction"]    = dominant
                    _state["direction_cycles"]  = 0
            else:
                _state["last_direction"]    = dominant
                _state["direction_cycles"]  = 0

        # Build signal objects
        signals = []
        for c in sorted(candidates, key=lambda x: (-x["score"], x["tf"])):
            sig = _build_signal(
                c["direction"], c["tf"], c["tf_data"], tf_1h,
                c["score"], c["setup_type"], c["conf_list"],
                c["phase"], session, htf_bias, c["ltf_dir"], account_bal
            )
            if news_blocked:
                sig["news_warning"] = f"HIGH NEWS: {news_reason}"
            signals.append(sig)

        # Deduplicate: keep best per TF+direction combo
        seen = set(); unique = []
        for s in signals:
            k = f"{s['timeframe']}-{s['direction']}"
            if k not in seen: seen.add(k); unique.append(s)
        signals = unique[:8]

        # No-signal reason
        if not signals:
            if not _session_active(session):
                no_sig = "Off-hours (4AM–6AM BD)"
            elif news_blocked:
                no_sig = f"HIGH NEWS paused: {news_reason}"
            elif htf_bias == "neutral" and ltf_consensus == "mixed":
                no_sig = "HTF neutral + LTF mixed — no clear direction"
            else:
                no_sig = f"Score below threshold — need OB/RB/BB + FVG/Sweep + BOS/CHoCH confluence"
        else:
            no_sig = ""

        best = next((s for s in signals if s["htf_aligned"]), signals[0] if signals else None)
        return {
            "signals": signals,
            "summary": {
                "total_signals":    len(signals),
                "htf_aligned":      sum(1 for s in signals if s["htf_aligned"]),
                "counter_htf":      sum(1 for s in signals if not s["htf_aligned"]),
                "htf_bias":         htf_bias,
                "htf_bias_raw":     new_htf,
                "ltf_consensus":    ltf_consensus,
                "divergence":       divergence,
                "market_phase":     _detect_phase(tfs.get("15m") or tfs.get("5m")),
                "session":          session,
                "in_killzone":      _session_active(session),
                "asia_session":     session in ("Asian","Tokyo/Early Asia"),
                "tokyo_session":    session == "Tokyo/Early Asia",
                "news_blocked":     news_blocked,
                "news_reason":      news_reason or "",
                "no_signal_reason": no_sig,
                "market_condition": self._mkt_cond(tfs),
                "flip_protection":  _state["direction_cycles"],
                "best_setup": {
                    "direction":  best["direction"],"timeframe": best["timeframe"],
                    "type":       best["setup_type"],"confidence": best["confidence"],
                    "score":      best["score"],
                } if best else None,
            }
        }

    def _mkt_cond(self, tfs):
        tf5 = tfs.get("5m",{})
        if not tf5: return "unknown"
        atr   = tf5.get("atr",5)
        trend = tf5.get("trend","ranging")
        if atr > 15: return "high_volatility"
        if atr <  3: return "low_volatility"
        if "strong" in trend:  return "trending_strong"
        if "ranging" in trend: return "ranging"
        return "trending"
