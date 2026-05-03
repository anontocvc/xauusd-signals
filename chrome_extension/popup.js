// popup.js — XAUUSD Signal Extension
// All event handlers here (not inline in HTML) to satisfy Chrome CSP

const SERVER = "http://localhost:5000";

async function loadData() {
  document.getElementById("status-text").textContent = "Fetching...";
  try {
    const res = await fetch(SERVER + "/api/refresh");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    if (data.status === "error") throw new Error(data.error || "Server error");
    renderData(data);
    chrome.storage.local.set({ lastData: data, lastPoll: new Date().toISOString() });
  } catch (e) {
    showOffline(e.message);
  }
}

function renderData(data) {
  const price      = data.price || 0;
  const analysis   = data.analysis || {};
  const signalData = data.signals || {};
  const signals    = signalData.signals || [];
  const summary    = signalData.summary || {};
  const tfs        = analysis.timeframes || {};
  const htfBias    = analysis.htf_bias || "neutral";

  // Header
  document.getElementById("price-display").textContent =
    price > 0 ? "$" + price.toFixed(2) : "—";
  document.getElementById("price-sub").textContent =
    "HTF: " + htfBias.replace(/_/g, " ") + "  ·  Session: " + (summary.session || "—");
  const dot = document.getElementById("live-dot");
  dot.classList.add("on");
  document.getElementById("status-text").textContent = "Live";
  document.getElementById("status-text").style.color = "#10b981";

  const ts = data.timestamp || "";
  document.getElementById("last-poll").textContent =
    ts ? ts.split(" ")[1] : "—";

  let html = "";

  // ── Signals ───────────────────────────────────────────────────────────────
  if (signals.length) {
    html += '<div class="section"><div class="section-title">Trade Signals (' +
      signals.length + ')</div>';
    signals.slice(0, 4).forEach(function(s) {
      html += '<div class="sig-row ' + (s.setup_type || "") + '">' +
        '<div class="sig-top">' +
          '<span class="sig-dir dir-' + s.direction.toLowerCase() + '">' +
            s.direction + " · " + (s.timeframe || "").toUpperCase() +
          "</span>" +
          '<span class="sig-badge badge-' + (s.setup_type || "medium") + '">' +
            (s.setup_type || "").toUpperCase() + " " + (s.confidence || 0) + "%" +
          "</span>" +
        "</div>" +
        '<div class="sig-levels">' +
          '<div class="lvl"><div class="lvl-label">Entry</div>' +
            '<div class="lvl-val entry-col">$' + (s.entry || 0) + "</div></div>" +
          '<div class="lvl"><div class="lvl-label">SL</div>' +
            '<div class="lvl-val sl-col">$' + (s.sl || 0) + "</div></div>" +
          '<div class="lvl"><div class="lvl-label">TP1</div>' +
            '<div class="lvl-val tp-col">$' + (s.tp1 || 0) + "</div></div>" +
          '<div class="lvl"><div class="lvl-label">TP2</div>' +
            '<div class="lvl-val tp-col">$' + (s.tp2 || 0) + "</div></div>" +
          '<div class="lvl"><div class="lvl-label">Lot</div>' +
            '<div class="lvl-val" style="color:#f59e0b">' + (s.lot_size || 0.01) + "</div></div>" +
          '<div class="lvl"><div class="lvl-label">RR</div>' +
            '<div class="lvl-val" style="color:#94a3b8">1:' + (s.rr1 || 0) + "</div></div>" +
        "</div>" +
        '<div class="sig-meta">' +
          "<span>Score: " + (s.score || 0) + "/10</span>" +
          "<span>" + (s.timestamp || "") + "</span>" +
        "</div></div>";
    });
    html += "</div>";
  } else {
    html += '<div class="section"><div class="section-title">Signals</div>' +
      '<div style="color:#64748b;font-size:10px;padding:4px 0">' +
      "No valid setups — waiting for confluence</div></div>";
  }

  // ── HTF Structure ─────────────────────────────────────────────────────────
  html += '<div class="section"><div class="section-title">Structure</div>';
  ["4h", "1h", "15m", "5m", "1m"].forEach(function(tf) {
    var d = tfs[tf];
    if (!d) return;
    var b = d.bias || "—";
    var cls = b.includes("bull") ? "bull-v" : b.includes("bear") ? "bear-v" : "neut-v";
    html += '<div class="htf-row">' +
      '<span class="htf-label">' + tf.toUpperCase() + "</span>" +
      '<span class="htf-val ' + cls + '">' + b.replace(/_/g, " ") + "</span></div>";
  });
  html += "</div>";

  // ── News ──────────────────────────────────────────────────────────────────
  var news = analysis.news || [];
  if (news.length) {
    html += '<div class="section"><div class="section-title">Events</div>';
    news.forEach(function(n) {
      var cls = n.impact === "HIGH" ? "imp-high" : "imp-med";
      html += '<div class="news-item">' +
        '<span class="news-imp ' + cls + '">' + n.impact + "</span>" +
        '<span class="news-txt">' + n.event + "</span>" +
        '<span class="news-time">' + (n.time || n.date) + "</span></div>";
    });
    html += "</div>";
  }

  document.getElementById("main-content").innerHTML = html;
}

function showOffline(msg) {
  document.getElementById("live-dot").classList.remove("on");
  document.getElementById("status-text").textContent = "Offline";
  document.getElementById("status-text").style.color = "#ef4444";
  document.getElementById("price-display").textContent = "Offline";
  document.getElementById("price-sub").textContent = "";
  document.getElementById("main-content").innerHTML =
    '<div class="offline-msg">' +
      '<div style="color:#ef4444;margin-bottom:6px">Cannot reach server</div>' +
      '<div style="font-size:10px;color:#94a3b8">Make sure your server is running:</div>' +
      '<div style="color:#f59e0b;font-size:10px;margin:6px 0">python app.py</div>' +
      '<div style="font-size:10px;color:#64748b">' + (msg || "") + "</div>" +
    "</div>";
}

// ── Wire up events (no inline handlers) ──────────────────────────────────────
document.addEventListener("DOMContentLoaded", function() {
  // Refresh button
  document.getElementById("refresh-btn").addEventListener("click", loadData);

  // Load cached data first for instant display, then refresh
  chrome.storage.local.get(["lastData", "lastPoll"], function(items) {
    if (items.lastData) {
      renderData(items.lastData);
      if (items.lastPoll) {
        document.getElementById("last-poll").textContent =
          new Date(items.lastPoll).toLocaleTimeString();
      }
    }
    // Then fetch fresh
    loadData();
  });
});
