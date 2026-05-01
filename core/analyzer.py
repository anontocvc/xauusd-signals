"""
Trading Analyzer — Full SMC/ICT Technical Analysis Engine
Computes: Structure, OBs, FVGs, Liquidity, RSI, MACD, EMA, ATR,
          Bollinger Bands, Volume analysis, Momentum, Premium/Discount
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class TradingAnalyzer:

    # ── Indicators ────────────────────────────────────────────────────────────

    def ema(self, series, period):
        return series.ewm(span=period, adjust=False).mean()

    def rsi(self, series, period=14):
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def macd(self, series, fast=12, slow=26, signal=9):
        e_fast = self.ema(series, fast)
        e_slow = self.ema(series, slow)
        macd_line = e_fast - e_slow
        signal_line = self.ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def atr(self, df, period=14):
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def bollinger_bands(self, series, period=20, std_dev=2):
        mid = series.rolling(period).mean()
        std = series.rolling(period).std()
        return mid + std_dev * std, mid, mid - std_dev * std

    def stochastic(self, df, k=14, d=3):
        low_min = df["low"].rolling(k).min()
        high_max = df["high"].rolling(k).max()
        stoch_k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
        stoch_d = stoch_k.rolling(d).mean()
        return stoch_k, stoch_d

    def williams_r(self, df, period=14):
        high_max = df["high"].rolling(period).max()
        low_min = df["low"].rolling(period).min()
        return -100 * (high_max - df["close"]) / (high_max - low_min).replace(0, np.nan)

    def volume_analysis(self, df):
        avg_vol = df["volume"].rolling(20).mean()
        vol_ratio = df["volume"] / avg_vol.replace(0, np.nan)
        return vol_ratio

    # ── SMC / ICT Concepts ────────────────────────────────────────────────────

    def find_swing_highs_lows(self, df, lookback=5):
        highs, lows = [], []
        for i in range(lookback, len(df) - lookback):
            if df["high"].iloc[i] == df["high"].iloc[i-lookback:i+lookback+1].max():
                highs.append((i, df["high"].iloc[i]))
            if df["low"].iloc[i] == df["low"].iloc[i-lookback:i+lookback+1].min():
                lows.append((i, df["low"].iloc[i]))
        return highs, lows

    def find_bos_choch(self, df, swing_highs, swing_lows):
        """Detect Break of Structure and Change of Character"""
        events = []
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values

        # Check last 50 candles for BOS/CHoCH
        recent_start = max(0, len(df) - 50)

        if len(swing_highs) >= 2:
            last_sh = swing_highs[-1][1]
            prev_sh = swing_highs[-2][1] if len(swing_highs) >= 2 else last_sh
            # Bearish BOS: lower swing high printed
            if last_sh < prev_sh:
                events.append({"type": "BOS", "direction": "bearish", "level": last_sh, "desc": f"Bearish BOS at ${last_sh:.2f} — lower swing high"})
            # Bullish CHoCH: price broke above recent swing high (after downtrend)
            if closes[-1] > last_sh:
                events.append({"type": "CHoCH", "direction": "bullish", "level": last_sh, "desc": f"Bullish CHoCH — price broke ${last_sh:.2f}"})

        if len(swing_lows) >= 2:
            last_sl = swing_lows[-1][1]
            prev_sl = swing_lows[-2][1] if len(swing_lows) >= 2 else last_sl
            # Bullish BOS: higher swing low
            if last_sl > prev_sl:
                events.append({"type": "BOS", "direction": "bullish", "level": last_sl, "desc": f"Bullish BOS at ${last_sl:.2f} — higher swing low"})
            # Bearish CHoCH: price broke below recent swing low
            if closes[-1] < last_sl:
                events.append({"type": "CHoCH", "direction": "bearish", "level": last_sl, "desc": f"Bearish CHoCH — price broke ${last_sl:.2f}"})

        return events[-3:] if events else []

    def find_order_blocks(self, df, n=5):
        """Identify bullish and bearish order blocks"""
        obs = []
        if len(df) < 10:
            return obs

        for i in range(2, min(len(df) - 1, 80)):
            idx = len(df) - 1 - i
            candle = df.iloc[idx]
            next_c = df.iloc[idx + 1]
            next2 = df.iloc[idx + 2] if idx + 2 < len(df) else next_c

            # Bearish OB: last bullish candle before a bearish impulse
            if (candle["close"] > candle["open"] and
                next_c["close"] < next_c["open"] and
                next2["close"] < next_c["open"]):
                body_size = abs(candle["close"] - candle["open"])
                impulse = candle["high"] - next2["close"]
                if impulse > body_size:
                    obs.append({
                        "type": "bearish_ob",
                        "high": round(candle["high"], 2),
                        "low": round(candle["low"], 2),
                        "mid": round((candle["high"] + candle["low"]) / 2, 2),
                        "age": i,
                        "mitigated": df["close"].iloc[idx+1:].max() > candle["high"],
                        "label": f"Bearish OB ${candle['high']:.2f}–${candle['low']:.2f}"
                    })

            # Bullish OB: last bearish candle before a bullish impulse
            if (candle["close"] < candle["open"] and
                next_c["close"] > next_c["open"] and
                next2["close"] > next_c["open"]):
                body_size = abs(candle["open"] - candle["close"])
                impulse = next2["close"] - candle["low"]
                if impulse > body_size:
                    obs.append({
                        "type": "bullish_ob",
                        "high": round(candle["high"], 2),
                        "low": round(candle["low"], 2),
                        "mid": round((candle["high"] + candle["low"]) / 2, 2),
                        "age": i,
                        "mitigated": df["close"].iloc[idx+1:].min() < candle["low"],
                        "label": f"Bullish OB ${candle['high']:.2f}–${candle['low']:.2f}"
                    })

        # Sort by age (most recent first) and filter unmitigated
        obs = sorted(obs, key=lambda x: x["age"])
        unmitigated = [o for o in obs if not o["mitigated"]]
        return unmitigated[:4]

    def find_fvg(self, df):
        """Fair Value Gaps — 3-candle structure"""
        fvgs = []
        if len(df) < 5:
            return fvgs

        for i in range(1, min(len(df) - 1, 60)):
            idx = len(df) - 1 - i
            c1 = df.iloc[idx - 1]
            c3 = df.iloc[idx + 1]

            # Bullish FVG: c1 high < c3 low
            if c1["high"] < c3["low"]:
                gap = c3["low"] - c1["high"]
                if gap > 0.5:  # Minimum 50 cent gap
                    fvgs.append({
                        "type": "bullish_fvg",
                        "top": round(c3["low"], 2),
                        "bottom": round(c1["high"], 2),
                        "mid": round((c3["low"] + c1["high"]) / 2, 2),
                        "size": round(gap, 2),
                        "age": i,
                        "filled": df["close"].iloc[idx+1:].min() <= c1["high"],
                        "label": f"Bullish FVG ${c1['high']:.2f}–${c3['low']:.2f}"
                    })

            # Bearish FVG: c1 low > c3 high
            if c1["low"] > c3["high"]:
                gap = c1["low"] - c3["high"]
                if gap > 0.5:
                    fvgs.append({
                        "type": "bearish_fvg",
                        "top": round(c1["low"], 2),
                        "bottom": round(c3["high"], 2),
                        "mid": round((c1["low"] + c3["high"]) / 2, 2),
                        "size": round(gap, 2),
                        "age": i,
                        "filled": df["close"].iloc[idx+1:].max() >= c1["low"],
                        "label": f"Bearish FVG ${c1['low']:.2f}–${c3['high']:.2f}"
                    })

        fvgs = sorted(fvgs, key=lambda x: x["age"])
        return [f for f in fvgs if not f["filled"]][:4]

    def find_liquidity_zones(self, df, swing_highs, swing_lows):
        """Equal highs/lows, stop clusters, liquidity pools"""
        zones = []
        closes = df["close"].values
        current = closes[-1]
        threshold = current * 0.0015  # 0.15% tolerance for "equal" levels

        # Equal highs (buy-side liquidity above)
        high_prices = [h[1] for h in swing_highs[-8:]]
        for i in range(len(high_prices)):
            for j in range(i + 1, len(high_prices)):
                if abs(high_prices[i] - high_prices[j]) < threshold:
                    lvl = (high_prices[i] + high_prices[j]) / 2
                    if lvl > current:
                        zones.append({
                            "type": "buy_side_liquidity",
                            "level": round(lvl, 2),
                            "label": f"BSL (Equal Highs) ${lvl:.2f}",
                            "side": "above"
                        })

        # Equal lows (sell-side liquidity below)
        low_prices = [l[1] for l in swing_lows[-8:]]
        for i in range(len(low_prices)):
            for j in range(i + 1, len(low_prices)):
                if abs(low_prices[i] - low_prices[j]) < threshold:
                    lvl = (low_prices[i] + low_prices[j]) / 2
                    if lvl < current:
                        zones.append({
                            "type": "sell_side_liquidity",
                            "level": round(lvl, 2),
                            "label": f"SSL (Equal Lows) ${lvl:.2f}",
                            "side": "below"
                        })

        # Previous highs/lows as liquidity
        if swing_highs:
            ph = swing_highs[-1][1]
            zones.append({"type": "prev_high", "level": round(ph, 2), "label": f"Prev High ${ph:.2f}", "side": "above" if ph > current else "below"})
        if swing_lows:
            pl = swing_lows[-1][1]
            zones.append({"type": "prev_low", "level": round(pl, 2), "label": f"Prev Low ${pl:.2f}", "side": "below" if pl < current else "above"})

        return zones[:6]

    def premium_discount(self, df, swing_highs, swing_lows):
        """Identify if price is in premium or discount zone"""
        if not swing_highs or not swing_lows:
            return "neutral", 50.0
        recent_high = max(h[1] for h in swing_highs[-5:])
        recent_low = min(l[1] for l in swing_lows[-5:])
        current = df["close"].iloc[-1]
        if recent_high == recent_low:
            return "neutral", 50.0
        pct = (current - recent_low) / (recent_high - recent_low) * 100
        if pct > 62:
            zone = "premium"
        elif pct < 38:
            zone = "discount"
        else:
            zone = "equilibrium"
        return zone, round(pct, 1)

    def market_structure_bias(self, df, swing_highs, swing_lows):
        """Determine overall market structure bias"""
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return "neutral"
        hh = swing_highs[-1][1] > swing_highs[-2][1]
        hl = swing_lows[-1][1] > swing_lows[-2][1]
        lh = swing_highs[-1][1] < swing_highs[-2][1]
        ll = swing_lows[-1][1] < swing_lows[-2][1]
        if hh and hl:
            return "bullish"
        if lh and ll:
            return "bearish"
        if hh and ll:
            return "ranging_bullish"
        if lh and hl:
            return "ranging_bearish"
        return "ranging"

    def liquidity_sweep_check(self, df, swing_highs, swing_lows):
        """Check if most recent candles swept liquidity"""
        sweeps = []
        if len(df) < 3:
            return sweeps
        last = df.iloc[-1]
        prev_last = df.iloc[-2]

        # Check last 3 candles for sweeps
        for i in [-1, -2, -3]:
            c = df.iloc[i]
            # Bullish sweep: wick below SSL then closes above
            for sl in swing_lows[-5:]:
                if c["low"] < sl[1] and c["close"] > sl[1]:
                    sweeps.append({
                        "type": "bullish_sweep",
                        "level": round(sl[1], 2),
                        "candle_ago": abs(i),
                        "label": f"Bullish sweep of SSL ${sl[1]:.2f} ({abs(i)} candle ago)"
                    })
            # Bearish sweep: wick above BSL then closes below
            for sh in swing_highs[-5:]:
                if c["high"] > sh[1] and c["close"] < sh[1]:
                    sweeps.append({
                        "type": "bearish_sweep",
                        "level": round(sh[1], 2),
                        "candle_ago": abs(i),
                        "label": f"Bearish sweep of BSL ${sh[1]:.2f} ({abs(i)} candle ago)"
                    })

        return sweeps[:3]

    # ── Full Analysis ─────────────────────────────────────────────────────────

    def analyze_timeframe(self, df, tf_label):
        """Full analysis for a single timeframe"""
        if df is None or len(df) < 30:
            return None

        try:
            closes = df["close"]
            current = float(closes.iloc[-1])
            atr_val = self.atr(df)
            current_atr = float(atr_val.iloc[-1]) if not atr_val.isna().all() else 5.0

            # Indicators
            rsi_series = self.rsi(closes)
            rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.isna().all() else 50.0

            macd_line, signal_line, histogram = self.macd(closes)
            macd_val = float(macd_line.iloc[-1]) if not macd_line.isna().all() else 0.0
            macd_sig = float(signal_line.iloc[-1]) if not signal_line.isna().all() else 0.0
            macd_hist = float(histogram.iloc[-1]) if not histogram.isna().all() else 0.0

            ema8 = float(self.ema(closes, 8).iloc[-1])
            ema21 = float(self.ema(closes, 21).iloc[-1])
            ema50 = float(self.ema(closes, 50).iloc[-1])
            ema200 = float(self.ema(closes, 200).iloc[-1]) if len(closes) >= 200 else float(self.ema(closes, min(len(closes)-1, 50)).iloc[-1])

            bb_upper, bb_mid, bb_lower = self.bollinger_bands(closes)
            bb_u = float(bb_upper.iloc[-1]) if not bb_upper.isna().all() else current + 50
            bb_m = float(bb_mid.iloc[-1]) if not bb_mid.isna().all() else current
            bb_l = float(bb_lower.iloc[-1]) if not bb_lower.isna().all() else current - 50

            stoch_k, stoch_d = self.stochastic(df)
            stoch_kv = float(stoch_k.iloc[-1]) if not stoch_k.isna().all() else 50.0
            stoch_dv = float(stoch_d.iloc[-1]) if not stoch_d.isna().all() else 50.0

            willy = self.williams_r(df)
            willy_val = float(willy.iloc[-1]) if not willy.isna().all() else -50.0

            vol_ratio = self.volume_analysis(df)
            vol_v = float(vol_ratio.iloc[-1]) if not vol_ratio.isna().all() else 1.0

            # SMC
            swing_highs, swing_lows = self.find_swing_highs_lows(df)
            structure_events = self.find_bos_choch(df, swing_highs, swing_lows)
            order_blocks = self.find_order_blocks(df)
            fvgs = self.find_fvg(df)
            liquidity_zones = self.find_liquidity_zones(df, swing_highs, swing_lows)
            prem_disc, pct_pos = self.premium_discount(df, swing_highs, swing_lows)
            bias = self.market_structure_bias(df, swing_highs, swing_lows)
            sweeps = self.liquidity_sweep_check(df, swing_highs, swing_lows)

            # Support/resistance
            recent_high = float(df["high"].tail(20).max())
            recent_low = float(df["low"].tail(20).min())
            pivot = (recent_high + recent_low + current) / 3
            r1 = 2 * pivot - recent_low
            s1 = 2 * pivot - recent_high

            # Trend direction
            if ema8 > ema21 > ema50:
                trend = "strong_bullish"
            elif ema8 < ema21 < ema50:
                trend = "strong_bearish"
            elif ema8 > ema21:
                trend = "bullish"
            elif ema8 < ema21:
                trend = "bearish"
            else:
                trend = "ranging"

            # Momentum
            price_change = (closes.iloc[-1] - closes.iloc[-5]) / closes.iloc[-5] * 100
            momentum = "bullish" if price_change > 0.1 else ("bearish" if price_change < -0.1 else "neutral")

            # Confluence score
            score = 0
            if "bullish" in bias: score += 1
            if "bullish" in trend: score += 1
            if rsi_val < 50: score -= 0.5
            if rsi_val > 50: score += 0.5
            if macd_hist > 0: score += 0.5
            if macd_hist < 0: score -= 0.5
            if prem_disc == "discount": score += 1
            if prem_disc == "premium": score -= 1
            if sweeps and sweeps[0]["type"] == "bullish_sweep": score += 1.5
            if sweeps and sweeps[0]["type"] == "bearish_sweep": score -= 1.5

            return {
                "timeframe": tf_label,
                "current_price": round(current, 2),
                "atr": round(current_atr, 2),
                "indicators": {
                    "rsi": round(rsi_val, 1),
                    "macd": round(macd_val, 2),
                    "macd_signal": round(macd_sig, 2),
                    "macd_hist": round(macd_hist, 2),
                    "ema8": round(ema8, 2),
                    "ema21": round(ema21, 2),
                    "ema50": round(ema50, 2),
                    "ema200": round(ema200, 2),
                    "bb_upper": round(bb_u, 2),
                    "bb_mid": round(bb_m, 2),
                    "bb_lower": round(bb_l, 2),
                    "stoch_k": round(stoch_kv, 1),
                    "stoch_d": round(stoch_dv, 1),
                    "williams_r": round(willy_val, 1),
                    "volume_ratio": round(vol_v, 2),
                },
                "smc": {
                    "structure_events": structure_events,
                    "order_blocks": order_blocks,
                    "fvgs": fvgs,
                    "liquidity_zones": liquidity_zones,
                    "sweeps": sweeps,
                },
                "levels": {
                    "recent_high": round(recent_high, 2),
                    "recent_low": round(recent_low, 2),
                    "pivot": round(pivot, 2),
                    "r1": round(r1, 2),
                    "s1": round(s1, 2),
                },
                "bias": bias,
                "trend": trend,
                "momentum": momentum,
                "premium_discount": prem_disc,
                "pd_position_pct": pct_pos,
                "confluence_score": round(score, 2),
                "candles_analyzed": len(df),
            }
        except Exception as e:
            logger.error(f"Analysis error on {tf_label}: {e}")
            return None

    def full_analysis(self, market_data):
        """Run full analysis across all timeframes"""
        result = {
            "current_price": market_data.get("current_price", 0),
            "news": market_data.get("news", []),
            "timeframes": {}
        }
        for tf in ["1m", "5m", "15m", "1h", "4h"]:
            if tf in market_data:
                tf_result = self.analyze_timeframe(market_data[tf], tf)
                if tf_result:
                    result["timeframes"][tf] = tf_result

        # HTF bias from 4H/1H
        htf_bias = "neutral"
        if "4h" in result["timeframes"]:
            htf_bias = result["timeframes"]["4h"]["bias"]
        elif "1h" in result["timeframes"]:
            htf_bias = result["timeframes"]["1h"]["bias"]

        result["htf_bias"] = htf_bias
        return result
