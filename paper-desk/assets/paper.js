/* Live panel for the paper desk: read-only access to the official Kalshi DEMO REST API.
 *
 * Endpoints used (public market data, no auth — verified 2026-11-20):
 *   GET /markets?tickers=a,b,c        https://docs.kalshi.com/api-reference/market/get-markets.md
 *   GET /markets/{ticker}/orderbook   https://docs.kalshi.com/api-reference/market/get-market-orderbook.md
 *   GET /events/{event_ticker}        https://docs.kalshi.com/api-reference/events/get-event.md
 *   GET /series/{s}/markets/{t}/candlesticks?start_ts&end_ts&period_interval=1|60|1440
 *                                     https://docs.kalshi.com/api-reference/market/get-market-candlesticks
 * This file never writes to the exchange and never fabricates a value: if a request
 * fails, the row/panel says so.
 */
(function () {
  "use strict";
  var API = window.PAPER_API_ROOT || "https://external-api.demo.kalshi.co/trade-api/v2";
  var TICKERS = window.PAPER_TICKERS || [];
  var MARKS = window.PAPER_MARKS || {};   /* {ticker: {mark, entry, side, count}} */
  var SWING = 0.10;                        /* the brief's $0.10 threshold */
  var $ = function (id) { return document.getElementById(id); };
  var timer = null, liveSeries = {}, liveOn = false;

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function usd(v, dp) {
    var n = Number(v);
    return (v === null || v === undefined || isNaN(n)) ? "—" : "$" + n.toFixed(dp === undefined ? 4 : dp);
  }
  function link(url, label) {
    if (!url) return '<span class="pill unv">no url</span>';
    return '<a class="src" href="' + esc(url) + '" target="_blank" rel="noopener">' +
      esc(label || "open") + "</a>";
  }
  function status(msg, kind) {
    var el = $("liveStatus");
    if (el) el.innerHTML = '<span class="pill ' + (kind || "") + '">' + esc(msg) + "</span>";
  }

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " from " + url);
      return r.json();
    });
  }

  function marketsUrl(tickers) {
    return API + "/markets?tickers=" + encodeURIComponent(tickers.join(","));
  }

  function rowFor(m) {
    var t = m.ticker, mark = MARKS[t] || {};
    var ask = Number(m.yes_ask_dollars), bid = Number(m.yes_bid_dollars);
    var delta = (mark.mark !== undefined && mark.mark !== null) ? (bid - mark.mark) : null;
    var big = delta !== null && Math.abs(delta) >= SWING;
    var cls = big ? (delta > 0 ? "pos" : "neg") : "";
    return "<tr data-ticker=\"" + esc(t) + "\" data-event=\"" + esc(m.event_ticker) + "\">" +
      '<td class="mono"><button class="chartBtn" title="plot this market">' + esc(t) + "</button></td>" +
      "<td>" + esc(m.yes_sub_title || m.title) +
      '<div class="muted small">' + esc((mark.topic || "") === "" ? "" : mark.topic) + "</div></td>" +
      "<td>" + esc(m.status) + (m.result ? ' <span class="pill">' + esc(m.result) + "</span>" : "") + "</td>" +
      "<td>" + usd(m.last_price_dollars) + "</td>" +
      "<td>" + usd(bid) + '<div class="muted small">' + esc(m.yes_bid_size_fp) + " ct</div></td>" +
      "<td>" + usd(ask) + '<div class="muted small">' + esc(m.yes_ask_size_fp) + " ct</div></td>" +
      "<td>" + usd(m.no_bid_dollars) + "</td><td>" + usd(m.no_ask_dollars) + "</td>" +
      "<td>" + (delta === null ? "—" : '<span class="' + cls + '">' +
        (delta >= 0 ? "+" : "") + delta.toFixed(4) + "</span>") +
      (big ? ' <span class="pill ' + (delta > 0 ? "ok" : "unv") + '">&ge;$0.10 move since the last desk cycle</span>' : "") +
      "</td>" +
      "<td>" + usd(mark.entry) + "</td><td>" + esc(mark.count !== undefined ? mark.count : "") + "</td>" +
      "<td class=" + '"' + '">' + esc(m.updated_time) + "</td>" +
      "<td>" + link(marketsUrl([t]), "API row") + "</td></tr>";
  }

  function renderMarkets(markets, url) {
    var box = $("liveTable");
    if (!box) return;
    if (!markets.length) {
      box.innerHTML = '<p class="muted small">No markets returned for the tracked tickers.</p>';
      return;
    }
    var head = "<tr><th>market</th><th>side label</th><th>status</th><th>last</th><th>YES bid</th>" +
      "<th>YES ask</th><th>NO bid</th><th>NO ask</th><th>vs desk mark</th><th>desk entry</th>" +
      "<th>desk ct</th><th>API updated</th><th>source</th></tr>";
    box.innerHTML = '<div class="scroll"><table><thead>' + head + "</thead><tbody>" +
      markets.map(rowFor).join("") + "</tbody></table></div>" +
      '<p class="muted small">Request used: <span class="mono">' + esc(url) + "</span></p>";
    Array.prototype.forEach.call(box.querySelectorAll(".chartBtn"), function (b) {
      b.addEventListener("click", function () {
        selectForChart(b.parentNode.getAttribute("data-ticker"),
          b.parentNode.getAttribute("data-event"));
      });
    });
  }

  function refresh() {
    if (!TICKERS.length) { status("nothing tracked yet", "warn"); return Promise.resolve(); }
    var url = marketsUrl(TICKERS);
    status("refreshing…");
    return getJSON(url).then(function (data) {
      var ms = (data && data.markets) || [];
      renderMarkets(ms, url);
      var moved = ms.filter(function (m) {
        var mk = MARKS[m.ticker];
        return mk && mk.mark !== undefined && mk.mark !== null &&
          Math.abs(Number(m.yes_bid_dollars) - mk.mark) >= SWING;
      }).length;
      status("live · " + ms.length + " market(s) from the demo API" +
        (moved ? " · " + moved + " moved &ge;$0.10 since the last desk cycle" : ""), "ok");
      if (liveOn) ms.forEach(function (m) { pushSample(m); });
    }).catch(function (err) {
      status("blocked or offline: " + err.message, "unv");
      var box = $("liveTable");
      if (box) {
        box.innerHTML = '<div class="note small"><strong>Could not reach the demo API from this ' +
          "browser.</strong> The committed ledger above is unaffected. This panel calls " +
          '<span class="mono">' + esc(url) + "</span> directly; a blocked or " +
          "CORS-restricted request leaves the table empty rather than showing estimated values.</div>";
      }
    });
  }

  /* ---- live (browser-sampled) series: the only sub-minute granularity available ---- */
  function pushSample(m) {
    var s = liveSeries[m.ticker] || (liveSeries[m.ticker] = []);
    s.push({ ts: Date.now() / 1000, price: Number(m.yes_bid_dollars),
             ask: Number(m.yes_ask_dollars) });
    if (s.length > 720) s.shift();
    if (selected.ticker === m.ticker) drawChart(s.map(function (p) {
      return { x: p.ts, y: p.price, label: new Date(p.ts * 1000).toISOString().slice(11, 19) };
    }), "browser samples every " + interval + "s · y = YES best bid (USD) · not API history");
  }

  var selected = {};
  var interval = 30;

  function selectForChart(ticker, eventTicker) {
    selected = { ticker: ticker, event: eventTicker };
    drawFromApi();
  }

  function svg(points, note) {
    var w = 1160, h = 240, pad = 40;
    if (points.length < 2) {
      return '<p class="muted small">' + esc(note || "not enough points") + "</p>";
    }
    var xs = points.map(function (p) { return p.x; });
    var ys = points.map(function (p) { return p.y; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (y1 - y0 < 1e-9) { y0 -= 0.01; y1 += 0.01; }
    if (x1 - x0 < 1e-9) { x1 = x0 + 1; }
    var sx = function (x) { return pad + (x - x0) / (x1 - x0) * (w - 2 * pad); };
    var sy = function (y) { return h - pad - (y - y0) / (y1 - y0) * (h - 2 * pad); };
    var grid = "", k, y, lab;
    for (k = 0; k < 5; k++) {
      y = sy(y0 + (y1 - y0) * k / 4);
      lab = usd(y0 + (y1 - y0) * k / 4);
      grid += '<line x1="' + pad + '" y1="' + y.toFixed(1) + '" x2="' + (w - pad) +
        '" y2="' + y.toFixed(1) + '" stroke="#232838"/><text x="4" y="' + (y + 3).toFixed(1) +
        '" fill="#7f8ca3" font-size="10">' + esc(lab) + "</text>";
    }
    var ticks = "";
    for (k = 0; k < points.length; k += Math.max(1, Math.floor(points.length / 7))) {
      ticks += '<text x="' + sx(points[k].x).toFixed(1) + '" y="' + (h - 10) +
        '" fill="#7f8ca3" font-size="10" text-anchor="middle">' +
        esc(points[k].label || "") + "</text>";
    }
    var line = points.map(function (p) { return sx(p.x).toFixed(1) + "," + sy(p.y).toFixed(1); })
      .join(" ");
    var last = points[points.length - 1], first = points[0];
    var color = last.y >= first.y ? "#3ddc97" : "#ff6b6b";
    var bars = points.map(function (p) {
      return '<circle cx="' + sx(p.x).toFixed(1) + '" cy="' + sy(p.y).toFixed(1) +
        '" r="1.6" fill="' + color + '"/>';
    }).join("");
    return '<svg class="chart" viewBox="0 0 ' + w + " " + h + '" role="img" ' +
      'aria-label="contract price over time">' + grid +
      '<polyline fill="none" stroke="' + color + '" stroke-width="2" points="' + line + '"/>' +
      bars + ticks +
      '<text x="' + (w - pad) + '" y="' + (sy(last.y) - 8).toFixed(1) + '" fill="' + color +
      '" font-size="11" text-anchor="end">' + esc(usd(last.y)) + "</text>" +
      '<text x="' + pad + '" y="16" fill="#93a0b5" font-size="11">' +
      esc(selected.ticker || "") + " — " + esc(note || "") + "</text></svg>";
  }

  function drawChart(points, note) { svgChart(points, note); }
  function svgChart(points, note) {
    var box = $("liveChartBox");
    if (box) box.innerHTML = svg(points, note);
  }

  function drawFromApi() {
    var box = $("liveChartBox");
    if (!box || !selected.ticker) return;
    box.innerHTML = '<p class="muted small">loading candles for ' + esc(selected.ticker) + "…</p>";
    var period = ($("liveChart") || {}).value || "60";
    if (period === "live") {
      var s = liveSeries[selected.ticker] || [];
      drawChart(s.map(function (p) {
        return { x: p.ts, y: p.price, label: new Date(p.ts * 1000).toISOString().slice(11, 19) };
      }), "browser samples every " + interval + "s · y = YES best bid (USD) · the demo API has no " +
        "sub-minute history, so this is the only seconds-level view available");
      return;
    }
    var minutes = Number(period);
    var span = { 1: 180 * 60, 60: 3 * 86400, 1440: 120 * 86400 }[minutes] || 3 * 86400;
    var end = Math.floor(Date.now() / 1000);
    var start = end - span;
    getJSON(API + "/events/" + encodeURIComponent(selected.event || ""))
      .then(function (ev) {
        var series = (ev && ev.event && ev.event.series_ticker) || "";
        if (!series) throw new Error("no series_ticker on the event record");
        var url = API + "/series/" + encodeURIComponent(series) + "/markets/" +
          encodeURIComponent(selected.ticker) + "/candlesticks?start_ts=" + start +
          "&end_ts=" + end + "&period_interval=" + minutes;
        return getJSON(url).then(function (d) { return { url: url, data: d }; });
      })
      .then(function (res) {
        var cs = (res.data && res.data.candlesticks) || [];
        var pts = cs.map(function (c) {
          var p = (c.price && (c.price.close_dollars !== undefined ? c.price.close_dollars : c.price.close)) ||
            (c.yes_bid && c.yes_bid.close_dollars);
          return { x: c.end_period_ts, y: Number(p),
                   label: new Date(c.end_period_ts * 1000).toISOString().slice(5, 16).replace("T", " ") };
        }).filter(function (p) { return !isNaN(p.y); });
        var unit = minutes === 1 ? "minute" : (minutes === 60 ? "hour" : "day");
        drawChart(pts, "demo API candlesticks, " + unit + " period · y = last traded YES price (USD) · " +
                  (pts.length ? pts.length + " candle(s)" : "the exchange published no candles for this window"));
        var b = $("liveChartBox");
        if (b) b.insertAdjacentHTML("beforeend",
          '<p class="muted small">Request: <span class="mono">' + esc(res.url) + "</span> " +
          link(res.url, "open") + " · series resolved from " +
          link(API + "/events/" + encodeURIComponent(selected.event || ""), "GET /events/{ticker}") +
          "</p>");
      })
      .catch(function (err) {
        box.innerHTML = '<p class="pill unv">chart unavailable: ' + esc(err.message) +
          "</p><p class=\"muted small\">No data is substituted for a failed request.</p>";
      });
  }

  /* ---- boot ---- */
  document.addEventListener("DOMContentLoaded", function () {
    var btn = $("liveRefresh");
    if (!btn) return;
    btn.addEventListener("click", refresh);
    var chk = $("liveAuto");
    if (chk) {
      chk.addEventListener("change", function () {
        liveOn = chk.checked;
        if (timer) { clearInterval(timer); timer = null; }
        if (liveOn) {
          var sel = $("liveInterval");
          interval = Math.max(10, Number(sel ? sel.value : 30) || 30);
          timer = setInterval(refresh, interval * 1000);
          status("auto-refresh every " + interval + "s (this browser)", "ok");
        } else { status("auto-refresh off"); }
      });
    }
    var sel2 = $("liveChart");
    if (sel2) sel2.addEventListener("change", function () {
      if (selected.ticker) drawFromApi();
    });
    if (!selected.ticker && TICKERS.length) {
      selected = { ticker: TICKERS[0], event: (TICKERS[0] || "").replace(/-[^-]*$/, "") };
    }
    refresh();
  });
})();
