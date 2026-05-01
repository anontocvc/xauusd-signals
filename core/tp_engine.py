"""
TP Engine — Structure-Based Take Profit Calculator
===================================================
Every TP level is derived from REAL market structure:
  - Nearest unmitigated Order Blocks
  - Unfilled Fair Value Gaps
  - Liquidity pools (equal highs/lows, stop clusters)
  - Previous swing highs/lows
  - Premium/Discount zone boundaries
  - Pivot points (R1, R2, S1, S2)

RR is DISCOVERED from market, not imposed blindly.
Result: TP1 might be 1:0.8 (tight) or 1:6 (wide) depending
on actual structure ahead of price. You see WHY each TP exists.
"""

import logging
import math

logger = logging.getLogger(__name__)

# ── Session volatility expectations ─────────────────────────────────────────
SESSION_ATR_MULTIPLIER = {
    "London":          1.00,   # most volatile — standard ATR
    "New York":        1.00,
    "London/NY Overlap": 1.10, # extra volatile overlap
    "Asian":           0.55,   # lower volatility — tighter realistic TPs
    "Off-hours":       0.45,
}

# How far ahead to scan for structure (as % of current price)
SCAN_RANGE_PCT = 0.025   # scan ±2.5% from current price for TP candidates


def find_structure_tp_levels(
    direction:    str,
    entry:        float,
    sl:           float,
    tf_data:      dict,
    tf_data_htf:  dict,   # 1H data for bigger structure targets
    session:      str = "London",
) -> list:
    """
    Find all valid TP levels derived from market structure.

    Returns a list of TP dicts, each with:
      - price       : the exact TP price
      - rr          : risk-reward ratio vs SL
      - source      : what structure created this level
      - confidence  : 1-3 (how strong/reliable the level is)
      - description : human-readable reason

    Sorted from nearest to furthest.
    """
    sl_dist  = abs(entry - sl)
    if sl_dist <= 0:
        return []

    scan_max = entry * SCAN_RANGE_PCT
    candidates = []

    # Pull data from current TF
    smc_ltf  = tf_data.get("smc", {})
    smc_htf  = (tf_data_htf or {}).get("smc", {})
    lvl_ltf  = tf_data.get("levels", {})
    lvl_htf  = (tf_data_htf or {}).get("levels", {})
    price    = tf_data.get("current_price", entry)
    atr      = tf_data.get("atr", 5.0)
    pd_pct   = tf_data.get("pd_position_pct", 50)

    # Session ATR multiplier
    atr_mult = SESSION_ATR_MULTIPLIER.get(session, 1.0)
    # Minimum TP distance = 0.5 × ATR (don't set TP inside noise)
    min_dist = atr * atr_mult * 0.5

    # ── 1. Opposite Order Blocks ─────────────────────────────────────────────
    for ob in (smc_ltf.get("order_blocks", []) + smc_htf.get("order_blocks", [])):
        ob_mid = ob.get("mid", (ob["high"] + ob["low"]) / 2)
        if direction == "BUY":
            # Bearish OB above price = resistance = TP target
            if ob["type"] == "bearish_ob" and ob_mid > entry:
                dist = ob_mid - entry
                if dist >= min_dist:
                    candidates.append({
                        "price":       round(ob_mid, 2),
                        "rr":          round(dist / sl_dist, 2),
                        "source":      "OB",
                        "confidence":  3,
                        "description": f"Bearish OB resistance ${ob['low']:.2f}–${ob['high']:.2f}"
                    })
        else:
            # Bullish OB below price = support = TP target
            if ob["type"] == "bullish_ob" and ob_mid < entry:
                dist = entry - ob_mid
                if dist >= min_dist:
                    candidates.append({
                        "price":       round(ob_mid, 2),
                        "rr":          round(dist / sl_dist, 2),
                        "source":      "OB",
                        "confidence":  3,
                        "description": f"Bullish OB support ${ob['low']:.2f}–${ob['high']:.2f}"
                    })

    # ── 2. Fair Value Gaps (unfilled) ────────────────────────────────────────
    for fvg in (smc_ltf.get("fvgs", []) + smc_htf.get("fvgs", [])):
        fvg_mid = fvg.get("mid", (fvg["top"] + fvg["bottom"]) / 2)
        if direction == "BUY":
            # Bearish FVG above = needs to be filled = TP
            if fvg["type"] == "bearish_fvg" and fvg_mid > entry:
                dist = fvg_mid - entry
                if dist >= min_dist:
                    candidates.append({
                        "price":       round(fvg_mid, 2),
                        "rr":          round(dist / sl_dist, 2),
                        "source":      "FVG",
                        "confidence":  2,
                        "description": f"Bearish FVG fill target ${fvg['bottom']:.2f}–${fvg['top']:.2f}"
                    })
        else:
            # Bullish FVG below = needs to be filled = TP
            if fvg["type"] == "bullish_fvg" and fvg_mid < entry:
                dist = entry - fvg_mid
                if dist >= min_dist:
                    candidates.append({
                        "price":       round(fvg_mid, 2),
                        "rr":          round(dist / sl_dist, 2),
                        "source":      "FVG",
                        "confidence":  2,
                        "description": f"Bullish FVG fill target ${fvg['top']:.2f}–${fvg['bottom']:.2f}"
                    })

    # ── 3. Liquidity pools (equal highs/lows, stop clusters) ────────────────
    for lz in (smc_ltf.get("liquidity_zones", []) + smc_htf.get("liquidity_zones", [])):
        lvl = lz.get("level", 0)
        if direction == "BUY" and lvl > entry:
            dist = lvl - entry
            if dist >= min_dist:
                candidates.append({
                    "price":       round(lvl, 2),
                    "rr":          round(dist / sl_dist, 2),
                    "source":      "LIQ",
                    "confidence":  3,
                    "description": f"Liquidity target: {lz.get('label','BSL')} ${lvl:.2f}"
                })
        elif direction == "SELL" and lvl < entry:
            dist = entry - lvl
            if dist >= min_dist:
                candidates.append({
                    "price":       round(lvl, 2),
                    "rr":          round(dist / sl_dist, 2),
                    "source":      "LIQ",
                    "confidence":  3,
                    "description": f"Liquidity target: {lz.get('label','SSL')} ${lvl:.2f}"
                })

    # ── 4. Previous swing highs/lows ─────────────────────────────────────────
    r_high = lvl_ltf.get("recent_high", 0)
    r_low  = lvl_ltf.get("recent_low",  0)
    r_high_htf = lvl_htf.get("recent_high", 0) if lvl_htf else 0
    r_low_htf  = lvl_htf.get("recent_low", 0)  if lvl_htf else 0

    for level, label, conf in [
        (r_high,     "LTF swing high",  2),
        (r_high_htf, "HTF swing high",  3),
        (r_low,      "LTF swing low",   2),
        (r_low_htf,  "HTF swing low",   3),
    ]:
        if level <= 0: continue
        if direction == "BUY" and level > entry:
            dist = level - entry
            if dist >= min_dist:
                candidates.append({
                    "price": round(level, 2), "rr": round(dist/sl_dist, 2),
                    "source": "SWING", "confidence": conf,
                    "description": f"{label} ${level:.2f}"
                })
        elif direction == "SELL" and level < entry:
            dist = entry - level
            if dist >= min_dist:
                candidates.append({
                    "price": round(level, 2), "rr": round(dist/sl_dist, 2),
                    "source": "SWING", "confidence": conf,
                    "description": f"{label} ${level:.2f}"
                })

    # ── 5. Pivot points (R1, R2, S1, S2) ────────────────────────────────────
    pivot = lvl_ltf.get("pivot", 0)
    r1    = lvl_ltf.get("r1", 0)
    s1    = lvl_ltf.get("s1", 0)

    for level, label in [(r1,"R1"), (s1,"S1"), (pivot,"Pivot")]:
        if level <= 0: continue
        if direction == "BUY" and level > entry:
            dist = level - entry
            if dist >= min_dist:
                candidates.append({
                    "price": round(level, 2), "rr": round(dist/sl_dist, 2),
                    "source": "PIVOT", "confidence": 2,
                    "description": f"Pivot {label} ${level:.2f}"
                })
        elif direction == "SELL" and level < entry:
            dist = entry - level
            if dist >= min_dist:
                candidates.append({
                    "price": round(level, 2), "rr": round(dist/sl_dist, 2),
                    "source": "PIVOT", "confidence": 2,
                    "description": f"Pivot {label} ${level:.2f}"
                })

    # ── 6. Premium/Discount zone boundaries ──────────────────────────────────
    if r_high > 0 and r_low > 0:
        equilibrium = (r_high + r_low) / 2
        if direction == "BUY" and equilibrium > entry:
            dist = equilibrium - entry
            if dist >= min_dist:
                candidates.append({
                    "price": round(equilibrium, 2), "rr": round(dist/sl_dist, 2),
                    "source": "ZONE", "confidence": 1,
                    "description": f"Equilibrium (50%) ${equilibrium:.2f}"
                })
        elif direction == "SELL" and equilibrium < entry:
            dist = entry - equilibrium
            if dist >= min_dist:
                candidates.append({
                    "price": round(equilibrium, 2), "rr": round(dist/sl_dist, 2),
                    "source": "ZONE", "confidence": 1,
                    "description": f"Equilibrium (50%) ${equilibrium:.2f}"
                })

    # ── 7. ATR extension levels as absolute fallback ─────────────────────────
    # Only added if fewer than 3 structure levels found
    if len(candidates) < 3:
        for mult, label in [(1.5,"1.5×ATR"), (2.5,"2.5×ATR"), (4.0,"4.0×ATR")]:
            ext = atr * mult * atr_mult
            if direction == "BUY":
                price_tgt = round(entry + ext, 2)
                if price_tgt > entry + min_dist:
                    candidates.append({
                        "price": price_tgt, "rr": round(ext/sl_dist, 2),
                        "source": "ATR", "confidence": 1,
                        "description": f"{label} extension ${price_tgt:.2f} (no structure found nearby)"
                    })
            else:
                price_tgt = round(entry - ext, 2)
                if price_tgt < entry - min_dist:
                    candidates.append({
                        "price": price_tgt, "rr": round(ext/sl_dist, 2),
                        "source": "ATR", "confidence": 1,
                        "description": f"{label} extension ${price_tgt:.2f} (no structure found nearby)"
                    })

    # ── Sort and deduplicate ──────────────────────────────────────────────────
    if direction == "BUY":
        candidates.sort(key=lambda x: x["price"])     # nearest first
    else:
        candidates.sort(key=lambda x: -x["price"])    # nearest first for SELL

    # Deduplicate: remove levels within 0.1% of each other
    deduped = []
    for c in candidates:
        too_close = any(
            abs(c["price"] - d["price"]) / max(entry, 1) < 0.001
            for d in deduped
        )
        if not too_close:
            deduped.append(c)

    # Cap at 6 TP levels maximum
    return deduped[:6]


def select_best_tps(tp_levels: list, min_rr: float = 1.0) -> tuple:
    """
    Select TP1, TP2, TP3 from the candidate list.
    Strategy:
      TP1 = nearest high-confidence level with RR >= min_rr
      TP2 = next level, higher RR
      TP3 = furthest realistic level

    Returns (tp1_dict, tp2_dict, tp3_dict, all_levels)
    Any that cannot be found are None.
    """
    valid = [t for t in tp_levels if t["rr"] >= min_rr]
    if not valid:
        valid = tp_levels  # use whatever we have

    # Sort by confidence descending then price proximity
    high_conf  = [t for t in valid if t["confidence"] >= 3]
    med_conf   = [t for t in valid if t["confidence"] == 2]
    low_conf   = [t for t in valid if t["confidence"] == 1]

    ordered = high_conf + med_conf + low_conf

    tp1 = ordered[0] if len(ordered) > 0 else None
    tp2 = ordered[1] if len(ordered) > 1 else None
    tp3 = ordered[2] if len(ordered) > 2 else None

    # Ensure TP2 RR > TP1 RR and TP3 RR > TP2 RR
    if tp1 and tp2 and tp2["rr"] <= tp1["rr"]:
        tp2 = next((t for t in valid if t["rr"] > tp1["rr"]), tp2)
    if tp2 and tp3 and tp3["rr"] <= tp2["rr"]:
        tp3 = next((t for t in valid if t["rr"] > tp2["rr"]), tp3)

    return tp1, tp2, tp3, tp_levels


def format_tp_summary(tp_levels: list, direction: str) -> str:
    """Human-readable TP summary for dashboard display."""
    if not tp_levels:
        return "No structure-based TPs found"
    lines = []
    for i, t in enumerate(tp_levels[:5], 1):
        arrow = "↑" if direction == "BUY" else "↓"
        conf_star = "★" * t["confidence"] + "☆" * (3 - t["confidence"])
        lines.append(
            f"TP{i} {arrow} ${t['price']}  RR 1:{t['rr']}  [{t['source']}] {conf_star}  {t['description']}"
        )
    return "\n".join(lines)
