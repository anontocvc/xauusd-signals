"""
Market Data Fetcher v4.1
========================
Priority:
  1. MetaTrader 5 (Windows only — real-time spot XAUUSD from broker)
  2. Yahoo Finance XAUUSD=X (spot price — matches broker closely)
  3. Synthetic fallback (offline demo only)

FIX: Changed from GC=F (Gold Futures) to XAUUSD=X (Spot Gold)
     GC=F is futures — different price, includes carry cost
     XAUUSD=X is spot — matches MT5/broker price
"""

import requests
import pandas as pd
import numpy as np
import time
import logging
import platform
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Yahoo Finance symbols ─────────────────────────────────────────────────────
# XAUUSD=X  = Spot Gold / US Dollar  ← USE THIS (matches broker)
# GC=F      = Gold Futures            ← OLD (wrong, different price)
YF_SPOT    = "XAUUSD%3DX"    # XAUUSD=X URL-encoded
YF_FUTURES = "GC%3DF"        # GC=F fallback only

YF_CONFIG = {
    "1m":  ("1d",   60),
    "5m":  ("5d",   300),
    "15m": ("60d",  900),
    "1h":  ("730d", 3600),
    "4h":  ("730d", 14400),
}

MT5_SYMBOL = "XAUUSDm"   # Exness broker default

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


class MarketDataFetcher:
    def __init__(self):
        self._mt5      = None
        self._mt5_ok   = False
        self._last_price = 3285.0
        self._session  = requests.Session()
        self._session.headers.update(HEADERS)
        self._source   = "none"

        if platform.system() == "Windows":
            self._init_mt5()
        else:
            logger.info("MT5: skipped (not Windows). Using Yahoo Finance XAUUSD=X spot.")

    # ── MT5 init ──────────────────────────────────────────────────────────────
    def _init_mt5(self):
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5
            if not mt5.initialize(timeout=5000):
                logger.warning(f"MT5: initialize() failed — {mt5.last_error()}")
                self._mt5_ok = False
                return
            acct = mt5.account_info()
            if acct:
                logger.info(f"MT5: connected broker={acct.company} account={acct.login}")
            # Try symbol
            sym_info = mt5.symbol_info(MT5_SYMBOL)
            if sym_info is None:
                for alt in ["XAUUSD", "XAUUSDc", "GOLD", "XAUUSD."]:
                    if mt5.symbol_info(alt):
                        import builtins; builtins._MT5_SYM = alt
                        logger.info(f"MT5: using symbol '{alt}'")
                        self._mt5_ok = True; self._source = "MT5"; return
                self._mt5_ok = False; return
            if not sym_info.visible:
                mt5.symbol_select(MT5_SYMBOL, True)
            self._mt5_ok = True; self._source = "MT5"
            logger.info(f"MT5: '{MT5_SYMBOL}' ready spread={sym_info.spread}")
        except ImportError:
            logger.warning("MT5: package not installed. Run: pip install MetaTrader5")
            self._mt5_ok = False
        except Exception as e:
            logger.error(f"MT5 init error: {e}")
            self._mt5_ok = False

    def _active_symbol(self):
        import builtins
        return getattr(builtins, "_MT5_SYM", MT5_SYMBOL)

    # ── Public API ────────────────────────────────────────────────────────────
    def get_all_timeframes(self):
        result = {}
        price  = self._get_price()
        self._last_price = price
        result["current_price"] = price
        result["data_source"]   = self._source

        for tf in ["1m", "5m", "15m", "1h", "4h"]:
            df = self._get_ohlcv(tf, price)
            if df is not None and len(df) >= 30:
                result[tf] = df
                logger.info(f"  [{self._source}] {tf}: {len(df)} bars  last={df['close'].iloc[-1]:.2f}")
            else:
                result[tf] = self._synthetic_ohlcv(tf, price)
                logger.warning(f"  {tf}: using synthetic fallback")

        result["news"] = self._news_events()
        return result

    # ── Price ─────────────────────────────────────────────────────────────────
    def _get_price(self):
        if self._mt5_ok:
            p = self._mt5_price()
            if p: return p
        p = self._yf_price()
        if p: return p
        return round(self._last_price + np.random.normal(0, 0.5), 2)

    def _mt5_price(self):
        try:
            tick = self._mt5.symbol_info_tick(self._active_symbol())
            if tick and tick.bid > 0:
                return round((tick.bid + tick.ask) / 2, 2)
        except Exception as e:
            logger.debug(f"MT5 price error: {e}")
        return None

    def _yf_price(self):
        """Fetch spot XAUUSD price — tries XAUUSD=X first, GC=F as fallback."""
        for symbol, label in [(YF_SPOT, "XAUUSD=X spot"), (YF_FUTURES, "GC=F futures")]:
            for host in ["query1", "query2"]:
                try:
                    url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
                    r   = self._session.get(url, timeout=8)
                    closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
                    closes = [c for c in closes if c is not None]
                    if closes:
                        price = round(closes[-1], 2)
                        logger.info(f"  Price from {label}: ${price}")
                        self._source = "Yahoo (spot)" if "spot" in label else "Yahoo (futures)"
                        return price
                except Exception as e:
                    logger.debug(f"YF price ({symbol}/{host}) error: {e}")
        return None

    # ── OHLCV ─────────────────────────────────────────────────────────────────
    def _get_ohlcv(self, interval, current_price):
        if self._mt5_ok:
            df = self._mt5_ohlcv(interval, current_price)
            if df is not None: return df
        return self._yf_ohlcv(interval, current_price)

    def _mt5_ohlcv(self, interval, current_price):
        try:
            mt5    = self._mt5
            sym    = self._active_symbol()
            tf_map = {
                "1m":  mt5.TIMEFRAME_M1,  "5m":  mt5.TIMEFRAME_M5,
                "15m": mt5.TIMEFRAME_M15, "1h":  mt5.TIMEFRAME_H1,
                "4h":  mt5.TIMEFRAME_H4,
            }
            tf_id = tf_map.get(interval)
            if tf_id is None: return None
            n = {"1m":500,"5m":500,"15m":400,"1h":500,"4h":300}.get(interval, 300)
            rates = mt5.copy_rates_from_pos(sym, tf_id, 0, n)
            if rates is None or len(rates) == 0: return None
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.rename(columns={"tick_volume":"volume"})
            df = df.set_index("time")[["open","high","low","close","volume"]].dropna()
            return df
        except Exception as e:
            logger.debug(f"MT5 OHLCV error ({interval}): {e}")
            return None

    def _yf_ohlcv(self, interval, current_price):
        """Fetch OHLCV — uses XAUUSD=X spot, falls back to GC=F."""
        range_param, _ = YF_CONFIG.get(interval, ("1d", 60))

        for symbol in [YF_SPOT, YF_FUTURES]:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                   f"?interval={interval}&range={range_param}")
            try:
                r    = self._session.get(url, timeout=10)
                data = r.json()
                res  = data["chart"]["result"][0]
                ts   = res["timestamp"]
                q    = res["indicators"]["quote"][0]
                df   = pd.DataFrame({
                    "open":   q["open"],   "high": q["high"],
                    "low":    q["low"],    "close": q["close"],
                    "volume": q["volume"],
                }, index=pd.to_datetime(ts, unit="s", utc=True))
                df = df.dropna()
                if len(df) < 30: continue

                # Align last close to current_price (removes futures premium)
                shift = current_price - df["close"].iloc[-1]
                if abs(shift) < current_price * 0.02:  # only shift if < 2% difference
                    for col in ["open","high","low","close"]:
                        df[col] = (df[col] + shift).round(2)

                logger.debug(f"  YF OHLCV {interval} from {'spot' if symbol==YF_SPOT else 'futures'}: {len(df)} bars")
                return df
            except Exception as e:
                logger.debug(f"YF OHLCV ({symbol}/{interval}) error: {e}")
        return None

    # ── Synthetic fallback ────────────────────────────────────────────────────
    def _synthetic_ohlcv(self, interval, current_price, n_bars=300):
        _, bar_sec = YF_CONFIG.get(interval, ("1d", 60))
        vol_map = {"1m":0.0004,"5m":0.0008,"15m":0.0012,"1h":0.002,"4h":0.004}
        vol     = vol_map.get(interval, 0.001)
        np.random.seed(int(time.time() / bar_sec))
        returns = np.random.normal(0, vol, n_bars)
        trend   = np.linspace(0, np.random.choice([-0.01,0,0.01]), n_bars)
        closes  = current_price * np.exp(np.cumsum(returns + trend/n_bars))
        closes  = closes * (current_price / closes[-1])
        bv      = vol * current_price
        highs   = closes + np.abs(np.random.normal(0, bv*0.6, n_bars))
        lows    = closes - np.abs(np.random.normal(0, bv*0.6, n_bars))
        opens   = np.roll(closes, 1); opens[0] = closes[0]
        volumes = np.random.lognormal(10, 0.5, n_bars).astype(int)
        now_ts  = int(time.time())
        ts      = [now_ts - (n_bars-i)*bar_sec for i in range(n_bars)]
        self._source = "Synthetic (demo only)"
        return pd.DataFrame({
            "open": np.round(opens,2), "high": np.round(highs,2),
            "low":  np.round(lows,2),  "close": np.round(closes,2),
            "volume": volumes,
        }, index=pd.to_datetime(ts, unit="s", utc=True))

    # ── MT5 info ──────────────────────────────────────────────────────────────
    def get_mt5_info(self):
        if not self._mt5_ok or self._mt5 is None:
            return {"connected": False, "reason": "MT5 not connected"}
        try:
            mt5  = self._mt5
            acct = mt5.account_info()
            sym  = mt5.symbol_info(self._active_symbol())
            tick = mt5.symbol_info_tick(self._active_symbol())
            return {
                "connected": True,
                "broker":    acct.company if acct else "—",
                "account":   acct.login   if acct else "—",
                "server":    acct.server  if acct else "—",
                "balance":   acct.balance if acct else 0,
                "symbol":    self._active_symbol(),
                "spread":    sym.spread   if sym  else "—",
                "bid":       tick.bid     if tick else 0,
                "ask":       tick.ask     if tick else 0,
                "last_tick": datetime.fromtimestamp(tick.time,tz=timezone.utc).strftime("%H:%M:%S UTC") if tick else "—",
            }
        except Exception as e:
            return {"connected": False, "reason": str(e)}

    # ── News ──────────────────────────────────────────────────────────────────
    def _news_events(self):
        return [
            {"date":"2026-04-29","time":"18:00 UTC","event":"FOMC Interest Rate Decision","impact":"HIGH",  "currency":"USD"},
            {"date":"2026-04-30","time":"12:30 UTC","event":"US Q1 GDP Advance Estimate", "impact":"HIGH",  "currency":"USD"},
            {"date":"2026-04-30","time":"12:30 UTC","event":"Initial Jobless Claims",      "impact":"MEDIUM","currency":"USD"},
            {"date":"2026-05-02","time":"12:30 UTC","event":"US Non-Farm Payrolls",        "impact":"HIGH",  "currency":"USD"},
        ]
