// XAUUSD Signal Extension — Background Service Worker
// Polls the local signal server every 60 seconds

const SERVER = "http://localhost:5000";
let lastSignalHash = "";

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("pollSignals", { periodInMinutes: 1 });
  console.log("XAUUSD Signal Extension installed.");
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "pollSignals") pollServer();
});

async function pollServer() {
  try {
    const res = await fetch(`${SERVER}/api/analysis`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.status === "error") return;

    const signals = data.signals?.signals || [];
    const best = signals.find(s => ["sniper","high"].includes(s.setup_type));

    if (best) {
      const hash = `${best.direction}-${best.timeframe}-${best.entry}-${best.setup_type}`;
      if (hash !== lastSignalHash) {
        lastSignalHash = hash;
        notifySignal(best, data.price);
      }
    }

    // Store latest for popup
    chrome.storage.local.set({
      lastData: data,
      lastPoll: new Date().toISOString()
    });
  } catch (e) {
    console.log("Server not reachable:", e.message);
    chrome.storage.local.set({ serverOffline: true });
  }
}

function notifySignal(signal, price) {
  const emoji = signal.direction === "BUY" ? "🟢" : "🔴";
  const typeLabel = signal.setup_type.toUpperCase();
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon48.png",
    title: `${emoji} ${typeLabel} — ${signal.direction} XAUUSD (${signal.timeframe.toUpperCase()})`,
    message: `Entry: $${signal.entry}  SL: $${signal.sl}  TP1: $${signal.tp1}\nRR: 1:${signal.rr1}  Conf: ${signal.confidence}%  Score: ${signal.score}/10`,
    priority: signal.setup_type === "sniper" ? 2 : 1
  });
}

// Poll immediately on startup
pollServer();
