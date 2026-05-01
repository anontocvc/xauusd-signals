# Signal Refresh Frequency Guide

## The honest truth about speed

| Method | Actual Speed | Reliability | Cost | Setup |
|--------|-------------|-------------|------|-------|
| GitHub Actions | Every 5 min (minimum) | Delays 2-10 min extra | Free | Easy |
| Railway / Render app | Every 60 seconds | 99.9% on time | Free | Medium |
| Your laptop (running) | Every 60 seconds | 100% | Free | Already done |
| Paid server (VPS) | Every 60 seconds | 100% | ~$5/mo | Medium |

---

## Why 60 seconds is the RIGHT interval (not 1 second)

You asked for every 1 minute or 5 minutes. Here is why 60 seconds
is actually the correct and optimal interval for this system:

### XAUUSD 1M candle = 60 seconds
A new 1-minute candle forms exactly once every 60 seconds.
If you check every 1 second, you get the same data 59 times
before anything changes. You are wasting API calls and CPU.
Checking every 60 seconds means you see every new candle
the moment it closes — which is when signals should be evaluated.

### SMC/ICT signals need candle closes
Order blocks, FVGs, BOS, CHoCH — all of these are defined by
candle close prices. An open (incomplete) candle can look like
a signal and then completely change before it closes.
Checking on closed candles only (every 60s) is more accurate
than checking on open candles every 5 seconds.

### GitHub Actions cannot go faster than 5 minutes
This is a hard GitHub platform limit. The cron scheduler
minimum interval is `*/5` (every 5 minutes). You cannot set
`*/1` — GitHub will ignore it or reject the workflow.
Even at 5 minutes, GitHub free tier often adds 2-10 minutes
of delay because many users are running workflows at the same time.

---

## Best free solution: Railway (60-second alerts, 24/7)

Railway runs your full Flask app as a server.
The background monitor thread runs every 60 seconds automatically.
You get Telegram alerts within 60-90 seconds of a signal forming.

### Setup (20 minutes, completely free):

**Step 1: Push to GitHub**
```
git init
git add .
git commit -m "xauusd v4"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/xauusd-signals.git
git push -u origin main
```

**Step 2: Deploy to Railway**
1. Go to railway.app
2. Login with GitHub
3. New Project → Deploy from GitHub repo
4. Select your xauusd-signals repo
5. Railway auto-detects Python, builds and deploys in ~2 minutes

**Step 3: Add Telegram variables**
In Railway dashboard → your service → Variables:
- TELEGRAM_TOKEN = your bot token
- TELEGRAM_CHAT_ID = your chat ID
- REFRESH_INTERVAL = 60

**Step 4: Get your URL**
Railway gives you: https://xauusd-signals-xxx.up.railway.app
Mobile dashboard:  https://xauusd-signals-xxx.up.railway.app/mobile

**Step 5: Install on phone**
Open the /mobile URL in Chrome (Android) or Safari (iPhone)
and add to home screen. Done.

### Result:
- Server runs 24/7 even when laptop is off
- Analyzes market every 60 seconds
- Sends Telegram alert within 60s of signal forming
- Full mobile dashboard accessible anywhere
- Uses Yahoo Finance data (MT5 only works locally on Windows)

---

## Use both together (recommended)

### At home with laptop on:
- app.py runs locally
- MT5 provides real-time data (best quality)
- Monitor checks every 60 seconds
- Telegram alerts to phone

### Away from home (laptop off):
- Railway server runs in cloud
- Yahoo Finance provides data
- Monitor still checks every 60 seconds
- Telegram alerts still arrive on phone
- Mobile dashboard accessible on Railway URL

### GitHub Actions as backup:
- Runs every 5 minutes as a redundant check
- If Railway has a brief outage, GitHub Actions still sends alerts
- Free, runs forever, no maintenance needed

---

## Summary: what to do right now

1. Set up Telegram bot (5 min) — TELEGRAM_SETUP.md
2. Deploy to Railway (20 min) — steps above
3. Enable GitHub Actions as backup (already in your repo)
4. Install mobile PWA on phone

After that: open your phone, see signals in real time,
get Telegram alerts within 60 seconds. Laptop can be off.
