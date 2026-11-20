/* Kalshi Demo Dashboard — live price-swing alerts (session 5125afd8, task T-A1).
 *
 * Hooked into the dashboard scan via window.KalshiAlerts.onScan(rows) (assets/dashboard.js).
 *  - Feed 1 "All swings": every open market whose last price moved by >= $0.10
 *    (either direction) from its anchor.
 *  - Feed 2 "High-ROI filter": the subset that passes CONFIG.roiRule.
 *
 * Anchor = the market's last price at its previous alert (or its first observation).
 * Anchors are re-set on every alert, so a slow drift that adds up to $0.10 also alerts.
 *
 * Sources / definitions (all verified, see COORDINATION.md session 5125afd8):
 *  - Price field: `last_price_dollars` (official Get Market schema,
 *    https://docs.kalshi.com/api-reference/market/get-market). Values are dollars per contract.
 *  - Payout: each contract settles to $1 if right, $0 if wrong
 *    (https://news.kalshi.com/p/what-are-event-contracts).
 *  - Gross ROI if right, buying at price p: YES (1 - p) / p ; NO p / (1 - p). Fees and spread are
 *    NOT included. This is arithmetic on the payout rule, not a probability forecast.
 *  - The API does not report what caused a move, so alerts never state a cause.
 *  - Sampling is once per dashboard scan (about 20 s). This is not a tick stream; the official
 *    WebSocket requires signed handshake headers that a browser page cannot attach
 *    (https://docs.kalshi.com/getting_started/quick_start_websockets), so the page polls REST.
 */
(function () {
  "use strict";
  var K = window.KalshiDemo;
  var $ = function (id) { return document.getElementById(id); };

  var CONFIG = {
    threshold: 0.10,          // dollars per contract, either direction
    maxItems: 200,            // rows kept per feed
    // PLACEHOLDER high-ROI rule. The owner's "model" criteria were NOT supplied to this repo,
    // so this rule is a visible, editable stand-in (flagged as an open question).
    roiRule: {
      minMove: 0.10,
      minPrice: 0.05,         // skip prices pinned at the extremes
      maxPrice: 0.95,
      requireVolume: true,    // total traded contracts > 0 (volume_fp)
      requireOpenInterest: true // open contracts > 0 (open_interest_fp)
    }
  };

  /* ---------- pure logic (exported for tests) ---------- */

  function round4(x) { return Math.round(x * 10000) / 10000; }

  // Gross return per $1 risked if the bought side pays $1. Returns null outside (0,1).
  function roiIfRight(price) {
    if (typeof price !== "number" || !(price > 0 && price < 1)) return null;
    return { yes: (1 - price) / price, no: price / (1 - price) };
  }

  // rows: markets as built by dashboard.js marketRow(); anchors: {ticker: dollars}.
  // Returns the alerts raised by this scan and the anchors for the next scan.
  function evaluate(anchors, rows, threshold, now) {
    var alerts = [];
    var next = {};
    (rows || []).forEach(function (m) {
      var last = m.last;
      if (last === null || last === undefined || isNaN(Number(last))) return;
      last = Number(last);
      var anchor = anchors[m.ticker];
      if (anchor === undefined) { next[m.ticker] = last; return; }
      var delta = round4(last - anchor);
      if (Math.abs(delta) + 1e-9 >= threshold) {
        var roi = roiIfRight(last);
        alerts.push({
          id: m.ticker + "@" + now,
          ts: now,
          ticker: m.ticker,
          title: m.title || m.ticker,
          topic: m.topic || "",
          event_ticker: m.event_ticker || "",
          series_ticker: m.series_ticker || "",
          from: anchor,
          to: last,
          delta: delta,
          direction: delta > 0 ? "up" : "down",
          yb: m.yb, ya: m.ya,
          vol: Number(m.vol) || 0,
          oi: Number(m.oi) || 0,
          roiYes: roi ? roi.yes : null,
          roiNo: roi ? roi.no : null
        });
        next[m.ticker] = last;
      } else {
        next[m.ticker] = anchor;
      }
    });
    return { alerts: alerts, anchors: next };
  }

  function passesRoi(a, rule) {
    if (!a || !rule) return false;
    if (!(a.to >= rule.minPrice && a.to <= rule.maxPrice)) return false;
    if (Math.abs(a.delta) + 1e-9 < rule.minMove) return false;
    if (rule.requireVolume && !(a.vol > 0)) return false;
    if (rule.requireOpenInterest && !(a.oi > 0)) return false;
    return true;
  }

  /* ---------- state + rendering ---------- */

  var state = {
    anchors: {}, primed: false,
    all: [], roi: [], pendingAll: [], pendingRoi: [],
    paused: false, count: { all: 0, roi: 0 }
  };

  function money(x) { return (x < 0 ? "-$" : "$") + Math.abs(x).toFixed(2); }
  function pct(x) { return x === null || x === undefined ? "—" : (x * 100).toFixed(0) + "%"; }
  function clock(ts) { return new Date(ts).toLocaleTimeString("en-GB"); }

  function rowHtml(a) {
    var arrow = a.direction === "up" ? "▲" : "▼";
    var href = "/markets/" + encodeURIComponent(a.ticker);
    var src = K.srcLink(href, "API record");
    var roi = a.roiYes === null ? "" :
      " · gross ROI if right: YES " + pct(a.roiYes) + " / NO " + pct(a.roiNo);
    return "<li class='alert " + a.direction + "'>" +
      "<span class='mono'>" + clock(a.ts) + "</span> " +
      "<span class='pill'>" + K.esc(a.topic || "—") + "</span> " +
      "<strong>" + K.esc(a.title) + "</strong> " +
      "<span class='mono small'>" + K.esc(a.ticker) + "</span><br>" +
      "<span class='delta " + a.direction + "'>" + arrow + " " +
      (a.delta > 0 ? "+" : "") + money(a.delta) + "</span> " +
      "<span class='mono'>" + money(a.from) + " → " + money(a.to) + "</span>" +
      "<span class='small muted'>" + K.esc(roi) + "</span><br>" +
      "<span class='small muted'>Cause: not reported by the API (none inferred) · " + src + "</span>" +
      "</li>";
  }

  function paint(list, el, countEl, count) {
    if (!el) return;
    el.innerHTML = list.map(rowHtml).join("") ||
      "<li class='muted small'>No alerts yet. Alerts appear after a scan sees a move of $0.10 or more.</li>";
    if (countEl) countEl.textContent = String(count);
  }

  function render() {
    paint(state.all, $("alertFeedAll"), $("alertCountAll"), state.count.all);
    paint(state.roi, $("alertFeedRoi"), $("alertCountRoi"), state.count.roi);
    var p = $("alertPauseBtn");
    if (p) p.textContent = state.paused ? "Resume feeds" : "Pause feeds";
    var pend = state.pendingAll.length + state.pendingRoi.length;
    var pn = $("alertPending");
    if (pn) pn.textContent = state.paused && pend ? pend + " new alert(s) held while paused" : "";
  }

  function push(list, items, cap) {
    items.slice().reverse().forEach(function (a) { list.unshift(a); });
    if (list.length > cap) list.splice(cap);
  }

  function onScan(rows) {
    if (!K) return;
    var now = Date.now();
    var res = evaluate(state.anchors, rows, CONFIG.threshold, now);
    state.anchors = res.anchors;
    // The first scan only sets anchors; it raises no alerts (no earlier price to compare).
    if (!state.primed) { state.primed = true; render(); return; }
    var roiHits = res.alerts.filter(function (a) { return passesRoi(a, CONFIG.roiRule); });
    state.count.all += res.alerts.length;
    state.count.roi += roiHits.length;
    if (state.paused) {
      state.pendingAll = res.alerts.concat(state.pendingAll);
      state.pendingRoi = roiHits.concat(state.pendingRoi);
    } else {
      push(state.all, res.alerts, CONFIG.maxItems);
      push(state.roi, roiHits, CONFIG.maxItems);
    }
    render();
  }

  function togglePause() {
    state.paused = !state.paused;
    if (!state.paused) {
      push(state.all, state.pendingAll, CONFIG.maxItems);
      push(state.roi, state.pendingRoi, CONFIG.maxItems);
      state.pendingAll = []; state.pendingRoi = [];
    }
    render();
  }

  function init() {
    var b = $("alertPauseBtn");
    if (b) b.addEventListener("click", togglePause);
    render();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  window.KalshiAlerts = {
    onScan: onScan,
    config: CONFIG,
    core: { evaluate: evaluate, roiIfRight: roiIfRight, passesRoi: passesRoi, round4: round4 }
  };
})();
