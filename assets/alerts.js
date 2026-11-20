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
  var API_BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  var ALERT_KEY = "kd_alerts_v1";
  var RES_KEY = "kd_resolutions_v1";
  var SWING = 0.10;                 // dollars = 10 cents, the alert threshold
  var MAX_ALERTS = 300;
  var MAX_RES = 200;
  var POLL_MS = 20000;              // resolution poll cadence (one batched REST call)
  var CHUNK = 100;                  // Get Markets `limit` for a ticker batch

  var state = {
    alerts: [],                     // all swing alerts (newest first)
    resolutions: [],                // yes/no resolutions (newest first)
    lastPrice: {},                  // ticker -> {price, ts} seeded from scans
    visible: "all",                 // "all" | "roi"
    enabled: true
  };
  try { state.alerts = JSON.parse(localStorage.getItem(ALERT_KEY) || "[]"); } catch (e) { state.alerts = []; }
  try { state.resolutions = JSON.parse(localStorage.getItem(RES_KEY) || "[]"); } catch (e) { state.resolutions = []; }

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
      // Float-safe threshold: in IEEE-754 dollars, 0.6499 - 0.5499 === 0.09999999999999998,
      // which silently dropped exact $0.10 swings (measured here: node -e on 2026-11-20).
      // The brief's rule is |change| >= $0.10, so compare with a 1e-9 tolerance.
      if (Math.abs(change) >= SWING - 1e-9) {
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
    // High-ROI screen. assets/roi-model.js publishes the rule and the demo statistics
    // behind it (data/latest/roi_model.json, built by model/build_roi_model.py). The
    // fallback below is the old inline heuristic and is labelled as such on the row, so
    // a chat never looks model-scored when the model file did not load (board F-alert-01).
    alert.roiSignal = false;
    alert.roiBasis = "model not loaded — fallback heuristic (same rule, not a model score)";
    var roiModelApplied = false;
    if (typeof KD.roiScore === "function") {
      try {
        var sc = KD.roiScore(alert);
        if (sc) {
          roiModelApplied = true;
          alert.roiSignal = !!sc.signal;
          alert.roiBasis = sc.basis || "screen " + (sc.id || "");
          alert.roiStats = sc.stats || null;
        }
      } catch (e) { /* the screen must never break the feed */ }
    }
    if (!roiModelApplied) {
      // Same rule as the published screen, so the chat still works when the model file
      // is missing (offline, Pages build mid-update). Labelled, never called a model score.
      var pct = Number(oldP) ? Math.abs(change) / Number(oldP) : 0;
      alert.roiSignal = Math.abs(change) >= SWING - 1e-9 && pct >= 0.10 - 1e-9;
    }
    // Resolution tracking starts at the alert: follow this market until `result` is yes/no.
    watchTicker(ticker, { series: series, title: alert.title, topic: alert.topic });
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

  /* ---------- yes/no resolution tracking ----------
   * The brief asks the tracker to follow each alerted event until it resolves and to say
   * HOW it resolved. Get Markets / Get Market report `result` ("yes" | "no", empty while
   * unsettled), `settlement_value_dollars` and `settlement_ts`; a winning YES contract
   * pays $1.00 and a winning NO pays $1.00 as the complement. Nothing is inferred: while
   * `result` is empty the market stays "open" and no resolution row is written.
   *   https://docs.kalshi.com/api-reference/market/get-markets   (tickers, limit, result)
   *   https://docs.kalshi.com/api-reference/market/get-market
   *   https://docs.kalshi.com/getting_started/market_settlement
   */
  var watch = {};                     // ticker -> {series, title, topic}
  var pollBusy = false;

  function watchTicker(ticker, meta) {
    if (!ticker || watch[ticker]) return;
    watch[ticker] = meta || {};
  }
  function chunk(a, n) {
    var out = [];
    for (var i = 0; i < a.length; i += n) out.push(a.slice(i, i + n));
    return out;
  }
  function fetchBatch(tickers) {
    var url = API_BASE + "/markets?tickers=" + tickers.map(encodeURIComponent).join(",") +
      "&limit=" + CHUNK;
    return fetch(url, { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
  }
  function absorb(rows) {
    var n = 0;
    ((rows && rows.markets) || []).forEach(function (m) {
      var res = String(m.result || "").toLowerCase();
      if (res !== "yes" && res !== "no") return;
      KD.noteResolution({
        ticker: m.ticker, title: m.title, result: res, status: m.status,
        settlement_value_dollars: m.settlement_value_dollars,
        settlement_ts: m.settlement_ts, event_ticker: m.event_ticker,
        series: (watch[m.ticker] || {}).series || "",
        topic: (watch[m.ticker] || {}).topic || "",
        source: "live poll (GET /markets?tickers=…)"
      });
      n++;
    });
    return n;
  }
  function pollOnce() {
    if (pollBusy) return Promise.resolve(0);
    var tickers = Object.keys(watch);
    if (!tickers.length) { state.pollMsg = "no markets under resolution watch yet"; return Promise.resolve(0); }
    pollBusy = true;
    state.pollMsg = "checking " + tickers.length + " market(s)…";
    render();
    return chunk(tickers, CHUNK).reduce(function (prev, g) {
      return prev.then(function (found) {
        return fetchBatch(g).then(function (j) { return found + absorb(j); },
                                    function (e) { state.pollErr = String(e.message || e); return found; });
      });
    }, Promise.resolve(0)).then(function (found) {
      pollBusy = false;
      state.pollMsg = "last check " + new Date().toLocaleTimeString("en-GB") +
        " · " + tickers.length + " market(s) · " + found + " new resolution(s)";
      render();
      return found;
    });
  }

  /** Record a resolution once per ticker; links it back to any alert for that market. */
  KD.noteResolution = function (r) {
    if (!r || !r.ticker) return false;
    var res = String(r.result || "").toLowerCase();
    if (res !== "yes" && res !== "no") return false;
    if (state.resolutions.some(function (x) { return x.ticker === r.ticker; })) return false;
    var entry = {
      id: "r" + Date.now() + Math.random().toString(36).slice(2, 6),
      ts: Math.floor(Date.now() / 1000),
      ticker: r.ticker,
      title: r.title || (watch[r.ticker] || {}).title || r.ticker,
      topic: r.topic || (watch[r.ticker] || {}).topic || "",
      series: r.series || (watch[r.ticker] || {}).series || "",
      result: res,
      status: r.status || "finalized",
      settlement_value_dollars: (r.settlement_value_dollars === undefined || r.settlement_value_dollars === null)
        ? "" : r.settlement_value_dollars,
      settlement_ts: r.settlement_ts || "",
      event: r.event_ticker || "",
      source: r.source || "reported by another module",
      api: apiUrl(r.ticker, r.series || (watch[r.ticker] || {}).series)
    };
    state.resolutions.unshift(entry);
    if (state.resolutions.length > MAX_RES) state.resolutions.length = MAX_RES;
    state.alerts.forEach(function (a) {
      if (a.ticker === entry.ticker) {
        a.resolution = { result: entry.result, settlement_ts: entry.settlement_ts,
                         settlement_value_dollars: entry.settlement_value_dollars };
      }
    });
    try {
      localStorage.setItem(RES_KEY, JSON.stringify(state.resolutions));
      localStorage.setItem(ALERT_KEY, JSON.stringify(state.alerts));
    } catch (e) {}
    render();
    return true;
  };

  // Existing alerts restored from localStorage keep being followed across reloads.
  (state.alerts || []).forEach(function (a) {
    if (a && a.ticker) watchTicker(a.ticker, { series: a.series, title: a.title, topic: a.topic });
  });

  /* ---------- chat row selection ---------- */
  KD.allRows = function () { return state.alerts; };
  KD.roiRows = function () { return state.alerts.filter(function (a) { return a.roiSignal; }); };
  function resFor(tickers) {
    return state.resolutions.filter(function (r) { return tickers[r.ticker]; });
  }
  function feed(swingRows, resolutions) {
    var items = swingRows.map(function (a) { return { kind: "swing", ts: a.ts, row: a }; });
    return items.concat((resolutions || []).map(function (r) { return { kind: "resolution", ts: r.ts, row: r }; }))
      .sort(function (x, y) { return (y.ts || 0) - (x.ts || 0); });
  }
  /** All-events chat: every swing alert plus every resolution of an alerted market. */
  KD.allFeed = function () {
    var rows = KD.allRows(), keep = {};
    rows.forEach(function (a) { keep[a.ticker] = 1; });
    return feed(rows, resFor(keep));
  };
  /** High-ROI chat: model-admitted swings plus the resolutions of those same markets. */
  KD.roiFeed = function () {
    var rows = KD.roiRows(), keep = {};
    rows.forEach(function (a) { keep[a.ticker] = 1; });
    return feed(rows, resFor(keep));
  };
  KD.pollResolutions = pollOnce;
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
    var roiBadge = a.roiSignal
      ? " <span class='roi'>&middot; high-ROI screen: " + esc(a.roiBasis || "admitted") + "</span>"
      : "";
    if (a.resolution) {
      roiBadge += " <span class='pill resolved'>&middot; resolved " + esc(String(a.resolution.result).toUpperCase()) + "</span>";
    }
    return "<tr class='" + esc(cls) + "'><td class='mono small muted'>" + fmtTs(a.ts) + "</td>" +
      "<td><span class='pill topic'>" + esc(a.topic) + "</span></td>" +
      "<td class='mono'>" + esc(a.ticker) + "</td>" +
      "<td>" + esc(a.title) + "</td>" +
      "<td class='num'>" + cents(a.oldPrice) + " &rarr; " + cents(a.newPrice) + "</td>" +
      "<td class='num " + esc(dirLabel) + "'>" + arrow + " " + cents(Math.abs(a.change)) + "</td>" +
      "<td><a class='src' href='" + esc(a.api) + "' target='_blank' rel='noopener'>market API</a>" + roiBadge + "</td>" +
      "<td class='ctx'>" + contextCell(a) + "<div class='small muted'>Cause not verified: a listed source is not proof that it moved the price.</div>" + rulesCell(a) + "</td></tr>";
  }
  function resRow(r) {
    var yes = r.result === "yes";
    var pay = r.settlement_value_dollars === "" ? "payout not reported"
      : "settled at $" + esc(r.settlement_value_dollars);
    return "<tr class='alert resolved-row'><td class='mono small muted'>" + fmtTs(r.ts) + "</td>" +
      "<td><span class='pill topic'>" + esc(r.topic) + "</span></td>" +
      "<td class='mono'>" + esc(r.ticker) + "</td>" +
      "<td><span class='pill " + (yes ? "up" : "down") + "'>RESOLVED " + (yes ? "YES" : "NO") + "</span> " +
      esc(r.title) + "</td>" +
      "<td class='num'>" + (yes ? "&rarr; $1.00" : "&rarr; $0.00") + "</td>" +
      "<td class='num'>" + esc(r.status) + "</td>" +
      "<td><a class='src' href='" + esc(r.api) + "' target='_blank' rel='noopener'>market API</a> " +
      "<span class='small muted'>" + esc(r.source) + "</span></td>" +
      "<td class='ctx'><span class='small'>" + pay +
      (r.settlement_ts ? " · settlement_ts " + esc(r.settlement_ts) : "") +
      (r.event ? " · " + contextCell({ event: r.event }) : "") + "</span></td></tr>";
  }
  function feedRow(it) { return it.kind === "resolution" ? resRow(it.row) : alertRow(it.row); }
  function renderPanel(el, items, label, emptyHint) {
    if (!el) return;
    var rows = (items || []).map(feedRow);
    var rowsHtml = rows.join("");
    var empty = rows.length ? "" : "<tr><td colspan='8' class='muted'>No " + label + " swing alerts yet. " + emptyHint + "</td></tr>";
    el.innerHTML =
      "<table class='alerts'><thead><tr><th>Time</th><th>Topic</th><th>Ticker</th><th>Event</th>" +
      "<th>Price move</th><th>Swing</th><th>Source</th><th>Context (official links)</th></tr></thead><tbody>" + rowsHtml + empty + "</tbody></table>";
  }
  function render() {
    renderPanel(document.getElementById("alertsAll"), KD.allFeed(), "all",
      "Swing a tracked market price by >= $0.10 to see alerts here.");
    renderPanel(document.getElementById("alertsROI"), KD.roiFeed(), "high-ROI",
      "The high-ROI chat applies the published screen in data/latest/roi_model.json.");
    var st = document.getElementById("resPollStatus");
    if (st) st.textContent = state.pollMsg + (state.pollErr ? " · last error: " + state.pollErr : "") +
      " · " + state.resolutions.length + " resolution(s) logged";
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
  state.pollMsg = "resolution watch idle";
  setTimeout(pollOnce, 4000);              // first check shortly after load
  setInterval(pollOnce, POLL_MS);          // then every 20 s while the page is open
})();
