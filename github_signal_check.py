"""
GitHub Actions Signal Check Script
====================================
Runs as a standalone script (no Flask server needed).
Fetches XAUUSD data, runs full SMC/ICT analysis,
and sends Telegram alerts for SNIPER/HIGH signals.

Used by: .github/workflows/signal_monitor.yml
Runs every 15 minutes during London + NY sessions.
"""

import sys
import os
import time
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("signal_log.txt")
    ]
)
logger = logging.getLogger(__name__)

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.market_data    import MarketDataFetcher
from core.analyzer       import TradingAnalyzer
from core.signal_engine  import SignalEngine
from core.telegram_alerts import (
    check_and_send_alerts,
    test_telegram,
    _send_message
)


def run_signal_check():
    logger.info("=" * 50)
    logger.info("XAUUSD Signal Check — GitHub Actions")
    logger.info("=" * 50)

    start = time.time()

    # ── 1. Fetch market data ──────────────────────────────────────────────────
    logger.info("Fetching market data...")
    fetcher = MarketDataFetcher()
    data    = fetcher.get_all_timeframes()
    price   = data.get("current_price", 0)
    source  = data.get("data_source", "unknown")
    logger.info(f"  Price: ${price:.2f}  Source: {source}")

    if price <= 0:
        logger.error("Failed to get valid price. Exiting.")
        sys.exit(1)

    # ── 2. Run analysis ───────────────────────────────────────────────────────
    logger.info("Running SMC/ICT analysis...")
    analyzer = TradingAnalyzer()
    analysis = analyzer.full_analysis(data)
    htf_bias = analysis.get("htf_bias", "neutral")
    logger.info(f"  HTF bias: {htf_bias}")

    # ── 3. Generate signals ───────────────────────────────────────────────────
    logger.info("Generating signals...")
    eng     = SignalEngine()
    signals = eng.generate_signals(analysis, data)
    sigs    = signals.get("signals", [])
    summary = signals.get("summary", {})

    logger.info(f"  Signals found: {len(sigs)}")
    logger.info(f"  Session: {summary.get('session','—')}")
    logger.info(f"  Phase:   {summary.get('market_phase','—')}")
    logger.info(f"  In killzone: {summary.get('in_killzone', False)}")

    for s in sigs:
        logger.info(
            f"  [{s['timeframe'].upper()}] {s['direction']} "
            f"{s['setup_type'].upper()} "
            f"score={s['score']} conf={s['confidence']}% "
            f"entry=${s['entry']} sl=${s['sl']} tp1=${s['tp1']}"
        )

    # ── 4. Send Telegram alerts ───────────────────────────────────────────────
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        logger.warning("TELEGRAM_TOKEN not set — alerts disabled")
        logger.info("Add TELEGRAM_TOKEN and TELEGRAM_CHAT_ID to GitHub Secrets")
    else:
        logger.info("Checking for alert-worthy signals...")
        sent = check_and_send_alerts(signals, analysis)
        logger.info(f"  Alerts sent: {sent}")

        if not sigs:
            logger.info("  No valid signals this cycle — no alert sent")
        elif all(s["setup_type"] not in ("sniper", "high") for s in sigs):
            logger.info("  Only MEDIUM/LOW signals — no alert (quality threshold)")

    # ── 5. Save summary log ───────────────────────────────────────────────────
    elapsed = round(time.time() - start, 2)
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "price":     price,
        "source":    source,
        "htf_bias":  htf_bias,
        "session":   summary.get("session", "—"),
        "phase":     summary.get("market_phase", "—"),
        "signals":   len(sigs),
        "best":      sigs[0]["setup_type"] if sigs else "none",
        "elapsed_s": elapsed,
    }
    logger.info(f"Completed in {elapsed}s")
    logger.info(json.dumps(log_entry))

    return len(sigs)


if __name__ == "__main__":
    try:
        count = run_signal_check()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Try to send error alert
        try:
            from core.telegram_alerts import _send_message
            _send_message(f"⚠️ <b>Signal check error</b>\n\n<code>{str(e)[:200]}</code>")
        except Exception:
            pass
        sys.exit(1)
