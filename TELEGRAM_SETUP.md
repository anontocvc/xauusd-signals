# 📱 Free Mobile Access — No Laptop Required

## Overview

There are 3 completely free ways to get signals on your phone
even when your laptop is off:

| Method | Setup Time | Signals When? | Dashboard? |
|--------|-----------|---------------|-----------|
| Telegram + GitHub Actions | 15 min | Every 15 min, auto | No (alerts only) |
| Railway (free hosting) | 20 min | 24/7, live | Yes (full dashboard) |
| Render (free hosting) | 20 min | 24/7 (may sleep) | Yes (full dashboard) |

---

## METHOD 1 — Telegram Alerts via GitHub Actions
### (Easiest — just alerts on phone, no dashboard)

### Step 1: Set up Telegram Bot (5 minutes)

1. Open **Telegram** on your phone
2. Search for **@BotFather** → tap Start
3. Send the message: `/newbot`
4. BotFather asks for a name → type: `XAUUSD Signals`
5. BotFather asks for username → type: `xauusd_myname_bot`
   (must end in `bot`, must be unique)
6. BotFather sends you a **TOKEN** like:
   `123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ`
7. **Copy and save this token**

### Step 2: Get your Chat ID

1. In Telegram, search for **@userinfobot** → tap Start
2. Send any message (like `/start`)
3. It replies with your **ID** like: `Your id: 987654321`
4. **Copy and save this number**

### Step 3: Push code to GitHub

1. Go to **github.com** → create a free account if needed
2. Click **New repository** → name it `xauusd-signals` → Create
3. In VS Code terminal:
```
git init
git add .
git commit -m "XAUUSD signal system"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/xauusd-signals.git
git push -u origin main
```

### Step 4: Add Telegram secrets to GitHub

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add secret name: `TELEGRAM_TOKEN`
   Value: your bot token from Step 1
5. Click **Add secret**
6. Add another secret: `TELEGRAM_CHAT_ID`
   Value: your chat ID from Step 2
7. Click **Add secret**

### Step 5: Enable GitHub Actions

1. In your repository, click the **Actions** tab
2. You should see "XAUUSD Signal Monitor" workflow
3. Click **Enable workflow** if prompted
4. The workflow runs automatically every 15 minutes
   during London (08-12 UTC) and NY (13-17 UTC) sessions

### That's it!
You will receive Telegram messages like this on your phone:
```
🎯 SNIPER — 🟢 BUY XAUUSD 5M

💰 Entry zone: $3,285
🛑 Stop Loss: $3,278
✅ TP1 (1:2.1): $3,299
✅ TP2 (1:3.2): $3,307

📊 Score: 8.5/10 | Confidence: 92%
📦 Lot size: 0.05 | Risk: 0.5% ($5.00)

🔒 HTF Bias: BEARISH
📍 Phase: RETRACEMENT
🕐 Session: London
```

---

## METHOD 2 — Railway Free Hosting (Full Dashboard 24/7)

Railway gives you a free cloud server that runs your full
signal system 24/7 with the complete mobile dashboard.

### Step 1: Create Railway account

1. Go to **railway.app**
2. Click **Login** → **Login with GitHub**
3. Authorize Railway

### Step 2: Deploy your app

1. On Railway dashboard, click **+ New Project**
2. Click **Deploy from GitHub repo**
3. Select your `xauusd-signals` repository
   (push to GitHub first if not done — see Method 1 Step 3)
4. Railway auto-detects Python and deploys

### Step 3: Add environment variables

1. In Railway project, click your service
2. Click **Variables** tab
3. Add these variables:
   - `TELEGRAM_TOKEN` = your bot token
   - `TELEGRAM_CHAT_ID` = your chat ID
   - `PORT` = 8080

### Step 4: Get your public URL

1. Click **Settings** tab in your Railway service
2. Under **Networking**, click **Generate Domain**
3. You get a URL like: `https://xauusd-signals-production.up.railway.app`
4. Your mobile dashboard: `https://xauusd-signals-production.up.railway.app/mobile`

### Open this URL on your phone and install as app (PWA):
- **Android**: Chrome → ⋮ → Add to Home screen
- **iPhone**: Safari → Share (↑) → Add to Home Screen

### Railway free tier limits:
- $5 free credit per month
- Enough for ~500 hours (more than enough for trading hours)
- No credit card required
- If you exceed: server sleeps until next month

---

## METHOD 3 — Render Free Hosting

Similar to Railway but with a different free tier.

### Step 1: Create Render account

1. Go to **render.com**
2. Click **Get Started** → Sign up with GitHub

### Step 2: Deploy

1. Click **New** → **Web Service**
2. Connect your GitHub repository
3. Settings:
   - **Name**: xauusd-signals
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
4. Click **Create Web Service**

### Step 3: Add environment variables

In Render dashboard → Environment:
- `TELEGRAM_TOKEN` = your token
- `TELEGRAM_CHAT_ID` = your chat ID

### Step 4: Get your URL

Render gives you: `https://xauusd-signals.onrender.com`
Mobile dashboard: `https://xauusd-signals.onrender.com/mobile`

### Render free tier note:
Free tier services sleep after 15 minutes of no traffic.
They wake up when someone opens the URL (takes ~30 seconds).
For always-on: use Railway or upgrade Render ($7/mo).

---

## TESTING TELEGRAM

Run this in VS Code terminal to test your setup:
```
python core/telegram_alerts.py
```
If configured correctly, you receive a test message on Telegram.

---

## SUMMARY — What to do

### If you just want alerts on phone (simplest):
→ Set up **Telegram + GitHub Actions** (Method 1)

### If you want the full dashboard on phone 24/7:
→ Deploy to **Railway** (Method 2) — free, always on

### When laptop is on (at home):
→ Use `http://YOUR_IP:5000/mobile` — real MT5 data, best quality

### When laptop is off (away):
→ Use Railway URL — Yahoo Finance data, still fully functional

---

## Data source when laptop is off

When running on Railway/Render (cloud servers):
- MT5 is NOT available (MT5 is Windows-only)
- System automatically uses **Yahoo Finance** as data source
- Yahoo Finance provides XAUUSD data with ~10-15 min delay
- All SMC/ICT analysis still runs normally
- Signals are still generated — just based on slightly delayed data

This is acceptable for trade planning. For execution,
always verify with your MT5 chart before entering.
