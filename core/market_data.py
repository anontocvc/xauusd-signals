"""
Market Data Fetcher v4.3
========================
Priority for cloud (Railway/Render):
  1. Twelve Data API (free tier, 800 req/day, works on cloud)
  2. Alpha Vantage API (free tier, 25 req/day, works on cloud)
  3. Yahoo Finance with multiple bypass methods
  4. Stooq.com (no key needed, often works on cloud)
  5. MT5 (Windows local only)
  6. Synthetic fallback

HOW TO GET FREE API KEYS (takes 2 minutes):
  Twelve Data: https://twelvedata.com/register (free = 800/day)
  Alpha Vantage: https://alphavantage.co/support/#api-key (free = 25/day)

Set in Railway Variables:
  TWELVE_DATA_KEY = your_key_here
  ALPHA_VANTAGE_KEY = your_key_here

Without keys: system tries Yahoo + Stooq automatically.
"""

import os
import requests
import pandas as pd
import numpy as np
import time
import logging
import platform
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── API Keys (set as environment variables) ───────────────────────────────────
TWELVE_DATA_KEY   = os.environ.get("TWELVE_DATA_KEY",   "").strip()
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "").strip()

# ── Symbols ───────────────────────────────────────────────────────────────────
MT5_SYMBOL = os.environ.get("MT5_SYMBOL", "XAUUSDm")  # Exness default

YF_SPOT    = "XAUUSD%3DX"   # spot gold
YF_FUTURES = "GC%3DF"       # futures fallback

YF_CONFIG = {
    "1m":  ("1d",   60),
    "5m":  ("5d",   300),
    "15m": ("60d",  900),
    "1h":  ("730d", 3600),
    "4h":  ("730d", 14400),
}

# Twelve Data interval names
TD_INTERVALS = {"1m":"1min","5m":"5min","15m":"15min","1h":"1h","4h":"4h"}


class MarketDataFetcher:
    def __init__(self):
        self._mt5        = None
        self._mt5_ok     = False
        self._last_price = 3285.0
        self._source     = "none"
        self._sess       = requests.Session()
        self._sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "application/json",
        })

        # Try MT5 on Windows
        if platform.system() == "Windows":
            self._init_mt5()
        else:
            logger.info("MT5: not available on cloud — using web data sources")

        # Log which API keys are configured
        if TWELVE_DATA_KEY:
            logger.info("Twelve Data API key: configured ✅")
        else:
            logger.info("Twelve Data API key: NOT SET — add TWELVE_DATA_KEY to Railway Variables")
        if ALPHA_VANTAGE_KEY:
            logger.info("Alpha Vantage API key: configured ✅")
        else:
            logger.info("Alpha Vantage API key: NOT SET — add ALPHA_VANTAGE_KEY to Railway Variables")

    # ── MT5 init ──────────────────────────────────────────────────────────────
    def _init_mt5(self):
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5
            if not mt5.initialize(timeout=5000):
                logger.warning(f"MT5: init failed — {mt5.last_error()}")
                return
            acct = mt5.account_info()
            if acct:
                logger.info(f"MT5: connected broker={acct.company}")
            sym = mt5.symbol_info(MT5_SYMBOL)
            if sym is None:
                for alt in ["XAUUSD","XAUUSDc","GOLD","XAUUSD."]:
                    if mt5.symbol_info(alt):
                        import builtins; builtins._MT5_SYM = alt
                        logger.info(f"MT5: using symbol '{alt}'")
                        self._mt5_ok = True; self._source = "MT5"; return
                return
            if not sym.visible:
                mt5.symbol_select(MT5_SYMBOL, True)
            self._mt5_ok = True; self._source = "MT5"
            logger.info(f"MT5: '{MT5_SYMBOL}' ready")
        except ImportError:
            logger.info("MT5: package not installed (normal on cloud)")
        except Exception as e:
            logger.error(f"MT5 init error: {e}")

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

        for tf in ["1m","5m","15m","1h","4h"]:
            df = self._get_ohlcv(tf, price)
            if df is not None and len(df) >= 30:
                result[tf] = df
                logger.info(f"  [{self._source}] {tf}: {len(df)} bars  last=${df['close'].iloc[-1]:.2f}")
            else:
                result[tf] = self._synthetic_ohlcv(tf, price)
                logger.warning(f"  {tf}: using synthetic fallback")

        result["news"] = self._news_events()
        return result

    # ── Price fetching ────────────────────────────────────────────────────────
    def _get_price(self):
        # 1. MT5 (local Windows only)
        if self._mt5_ok:
            p = self._mt5_price()
            if p: return p

        # 2. Twelve Data (free API key, works on cloud)
        if TWELVE_DATA_KEY:
            p = self._twelvedata_price()
            if p: return p

        # 3. Alpha Vantage (free API key, works on cloud)
        if ALPHA_VANTAGE_KEY:
            p = self._alphavantage_price()
            if p: return p

        # 4. Yahoo Finance (multiple bypass attempts)
        p = self._yf_price()
        if p: return p

        # 5. Stooq (no key, sometimes works on cloud)
        p = self._stooq_price()
        if p: return p

        # 6. Use last known + tiny noise
        logger.warning("All data sources failed — using last known price")
        self._source = "Synthetic (Demo only)"
        return round(self._last_price + np.random.normal(0, 0.5), 2)

    def _mt5_price(self):
        try:
            tick = self._mt5.symbol_info_tick(self._active_symbol())
            if tick and tick.bid > 0:
                return round((tick.bid + tick.ask) / 2, 2)
        except: pass
        return None

    def _twelvedata_price(self):
        """Twelve Data free API — 800 requests/day, works on Railway."""
        try:
            url = (f"https://api.twelvedata.com/price"
                   f"?symbol=XAU/USD&apikey={TWELVE_DATA_KEY}")
            r = self._sess.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if "price" in data:
                    price = round(float(data["price"]), 2)
                    self._source = "Twelve Data"
                    logger.info(f"  Twelve Data price: ${price}")
                    return price
                elif "code" in data:
                    logger.warning(f"Twelve Data error: {data.get('message','unknown')}")
        except Exception as e:
            logger.debug(f"Twelve Data price error: {e}")
        return None

    def _alphavantage_price(self):
        """Alpha Vantage free API — 25 requests/day, works on Railway."""
        try:
            url = (f"https://www.alphavantage.co/query"
                   f"?function=CURRENCY_EXCHANGE_RATE"
                   f"&from_currency=XAU&to_currency=USD"
                   f"&apikey={ALPHA_VANTAGE_KEY}")
            r = self._sess.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                rate = data.get("Realtime Currency Exchange Rate", {}).get("5. Exchange Rate")
                if rate:
                    price = round(float(rate), 2)
                    self._source = "Alpha Vantage"
                    logger.info(f"  Alpha Vantage price: ${price}")
                    return price
        except Exception as e:
            logger.debug(f"Alpha Vantage price error: {e}")
        return None

    def _yf_price(self):
        """Yahoo Finance — works on home IP, sometimes blocked on cloud."""
        for symbol, label in [(YF_SPOT,"spot"), (YF_FUTURES,"futures")]:
            for host in ["query1","query2"]:
                try:
                    url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
                    r   = self._sess.get(url, timeout=8)
                    if r.status_code != 200:
                        continue
                    closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
                    closes = [c for c in closes if c is not None]
                    if closes:
                        price = round(closes[-1], 2)
                        self._source = f"Yahoo ({label})"
                        logger.info(f"  Yahoo {label} price: ${price}")
                        return price
                except Exception as e:
                    logger.debug(f"YF price error ({symbol}): {e}")
        return None

    def _stooq_price(self):
        """Stooq.com — no API key, sometimes accessible from cloud."""
        try:
            url = "https://stooq.com/q/l/?s=xauusd&f=l&e=json"
            r   = self._sess.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                price = float(data.get("l", 0) or data.get("close", 0))
                if price > 100:
                    self._source = "Stooq"
                    logger.info(f"  Stooq price: ${price}")
                    return round(price, 2)
        except Exception as e:
            logger.debug(f"Stooq price error: {e}")
        return None

    # ── OHLCV fetching ────────────────────────────────────────────────────────
    def _get_ohlcv(self, interval, current_price):
        if self._mt5_ok:
            df = self._mt5_ohlcv(interval)
            if df is not None: return df

        if TWELVE_DATA_KEY:
            df = self._twelvedata_ohlcv(interval, current_price)
            if df is not None: return df

        if ALPHA_VANTAGE_KEY:
            df = self._alphavantage_ohlcv(interval, current_price)
            if df is not None: return df

        df = self._yf_ohlcv(interval, current_price)
        if df is not None: return df

        return None

    def _mt5_ohlcv(self, interval):
        try:
            mt5 = self._mt5
            tf_map = {
                "1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5,
                "15m":mt5.TIMEFRAME_M15,"1h": mt5.TIMEFRAME_H1,
                "4h": mt5.TIMEFRAME_H4,
            }
            n = {"1m":500,"5m":500,"15m":400,"1h":500,"4h":300}.get(interval,300)
            rates = mt5.copy_rates_from_pos(self._active_symbol(), tf_map[interval], 0, n)
            if rates is None or len(rates) == 0: return None
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.rename(columns={"tick_volume":"volume"})
            return df.set_index("time")[["open","high","low","close","volume"]].dropna()
        except Exception as e:
            logger.debug(f"MT5 OHLCV error ({interval}): {e}")
            return None

    def _twelvedata_ohlcv(self, interval, current_price):
        """Twelve Data OHLCV — free tier supports 1m/5m/15m/1h/4h."""
        td_interval = TD_INTERVALS.get(interval)
        if not td_interval: return None

        # Output size based on interval
        output_size = {"1m":500,"5m":500,"15m":400,"1h":500,"4h":300}.get(interval,300)

        try:
            url = (f"https://api.twelvedata.com/time_series"
                   f"?symbol=XAU/USD&interval={td_interval}"
                   f"&outputsize={output_size}&apikey={TWELVE_DATA_KEY}")
            r = self._sess.get(url, timeout=15)
            if r.status_code != 200: return None
            data = r.json()
            if "values" not in data:
                logger.warning(f"Twelve Data OHLCV error: {data.get('message','no values')}")
                return None

            rows = data["values"]
            df = pd.DataFrame(rows)
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
            df = df.rename(columns={"datetime":"time"})
            df = df.set_index("time")
            for col in ["open","high","low","close","volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df[["open","high","low","close","volume"]].dropna()
            df = df.sort_index()   # Twelve Data returns newest first

            # Align to current price
            if len(df) > 0:
                shift = current_price - float(df["close"].iloc[-1])
                if abs(shift) < current_price * 0.02:
                    for col in ["open","high","low","close"]:
                        df[col] = (df[col] + shift).round(2)

            logger.debug(f"Twelve Data OHLCV {interval}: {len(df)} bars")
            return df if len(df) >= 30 else None

        except Exception as e:
            logger.debug(f"Twelve Data OHLCV error ({interval}): {e}")
            return None

    def _alphavantage_ohlcv(self, interval, current_price):
        """Alpha Vantage OHLCV — very limited free tier (25 req/day)."""
        # Only use for higher timeframes to conserve API calls
        if interval in ("1m","5m"): return None

        av_func = {
            "15m":"FX_INTRADAY","1h":"FX_INTRADAY","4h":"FX_INTRADAY"
        }.get(interval)
        av_interval = {"15m":"15min","1h":"60min","4h":"60min"}.get(interval)
        if not av_func: return None

        try:
            url = (f"https://www.alphavantage.co/query"
                   f"?function={av_func}&from_symbol=XAU&to_symbol=USD"
                   f"&interval={av_interval}&outputsize=compact"
                   f"&apikey={ALPHA_VANTAGE_KEY}")
            r = self._sess.get(url, timeout=15)
            if r.status_code != 200: return None
            data = r.json()

            key = f"Time Series FX ({av_interval})"
            if key not in data: return None

            ts = data[key]
            rows = []
            for dt_str, vals in ts.items():
                rows.append({
                    "time":   pd.to_datetime(dt_str, utc=True),
                    "open":   float(vals["1. open"]),
                    "high":   float(vals["2. high"]),
                    "low":    float(vals["3. low"]),
                    "close":  float(vals["4. close"]),
                    "volume": 1000,
                })
            df = pd.DataFrame(rows).set_index("time").sort_index()

            if len(df) > 0:
                shift = current_price - float(df["close"].iloc[-1])
                if abs(shift) < current_price * 0.02:
                    for col in ["open","high","low","close"]:
                        df[col] = (df[col] + shift).round(2)

            return df if len(df) >= 30 else None

        except Exception as e:
            logger.debug(f"Alpha Vantage OHLCV error ({interval}): {e}")
            return None

    def _yf_ohlcv(self, interval, current_price):
        range_param, _ = YF_CONFIG.get(interval, ("1d",60))
        for symbol in [YF_SPOT, YF_FUTURES]:
            try:
                url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                       f"?interval={interval}&range={range_param}")
                r   = self._sess.get(url, timeout=10)
                if r.status_code != 200: continue
                res = r.json()["chart"]["result"][0]
                q   = res["indicators"]["quote"][0]
                df  = pd.DataFrame({
                    "open": q["open"], "high": q["high"],
                    "low":  q["low"],  "close":q["close"], "volume":q["volume"],
                }, index=pd.to_datetime(res["timestamp"], unit="s", utc=True))
                df  = df.dropna()
                if len(df) < 30: continue
                shift = current_price - df["close"].iloc[-1]
                if abs(shift) < current_price * 0.02:
                    for col in ["open","high","low","close"]:
                        df[col] = (df[col] + shift).round(2)
                return df
            except Exception as e:
                logger.debug(f"YF OHLCV error ({interval}): {e}")
        return None

    # ── Synthetic fallback ────────────────────────────────────────────────────
    def _synthetic_ohlcv(self, interval, current_price, n_bars=300):
        _, bar_sec = YF_CONFIG.get(interval, ("1d",60))
        vol = {"1m":0.0004,"5m":0.0008,"15m":0.0012,"1h":0.002,"4h":0.004}.get(interval,0.001)
        np.random.seed(int(time.time() / bar_sec))
        returns = np.random.normal(0, vol, n_bars)
        closes  = current_price * np.exp(np.cumsum(returns))
        closes  = closes * (current_price / closes[-1])
        bv      = vol * current_price
        highs   = closes + np.abs(np.random.normal(0, bv*0.6, n_bars))
        lows    = closes - np.abs(np.random.normal(0, bv*0.6, n_bars))
        opens   = np.roll(closes, 1); opens[0] = closes[0]
        volumes = np.random.lognormal(10, 0.5, n_bars).astype(int)
        now_ts  = int(time.time())
        ts      = [now_ts - (n_bars-i)*bar_sec for i in range(n_bars)]
        self._source = "Synthetic (Demo only)"
        return pd.DataFrame({
            "open": np.round(opens,2), "high": np.round(highs,2),
            "low":  np.round(lows,2),  "close":np.round(closes,2),
            "volume": volumes,
        }, index=pd.to_datetime(ts, unit="s", utc=True))

    # ── MT5 info ──────────────────────────────────────────────────────────────
    def get_mt5_info(self):
        if not self._mt5_ok or self._mt5 is None:
            configured = bool(TWELVE_DATA_KEY or ALPHA_VANTAGE_KEY)
            return {
                "connected": False,
                "reason":    "MT5 not connected (cloud deployment — using web API)",
                "cloud_data_ok": configured,
                "twelve_data":   bool(TWELVE_DATA_KEY),
                "alpha_vantage": bool(ALPHA_VANTAGE_KEY),
            }
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
            {"date":"2026-05-02","time":"12:30 UTC","event":"US Non-Farm Payrolls",        "impact":"HIGH",  "currency":"USD"},
            {"date":"2026-05-06","time":"14:00 UTC","event":"ISM Services PMI",            "impact":"MEDIUM","currency":"USD"},
            {"date":"2026-05-07","time":"18:00 UTC","event":"FOMC Meeting Minutes",        "impact":"HIGH",  "currency":"USD"},
            {"date":"2026-05-13","time":"12:30 UTC","event":"US CPI Inflation",            "impact":"HIGH",  "currency":"USD"},
        ]
