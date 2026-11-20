/* Kalshi Demo Tracker — price-swing alert chat.
 *
 * Detects live contract price swings >= $0.10 (10 cents) in either direction
 * and publishes them to two scrolling chats:
 *   - "All events": every swing alert
 *   - "High ROI model": a selective, labeled heuristic filter (NOT a real model)
 *
 * Data: reuses the dashboard's live market samples (GET /markets, demo API,
 * no key needed). No extra network requests. Each alert links its exact market
 * API URL. Values the exchange does not report are left blank — never inferred.
 *
 * The high-ROI rule below is a transparent placeholder heuristic. No model is
 * defined in this repo, so nothing is presented as a verified ROI signal. It is
 * flagged for review (F-alert-01) until a real model is specified.
 *
 * Source: https://docs.kalshi.com/getting_started/quick_start_market_data
 *         https://docs.kalshi.com/api-reference/market/get-markets
 *         https://docs.kalshi.com/getting_started/demo_env
 */
(function () {
  "use strict";

  var KD = window.KD = window.KD || {};
  var ALERT_KEY = "kd_alerts_v1";
  var SWING = 0.10;                 // dollars = 10 cents, the alert threshold
  var MAX_ALERTS = 300;

  var state = {
    alerts: [],                     // all swing alerts (newest first)
    lastPrice: {},                  // ticker -> {price, ts} seeded from scans
    visible: "all",                 // "all" | "roi"
    enabled: true
  };
  try { state.alerts = JSON.parse(localStorage.getItem(ALERT_KEY) || "[]"); } catch (e) { state.alerts = []; }

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function cents(x) {
    if (x === null || x === undefined || x === "" || isNaN(Number(x))) return "—";
    return (Number(x) * 100).toFixed(2) + "\u00a2";
  }
  function fmtTs(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    return d.toLocaleTimeString("en-GB");
  }
  function apiUrl(ticker, series) {
    var path = series
      ? "/series/" + encodeURIComponent(series) + "/markets/" + encodeURIComponent(ticker)
      : "/markets/" + encodeURIComponent(ticker);
    return "https://external-api.demo.kalshi.co/trade-api/v2" + path;
  }

  /* ---------- swing detection ---------- */
  KD.onSample = function (m, sample) {
    if (!state.enabled || !m) return;
    var cur = sample.price;
    if (cur === null || cur === undefined) return;
    var prev = state.lastPrice[m.ticker];
    if (prev && prev.price !== null && prev.price !== undefined) {
      var change = cur - prev.price;
      // Tolerate floating-point representation error at the inclusive boundary.
      if (Math.abs(change) + 1e-12 >= SWING) {
        var a = pushAlert(m.ticker, m.title, m.topic, m.series_ticker, prev.price, cur);
        if (a) { a.event = m.event_ticker || ""; a.rules = m.rules_primary || ""; persist(); loadEvent(a.event); }
      }
    }
    state.lastPrice[m.ticker] = { price: cur, ts: sample.t };
  };

  KD.onMarkets = function (markets) {
    // Seed lastPrice from full market rows on each scan (no extra API calls).
    var now = Math.floor(Date.now() / 1000);
    (markets || []).forEach(function (m) {
      if (m.last !== null && m.last !== undefined && !state.lastPrice[m.ticker]) {
        state.lastPrice[m.ticker] = { price: m.last, ts: now };
      }
    });
  };

  function pushAlert(ticker, title, topic, series, oldP, newP) {
    var change = Number(newP) - Number(oldP);
    var dir = change > 0 ? "up" : change < 0 ? "down" : "flat";
    var alert = {
      id: "a" + Date.now() + Math.random().toString(36).slice(2, 6),
      ts: Math.floor(Date.now() / 1000),
      ticker: ticker,
      title: title || ticker,
      topic: topic || "",
      series: series || "",
      oldPrice: Number(oldP),
      newPrice: Number(newP),
      change: change,
      dir: dir,
      api: apiUrl(ticker, series)
    };
    // High-ROI placeholder heuristic: swing >= $0.10 AND the move is at least 10%
    // of the prior price. NOT a real model — labeled, unverified, flagged F-alert-01.
    var pct = Number(oldP) ? Math.abs(change) / Number(oldP) : 0;
    alert.roiSignal = Math.abs(change) + 1e-12 >= SWING && pct >= 0.10;
    state.alerts.unshift(alert);
    if (state.alerts.length > MAX_ALERTS) state.alerts.length = MAX_ALERTS;
    persist();
    render();
    if (window.KalshiTrade && window.KalshiTrade.onSwingAlert) {
      try { window.KalshiTrade.onSwingAlert(alert); } catch (e) { /* automation must not break alerts */ }
    }
    return alert;
  }

  function persist() {
    try { localStorage.setItem(ALERT_KEY, JSON.stringify(state.alerts)); } catch (e) {}
  }

  /* ---------- sharp-jump context: official event record ----------
   * GET /events/{event_ticker} (Get Event) returns settlement_sources[{name,url}]:
   * the sources the exchange uses to resolve the event. These are shown as
   * context links only. They do NOT prove what caused a price move.
   * Source: https://docs.kalshi.com/api-reference/events/get-event
   */
  KD.events = {};                   // event_ticker -> {status, sources, title, api}
  function loadEvent(evt) {
    if (!evt || KD.events[evt]) return;
    KD.events[evt] = { status: "loading", sources: [], title: "", api: eventUrl(evt) };
    fetch(eventUrl(evt), { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (j) {
        var ev = j.event || {};
        KD.events[evt] = {
          status: "ok", title: ev.title || "", api: eventUrl(evt),
          sources: (ev.settlement_sources || []).filter(function (s) {
            return s && typeof s.url === "string" && /^https:\/\//.test(s.url);
          })
        };
        render();
      })
      .catch(function () {
        KD.events[evt] = { status: "error", sources: [], title: "", api: eventUrl(evt) };
        render();
      });
  }
  function eventUrl(evt) {
    return "https://external-api.demo.kalshi.co/trade-api/v2/events/" + encodeURIComponent(evt);
  }
  function contextCell(a) {
    if (!a.event) return "<span class='muted small'>event not recorded (older alert)</span>";
    var ev = KD.events[a.event];
    var out = "<a class='src' href='" + esc(eventUrl(a.event)) + "' target='_blank' rel='noopener'>event API</a>";
    if (!ev || ev.status === "loading") return out + " <span class='muted small'>loading settlement sources&hellip;</span>";
    if (ev.status === "error") return out + " <span class='muted small'>event record unavailable (browser/API blocked) &mdash; not inferred</span>";
    if (!ev.sources.length) return out + " <span class='muted small'>API lists no settlement sources</span>";
    out += ev.sources.map(function (s) {
      return " <a class='src' href='" + esc(s.url) + "' target='_blank' rel='noopener'>" + esc(s.name || s.url) + "</a>";
    }).join("");
    return out;
  }
  function rulesCell(a) {
    if (!a.rules) return "";
    return "<details class='rules'><summary class='small'>rules (Get Market rules_primary)</summary><div class='small'>" +
      esc(a.rules) + "</div></details>";
  }

  /* ---------- chat row selection ---------- */
  KD.allRows = function () { return state.alerts; };
  KD.roiRows = function () { return state.alerts.filter(function (a) { return a.roiSignal; }); };
  KD.setFilter = function (v) { state.visible = v; render(); };
  KD.clear = function () {
    state.alerts = [];
    try { localStorage.removeItem(ALERT_KEY); } catch (e) {}
    render();
  };
  KD.toggle = function () { state.enabled = !state.enabled; render(); };

  /* ---------- rendering (two scrolling chats) ---------- */
  function alertRow(a) {
    var cls = "alert " + (a.dir === "up" ? "up" : a.dir === "down" ? "down" : "flat");
    var arrow = a.dir === "up" ? "\u25b2" : a.dir === "down" ? "\u25bc" : "\u25b6";
    var dirLabel = a.dir === "up" ? "up" : a.dir === "down" ? "down" : "flat";
    var roiBadge = a.roiSignal ? " <span class='roi'>&middot; high-ROI signal (heuristic)</span>" : "";
    return "<tr class='" + esc(cls) + "'><td class='mono small muted'>" + fmtTs(a.ts) + "</td>" +
      "<td><span class='pill topic'>" + esc(a.topic) + "</span></td>" +
      "<td class='mono'>" + esc(a.ticker) + "</td>" +
      "<td>" + esc(a.title) + "</td>" +
      "<td class='num'>" + cents(a.oldPrice) + " &rarr; " + cents(a.newPrice) + "</td>" +
      "<td class='num " + esc(dirLabel) + "'>" + arrow + " " + cents(Math.abs(a.change)) + "</td>" +
      "<td><a class='src' href='" + esc(a.api) + "' target='_blank' rel='noopener'>market API</a>" + esc(roiBadge) + "</td>" +
      "<td class='ctx'>" + contextCell(a) + "<div class='small muted'>Cause not verified: a listed source is not proof that it moved the price.</div>" + rulesCell(a) + "</td></tr>";
  }
  function renderPanel(el, rows, label, emptyHint) {
    if (!el) return;
    var rowsHtml = rows.map(alertRow).join("");
    var empty = rows.length ? "" : "<tr><td colspan='8' class='muted'>No " + label + " swing alerts yet. " + emptyHint + "</td></tr>";
    el.innerHTML =
      "<table class='alerts'><thead><tr><th>Time</th><th>Topic</th><th>Ticker</th><th>Event</th>" +
      "<th>Price move</th><th>Swing</th><th>Source</th><th>Context (official links)</th></tr></thead><tbody>" + rowsHtml + empty + "</tbody></table>";
  }
  function render() {
    renderPanel(document.getElementById("alertsAll"), KD.allRows(), "all",
      "Swing a tracked market price by >= $0.10 to see alerts here.");
    renderPanel(document.getElementById("alertsROI"), KD.roiRows(), "high-ROI",
      "The high-ROI chat applies a labeled placeholder rule — no real model is defined yet.");
  }

  /* public */
  KD.renderAlerts = render;

  /* ---------- UI wiring ---------- */
  function wireUI() {
    var tabAll = document.getElementById("tabAll");
    var tabROI = document.getElementById("tabROI");
    var chatAll = document.getElementById("chatAll");
    var chatROI = document.getElementById("chatROI");
    var enabled = document.getElementById("alertsEnabled");
    var clear = document.getElementById("clearAlertsBtn");
    var countEl = document.getElementById("alertCount");
    function setActive(tab) {
      state.visible = tab.getAttribute("data-chat");
      [tabAll, tabROI].forEach(function (t) {
        if (t) { t.classList.toggle("active", t === tab); t.setAttribute("aria-pressed", String(t === tab)); }
      });
      if (chatAll) chatAll.style.display = tab === tabAll ? "" : "none";
      if (chatROI) chatROI.style.display = tab === tabROI ? "" : "none";
      render();
    }
    if (tabAll) tabAll.addEventListener("click", function () { setActive(tabAll); });
    if (tabROI) tabROI.addEventListener("click", function () { setActive(tabROI); });
    if (clear) clear.addEventListener("click", KD.clear);
    if (enabled) {
      enabled.addEventListener("change", function () { KD.toggle(); enabled.checked = state.enabled; });
    }
    function updateCount() {
      if (countEl) countEl.textContent = state.alerts.length + " alert" +
        (state.alerts.length === 1 ? "" : "s") + (state.enabled ? "" : " (paused)");
    }
    var _render = render;
    render = function () { _render(); updateCount(); };
    var first = tabAll || document.querySelector(".chat-tab.active");
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { setActive(first); render(); });
    } else {
      setActive(first);
      render();
    }
  }
  wireUI();
  setInterval(render, 2000); // keep the chats current while the page is open
})();
