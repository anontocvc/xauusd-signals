"""
XAUUSD Pro Signal System — Flask Server v4.0
============================================
- Background monitor runs every 60s (1M candle interval)
- Sends Telegram alerts instantly on SNIPER/HIGH signals
- Deploys free to Railway / Render / Replit
- Works on laptop + accessible from phone
"""
from flask import Flask, render_template, send_from_directory, Response
import threading, time, logging, json, socket, os
import numpy as np

from core.market_data     import MarketDataFetcher
from core.analyzer        import TradingAnalyzer
from core.signal_engine   import SignalEngine
from core.monitor         import SignalMonitor
from core.telegram_alerts import send_startup_message, test_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# ── App + shared state ────────────────────────────────────────────────────────
app     = Flask(__name__)
fetcher = MarketDataFetcher()
analyzer= TradingAnalyzer()
engine  = SignalEngine()

_cache  = {}                          # shared between monitor + Flask routes
_lock   = threading.Lock()            # protects _cache

monitor = SignalMonitor(fetcher, analyzer, engine, _cache, _lock)

# ── JSON encoder (numpy-safe) ─────────────────────────────────────────────────
class SE(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, np.integer):  return int(o)
        if isinstance(o, np.floating): return round(float(o), 4)
        if isinstance(o, np.bool_):    return bool(o)
        if isinstance(o, np.ndarray):  return o.tolist()
        if isinstance(o, bool):        return bool(o)
        return super().default(o)

def jresp(data):
    try:    return Response(json.dumps(data, cls=SE), mimetype="application/json")
    except Exception as e:
        return Response(json.dumps({"status":"error","error":str(e)}),
                        mimetype="application/json")

# ── Network helper ────────────────────────────────────────────────────────────
def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except: return "127.0.0.1"

# ── Forced refresh (for /api/refresh button) ──────────────────────────────────
def _force_refresh():
    """Run one analysis cycle immediately and update cache."""
    data     = fetcher.get_all_timeframes()
    analysis = analyzer.full_analysis(data)
    signals  = engine.generate_signals(analysis, data)
    payload  = {
        "analysis":    analysis,
        "signals":     signals,
        "timestamp":   time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "price":       float(data.get("current_price", 0)),
        "data_source": data.get("data_source", "unknown"),
        "mt5_info":    fetcher.get_mt5_info(),
        "status":      "live",
        "monitor":     monitor.get_status(),
    }
    with _lock: _cache.clear(); _cache.update(payload)
    return payload

# ── Page routes ───────────────────────────────────────────────────────────────
@app.route("/")
def index():  return render_template("index.html")

@app.route("/mobile")
def mobile(): return render_template("mobile.html")

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static","manifest.json",
                               mimetype="application/manifest+json")

@app.route("/sw.js")
def sw():
    r = send_from_directory("static","sw.js", mimetype="application/javascript")
    r.headers["Service-Worker-Allowed"] = "/"
    r.headers["Cache-Control"] = "no-cache"
    return r

@app.route("/static/<path:fn>")
def static_file(fn): return send_from_directory("static", fn)

# ── API routes ────────────────────────────────────────────────────────────────
@app.route("/api/analysis")
def get_analysis():
    try:
        with _lock:
            if _cache: return jresp(dict(_cache))
        # Cache empty — do first refresh synchronously
        return jresp(_force_refresh())
    except Exception as e:
        return jresp({"status":"error","error":str(e),
                      "timestamp":time.strftime("%Y-%m-%d %H:%M:%S UTC")})

@app.route("/api/refresh")
def api_refresh():
    try:    return jresp(_force_refresh())
    except Exception as e:
        return jresp({"status":"error","error":str(e),
                      "timestamp":time.strftime("%Y-%m-%d %H:%M:%S UTC")})

@app.route("/api/health")
def health():
    return jresp({
        "status":   "ok",
        "timestamp":time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source":   fetcher._source,
        "mt5":      fetcher._mt5_ok,
        "monitor":  monitor.get_status(),
        "price":    _cache.get("price", 0),
    })

@app.route("/api/monitor")
def monitor_status():
    """Live monitor stats — useful for debugging."""
    return jresp(monitor.get_status())

@app.route("/api/network")
def network():
    ip = local_ip()
    return jresp({
        "local_ip":    ip,
        "mobile_url":  f"http://{ip}:5000/mobile",
        "desktop_url": f"http://{ip}:5000",
    })

@app.route("/api/mt5")
def mt5(): return jresp(fetcher.get_mt5_info())


@app.route("/api/test_telegram")
def test_telegram_route():
    """Test Telegram from browser — open this URL to check if Telegram works."""
    import os
    from core.telegram_alerts import _send, is_configured
    token = os.environ.get("TELEGRAM_TOKEN","").strip()
    chat  = os.environ.get("TELEGRAM_CHAT_ID","").strip()

    if not token:
        return jresp({"status":"error","error":"TELEGRAM_TOKEN not set in environment variables",
                      "fix":"Add TELEGRAM_TOKEN in Railway → Variables tab"})
    if not chat:
        return jresp({"status":"error","error":"TELEGRAM_CHAT_ID not set in environment variables",
                      "fix":"Add TELEGRAM_CHAT_ID in Railway → Variables tab"})

    # Verify token via getMe
    try:
        import requests as req
        check = req.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if check.status_code != 200:
            return jresp({"status":"error","error":f"Invalid token — Telegram says: {check.json().get('description','unknown')}",
                          "fix":"Get correct token from @BotFather on Telegram"})
        bot = check.json()["result"]
    except Exception as e:
        return jresp({"status":"error","error":f"Cannot reach Telegram: {str(e)}",
                      "fix":"Check internet connection on Railway server"})

    # Send test message
    ok = _send("🧪 <b>Telegram Test from Railway</b>\n\nYour XAUUSD signal bot is connected!\nAlerts will arrive here for SNIPER and HIGH signals.")
    if ok:
        return jresp({"status":"ok","message":"Test message sent! Check your Telegram app.",
                      "bot_name": bot.get("username"), "chat_id": chat})
    else:
        return jresp({"status":"error",
                      "error":"Bot token valid but message failed — chat_id may be wrong",
                      "fix":"Make sure you sent /start to your bot in Telegram first",
                      "chat_id_used": chat, "bot_name": bot.get("username")})


@app.route("/api/config")
def config_check():
    """Check all environment variables are set correctly."""
    import os
    return jresp({
        "telegram_token_set":   bool(os.environ.get("TELEGRAM_TOKEN","").strip()),
        "telegram_chat_set":    bool(os.environ.get("TELEGRAM_CHAT_ID","").strip()),
        "port":                 os.environ.get("PORT","5000"),
        "refresh_interval":     os.environ.get("REFRESH_INTERVAL","60"),
        "platform":             __import__("platform").system(),
        "mt5_connected":        fetcher._mt5_ok,
        "data_source":          fetcher._source or "none",
        "hint": "Visit /api/test_telegram to test your Telegram bot"
    })

@app.route("/api/qr")
def qr():
    ip  = local_ip()
    url = f"http://{ip}:5000/mobile"
    try:
        import qrcode, io, base64  # pip install qrcode[pil] pillow
        q = qrcode.QRCode(version=None,
                          error_correction=qrcode.constants.ERROR_CORRECT_M,
                          box_size=8, border=3)
        q.add_data(url); q.make(fit=True)
        img = q.make_image(fill_color="#f59e0b", back_color="#0a0c10")
        buf = io.BytesIO(); img.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        qr_html = (f'<img src="data:image/png;base64,{b64}" '
                   f'style="width:220px;height:220px;border-radius:8px">')
    except (ImportError, Exception):  # graceful fallback — qrcode not required
        qr_html = (f'<div style="width:220px;height:220px;background:#161b27;'
                   f'border:2px solid #f59e0b;border-radius:12px;display:flex;'
                   f'align-items:center;justify-content:center;flex-direction:column;'
                   f'gap:8px;font-size:11px;color:#94a3b8;text-align:center;padding:16px">'
                   f'<span style="font-size:40px">📱</span>'
                   f'<span style="color:#f59e0b;word-break:break-all">{url}</span>'
                   f'<span style="font-size:10px;color:#64748b">pip install qrcode for real QR</span>'
                   f'</div>')
    html = (f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Mobile Access</title>'
            f'<style>body{{background:#0a0c10;color:#e2e8f0;font-family:monospace;'
            f'display:flex;align-items:center;justify-content:center;'
            f'min-height:100vh;flex-direction:column;gap:12px;padding:20px}}'
            f'h2{{color:#f59e0b;font-size:16px;letter-spacing:2px}}'
            f'.url{{background:#161b27;border:1px solid #f59e0b;border-radius:8px;'
            f'padding:10px 18px;color:#f59e0b;cursor:pointer;font-size:13px;'
            f'word-break:break-all;max-width:340px;text-align:center}}'
            f'.btn{{background:#f59e0b;color:#000;border:none;border-radius:8px;'
            f'padding:10px 28px;font-size:13px;font-weight:700;cursor:pointer;'
            f'text-decoration:none;display:block;text-align:center}}'
            f'.steps{{background:#111520;border:1px solid #1e2a3a;border-radius:10px;'
            f'padding:14px;max-width:340px;font-size:12px;color:#94a3b8;line-height:1.9;width:100%}}'
            f'.steps b{{color:#e2e8f0}}</style></head><body>'
            f'<h2>OPEN ON YOUR PHONE</h2>{qr_html}'
            f'<div class="url" onclick="navigator.clipboard&&'
            f'navigator.clipboard.writeText(\'{url}\').then(()=>alert(\'Copied!\'))">'
            f'{url}</div>'
            f'<a href="{url}" target="_blank" class="btn">Open Mobile Dashboard</a>'
            f'<div class="steps">'
            f'<b>Android Chrome:</b><br>1. Same WiFi as laptop<br>'
            f'2. Open Chrome → enter URL<br>3. Menu (⋮) → Add to Home screen<br><br>'
            f'<b>iPhone Safari:</b><br>1. Same WiFi as laptop<br>'
            f'2. Open Safari → enter URL<br>3. Share (↑) → Add to Home Screen<br><br>'
            f'<b>From anywhere:</b><br>Run: <span style="color:#f59e0b">ngrok http 5000</span>'
            f'</div></body></html>')
    return Response(html, mimetype="text/html")

# ── Startup ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5000))
    ip   = local_ip()

    # Start background monitor (every 60 seconds)
    monitor.start()

    # Send Telegram startup message
    send_startup_message(ip)

    print("\n" + "="*58)
    print("  XAUUSD PRO SIGNAL SYSTEM  v4.0")
    print("="*58)
    print(f"  Laptop   ->  http://localhost:{PORT}")
    print(f"  Mobile   ->  http://{ip}:{PORT}/mobile")
    print(f"  QR Code  ->  http://localhost:{PORT}/api/qr")
    print(f"  Monitor  ->  http://localhost:{PORT}/api/monitor")
    print(f"  MT5      ->  {'Connected' if fetcher._mt5_ok else 'Not connected'}")
    print(f"  Source   ->  {fetcher._source or 'initializing'}")
    tg = os.environ.get("TELEGRAM_TOKEN","")
    print(f"  Telegram ->  {'Configured ✓' if tg else 'Not set (see TELEGRAM_SETUP.md)'}")
    print(f"  Interval ->  60s (1M candle refresh)")
    print("="*58)
    print(f"  Monitor running every 60s in background")
    print(f"  Telegram alerts on SNIPER + HIGH signals")
    print("="*58 + "\n")

    app.run(debug=False, host="0.0.0.0", port=PORT, use_reloader=False)
