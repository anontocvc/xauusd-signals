# 📱 Mobile Access Guide

## Overview — 3 Ways to Access on Phone

| Method | Works When | Setup Difficulty | Cost |
|--------|-----------|-----------------|------|
| **WiFi (Same Network)** | At home/office on same WiFi | ⭐ Easy | Free |
| **Ngrok Tunnel** | Anywhere — mobile data, any WiFi | ⭐⭐ Medium | Free |
| **VPS (24/7)** | Always, even laptop is off | ⭐⭐⭐ Advanced | ~$5/mo |

---

## Method 1 — Same WiFi (Easiest, Use This First)

### Step 1: Start your server
```
python app.py
```
Look at the startup output — you will see:
```
📱 Mobile  →  http://192.168.1.X:5000/mobile
```

### Step 2: Connect phone to same WiFi
Your phone and laptop **must be on the same WiFi network**.

### Step 3: Open on phone
- Open Chrome (Android) or Safari (iPhone)
- Type exactly: `http://192.168.1.X:5000/mobile`
  (use YOUR IP from the terminal, not this example)

### Step 4: Get the QR code (easier than typing)
Open in laptop browser: `http://localhost:5000/api/qr`
A page appears with the URL and QR code. Scan or copy to phone.

### Step 5: Install as app (optional but recommended)

**Android (Chrome):**
1. Open the mobile URL in Chrome
2. Tap ⋮ (3-dot menu) → "Add to Home screen"
3. Tap "Install"
4. XAU icon appears on your home screen

**iPhone (Safari):**
1. Open the mobile URL in Safari (NOT Chrome)
2. Tap the Share button (□ with arrow up)
3. Scroll down → tap "Add to Home Screen"
4. Tap "Add"
5. XAU icon appears on your home screen

---

## Method 2 — Ngrok (Access from Anywhere)

Use this when you are away from home WiFi (mobile data, different location).

### Step 1: Install Ngrok (free)
Download from: https://ngrok.com/download

Or run in terminal:
```
winget install ngrok
```
Or:
```
choco install ngrok
```

### Step 2: Sign up (free account)
1. Go to https://dashboard.ngrok.com/signup
2. Create a free account
3. Copy your authtoken from the dashboard

### Step 3: Set your authtoken (one time only)
```
ngrok config add-authtoken YOUR_TOKEN_HERE
```

### Step 4: Start server + ngrok (2 terminals)
**Terminal 1:**
```
python app.py
```
**Terminal 2:**
```
ngrok http 5000
```

### Step 5: Get your URL
Ngrok shows output like:
```
Forwarding  https://abc123.ngrok-free.app -> localhost:5000
```
Open on your phone: `https://abc123.ngrok-free.app/mobile`

**This URL works on any network worldwide.**

> ⚠️ Free ngrok URL changes every time you restart ngrok.
> Paid ngrok ($8/mo) gives you a fixed URL.

---

## Method 3 — Windows VPS (24/7, Laptop Can Be Off)

If you want signals 24 hours a day even when your laptop is off:

### Recommended VPS providers
| Provider | Price | Setup |
|---------|-------|-------|
| Contabo | $5/mo | contabo.com |
| Vultr | $6/mo | vultr.com |
| DigitalOcean | $6/mo | digitalocean.com |

### Setup steps
1. Order Windows Server 2022 VPS (2GB RAM minimum)
2. Connect via Remote Desktop: `Win+R → mstsc → enter VPS IP`
3. Install MetaTrader 5 on the VPS
4. Install Python 3.11 on the VPS
5. Copy your project folder to the VPS
6. Run: `pip install flask requests pandas numpy MetaTrader5`
7. Log MT5 into your broker demo account
8. Run: `python app.py`
9. Open on phone: `http://VPS_IP:5000/mobile`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "This site can't be reached" | Laptop and phone not on same WiFi, or server not running |
| URL shows but no data loads | Click the ↻ button, wait 10 seconds |
| Can't find the IP address | Look at terminal output when you run app.py |
| iPhone won't install as app | Must use Safari, not Chrome |
| Ngrok says "authtoken required" | Run: `ngrok config add-authtoken YOUR_TOKEN` |
| Windows Firewall blocks connection | Allow Python through Windows Firewall |

### Windows Firewall fix (if phone can't reach laptop)
1. Press `Win + S` → search "Windows Firewall"
2. Click "Allow an app through firewall"
3. Click "Change settings" → "Allow another app"
4. Browse to: `C:\Users\...\Python311\python.exe`
5. Check both Private and Public → OK

---

## Notification Setup on Phone

### Android (Chrome):
1. Open the mobile URL in Chrome
2. Go to the **Alerts** tab in the bottom navigation
3. Tap "Enable Notifications"
4. Allow when Chrome asks for permission
5. You'll get a notification whenever a SNIPER or HIGH signal fires

### iPhone:
iOS does not support web push notifications from non-App-Store apps.
Instead, check the app manually or keep it open in the background.

---

## Quick Reference

| What to do | Command / URL |
|-----------|--------------|
| Start server | `python app.py` |
| Desktop dashboard | `http://localhost:5000` |
| Mobile dashboard | `http://YOUR_IP:5000/mobile` |
| QR code page | `http://localhost:5000/api/qr` |
| Start ngrok | `ngrok http 5000` |
| Health check | `http://localhost:5000/api/health` |
