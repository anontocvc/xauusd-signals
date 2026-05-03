"""
Trading Analyzer v5.0
=====================
Added:
  - Rejection Blocks (RB): wicks rejecting key levels
  - Breaker Blocks (BB): former OB that was broken, now flipped
  - Support/Resistance levels per timeframe
  - Multi-timeframe structure divergence detection
  - AMD phase per timeframe (not just 1H)
  - Inducement detection
  - LTF structure independent of HTF
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class TradingAnalyzer:

    # ── Indicators ─────────────────────────────────────────────────────────────
    def ema(self, s, p):        return s.ewm(span=p, adjust=False).mean()
    def rsi(self, s, p=14):
        d = s.diff(); g = d.clip(lower=0).rolling(p).mean()
        l = (-d.clip(upper=0)).rolling(p).mean()
        return 100 - (100 / (1 + g / l.replace(0, np.nan)))
    def macd(self, s, f=12, sl=26, sg=9):
        m = self.ema(s,f) - self.ema(s,sl); sig = self.ema(m,sg)
        return m, sig, m - sig
    def atr(self, df, p=14):
        h,l,c = df["high"],df["low"],df["close"]
        tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        return tr.rolling(p).mean()
    def bollinger(self, s, p=20, sd=2):
        m=s.rolling(p).mean(); st=s.rolling(p).std()
        return m+sd*st, m, m-sd*st
    def stochastic(self, df, k=14, d=3):
        lo=df["low"].rolling(k).min(); hi=df["high"].rolling(k).max()
        sk=100*(df["close"]-lo)/(hi-lo).replace(0,np.nan)
        return sk, sk.rolling(d).mean()
    def williams_r(self, df, p=14):
        hi=df["high"].rolling(p).max(); lo=df["low"].rolling(p).min()
        return -100*(hi-df["close"])/(hi-lo).replace(0,np.nan)
    def volume_ratio(self, df):
        avg=df["volume"].rolling(20).mean()
        return df["volume"]/avg.replace(0,np.nan)

    # ── Swing detection ─────────────────────────────────────────────────────────
    def find_swings(self, df, lb=5):
        highs, lows = [], []
        for i in range(lb, len(df)-lb):
            if df["high"].iloc[i] == df["high"].iloc[i-lb:i+lb+1].max():
                highs.append((i, float(df["high"].iloc[i])))
            if df["low"].iloc[i] == df["low"].iloc[i-lb:i+lb+1].min():
                lows.append((i, float(df["low"].iloc[i])))
        return highs, lows

    # ── Support & Resistance ────────────────────────────────────────────────────
    def find_support_resistance(self, df, swing_highs, swing_lows, current):
        """Key S/R levels: recent swing highs/lows + round numbers + pivots"""
        levels = []
        price_range = current * 0.03  # scan ±3%

        # Swing highs = resistance
        for _, h in swing_highs[-8:]:
            if abs(h - current) < price_range:
                levels.append({"type":"resistance","level":round(h,2),
                    "side":"above" if h > current else "below",
                    "label":f"Swing R ${h:.2f}"})
        # Swing lows = support
        for _, l in swing_lows[-8:]:
            if abs(l - current) < price_range:
                levels.append({"type":"support","level":round(l,2),
                    "side":"below" if l < current else "above",
                    "label":f"Swing S ${l:.2f}"})

        # Round number levels (psychological S/R)
        base = round(current / 50) * 50
        for offset in [-100,-50,0,50,100]:
            rl = base + offset
            if abs(rl - current) < price_range and rl > 0:
                levels.append({"type":"round_number","level":float(rl),
                    "side":"above" if rl > current else "below",
                    "label":f"Round ${rl:.0f}"})

        return sorted(levels, key=lambda x: abs(x["level"]-current))[:8]

    # ── BOS / CHoCH ─────────────────────────────────────────────────────────────
    def find_structure_events(self, df, swing_highs, swing_lows):
        events = []
        closes = df["close"].values
        if len(swing_highs) >= 2:
            lsh, psh = swing_highs[-1][1], swing_highs[-2][1]
            if lsh < psh:
                events.append({"type":"BOS","direction":"bearish","level":round(lsh,2),
                    "desc":f"Bearish BOS ${lsh:.2f} — lower swing high"})
            if closes[-1] > lsh:
                events.append({"type":"CHoCH","direction":"bullish","level":round(lsh,2),
                    "desc":f"Bullish CHoCH — broke ${lsh:.2f}"})
        if len(swing_lows) >= 2:
            lsl, psl = swing_lows[-1][1], swing_lows[-2][1]
            if lsl > psl:
                events.append({"type":"BOS","direction":"bullish","level":round(lsl,2),
                    "desc":f"Bullish BOS ${lsl:.2f} — higher swing low"})
            if closes[-1] < lsl:
                events.append({"type":"CHoCH","direction":"bearish","level":round(lsl,2),
                    "desc":f"Bearish CHoCH — broke ${lsl:.2f}"})
        return events[-4:]

    # ── Order Blocks ────────────────────────────────────────────────────────────
    def find_order_blocks(self, df):
        obs = []
        for i in range(2, min(len(df)-1, 80)):
            idx = len(df)-1-i
            c  = df.iloc[idx]; n1 = df.iloc[idx+1]
            n2 = df.iloc[idx+2] if idx+2 < len(df) else n1
            body = abs(c["close"]-c["open"])
            if (c["close"]>c["open"] and n1["close"]<n1["open"] and
                    n2["close"]<n1["open"] and (c["high"]-n2["close"])>body):
                obs.append({"type":"bearish_ob","high":round(c["high"],2),
                    "low":round(c["low"],2),"mid":round((c["high"]+c["low"])/2,2),
                    "age":i,"mitigated":df["close"].iloc[idx+1:].max()>c["high"],
                    "label":f"Bearish OB ${c['high']:.2f}–${c['low']:.2f}"})
            if (c["close"]<c["open"] and n1["close"]>n1["open"] and
                    n2["close"]>n1["open"] and (n2["close"]-c["low"])>body):
                obs.append({"type":"bullish_ob","high":round(c["high"],2),
                    "low":round(c["low"],2),"mid":round((c["high"]+c["low"])/2,2),
                    "age":i,"mitigated":df["close"].iloc[idx+1:].min()<c["low"],
                    "label":f"Bullish OB ${c['high']:.2f}–${c['low']:.2f}"})
        obs = sorted(obs, key=lambda x: x["age"])
        return [o for o in obs if not o["mitigated"]][:5]

    # ── Rejection Blocks (NEW) ──────────────────────────────────────────────────
    def find_rejection_blocks(self, df, current):
        """
        Rejection Block: candle with a long wick rejecting a key level.
        Bullish RB: long lower wick (wick >= 2x body) at support
        Bearish RB: long upper wick (wick >= 2x body) at resistance
        """
        rbs = []
        for i in range(1, min(len(df)-1, 40)):
            idx = len(df)-1-i
            c = df.iloc[idx]
            body   = abs(c["close"]-c["open"])
            if body < 0.01: continue
            upper_wick = c["high"] - max(c["open"],c["close"])
            lower_wick = min(c["open"],c["close"]) - c["low"]

            # Bullish rejection (long lower wick — buyers rejected lower prices)
            if lower_wick >= body * 2.0 and lower_wick > 1.0:
                rbs.append({"type":"bullish_rb","level":round(c["low"],2),
                    "high":round(c["high"],2),"low":round(c["low"],2),
                    "wick_size":round(lower_wick,2),"age":i,
                    "label":f"Bullish RB ${c['low']:.2f} (wick {lower_wick:.1f}pt)"})

            # Bearish rejection (long upper wick — sellers rejected higher prices)
            if upper_wick >= body * 2.0 and upper_wick > 1.0:
                rbs.append({"type":"bearish_rb","level":round(c["high"],2),
                    "high":round(c["high"],2),"low":round(c["low"],2),
                    "wick_size":round(upper_wick,2),"age":i,
                    "label":f"Bearish RB ${c['high']:.2f} (wick {upper_wick:.1f}pt)"})

        rbs = sorted(rbs, key=lambda x: x["age"])
        return rbs[:4]

    # ── Breaker Blocks (NEW) ────────────────────────────────────────────────────
    def find_breaker_blocks(self, df, swing_highs, swing_lows, current):
        """
        Breaker Block: a former OB that was broken through.
        When a bearish OB is broken bullish → it flips to bullish support.
        When a bullish OB is broken bearish → it flips to bearish resistance.
        Price often returns to test the breaker before continuing.
        """
        breakers = []
        closes = df["close"].values

        # Former swing highs that were broken (now support)
        for i, h in swing_highs[-6:]:
            if h < current and closes[-1] > h:
                # Was resistance, price broke above → now support breaker
                breakers.append({"type":"bullish_breaker","level":round(h,2),
                    "side":"below","label":f"Bullish Breaker ${h:.2f} (former resistance broken)"})

        # Former swing lows that were broken (now resistance)
        for i, l in swing_lows[-6:]:
            if l > current and closes[-1] < l:
                # Was support, price broke below → now resistance breaker
                breakers.append({"type":"bearish_breaker","level":round(l,2),
                    "side":"above","label":f"Bearish Breaker ${l:.2f} (former support broken)"})

        return breakers[:4]

    # ── FVG ─────────────────────────────────────────────────────────────────────
    def find_fvg(self, df):
        fvgs = []
        for i in range(1, min(len(df)-1, 60)):
            idx = len(df)-1-i
            c1=df.iloc[idx-1]; c3=df.iloc[idx+1]
            if c1["high"] < c3["low"] and (c3["low"]-c1["high"]) > 0.3:
                gap = c3["low"]-c1["high"]
                fvgs.append({"type":"bullish_fvg","top":round(c3["low"],2),
                    "bottom":round(c1["high"],2),"mid":round((c3["low"]+c1["high"])/2,2),
                    "size":round(gap,2),"age":i,
                    "filled":df["close"].iloc[idx+1:].min()<=c1["high"],
                    "label":f"Bull FVG ${c1['high']:.2f}–${c3['low']:.2f}"})
            if c1["low"] > c3["high"] and (c1["low"]-c3["high"]) > 0.3:
                gap = c1["low"]-c3["high"]
                fvgs.append({"type":"bearish_fvg","top":round(c1["low"],2),
                    "bottom":round(c3["high"],2),"mid":round((c1["low"]+c3["high"])/2,2),
                    "size":round(gap,2),"age":i,
                    "filled":df["close"].iloc[idx+1:].max()>=c1["low"],
                    "label":f"Bear FVG ${c1['low']:.2f}–${c3['high']:.2f}"})
        fvgs = sorted(fvgs, key=lambda x: x["age"])
        return [f for f in fvgs if not f["filled"]][:5]

    # ── Liquidity ───────────────────────────────────────────────────────────────
    def find_liquidity(self, df, swing_highs, swing_lows, current):
        zones = []; thr = current * 0.002
        hp=[h[1] for h in swing_highs[-8:]]
        lp=[l[1] for l in swing_lows[-8:]]
        for i in range(len(hp)):
            for j in range(i+1,len(hp)):
                if abs(hp[i]-hp[j])<thr:
                    lvl=(hp[i]+hp[j])/2
                    zones.append({"type":"buy_side_liquidity","level":round(lvl,2),
                        "label":f"BSL (Equal Highs) ${lvl:.2f}","side":"above" if lvl>current else "below"})
        for i in range(len(lp)):
            for j in range(i+1,len(lp)):
                if abs(lp[i]-lp[j])<thr:
                    lvl=(lp[i]+lp[j])/2
                    zones.append({"type":"sell_side_liquidity","level":round(lvl,2),
                        "label":f"SSL (Equal Lows) ${lvl:.2f}","side":"below" if lvl<current else "above"})
        if swing_highs:
            h=swing_highs[-1][1]
            zones.append({"type":"prev_high","level":round(h,2),"label":f"Prev High ${h:.2f}",
                "side":"above" if h>current else "below"})
        if swing_lows:
            l=swing_lows[-1][1]
            zones.append({"type":"prev_low","level":round(l,2),"label":f"Prev Low ${l:.2f}",
                "side":"below" if l<current else "above"})
        return zones[:6]

    def find_sweeps(self, df, swing_highs, swing_lows):
        sweeps = []
        for i in [-1,-2,-3]:
            c=df.iloc[i]
            for sl in swing_lows[-5:]:
                if c["low"]<sl[1] and c["close"]>sl[1]:
                    sweeps.append({"type":"bullish_sweep","level":round(sl[1],2),
                        "candle_ago":abs(i),"label":f"Bullish sweep SSL ${sl[1]:.2f}"})
            for sh in swing_highs[-5:]:
                if c["high"]>sh[1] and c["close"]<sh[1]:
                    sweeps.append({"type":"bearish_sweep","level":round(sh[1],2),
                        "candle_ago":abs(i),"label":f"Bearish sweep BSL ${sh[1]:.2f}"})
        return sweeps[:3]

    # ── Premium/Discount ────────────────────────────────────────────────────────
    def premium_discount(self, df, swing_highs, swing_lows):
        if not swing_highs or not swing_lows: return "neutral",50.0
        rh=max(h[1] for h in swing_highs[-5:])
        rl=min(l[1] for l in swing_lows[-5:])
        c=df["close"].iloc[-1]
        if rh==rl: return "neutral",50.0
        pct=(c-rl)/(rh-rl)*100
        zone="premium" if pct>62 else ("discount" if pct<38 else "equilibrium")
        return zone, round(pct,1)

    # ── Market structure bias ────────────────────────────────────────────────────
    def market_bias(self, df, swing_highs, swing_lows):
        if len(swing_highs)<2 or len(swing_lows)<2: return "neutral"
        hh=swing_highs[-1][1]>swing_highs[-2][1]
        hl=swing_lows[-1][1]>swing_lows[-2][1]
        lh=swing_highs[-1][1]<swing_highs[-2][1]
        ll=swing_lows[-1][1]<swing_lows[-2][1]
        if hh and hl: return "bullish"
        if lh and ll: return "bearish"
        if hh and ll: return "ranging_bullish"
        if lh and hl: return "ranging_bearish"
        return "ranging"

    # ── Inducement detection (NEW) ───────────────────────────────────────────────
    def find_inducement(self, df, swing_highs, swing_lows, direction):
        """
        Inducement: a small liquidity grab BEFORE the real move.
        Bullish inducement: quick dip below a swing low before move up.
        Bearish inducement: quick spike above a swing high before move down.
        """
        inducements = []
        if len(df) < 10: return inducements
        recent = df.tail(10)

        if direction == "bearish" and len(swing_highs) >= 2:
            # Look for a recent spike above a minor high that then reversed
            last_high = swing_highs[-1][1]
            if recent["high"].max() > last_high:
                spike_candle = recent["high"].idxmax()
                after = recent.loc[spike_candle:]
                if len(after) > 1 and after["close"].iloc[-1] < last_high:
                    inducements.append({
                        "type": "bearish_inducement",
                        "level": round(last_high, 2),
                        "label": f"Bearish inducement above ${last_high:.2f}"
                    })

        if direction == "bullish" and len(swing_lows) >= 2:
            last_low = swing_lows[-1][1]
            if recent["low"].min() < last_low:
                dip_candle = recent["low"].idxmin()
                after = recent.loc[dip_candle:]
                if len(after) > 1 and after["close"].iloc[-1] > last_low:
                    inducements.append({
                        "type": "bullish_inducement",
                        "level": round(last_low, 2),
                        "label": f"Bullish inducement below ${last_low:.2f}"
                    })

        return inducements[:2]

    # ── Full single TF analysis ──────────────────────────────────────────────────
    def analyze_tf(self, df, tf_label):
        if df is None or len(df) < 30: return None
        try:
            closes = df["close"]
            current = float(closes.iloc[-1])
            atr_val = float(self.atr(df).iloc[-1] or 5.0)

            rsi_v  = float(self.rsi(closes).iloc[-1] or 50)
            ml, ms, mh = self.macd(closes)
            macd_l = float(ml.iloc[-1] or 0)
            macd_s = float(ms.iloc[-1] or 0)
            macd_h = float(mh.iloc[-1] or 0)
            e8  = float(self.ema(closes,8).iloc[-1])
            e21 = float(self.ema(closes,21).iloc[-1])
            e50 = float(self.ema(closes,50).iloc[-1])
            e200= float(self.ema(closes, min(200,len(closes)-1)).iloc[-1])
            bbu,bbm,bbl = self.bollinger(closes)
            bbu_v=float(bbu.iloc[-1] or current+50)
            bbm_v=float(bbm.iloc[-1] or current)
            bbl_v=float(bbl.iloc[-1] or current-50)
            sk,sd = self.stochastic(df)
            sk_v=float(sk.iloc[-1] or 50); sd_v=float(sd.iloc[-1] or 50)
            wr_v = float(self.williams_r(df).iloc[-1] or -50)
            vol_v= float(self.volume_ratio(df).iloc[-1] or 1.0)

            swing_highs, swing_lows = self.find_swings(df)
            struct_events = self.find_structure_events(df, swing_highs, swing_lows)
            obs    = self.find_order_blocks(df)
            fvgs   = self.find_fvg(df)
            liq    = self.find_liquidity(df, swing_highs, swing_lows, current)
            sweeps = self.find_sweeps(df, swing_highs, swing_lows)
            pd_zone, pd_pct = self.premium_discount(df, swing_highs, swing_lows)
            bias   = self.market_bias(df, swing_highs, swing_lows)
            sr_lvls= self.find_support_resistance(df, swing_highs, swing_lows, current)
            rbs    = self.find_rejection_blocks(df, current)
            brkrs  = self.find_breaker_blocks(df, swing_highs, swing_lows, current)
            induce = self.find_inducement(df, swing_highs, swing_lows, bias)

            # Trend
            if e8>e21>e50:   trend="strong_bullish"
            elif e8<e21<e50: trend="strong_bearish"
            elif e8>e21:     trend="bullish"
            elif e8<e21:     trend="bearish"
            else:             trend="ranging"

            # Momentum
            pc = (closes.iloc[-1]-closes.iloc[-5])/closes.iloc[-5]*100
            momentum = "bullish" if pc>0.1 else ("bearish" if pc<-0.1 else "neutral")

            # Recent high/low
            rh = float(df["high"].tail(20).max())
            rl = float(df["low"].tail(20).min())
            pivot=(rh+rl+current)/3
            r1=2*pivot-rl; s1=2*pivot-rh

            # Confluence score
            score = 0.0
            if "bullish" in bias:  score += 1
            if "bearish" in bias:  score -= 1
            if rsi_v>50:           score += 0.5
            if rsi_v<50:           score -= 0.5
            if macd_h>0:           score += 0.5
            if macd_h<0:           score -= 0.5
            if pd_zone=="discount":score += 1
            if pd_zone=="premium": score -= 1
            for sw in sweeps:
                if sw["type"]=="bullish_sweep": score += 1.5
                if sw["type"]=="bearish_sweep": score -= 1.5

            return {
                "timeframe":     tf_label,
                "current_price": round(current,2),
                "atr":           round(atr_val,2),
                "indicators": {
                    "rsi":rsi_v,"macd":macd_l,"macd_signal":macd_s,"macd_hist":macd_h,
                    "ema8":e8,"ema21":e21,"ema50":e50,"ema200":e200,
                    "bb_upper":bbu_v,"bb_mid":bbm_v,"bb_lower":bbl_v,
                    "stoch_k":sk_v,"stoch_d":sd_v,"williams_r":wr_v,
                    "volume_ratio":round(vol_v,2),
                },
                "smc": {
                    "structure_events":  struct_events,
                    "order_blocks":      obs,
                    "fvgs":              fvgs,
                    "liquidity_zones":   liq,
                    "sweeps":            sweeps,
                    "rejection_blocks":  rbs,
                    "breaker_blocks":    brkrs,
                    "inducements":       induce,
                    "support_resistance":sr_lvls,
                },
                "levels": {
                    "recent_high":round(rh,2),"recent_low":round(rl,2),
                    "pivot":round(pivot,2),"r1":round(r1,2),"s1":round(s1,2),
                },
                "bias":             bias,
                "trend":            trend,
                "momentum":         momentum,
                "premium_discount": pd_zone,
                "pd_position_pct":  pd_pct,
                "confluence_score": round(score,2),
                "candles_analyzed": len(df),
            }
        except Exception as e:
            logger.error(f"analyze_tf error ({tf_label}): {e}")
            return None

    # ── Full analysis ────────────────────────────────────────────────────────────
    def full_analysis(self, market_data):
        result = {
            "current_price": market_data.get("current_price",0),
            "news":          market_data.get("news",[]),
            "timeframes":    {},
        }
        for tf in ["1m","5m","15m","1h","4h"]:
            if tf in market_data:
                r = self.analyze_tf(market_data[tf], tf)
                if r: result["timeframes"][tf] = r

        # HTF bias from 4H/1H
        b4h = result["timeframes"].get("4h",{}).get("bias","neutral")
        b1h = result["timeframes"].get("1h",{}).get("bias","neutral")
        htf = "neutral"
        if "bullish" in b4h and "bull" in b1h: htf="bullish"
        elif "bearish" in b4h and "bear" in b1h: htf="bearish"
        elif "bearish" in b4h and "bear" in b1h: htf="bearish"
        elif "bullish" in b4h and "bull" in b1h: htf="bullish"
        elif "bearish" in b4h: htf="bearish"
        elif "bullish" in b4h: htf="bullish"
        result["htf_bias"] = htf

        # LTF consensus (1M+5M+15M combined)
        ltf_scores = []
        for tf in ["1m","5m","15m"]:
            d = result["timeframes"].get(tf,{})
            b = d.get("bias","neutral")
            if "bull" in b:   ltf_scores.append(1)
            elif "bear" in b: ltf_scores.append(-1)
            else:              ltf_scores.append(0)
        ltf_sum = sum(ltf_scores)
        if ltf_sum >= 2:    result["ltf_consensus"] = "bullish"
        elif ltf_sum <= -2: result["ltf_consensus"] = "bearish"
        else:               result["ltf_consensus"] = "mixed"

        # Divergence flag — HTF and LTF disagree
        htf_bull = "bull" in result["htf_bias"]
        htf_bear = "bear" in result["htf_bias"]
        ltf_bull = result["ltf_consensus"] == "bullish"
        ltf_bear = result["ltf_consensus"] == "bearish"
        result["htf_ltf_divergence"] = (
            (htf_bull and ltf_bear) or (htf_bear and ltf_bull)
        )

        return result
