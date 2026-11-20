/* Kalshi Demo Tracker — price-swing alert chat.
 *
 * Detects live contract price swings >= $0.10 (10 cents) in either direction
 * and publishes them to two scrolling chats:
 *   - "All events": every swing alert
 *   - "High ROI model": a selective filter using a documented, transparent
 *     multi-factor score (NOT a trained model — no model exists in this repo).
 *
 * Each alert row links official sources:
 *   - the exact market API URL (GET /markets/{ticker})
 *   - the event API URL (GET /events/{event_ticker}) and the event's official
 *     Kalshi "settlement_sources" website links (fetched on demand), shown under
 *     "Context". These are Kalshi's official resolution sources for the event; they
 *     are listed for context and are NOT verified as the cause of any swing
 *     (labeled "Cause not verified" on every row). Only https URLs the API actually
 *     returns are rendered — never inferred.
 *
 * The "High ROI model" score is a documented, transparent heuristic built only
 * from verified API fields (swing size, relative move, open interest). No trained
 * model exists in this repo, so it is labeled an unverified model heuristic
 * (F-5B-02) and is never presented as verified ROI or investment advice.
 *
 * Data: reuses the dashboard's live market samples (GET /markets, demo API,
 * no key needed); the event context is one extra GET /events/{event_ticker}
 * per new swing. Values the exchange does not report are left blank — never
 * inferred.
 *
 * Sources:
 *   https://docs.kalshi.com/getting_started/quick_start_market_data
 *   https://docs.kalshi.com/api-reference/market/get-markets
 *   https://docs.kalshi.com/api-reference/events/get-event
 *   https://docs.kalshi.com/getting_started/demo_env
 */
(function () {
  "use strict";

  var KD = window.KD = window.KD || {};
  var ALERT_KEY = "kd_alerts_v1";
  var SWING = 0.10;                 // dollars = 10 cents, the alert threshold
  var MAX_ALERTS = 300;

  /* ---------- documented ROI heuristic (unverified model) ----------
   * No trained model exists in this repo, so this is a transparent, deterministic
   * heuristic built only from verified API fields. It is labeled everywhere as an
   * unverified model heuristic (F-5B-02) and is never presented as a verified ROI
   * signal or as investment advice.
   *   swingNorm = clamp(|Δprice| cents / 50¢, 0, 1)       bigger swings score higher
   *   pctNorm   = clamp(|Δprice| / priorPrice / 50%, 0, 1)  bigger relative moves higher
   *   liqNorm   = clamp(log10(1 + open_interest_fp) / 6, 0, 1)  1M contracts = 1.0
   *   score     = 0.4*swingNorm + 0.3*pctNorm + 0.3*liqNorm
   *   high-ROI signal when score >= 0.5
   */
  var ROI_THRESHOLD = 0.5;
  function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
  function roiModel(oldP, newP, oi) {
    var change = Number(newP) - Number(oldP);
    var swingC = Math.abs(change) * 100;                 // cents
    var swingNorm = clamp(swingC / 50, 0, 1);
    var pct = Number(oldP) ? Math.abs(change) / Number(oldP) : 0;
    var pctNorm = clamp(pct / 0.5, 0, 1);
    var oiNum = Number(oi) || 0;
    var liqNorm = clamp(Math.log10(1 + oiNum) / 6, 0, 1);
    var score = 0.4 * swingNorm + 0.3 * pctNorm + 0.3 * liqNorm;
    return { swingC: swingC, pct: pct, oi: oiNum, swingNorm: swingNorm,
      pctNorm: pctNorm, liqNorm: liqNorm, score: score };
  }

  var state = {
    alerts: [],                     // all swing alerts (newest first)
    lastPrice: {},                  // ticker -> {price, ts} seeded from scans
    visible: "all",                 // "all" | "roi"
    enabled: true
  };
  try { state.alerts = JSON.parse(localStorage.getItem(ALERT_KEY) || "[]"); } catch (e) { state.alerts = []; }

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
  }
  function cents(x) {
    if (x === null || x === undefined || x === "" || isNaN(Number(x))) return "—";
    return (Number(x) * 100).toFixed(2) + "¢";
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
      // Float-safe: an exact 10¢ move (0.60 - 0.50) is 0.0999… in binary, so
      // compare with a tiny epsilon rather than dropping boundary swings.
      if (Math.abs(change) >= SWING - 1e-9) {
        var a = pushAlert(m, prev.price, cur);
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

  function pushAlert(m, oldP, newP) {
    var change = Number(newP) - Number(oldP);
    var dir = change > 0 ? "up" : change < 0 ? "down" : "flat";
    var series = m.series_ticker || "";
    var eventTicker = m.event_ticker || "";
    var model = roiModel(oldP, newP, m.oi);
    var alert = {
      id: "a" + Date.now() + Math.random().toString(36).slice(2, 6),
      ts: Math.floor(Date.now() / 1000),
      ticker: m.ticker,
      title: m.title || m.ticker,
      topic: m.topic || "",
      series: series,
      event: eventTicker,
      oldPrice: Number(oldP),
      newPrice: Number(newP),
      change: change,
      dir: dir,
      oi: model.oi,
      api: apiUrl(m.ticker, series),
      roi: model,                   // documented model output
      roiSignal: model.score >= ROI_THRESHOLD
    };
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
  function roiCell(a) {
    if (!a.roi) return "—";
    var badge = a.roiSignal ? " <span class='roi'>· signal</span>" : "";
    return "<span class='mono'>" + a.roi.score.toFixed(2) + "</span>" + badge;
  }
  function alertRow(a) {
    var cls = "alert " + (a.dir === "up" ? "up" : a.dir === "down" ? "down" : "flat");
    var arrow = a.dir === "up" ? "▲" : a.dir === "down" ? "▼" : "▶";
    var dirLabel = a.dir === "up" ? "up" : a.dir === "down" ? "down" : "flat";
    var roiBadge = a.roiSignal ? " <span class='roi'>· high-ROI signal (heuristic)</span>" : "";
    return "<tr class='" + esc(cls) + "'>" +
      "<td class='mono small muted'>" + fmtTs(a.ts) + "</td>" +
      "<td><span class='pill topic'>" + esc(a.topic) + "</span></td>" +
      "<td class='mono'>" + esc(a.ticker) + "</td>" +
      "<td>" + esc(a.title) + roiBadge + "</td>" +
      "<td class='num'>" + cents(a.oldPrice) + " → " + cents(a.newPrice) + "</td>" +
      "<td class='num " + esc(dirLabel) + "'>" + arrow + " " + cents(Math.abs(a.change)) + "</td>" +
      "<td class='num'>" + roiCell(a) + "</td>" +
      "<td><a class='src' href='" + esc(a.api) + "' target='_blank' rel='noopener'>market API</a></td>" +
      "<td class='ctx'>" + contextCell(a) + "<div class='small muted'>Cause not verified: a listed source is not proof that it moved the price.</div>" + rulesCell(a) + "</td></tr>";
  }
  function renderPanel(el, rows, label, emptyHint) {
    if (!el) return;
    var rowsHtml = rows.map(alertRow).join("");
    var empty = rows.length ? "" :
      "<tr><td colspan='9' class='muted'>No " + label + " swing alerts yet. " + emptyHint + "</td></tr>";
    el.innerHTML =
      "<table class='alerts'><thead><tr><th>Time</th><th>Topic</th><th>Ticker</th><th>Event</th>" +
      "<th>Price move</th><th>Swing</th><th>ROI score</th><th>Source</th><th>Context (official links)</th></tr></thead><tbody>" +
      rowsHtml + empty + "</tbody></table>";
  }
  function render() {
    renderPanel(document.getElementById("alertsAll"), KD.allRows(), "all",
      "Swing a tracked market price by >= $0.10 to see alerts here.");
    renderPanel(document.getElementById("alertsROI"), KD.roiRows(), "high-ROI",
      "The high-ROI chat applies a labeled placeholder model — no trained model exists yet.");
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
