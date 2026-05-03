# Setup page HTML generator - separate file to avoid encoding issues
def get_setup_html(src, td_key, av_key, tg_tok, tg_cid):
    is_synthetic = "Synthetic" in (src or "") or not src or src == "none"

    def row(label, ok, value="", fix=""):
        icon  = "OK" if ok else "MISSING"
        color = "#10b981" if ok else "#ef4444"
        return (f'<tr><td style="padding:10px 14px;color:#94a3b8;font-size:13px">{label}</td>'
                f'<td style="padding:10px 14px"><span style="color:{color};font-weight:600">{icon}: {value}</span></td>'
                f'<td style="padding:10px 14px;color:#64748b;font-size:12px">{fix}</td></tr>')

    warn_box = ""
    if is_synthetic:
        warn_box = """<div class="box warn">
<p style="color:#f59e0b;font-weight:600;font-size:14px">DATA SOURCE = SYNTHETIC — signals use fake data!</p>
<p>Yahoo Finance blocks Railway cloud servers. Add a free Twelve Data API key to fix this.</p>
</div>"""

    tg_box = ""
    if tg_tok and tg_cid:
        tg_box = "<p style='color:#10b981'>Telegram is configured and active.</p>"
    else:
        tg_box = """<p>Get instant trade alerts on your phone.</p>
<p><b>Setup:</b></p>
<p>1. Open Telegram - search @BotFather - /newbot - copy the TOKEN</p>
<p>2. Search @userinfobot - /start - copy your ID number</p>
<p>3. Add to Railway Variables:</p>
<code>TELEGRAM_TOKEN = your_bot_token
TELEGRAM_CHAT_ID = your_chat_id</code>
<a href="/api/test_telegram" style="color:#f59e0b">Click here to test Telegram</a>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XAUUSD Setup</title>
<style>
body{{background:#0a0c10;color:#e2e8f0;font-family:monospace;padding:20px;max-width:900px;margin:0 auto}}
h1{{color:#f59e0b;font-size:20px;margin-bottom:4px}}
h2{{color:#3b82f6;font-size:13px;margin:20px 0 8px;letter-spacing:1px;text-transform:uppercase;border-bottom:1px solid #1e2a3a;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse;background:#111520;border-radius:10px;overflow:hidden;margin-bottom:16px}}
th{{background:#1c2233;padding:10px 14px;text-align:left;font-size:11px;color:#64748b;letter-spacing:1px;text-transform:uppercase}}
tr:not(:last-child){{border-bottom:1px solid #1e2a3a}}
.box{{background:#111520;border-radius:10px;padding:16px;margin-bottom:14px;border:1px solid #1e2a3a}}
.warn{{border-color:#f59e0b;background:rgba(245,158,11,0.06)}}
code{{color:#f59e0b;font-size:12px;display:block;background:#161b27;padding:8px 12px;border-radius:6px;margin:6px 0;word-break:break-all;white-space:pre-wrap}}
.btn{{display:inline-block;background:#f59e0b;color:#000;padding:8px 20px;border-radius:6px;text-decoration:none;font-weight:700;font-size:13px;margin:4px 4px 4px 0}}
p{{font-size:13px;color:#94a3b8;line-height:1.6;margin:6px 0}}
</style></head><body>
<h1>XAUUSD Signal System - Setup Checker</h1>
<p style="color:#64748b">Configuration status for Railway cloud deployment</p>

<h2>Current Status</h2>
<table><tr><th>Component</th><th>Status</th><th>Action</th></tr>
{row("Data source", not is_synthetic, src or "none", "Add API key" if is_synthetic else "Working")}
{row("Twelve Data API", bool(td_key), "Configured" if td_key else "NOT SET", "Required for cloud data")}
{row("Alpha Vantage API", bool(av_key), "Configured" if av_key else "NOT SET", "Optional backup")}
{row("Telegram Token", bool(tg_tok), "Configured" if tg_tok else "NOT SET", "For phone alerts")}
{row("Telegram Chat ID", bool(tg_cid), "Configured" if tg_cid else "NOT SET", "For phone alerts")}
</table>

{warn_box}

<h2>Step 1 - Get Free Twelve Data API Key (Most Important)</h2>
<div class="box">
<p>Twelve Data: 800 free requests/day. Works perfectly on Railway. Real XAUUSD spot price.</p>
<p><b>1.</b> Go to: <a href="https://twelvedata.com/register" target="_blank" style="color:#f59e0b">https://twelvedata.com/register</a></p>
<p><b>2.</b> Create free account - verify email</p>
<p><b>3.</b> Log in - click your profile avatar (top right) - API Keys - copy your key</p>
<p><b>4.</b> In Railway: your service - Variables tab - New Variable:</p>
<code>Variable name:  TWELVE_DATA_KEY
Value:          paste_your_key_here</code>
<p><b>5.</b> Railway redeploys automatically in 2 minutes</p>
<p><b>6.</b> Refresh dashboard - data source shows "Twelve Data (Live)"</p>
</div>

<h2>Step 2 - Alpha Vantage Backup Key (Optional)</h2>
<div class="box">
<p>25 free requests/day. Used when Twelve Data limit is reached.</p>
<p>Get key: <a href="https://www.alphavantage.co/support/#api-key" target="_blank" style="color:#f59e0b">https://www.alphavantage.co/support/#api-key</a></p>
<p>Add to Railway Variables:</p>
<code>ALPHA_VANTAGE_KEY = your_key_here</code>
</div>

<h2>Step 3 - Telegram Alerts</h2>
<div class="box">
{tg_box}
</div>

<h2>Links</h2>
<p>
<a href="/" class="btn">Main Dashboard</a>
<a href="/mobile" class="btn" style="background:#3b82f6;color:#fff">Mobile Dashboard</a>
<a href="/api/test_telegram" class="btn" style="background:#a855f7;color:#fff">Test Telegram</a>
<a href="/api/health" class="btn" style="background:#374151;color:#fff">Health Check</a>
</p>
</body></html>"""
