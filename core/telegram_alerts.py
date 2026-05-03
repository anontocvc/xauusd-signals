"""
Telegram Alert Bot - XAUUSD Signals v4.1
Fixes: better error messages, test command, env var debugging
"""
import os, requests, logging, time, json

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

_sent_ids       = set()
_last_sent_time = 0
MIN_ALERT_GAP   = 300   # 5 min between alerts minimum


def is_configured():
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def _send(text: str) -> bool:
    if not TELEGRAM_TOKEN:
        logger.debug("Telegram: TELEGRAM_TOKEN not set — skipping")
        return False
    if not TELEGRAM_CHAT_ID:
        logger.debug("Telegram: TELEGRAM_CHAT_ID not set — skipping")
        return False
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=15)
        if resp.status_code == 200:
            logger.info("✅ Telegram alert sent OK")
            return True
        else:
            error_data = resp.json()
            logger.warning(f"Telegram error {resp.status_code}: {error_data.get('description','unknown')}")
            return False
    except requests.exceptions.Timeout:
        logger.error("Telegram: request timed out (15s)")
        return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def check_and_send_alerts(signals_data: dict, analysis_data: dict) -> int:
    global _last_sent_time
    if not is_configured(): return 0

    signals = signals_data.get("signals", [])
    summary = signals_data.get("summary", {})
    sent    = 0
    if not signals: return 0
    if time.time() - _last_sent_time < MIN_ALERT_GAP: return 0

    for sig in signals:
        if sig.get("setup_type") not in ("sniper", "high"): continue
        sig_id = sig.get("id", "")
        if sig_id in _sent_ids: continue
        if _send(_format_signal_message(sig, summary)):
            _sent_ids.add(sig_id)
            _last_sent_time = time.time()
            sent += 1
            break  # send best signal only per cycle

    if len(_sent_ids) > 200: _sent_ids.clear()
    return sent


def _format_signal_message(sig: dict, summary: dict) -> str:
    d   = sig.get("direction","—")
    tf  = sig.get("timeframe","—").upper()
    typ = sig.get("setup_type","—").upper()
    em  = "🎯" if typ=="SNIPER" else "⭐"
    de  = "🟢" if d=="BUY" else "🔴"
    tp_details = sig.get("tp_details", [])
    tp_lines = ""
    for td in tp_details[:3]:
        src = td.get("source","")
        conf = "★" * td.get("confidence",1)
        tp_lines += f"\n  TP{td['tp'][-1]} ${td['price']}  1:{td['rr']}  [{src}] {conf} — {td['description'][:40]}"

    reasons = sig.get("confluence", sig.get("reasons", []))
    conf_text = "\n".join(f"  • {r}" for r in reasons[:4])

    return (
        f"{em} <b>{typ} — {de} {d} XAUUSD {tf}</b>\n\n"
        f"💰 <b>Entry:</b>  ${sig.get('entry',0)}\n"
        f"🛑 <b>SL:</b>     ${sig.get('sl',0)}  ({sig.get('sl_pips',0)} pips)\n"
        f"{tp_lines or f'TP1: ${sig.get(chr(116)+chr(112)+chr(49),0)}  1:{sig.get(chr(114)+chr(114)+chr(49),0)}'}\n\n"
        f"📊 Score: {sig.get('score',0)}/10  Conf: {sig.get('confidence',0)}%\n"
        f"📦 Lot: {sig.get('lot_size',0.01)}  Risk: {sig.get('risk_pct',1)}% (${sig.get('risk_usd',0)})\n"
        f"🔒 HTF: {summary.get('htf_bias','—').replace('_',' ').upper()}\n"
        f"📍 Phase: {sig.get('market_phase','—').upper()}\n"
        f"🕐 Session: {summary.get('session','—')}\n\n"
        f"<b>Confluence:</b>\n{conf_text}\n\n"
        f"⏰ {sig.get('timestamp','')}\n"
        f"<i>XAU Signal System v4.1</i>"
    )


def send_startup_message(local_ip: str = "") -> bool:
    if not is_configured(): return False
    url = f"http://{local_ip}:5000/mobile" if local_ip else "http://localhost:5000/mobile"
    return _send(
        f"⚡ <b>XAUUSD Signal Server Started</b>\n\n"
        f"🔄 Monitoring every 60s\n"
        f"📱 Dashboard: <code>{url}</code>\n"
        f"📡 Data: {'MT5 Real-time' if not local_ip else 'Yahoo Finance'}\n\n"
        f"<i>You will receive alerts here for SNIPER and HIGH signals\n"
        f"Active sessions: Asian, London, New York</i>"
    )


def send_daily_summary(signals_sent: int, price: float, htf_bias: str) -> bool:
    if not is_configured(): return False
    return _send(
        f"📋 <b>Daily Summary — XAUUSD</b>\n\n"
        f"Alerts today: {signals_sent}\n"
        f"Current price: ${price:.2f}\n"
        f"HTF bias: {htf_bias.replace('_',' ').upper()}"
    )


def test_telegram() -> bool:
    """
    Test Telegram connection. Run directly:
      python core/telegram_alerts.py
    Or set env vars first:
      set TELEGRAM_TOKEN=your_token
      set TELEGRAM_CHAT_ID=your_chat_id
      python core/telegram_alerts.py
    """
    print("\n" + "="*50)
    print("  TELEGRAM CONNECTION TEST")
    print("="*50)

    token = os.environ.get("TELEGRAM_TOKEN","").strip()
    chat  = os.environ.get("TELEGRAM_CHAT_ID","").strip()

    if not token:
        print("❌ TELEGRAM_TOKEN not set")
        print()
        print("  Fix: set TELEGRAM_TOKEN=your_token_here")
        print("  Get token: Telegram → @BotFather → /newbot")
        return False

    if not chat:
        print("❌ TELEGRAM_CHAT_ID not set")
        print()
        print("  Fix: set TELEGRAM_CHAT_ID=your_chat_id")
        print("  Get ID: Telegram → @userinfobot → /start")
        return False

    print(f"  Token:   {token[:8]}...{token[-4:]}")
    print(f"  Chat ID: {chat}")
    print()
    print("  Sending test message...")

    # First verify bot token is valid
    try:
        check = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10
        )
        if check.status_code != 200:
            print(f"❌ Invalid token — Telegram returned: {check.status_code}")
            print(f"   Response: {check.text[:200]}")
            return False
        bot_info = check.json().get("result", {})
        print(f"  Bot name: @{bot_info.get('username','unknown')}")
    except Exception as e:
        print(f"❌ Cannot reach Telegram API: {e}")
        print("   Check internet connection")
        return False

    # Send test message
    ok = _send(
        "✅ <b>XAUUSD Signal Bot — Connected!</b>\n\n"
        "You will receive trade alerts here.\n"
        "Signals fire for SNIPER and HIGH setups\n"
        "during Asian, London, and NY sessions.\n\n"
        "<i>Test successful — system is working.</i>"
    )

    if ok:
        print("✅ Test message sent! Check your Telegram.")
        print("="*50)
    else:
        print("❌ Message failed to send")
        print()
        print("  Possible causes:")
        print("  1. Chat ID wrong — must be a number like 987654321")
        print("  2. You never started the bot — search your bot on Telegram and send /start")
        print("  3. Token has extra spaces — copy it exactly")
        print("="*50)
    return ok


if __name__ == "__main__":
    test_telegram()
