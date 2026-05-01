# XAUUSD Pro Signal System 🏆

> Real-time SMC/ICT multi-timeframe trading signal engine for XAUUSD (Gold)

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## What This System Does

- **Fetches live XAUUSD price data** every 60 seconds from Yahoo Finance
- **Analyzes 5 timeframes**: 1M, 5M, 15M, 1H, 4H simultaneously
- **Detects SMC/ICT concepts**: Order Blocks, FVGs, BOS/CHoCH, Liquidity Sweeps
- **Calculates 10+ indicators**: RSI, MACD, EMA stack, Bollinger Bands, Stochastic, Williams %R, ATR
- **Generates trade signals** classified as: SNIPER / HIGH / MEDIUM / LOW / AGGRESSIVE
- **Every signal includes**: Entry zone, SL, TP1/TP2/TP3, RR ratio (min 1:2), Lot size
- **Chrome Extension** for desktop notifications when a Sniper/High signal fires
- **Works with real data** (Yahoo Finance) + synthetic fallback when offline

---

## Quick Start

### 1. Clone / Download
```bash
git clone https://github.com/YOUR_USERNAME/xauusd-signal-system.git
cd xauusd-signal-system
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the Server
```bash
python app.py
```

### 4. Open Dashboard
Open your browser and go to: **http://localhost:5000**

---

## VS Code Setup

1. Open the project folder in VS Code
2. Press `F5` to launch with the debugger (uses `.vscode/launch.json`)
3. Or use `Ctrl+Shift+B` → "Run Trading Server"
4. Dashboard opens at `http://localhost:5000`

---

## Chrome Extension Setup

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `chrome_extension/` folder
5. The extension icon appears in your toolbar
6. Start `python app.py` first, then click the extension icon

The extension:
- Shows live price + all signals in a popup
- Sends desktop notifications for SNIPER and HIGH signals
- Polls the server every 60 seconds automatically

---

## Signal Types

| Type | Score | Risk % | Description |
|------|-------|--------|-------------|
| 🎯 SNIPER | 8.5+ | 0.5% | Highest confluence — HTF aligned + sweep + OB + FVG |
| 🟢 HIGH | 7.0+ | 1.0% | Strong setup, HTF aligned |
| 🔵 MEDIUM | 5.5+ | 1.5% | Good confluence, valid entry |
| ⚪ LOW | 4.0+ | 0.75% | Partial confluence, smaller size |
| 🔴 AGGRESSIVE | 3.0+ | 2.5% | Counter-trend or early-stage setup |

All signals have **minimum 1:2 RR**. Sniper/High targets 1:3–1:4.5.

---

## SMC/ICT Concepts Used

- **BOS** — Break of Structure
- **CHoCH** — Change of Character
- **OB** — Order Blocks (bullish/bearish, unmitigated)
- **FVG** — Fair Value Gaps (unfilled)
- **BSL/SSL** — Buy-Side / Sell-Side Liquidity pools
- **Liquidity Sweeps** — Stop hunts before reversals
- **Premium/Discount** — Fibonacci-based zone classification
- **AMD Model** — Accumulation → Manipulation → Distribution

---

## Project Structure

```
xauusd_trader/
├── app.py                    # Flask server entry point
├── requirements.txt          # Python dependencies
├── core/
│   ├── market_data.py        # Yahoo Finance + synthetic data
│   ├── analyzer.py           # Full SMC/ICT + indicator engine
│   └── signal_engine.py      # Signal generation + lot sizing
├── templates/
│   └── index.html            # Main dashboard (dark theme)
├── chrome_extension/
│   ├── manifest.json         # Extension config
│   ├── background.js         # Auto-poll + notifications
│   └── popup.html            # Extension popup UI
└── .vscode/
    ├── launch.json           # F5 debug config
    └── tasks.json            # Build tasks
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main dashboard |
| `/api/analysis` | GET | Cached analysis (fast) |
| `/api/refresh` | GET | Force fresh market data fetch |
| `/api/health` | GET | Server health check |

---

## Risk Disclaimer

> This system is for **educational purposes only**. Trading XAUUSD with leverage carries extreme risk of loss. Always use proper risk management. Never risk more than you can afford to lose. Past performance of any strategy does not guarantee future results. Use demo accounts before trading live.

---

## License

MIT License — Free to use, modify, and distribute.
