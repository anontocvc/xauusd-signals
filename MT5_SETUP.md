# MT5 Setup Guide — XAUUSD Signal System

## Why MT5?

| Feature           | Yahoo Finance     | MetaTrader 5       |
|-------------------|-------------------|--------------------|
| Price feed        | Gold Futures (delayed) | Real-time spot XAUUSD |
| Latency           | 10–15 min delay   | Milliseconds (tick) |
| 1M OHLCV          | Often missing     | Full real history  |
| Spread data       | ❌                | ✅ Live bid/ask    |
| Volume            | Approximate       | Real broker volume |
| Cost              | Free              | Free (via broker)  |
| Reliability       | Blocks randomly   | 99.9% uptime       |

---

## Step 1 — Install MetaTrader 5

1. Download from: https://www.metatrader5.com/en/download
2. Install on **Windows** (MT5 Python library is Windows-only)
3. Open MT5 and log in to your broker account

**Recommended FREE demo brokers for XAUUSD:**
- **ICMarkets** — tight spreads, reliable XAUUSD feed
- **Pepperstone** — excellent for gold
- **XM** — easy demo signup, symbol: `XAUUSD`
- **RoboForex** — symbol: `XAUUSDm`

---

## Step 2 — Install Python package

```bash
pip install MetaTrader5
```

> ⚠️ This only works on **Windows**. If you are on Mac/Linux, use a Windows VM or VPS.

---

## Step 3 — Configure symbol name

Every broker uses a slightly different symbol name for gold. Open your system's config:

**In `core/market_data.py` line 18:**
```python
MT5_SYMBOL = "XAUUSD"   # Change this if needed
```

Common broker symbol names:
| Broker       | Symbol       |
|--------------|--------------|
| ICMarkets    | `XAUUSD`     |
| Pepperstone  | `XAUUSD`     |
| XM           | `XAUUSD`     |
| RoboForex    | `XAUUSDm`    |
| FxPro        | `XAUUSD`     |
| FXCM         | `XAUUSD`     |
| Exness       | `XAUUSDc`    |
| HFM          | `XAUUSD.`    |

The system **auto-detects** alternative names if the primary symbol is not found.

---

## Step 4 — Make sure MT5 is open before running

The Python library connects to the **already-running** MT5 terminal.

Startup sequence every session:
```
1. Open MetaTrader 5
2. Log in to your account
3. Run: python app.py
4. Open: http://localhost:5000
```

---

## Step 5 — Enable Algo Trading in MT5

MT5 must allow Python API connections:

1. In MT5 → **Tools** → **Options** → **Expert Advisors**
2. Check: ✅ "Allow automated trading"
3. Check: ✅ "Allow DLL imports"

---

## Verifying the connection

When MT5 is connected, the dashboard shows:
- **Data source: ✅ MetaTrader 5 (Live)**
- **MT5 status: 🟢 Connected**
- **Broker:** your broker name
- **Spread:** live spread in points
- **Bid / Ask:** live prices

When not connected, you'll see:
- **Data source: ⚠ Yahoo Finance (Delayed)** — still works but delayed
- **Data source: 🔴 Synthetic (Demo only)** — fake data, for testing only

---

## Troubleshooting

**"MT5: initialize() failed"**
→ MT5 terminal is not open. Start it first.

**"Symbol 'XAUUSD' not found"**
→ Your broker uses a different name. Check Market Watch in MT5 for the exact gold symbol name, then update `MT5_SYMBOL` in `core/market_data.py`.

**"MetaTrader5 package not installed"**
→ Run: `pip install MetaTrader5`

**"Only runs on Windows"**
→ MT5 Python API is Windows-only. Use a Windows VPS (cheapest: ~$5/month on Contabo or Vultr) to run 24/7.

---

## Running 24/7 on a Windows VPS

For automated signal generation around the clock:

1. Get a Windows VPS (Contabo, Vultr, AWS, Azure)
2. Install MT5 + Python on the VPS
3. Log in to MT5 on VPS with your broker
4. Run `python app.py` as a startup service
5. Access dashboard from any device via `http://VPS_IP:5000`

To run as a Windows service (stays running after reboot):
```bash
pip install pywin32
python -m pywin32_setup install
# Then use Windows Task Scheduler to auto-start app.py at login
```
