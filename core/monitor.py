"""
XAUUSD 1-Minute Signal Monitor
================================
Runs inside the Flask server as a background thread.
Checks for new signals every 60 seconds (1 minute).
Sends Telegram alerts instantly when signals are found.

This replaces GitHub Actions completely.
Deploy to Railway/Render for FREE 24/7 operation.

Why 60 seconds and not 1 second?
- XAUUSD 1M candle forms every 60 seconds
- Checking faster than that gives no new data
- 60s is the natural refresh rate for 1M analysis
"""

import time
import logging
import threading
import os

logger = logging.getLogger(__name__)


class SignalMonitor:
    """
    Background thread that runs full market analysis every 60 seconds.
    Sends Telegram alerts for new SNIPER/HIGH signals.
    Completely independent of the Flask web server.
    """

    def __init__(self, fetcher, analyzer, engine, cache, lock):
        self.fetcher  = fetcher
        self.analyzer = analyzer
        self.engine   = engine
        self.cache    = cache
        self.lock     = lock

        self.running        = False
        self.cycle_count    = 0
        self.alerts_sent    = 0
        self.last_price     = 0
        self.last_cycle_ms  = 0
        self.errors         = 0
        self.interval       = int(os.environ.get("REFRESH_INTERVAL", 60))  # seconds

    def start(self):
        """Start the background monitoring thread."""
        self.running = True
        t = threading.Thread(target=self._loop, daemon=True, name="SignalMonitor")
        t.start()
        logger.info(f"SignalMonitor started — interval={self.interval}s")
        return t

    def stop(self):
        self.running = False

    def _loop(self):
        """Main monitoring loop — runs every self.interval seconds."""
        # Wait a few seconds after startup before first run
        time.sleep(5)

        while self.running:
            t_start = time.time()
            try:
                self._run_cycle()
                self.errors = 0
            except Exception as e:
                self.errors += 1
                logger.error(f"Monitor cycle error #{self.errors}: {e}")
                if self.errors >= 10:
                    logger.critical("10 consecutive errors — monitor sleeping 10 min")
                    time.sleep(600)
                    self.errors = 0

            # Sleep precisely to maintain interval
            elapsed = time.time() - t_start
            sleep_time = max(1, self.interval - elapsed)
            self.last_cycle_ms = int(elapsed * 1000)
            time.sleep(sleep_time)

    def _run_cycle(self):
        """Single analysis cycle."""
        import numpy as np
        import json

        self.cycle_count += 1

        # 1. Fetch market data
        data     = self.fetcher.get_all_timeframes()
        price    = data.get("current_price", 0)
        source   = data.get("data_source", "unknown")

        # 2. Run full SMC/ICT analysis
        analysis = self.analyzer.full_analysis(data)
        signals  = self.engine.generate_signals(analysis, data)
        sigs     = signals.get("signals", [])
        summary  = signals.get("summary", {})

        # 3. Build payload (safe JSON serialization)
        class _SE(json.JSONEncoder):
            def default(self, o):
                if isinstance(o, np.integer):  return int(o)
                if isinstance(o, np.floating): return round(float(o), 4)
                if isinstance(o, np.bool_):    return bool(o)
                if isinstance(o, np.ndarray):  return o.tolist()
                if isinstance(o, bool):        return bool(o)
                return super().default(o)

        payload = {
            "analysis":    analysis,
            "signals":     signals,
            "timestamp":   time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "price":       float(price),
            "data_source": source,
            "mt5_info":    self.fetcher.get_mt5_info(),
            "status":      "live",
            "monitor": {
                "cycle":        self.cycle_count,
                "alerts_sent":  self.alerts_sent,
                "cycle_ms":     self.last_cycle_ms,
                "interval_s":   self.interval,
            }
        }

        # Validate JSON before storing
        json.dumps(payload, cls=_SE)

        # 4. Update shared cache (thread-safe)
        with self.lock:
            self.cache.clear()
            self.cache.update(payload)

        # 5. Send Telegram alerts
        from core.telegram_alerts import check_and_send_alerts
        sent = check_and_send_alerts(signals, analysis)
        if sent > 0:
            self.alerts_sent += sent
            logger.info(f"Telegram alert sent! Total today: {self.alerts_sent}")

        # 6. Log cycle summary
        best = sigs[0] if sigs else None
        logger.info(
            f"Cycle {self.cycle_count:04d} | "
            f"${price:.2f} | "
            f"src={source[:5]} | "
            f"bias={summary.get('htf_bias','?')[:8]} | "
            f"phase={summary.get('market_phase','?')[:8]} | "
            f"sigs={len(sigs)} | "
            f"best={best['setup_type'] if best else 'none'} | "
            f"{self.last_cycle_ms}ms"
        )

        self.last_price = price

    def get_status(self) -> dict:
        """Return monitor status for the /api/health endpoint."""
        return {
            "running":      self.running,
            "cycle":        self.cycle_count,
            "alerts_sent":  self.alerts_sent,
            "last_price":   self.last_price,
            "cycle_ms":     self.last_cycle_ms,
            "interval_s":   self.interval,
            "errors":       self.errors,
        }
