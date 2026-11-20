/* Kalshi Demo Tracker — price-swing alert chat.
 *
 * Detects live contract price swings >= $0.10 (10 cents) in either direction
 * and publishes them to two scrolling chats:
 *   - "All events": every swing alert, plus RESOLVED yes/no messages when a
 *     tracked market settles (status "finalized", result "yes" | "no")
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
  var ROI_MIN_PRICE = 0.05;         // placeholder high-ROI rule: skip prices pinned at the extremes
  var ROI_MAX_PRICE = 0.95;

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
  // Official Get Market endpoint: GET /markets/{ticker}
  // (https://docs.kalshi.com/api-reference/market/get-market). The series-scoped path
  // /series/{s}/markets/{t} is the candlestick route and returned an error for this record.
  function apiUrl(ticker) {
    return "https://external-api.demo.kalshi.co/trade-api/v2/markets/" + encodeURIComponent(ticker);
  }
  // Float-safe rounding: 0.6 - 0.5 is 0.09999999999999998 in IEEE doubles, which would drop an
  // exact $0.10 swing. Round to 4 decimals (the API's dollar precision).
  function round4(x) { return Math.round(Number(x) * 10000) / 10000; }

  /* ---------- swing detection ---------- */
  KD.onSample = function (m, sample) {
    if (!state.enabled || !m) return;
    var cur = sample.price;
    if (cur === null || cur === undefined) return;
    var prev = state.lastPrice[m.ticker];
    if (prev && prev.price !== null && prev.price !== undefined) {
      var change = round4(cur - prev.price);
      // Tolerate floating-point representation error at the inclusive boundary.
      if (Math.abs(change) + 1e-12 >= SWING) {
        var a = pushAlert(m.ticker, m.title, m.topic, m.series_ticker, prev.price, cur,
          { vol: m.vol, oi: m.oi });
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

  function pushAlert(ticker, title, topic, series, oldP, newP, liq) {
    var change = round4(Number(newP) - Number(oldP));
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
      api: apiUrl(ticker)
    };
    // High-ROI PLACEHOLDER heuristic (NOT a real model; flagged F-alert-01): swing >= $0.10,
    // price between $0.05 and $0.95, and traded and open contracts > 0 (volume_fp, open_interest_fp
    // from the official Get Market record). A bare "$0.10 swing" test would always pass at these
    // price scales, so the band and liquidity terms are what actually filter.
    var liqOk = !!liq && Number(liq.vol) > 0 && Number(liq.oi) > 0;
    alert.roiSignal = Math.abs(change) >= SWING && Number(newP) >= ROI_MIN_PRICE &&
      Number(newP) <= ROI_MAX_PRICE && liqOk;
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
    var req;
    try {
      req = fetch(eventUrl(evt), { headers: { Accept: "application/json" } });
    } catch (e) {
      KD.events[evt] = { status: "error", sources: [], title: "", api: eventUrl(evt) };
      render();
      return;
    }
    Promise.resolve(req)
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

  /* ---------- resolutions (yes / no) ----------
   * A market that settles returns status "finalized" with result "yes" or "no"
   * (plus settlement_ts, settlement_value_dollars) — verified live on the demo
   * API 2026-11-20 (e.g. GET /markets?series_ticker=KXAAAGASW&status=settled).
   * The dashboard's scan feeds settled rows here; each resolution is posted
   * once to the All-events chat so a tracked event can be followed until it
   * resolves. Source: https://docs.kalshi.com/getting_started/market_settlement
   */
  function isResolved(m) {
    if (!m) return false;
    var st = String(m.status || "").toLowerCase();
    var r = String(m.result || "").toLowerCase();
    return (r === "yes" || r === "no") &&
      (st === "finalized" || st === "settled" || st === "closed");
  }
  function pushResolution(m) {
    var t = m.ticker;
    var dup = state.alerts.some(function (a) {
      return a.kind === "resolution" && a.ticker === t;
    });
    if (dup) return null;
    var alert = {
      id: "r" + Date.now() + Math.random().toString(36).slice(2, 6),
      ts: Math.floor(Date.now() / 1000),
      kind: "resolution",
      ticker: t,
      title: m.title || t,
      topic: m.topic || "",
      series: m.series_ticker || "",
      result: String(m.result || "").toLowerCase(),
      settlementTs: m.settlement_ts || "",
      settlementValue: m.settlement_value || "",
      api: apiUrl(t)
    };
    state.alerts.unshift(alert);
    if (state.alerts.length > MAX_ALERTS) state.alerts.length = MAX_ALERTS;
    persist();
    render();
    return alert;
  }
  KD.onSettled = function (rows) {
    if (!state.enabled) return;
    (rows || []).forEach(function (m) {
      if (!m || !m.ticker || !isResolved(m)) return;
      var a = pushResolution(m);
      if (a && m.event_ticker) {
        a.event = m.event_ticker;
        a.rules = m.rules_primary || "";
        persist();
        if (KD.events[a.event]) render();
        loadEvent(a.event);
      }
    });
  };

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
  function resolutionRow(a) {
    var settle = a.settlementTs ? " <span class='small muted'>settled " + esc(a.settlementTs) + "</span>" : "";
    var value = a.settlementValue ? " &middot; settlement value " + esc(a.settlementValue) : "";
    return "<tr class='alert resolved'><td class='mono small muted'>" + fmtTs(a.ts) + "</td>" +
      "<td><span class='pill topic'>" + esc(a.topic) + "</span></td>" +
      "<td class='mono'>" + esc(a.ticker) + "</td>" +
      "<td>" + esc(a.title) + "</td>" +
      "<td class='num'>RESOLVED</td>" +
      "<td class='num'><strong>" + esc(a.result.toUpperCase()) + "</strong></td>" +
      "<td><a class='src' href='" + esc(a.api) + "' target='_blank' rel='noopener'>market API</a></td>" +
      "<td class='ctx'>" + contextCell(a) + settle + value +
      "<div class='small muted'>Official result from the settlement record — how the event resolved.</div>" +
      rulesCell(a) + "</td></tr>";
  }
  function alertRow(a) {
    if (a.kind === "resolution") return resolutionRow(a);
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
      "<td><a class='src' href='" + esc(a.api) + "' target='_blank' rel='noopener'>market API</a>" + roiBadge + "</td>" +
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
