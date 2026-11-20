/* Kalshi Demo Tracker — dashboard/page engine. All market data live from the
 * Kalshi Demo Trade API (browser -> Kalshi); paper trading is simulated and
 * labeled; live trading requires a demo API key (docs.kalshi.com/getting_started/api_keys).
 * Shared by dashboard.html, portfolio.html and trades.html (ids are guarded).
 */
(function () {
  "use strict";
  var K = window.KalshiDemo;
  var T = window.KalshiTrade;
  var $ = function (id) { return document.getElementById(id); };
  var state = {
    seriesByTopic: {}, markets: [], selected: null,
    samples: {}, candles: [], orderbook: null, trades: [],
    windowSec: 3600, scanSec: 20, obSec: 10,
    timers: [], resolutions: [], fills: [],
    connected: false, lastScan: null, errors: 0
  };
  try { state.resolutions = JSON.parse(localStorage.getItem("kd_resolutions") || "[]"); }
  catch (e) { state.resolutions = []; }

  function banner(kind, html) {
    var el = $("banner");
    if (!el) return;
    el.className = kind; el.innerHTML = html; el.style.display = html ? "block" : "none";
  }
  function showError(e) {
    state.errors++;
    var msg = K.esc(e.message || String(e));
    if (e instanceof TypeError) {
      msg += " — This usually means the browser blocked the request (CORS/network). " +
        "Static snapshots with source links remain available on the category pages and " +
        "<a href='flagged.html'>Flagged for review</a> (F1). " +
        "Source: https://docs.kalshi.com/getting_started/demo_env";
    }
    banner("error", "<strong>Request failed:</strong> " + msg);
  }
  function field(m, dollarsKey, legacyKey) {
    if (m[dollarsKey] !== undefined && m[dollarsKey] !== null && m[dollarsKey] !== "") {
      return Number(m[dollarsKey]);
    }
    if (m[legacyKey] !== undefined && m[legacyKey] !== null && m[legacyKey] !== "") {
      return Number(m[legacyKey]) / 100;
    }
    return null;
  }
  function marketRow(m) {
    var last = field(m, "last_price_dollars", "last_price");
    var yb = field(m, "yes_bid_dollars", "yes_bid");
    var ya = field(m, "yes_ask_dollars", "yes_ask");
    var vol = Number(m.volume_fp !== undefined ? m.volume_fp : m.volume || 0);
    var oi = Number(m.open_interest_fp !== undefined ? m.open_interest_fp :
      (m.open_interest || 0));
    return {
      ticker: m.ticker, event_ticker: m.event_ticker, title: m.title || m.ticker,
      status: m.status, result: m.result || "",
      last: last, yb: yb, ya: ya, vol: vol, oi: oi,
      volDollars: K.estDollars(vol, last), oiDollars: K.estDollars(oi, last),
      close_time: m.close_time, series_ticker: m.series_ticker || "",
      topic: m._topic || ""
    };
  }

  /* ---------- 1. Discovery (per-row API source links) ---------- */
  async function discover() {
    if (!$("discoveryTable")) return;
    $("discoveryStatus").textContent = "Discovering series from GET /series …";
    var all = await K.discoverSeries();
    var byTopic = {};
    K.TOPICS.forEach(function (t) { byTopic[t.id] = []; });
    var unmatched = 0;
    all.forEach(function (s) {
      if (s.topic) byTopic[s.topic].push(s); else unmatched++;
    });
    state.seriesByTopic = byTopic;
    var html = "";
    K.TOPICS.forEach(function (t) {
      var list = byTopic[t.id];
      html += "<h3>" + K.esc(t.label) + " — " + list.length + " series matched</h3>";
      if (!list.length) {
        html += "<p class='muted'>No series matched the keywords. Discovery is keyword-based " +
          "(see <a href='methodology.html'>Methodology</a>); add a series manually below.</p>";
        return;
      }
      html += "<table><thead><tr><th>Series ticker</th><th>Title</th>" +
        "<th>Matched keyword</th><th>Category</th><th>Frequency</th></tr></thead><tbody>";
      list.slice(0, 40).forEach(function (s) {
        html += "<tr><td class='mono'>" +
          K.srcLink("/series/" + encodeURIComponent(s.ticker), s.ticker) + "</td><td>" +
          K.esc(s.title) + "</td><td>" + K.esc(s.matched) + "</td><td>" +
          K.esc(s.category) + "</td><td>" + K.esc(s.frequency) + "</td></tr>";
      });
      html += "</tbody></table>";
    });
    html += "<p class='muted'>" + all.length + " series returned by the API; " +
      unmatched + " unmatched (not in the 5 tracked topics). Each ticker links its exact " +
      "API URL. Source: <a href='https://docs.kalshi.com/api-reference/market/get-series-list'>Get Series List</a>.</p>";
    $("discoveryTable").innerHTML = html;
    $("discoveryStatus").textContent = "Discovery complete — " + new Date().toLocaleTimeString();
  }

  /* ---------- 2. Market scan + ranking ---------- */
  async function scan() {
    try {
      var markets = [];
      var depthSel = $("scanDepth");
      var depth = depthSel ? Number(depthSel.value) : 15; // 0 = all
      var topics = Object.keys(state.seriesByTopic);
      for (var i = 0; i < topics.length; i++) {
        var topic = topics[i];
        var list = state.seriesByTopic[topic];
        var series = depth > 0 ? list.slice(0, depth) : list;
        for (var j = 0; j < series.length; j++) {
          try {
            var page = await K.apiGetAll("/markets",
              { series_ticker: series[j].ticker, status: "open", limit: 200 }, 3);
            page.forEach(function (m) { m._topic = topic; markets.push(m); });
          } catch (e) { /* one series failing must not kill the scan */ }
        }
      }
      var manual = (($("manualSeries") || {}).value || "").split(",").map(function (s) {
        return s.trim();
      }).filter(Boolean);
      for (var k = 0; k < manual.length; k++) {
        try {
          var mp = await K.apiGetAll("/markets",
            { series_ticker: manual[k], status: "open", limit: 200 }, 2);
          mp.forEach(function (m) { m._topic = m._topic || "manual"; markets.push(m); });
        } catch (e) { /* ignore */ }
      }
      state.markets = markets.map(marketRow);
      state.markets.sort(function (a, b) {
        return (b.volDollars || 0) - (a.volDollars || 0) ||
          (b.oiDollars || 0) - (a.oiDollars || 0);
      });
      state.lastScan = Date.now();
      renderRanking();
      recordSamples();
      trackResolutions();
      var capNote = depth > 0 ? ("top " + depth + " matched series per topic") : "ALL matched series";
      $("scanStatus").textContent = "Last scan: " + new Date().toLocaleTimeString() +
        " — " + state.markets.length + " open markets (coverage: " + capNote + ").";
      banner("", "");
    } catch (e) { showError(e); }
  }
  function renderRanking() {
    if (!$("rankingTable")) return;
    var top = state.markets.slice(0, 25);
    var html = "<table><thead><tr><th>#</th><th>Topic</th><th>Market</th>" +
      "<th class='num'>Last</th><th class='num'>Yes bid/ask</th>" +
      "<th class='num'>Volume (contracts)</th>" +
      "<th class='num'>Est. $ volume (unverified estimate)</th>" +
      "<th class='num'>Open interest</th><th class='num'>Est. $ OI (estimate)</th>" +
      "<th>Closes</th><th>Status</th><th></th></tr></thead><tbody>";
    top.forEach(function (m, i) {
      var sel = state.selected === m.ticker;
      html += "<tr" + (sel ? " style='background:#e6f4ec'" : "") + ">" +
        "<td class='num'>" + (i + 1) + "</td>" +
        "<td><span class='pill'>" + K.esc(m.topic) + "</span></td>" +
        "<td>" + K.esc(m.title) + "<br><span class='mono small muted'>" +
        K.srcLink("/markets/" + encodeURIComponent(m.ticker), m.ticker) + "</span></td>" +
        "<td class='num'>" + K.cents(m.last) + "</td>" +
        "<td class='num'>" + K.cents(m.yb) + " / " + K.cents(m.ya) + "</td>" +
        "<td class='num'>" + K.num(m.vol, 0) + "</td>" +
        "<td class='num'>" + (m.volDollars === null ? "—" : K.money(m.volDollars)) + "</td>" +
        "<td class='num'>" + K.num(m.oi, 0) + "</td>" +
        "<td class='num'>" + (m.oiDollars === null ? "—" : K.money(m.oiDollars)) + "</td>" +
        "<td>" + K.timeStr(m.close_time ? Date.parse(m.close_time) / 1000 : null) + "</td>" +
        "<td>" + K.esc(m.status) + "</td>" +
        "<td><button class='btn secondary' data-ticker='" + K.esc(m.ticker) +
        "'>Track</button></td></tr>";
    });
    html += "</tbody></table><p class='muted'>Estimated $ = contracts × last price — an " +
      "<strong>unverified estimate</strong> (the API reports contracts, not dollars). " +
      "Each ticker links its exact API URL. Methodology: " +
      "<a href='methodology.html'>Methodology</a>. Source: " +
      "<a href='https://docs.kalshi.com/api-reference/market/get-markets'>Get Markets</a> " +
      "(live, demo environment).</p>";
    $("rankingTable").innerHTML = html;
    Array.prototype.forEach.call($("rankingTable").querySelectorAll("button[data-ticker]"),
      function (b) {
        b.addEventListener("click", function () { selectMarket(b.getAttribute("data-ticker")); });
      });
  }
  function recordSamples() {
    var now = Math.floor(Date.now() / 1000);
    state.markets.forEach(function (m) {
      if (m.last === null) return;
      var arr = state.samples[m.ticker] || (state.samples[m.ticker] = []);
      var last = arr[arr.length - 1];
      if (!last || now - last.t >= 5) {
        arr.push({ t: now, price: m.last, bid: m.yb, ask: m.ya });
        if (arr.length > 4000) arr.splice(0, arr.length - 4000);
      }
    });
  }

  /* ---------- 3. Detail: chart (seconds/minutes/hours) + orderbook + trades ---------- */
  async function selectMarket(ticker) {
    state.selected = ticker;
    renderRanking();
    if (window.KalshiAlerts && window.KalshiAlerts.onSelected) {
      window.KalshiAlerts.onSelected(ticker);
    }
    var m = state.markets.find(function (x) { return x.ticker === ticker; });
    if ($("detailTitle")) {
      $("detailTitle").textContent = m ? (m.title + " (" + ticker + ")") : ticker;
    }
    if ($("detailMeta")) {
      $("detailMeta").innerHTML = m ?
        ("Topic: " + K.esc(m.topic) + " · Status: " + K.esc(m.status) + " · Last: " +
         K.cents(m.last) + " · Yes bid/ask: " + K.cents(m.yb) + "/" + K.cents(m.ya) +
         " · Volume: " + K.num(m.vol, 0) + " contracts · OI: " + K.num(m.oi, 0) +
         " · API: " + K.srcLink("/markets/" + encodeURIComponent(ticker), "market")) : "";
    }
    var tk = $("tradeTicker");
    if (tk) tk.value = ticker;
    await loadCandles();
    await loadOrderbook();
    await loadTrades();
    drawChart();
  }
  function periodFor(windowSec) {
    // candlesticks period_interval is in minutes (docs: get-market-candlesticks)
    return windowSec > 21600 ? 60 : 1;
  }
  async function loadCandles() {
    var m = state.markets.find(function (x) { return x.ticker === state.selected; });
    if (!m || !m.series_ticker) {
      state.candles = (state.samples[state.selected] || [])
        .filter(function (p) { return p.t >= Math.floor(Date.now() / 1000) - state.windowSec; });
      return;
    }
    var end = Math.floor(Date.now() / 1000);
    var start = end - state.windowSec;
    try {
      var j = await K.apiGet("/series/" + encodeURIComponent(m.series_ticker) +
        "/markets/" + encodeURIComponent(state.selected) + "/candlesticks",
        { start_ts: start, end_ts: end, period_interval: periodFor(state.windowSec) });
      var candles = (j.candlesticks || []).map(function (c) {
        var p = c.price || {};
        return { t: c.end_period_ts, price: Number(p.close_dollars),
          bid: c.yes_bid ? Number(c.yes_bid.close_dollars) : null,
          ask: c.yes_ask ? Number(c.yes_ask.close_dollars) : null };
      }).filter(function (p) { return !isNaN(p.price); });
      var byT = {};
      candles.forEach(function (p) { byT[p.t] = p; });
      (state.samples[state.selected] || []).forEach(function (p) {
        if (p.t >= start) byT[p.t] = p; // live samples win (finer granularity)
      });
      state.candles = Object.keys(byT).map(Number).sort(function (a, b) { return a - b; })
        .map(function (t) { return byT[t]; });
    } catch (e) {
      state.candles = (state.samples[state.selected] || [])
        .filter(function (p) { return p.t >= start; });
    }
  }
  function drawChart() {
    if (!$("priceChart")) return;
    var pts = state.candles || [];
    var A = window.KalshiAlerts;
    K.drawPriceChart($("priceChart"), pts, {
      windowLabel: "window: " + windowLabel(), spanSec: state.windowSec,
      annotations: (A && A.annotationsFor) ? A.annotationsFor(state.selected) : []
    });
  }
  function windowLabel() {
    var s = state.windowSec;
    if (s < 60) return s + " s";
    if (s < 3600) return Math.round(s / 60) + " min";
    return (s / 3600) + " h";
  }
  async function loadOrderbook() {
    if (!state.selected) return;
    try {
      var j = await K.apiGet("/markets/" + encodeURIComponent(state.selected) + "/orderbook", {});
      var ob = j.orderbook_fp || j.orderbook || {};
      function levels(arr) {
        return (arr || []).map(function (l) {
          return { price: Number(l[0]), count: Number(l[1]) };
        }).filter(function (l) { return !isNaN(l.price) && !isNaN(l.count); });
      }
      var yes = levels(ob.yes_dollars), no = levels(ob.no_dollars);
      state.orderbook = { yes: yes, no: no };
      if ($("depthChart")) K.drawDepthChart($("depthChart"), yes, no);
      var bestY = yes.length ? yes[yes.length - 1] : null;
      var bestN = no.length ? no[no.length - 1] : null;
      var spread = (bestY && bestN) ? (1 - bestN.price) - bestY.price : null;
      var liq = yes.reduce(function (a, l) { return a + l.count * l.price; }, 0) +
        no.reduce(function (a, l) { return a + l.count * l.price; }, 0);
      var totContracts = yes.reduce(function (a, l) { return a + l.count; }, 0) +
        no.reduce(function (a, l) { return a + l.count; }, 0);
      if ($("obSummary")) {
        $("obSummary").innerHTML =
          "Best YES bid: <strong>" + (bestY ? K.cents(bestY.price) : "—") + "</strong> (" +
          (bestY ? K.num(bestY.count, 0) : "—") + " contracts) · " +
          "Best NO bid: <strong>" + (bestN ? K.cents(bestN.price) : "—") + "</strong> (" +
          (bestN ? K.num(bestN.count, 0) : "—") + ") · " +
          "Implied YES ask: <strong>" +
          (bestN ? K.cents(1 - bestN.price) : "—") + "</strong> · " +
          "Spread: <strong>" + (spread === null ? "—" : K.cents(spread)) + "</strong> · " +
          "Resting liquidity (Σ price×contracts): <strong>" + K.money(liq) + "</strong> · " +
          "Total contracts at rest: <strong>" + K.num(totContracts, 0) + "</strong> · " +
          "Levels: " + yes.length + " YES / " + no.length + " NO. " +
          "Source: " + K.srcLink("/markets/" + encodeURIComponent(state.selected) + "/orderbook",
            "orderbook") + " · " +
          "<a href='https://docs.kalshi.com/getting_started/orderbook_responses'>Orderbook Responses</a>.";
      }
      if ($("obTable")) {
        var html = "<table><thead><tr><th>YES price</th><th class='num'>YES contracts</th>" +
          "<th>NO price</th><th class='num'>NO contracts</th></tr></thead><tbody>";
        var n = Math.max(yes.length, no.length);
        for (var i = n - 1; i >= 0; i--) {
          var y = yes[i], noL = no[i];
          html += "<tr><td>" + (y ? K.cents(y.price) : "—") + "</td><td class='num'>" +
            (y ? K.num(y.count, 0) : "—") + "</td><td>" + (noL ? K.cents(noL.price) : "—") +
            "</td><td class='num'>" + (noL ? K.num(noL.count, 0) : "—") + "</td></tr>";
        }
        html += "</tbody></table><p class='small muted'>Contracts available at each price " +
          "(best bids at the top). " +
          K.srcLink("/markets/" + encodeURIComponent(state.selected) + "/orderbook", "API source") + "</p>";
        $("obTable").innerHTML = html;
      }
    } catch (e) { showError(e); }
  }
  async function loadTrades() {
    if (!state.selected || !$("tradesTable")) return;
    try {
      var j = await K.apiGet("/markets/trades",
        { ticker: state.selected, limit: 50 });
      state.trades = j.trades || [];
      var html = "<table><thead><tr><th>Time</th><th class='num'>Count</th>" +
        "<th class='num'>YES price</th><th class='num'>NO price</th>" +
        "<th>Taker side</th><th>Block?</th></tr></thead><tbody>";
      state.trades.forEach(function (t) {
        html += "<tr><td>" + K.esc(t.created_time || "") + "</td><td class='num'>" +
          K.num(t.count_fp, 0) + "</td><td class='num'>" + K.cents(t.yes_price_dollars) +
          "</td><td class='num'>" + K.cents(t.no_price_dollars) + "</td><td>" +
          K.esc(t.taker_outcome_side || t.taker_side || "") + "</td><td>" +
          (t.is_block_trade ? "yes" : "no") + "</td></tr>";
      });
      html += "</tbody></table><p class='muted'>Source: " +
        K.srcLink("/markets/trades?ticker=" + encodeURIComponent(state.selected), "trades") +
        " · <a href='https://docs.kalshi.com/api-reference/market/get-trades'>Get Trades</a> (live).</p>";
      $("tradesTable").innerHTML = html;
    } catch (e) { showError(e); }
  }

  /* ---------- 4. Resolution tracking (yes / no) ---------- */
  function trackResolutions() {
    var changed = false;
    state.markets.forEach(function (m) {
      if ((m.status === "closed" || m.status === "settled" || m.status === "finalized") &&
          m.result &&
          !state.resolutions.find(function (r) { return r.ticker === m.ticker; })) {
        state.resolutions.push({ ticker: m.ticker, title: m.title, topic: m.topic,
          result: String(m.result).toLowerCase(), status: m.status,
          ts: Math.floor(Date.now() / 1000) });
        changed = true;
      }
    });
    if (changed) {
      localStorage.setItem("kd_resolutions", JSON.stringify(state.resolutions));
      renderResolutions();
    }
    if (T && T.markResolutions) {
      T.markResolutions(state.resolutions.concat(seededResolutionList()));
    }
  }
  var seeded = [];
  function seededResolutionList() { return seeded; }
  function renderResolutions() {
    if (!$("resolutionsTable")) return;
    var html = "<table><thead><tr><th>Market</th><th>Topic</th><th>Result</th>" +
      "<th>Status</th><th>Logged at</th></tr></thead><tbody>";
    if (!state.resolutions.length) {
      html += "<tr><td colspan='5' class='muted'>No resolutions logged yet. " +
        "Markets are logged when they close/settle with a yes/no result while this page is open. " +
        "Settlement pays $1/contract to winners — " +
        "<a href='https://docs.kalshi.com/getting_started/market_settlement'>Market Settlement</a>.</td></tr>";
    }
    state.resolutions.slice().reverse().forEach(function (r) {
      html += "<tr><td>" + K.esc(r.title) + "<br><span class='mono small muted'>" +
        K.esc(r.ticker) + "</span></td><td>" + K.esc(r.topic) + "</td>" +
        "<td><span class='pill'>" + K.esc(r.result) + "</span></td><td>" +
        K.esc(r.status) + "</td><td>" + K.timeStr(r.ts) + "</td></tr>";
    });
    html += "</tbody></table>";
    $("resolutionsTable").innerHTML = html;
  }
  async function loadSeededResolutions() {
    var el = $("seededResolutions");
    if (!el) return;
    var rows = [];
    function push(list, srcKey) {
      (list || []).forEach(function (r) {
        if (r && r.result) {
          rows.push({ ticker: r.ticker, title: r.title || r.ticker, topic: r.topic || r.cat || "",
            result: String(r.result).toLowerCase(), when: r.settlement_ts || r.close_time || "",
            src: r[srcKey] || r.source || "" });
        }
      });
    }
    try {
      var snap = await (await fetch("docs/tracker/data/snapshot.json")).json();
      push(snap.markets, "source_api");
    } catch (e) { /* archive may be unavailable */ }
    try {
      var ver = await (await fetch("docs/data/verified.json")).json();
      push(ver.resolved, "source");
    } catch (e) { /* */ }
    seeded = rows;
    if (T && T.markResolutions) T.markResolutions(state.resolutions.concat(rows));
    var html = "<table><thead><tr><th>Market</th><th>Topic</th><th>Resolved</th>" +
      "<th>Settled / closed</th></tr></thead><tbody>";
    if (!rows.length) {
      html += "<tr><td colspan='4' class='muted'>Snapshot archives did not load " +
        "(open <a href='docs/tracker/data/snapshot.json'>snapshot.json</a> directly).</td></tr>";
    }
    rows.forEach(function (r) {
      html += "<tr><td>" + K.esc(r.title) + "<br><span class='mono small'>" +
        K.srcLink(r.src.indexOf("http") === 0 ? r.src : r.src, r.ticker) + "</span></td>" +
        "<td>" + K.esc(r.topic) + "</td><td><span class='pill'>" + K.esc(r.result) +
        "</span></td><td>" + K.esc(r.when) + "</td></tr>";
    });
    html += "</tbody></table>";
    el.innerHTML = html;
  }

  /* ---------- 5. Portfolio (live with key; paper via KalshiTrade) ---------- */
  async function connect() {
    try {
      var keyId = ($("keyId") || {}).value || "";
      var pem = ($("keyPem") || {}).value || "";
      keyId = keyId.trim();
      if (!keyId || !pem.trim()) throw new Error("Enter both Key ID and private key PEM.");
      var alg = await K.Auth.load(keyId, pem);
      localStorage.setItem("kd_key", JSON.stringify({ keyId: keyId, pem: pem }));
      state.connected = true;
      if ($("connStatus")) {
        $("connStatus").innerHTML = "<span class='pill'>Connected (" + K.esc(alg) + ") — LIVE demo</span>";
      }
      if (T) T.setLive(true);
      await refreshPortfolio();
    } catch (e) { showError(e); }
  }
  function disconnect() {
    localStorage.removeItem("kd_key");
    state.connected = false;
    if ($("keyId")) $("keyId").value = "";
    if ($("keyPem")) $("keyPem").value = "";
    if ($("connStatus")) {
      $("connStatus").innerHTML = "<span class='pill warn'>Not connected — paper mode</span>";
    }
    if ($("portfolioBody")) $("portfolioBody").innerHTML = "<p class='muted'>Disconnected — paper mode.</p>";
    if (T) T.setLive(false);
  }
  async function refreshPortfolio() {
    if (!state.connected) return;
    try {
      var bal = await K.Auth.request("GET", "/portfolio/balance", {});
      var pos = await K.Auth.request("GET", "/portfolio/positions",
        { settlement_status: "all", limit: 200 });
      var fills = await K.Auth.request("GET", "/portfolio/fills", { limit: 500 });
      var orders = null;
      try { orders = await K.Auth.request("GET", "/portfolio/orders", { limit: 100 }); }
      catch (e) { /* orders read is optional */ }
      state.fills = fills.fills || [];
      renderPortfolio(bal, pos, orders);
      if (T) {
        T.setLive(true);
        if (T.refreshLivePortfolio) await T.refreshLivePortfolio();
        T.renderAll();
      }
    } catch (e) { showError(e); }
  }
  function renderPortfolio(bal, pos, orders) {
    if (!$("portfolioBody")) return;
    var html = "<div class='grid'>" +
      "<div class='card'><div class='muted'>Available balance</div><div class='stat'>" +
      K.money(bal.balance_dollars !== undefined ? bal.balance_dollars :
        (bal.balance / 100)) + "</div></div>" +
      "<div class='card'><div class='muted'>Portfolio value</div><div class='stat'>" +
      K.money((bal.portfolio_value_dollars !== undefined ? bal.portfolio_value_dollars :
        (bal.portfolio_value || 0) / 100)) + "</div></div>" +
      "<div class='card'><div class='muted'>Open positions</div><div class='stat'>" +
      ((pos.market_positions || []).length) + "</div></div></div>";
    html += "<h3>Positions</h3><table><thead><tr><th>Ticker</th><th class='num'>Qty</th>" +
      "<th class='num'>Avg cost</th><th class='num'>Realized P&L</th><th>Settlement</th>" +
      "</tr></thead><tbody>";
    (pos.market_positions || []).forEach(function (p) {
      html += "<tr><td class='mono'>" + K.esc(p.ticker || p.market_ticker || "") +
        "</td><td class='num'>" + K.num(p.position_fp || p.position, 0) + "</td>" +
        "<td class='num'>" + K.esc(p.average_cost_dollars || p.average_cost || "—") +
        "</td><td class='num'>" + K.esc(p.realized_pnl_dollars || p.realized_pnl || "—") +
        "</td><td>" + K.esc(p.settlement_status || "") + "</td></tr>";
    });
    html += "</tbody></table>";
    html += "<h3>Recent fills (" + state.fills.length + ")</h3>" +
      "<table><thead><tr><th>Ticker</th><th>Side</th><th class='num'>Count</th>" +
      "<th class='num'>YES price</th><th class='num'>Fee</th><th>Taker?</th></tr>" +
      "</thead><tbody>";
    state.fills.slice(0, 30).forEach(function (f) {
      html += "<tr><td class='mono'>" + K.esc(f.ticker || f.market_ticker || "") +
        "</td><td>" + K.esc(f.outcome_side || f.side || "") + "</td><td class='num'>" +
        K.num(f.count_fp, 0) + "</td><td class='num'>" + K.cents(f.yes_price_dollars) +
        "</td><td class='num'>" + K.esc(f.fee_cost || "—") + "</td><td>" +
        (f.is_taker ? "yes" : "no") + "</td></tr>";
    });
    html += "</tbody></table>";
    if (orders && orders.orders) {
      html += "<h3>Orders (" + orders.orders.length + ")</h3>" +
        "<table><thead><tr><th>Order ID</th><th>Ticker</th><th>Status</th>" +
        "<th class='num'>Filled / Remaining</th></tr></thead><tbody>";
      orders.orders.slice(0, 30).forEach(function (o) {
        html += "<tr><td class='mono small'>" + K.esc(o.order_id || "") + "</td>" +
          "<td class='mono'>" + K.esc(o.ticker || "") + "</td><td>" + K.esc(o.status || "") +
          "</td><td class='num'>" + K.num(o.fill_count_fp, 0) + " / " +
          K.num(o.remaining_count_fp, 0) + "</td></tr>";
      });
      html += "</tbody></table>";
    }
    html += "<p class='muted'>Sources: " +
      K.srcLink("/portfolio/balance", "balance") + " · " +
      K.srcLink("/portfolio/positions", "positions") + " · " +
      K.srcLink("/portfolio/fills", "fills") + " · " +
      "<a href='https://docs.kalshi.com/api-reference/portfolio/get-balance'>Get Balance</a>, " +
      "<a href='https://docs.kalshi.com/api-reference/portfolio/get-positions'>Get Positions</a>, " +
      "<a href='https://docs.kalshi.com/api-reference/portfolio/get-fills'>Get Fills</a>, " +
      "<a href='https://docs.kalshi.com/api-reference/orders/get-orders'>Get Orders</a> " +
      "(live, demo account).</p>";
    $("portfolioBody").innerHTML = html;
  }

  /* ---------- wiring ---------- */
  function setWindow(sec) {
    state.windowSec = sec;
    Array.prototype.forEach.call(document.querySelectorAll("[data-window]"),
      function (b) {
        b.setAttribute("aria-pressed", String(Number(b.getAttribute("data-window")) === sec));
      });
    if (state.selected) { loadCandles().then(drawChart); }
  }
  function startTimers() {
    state.timers.forEach(clearInterval);
    state.timers = [
      setInterval(function () { if ($("rankingTable")) scan(); }, state.scanSec * 1000),
      setInterval(function () {
        if (state.selected) { loadOrderbook(); loadTrades(); }
      }, state.obSec * 1000),
      setInterval(function () {
        if (state.selected) { recordSamples(); loadCandles().then(drawChart); }
      }, 15000)
    ];
  }
  async function init() {
    try {
      var saved = JSON.parse(localStorage.getItem("kd_key") || "null");
      if (saved && saved.keyId && saved.pem) {
        if ($("keyId")) $("keyId").value = saved.keyId;
        if ($("keyPem")) $("keyPem").value = saved.pem;
        await K.Auth.load(saved.keyId, saved.pem);
        state.connected = true;
        if ($("connStatus")) {
          $("connStatus").innerHTML = "<span class='pill'>Connected (" +
            K.esc(K.Auth.alg) + ") — LIVE demo</span>";
        }
        if (T) T.setLive(true);
        refreshPortfolio();
      }
    } catch (e) { /* key may be stale; user can reconnect */ }
    if ($("connectBtn")) $("connectBtn").addEventListener("click", connect);
    if ($("disconnectBtn")) $("disconnectBtn").addEventListener("click", disconnect);
    if ($("refreshPortfolioBtn")) $("refreshPortfolioBtn").addEventListener("click", refreshPortfolio);
    if ($("discoverBtn")) $("discoverBtn").addEventListener("click", function () {
      discover().then(scan);
    });
    if ($("scanBtn")) $("scanBtn").addEventListener("click", scan);
    if ($("refreshObBtn")) $("refreshObBtn").addEventListener("click", function () {
      loadOrderbook(); loadTrades();
    });
    if ($("clearResolutionsBtn")) $("clearResolutionsBtn").addEventListener("click", function () {
      state.resolutions = []; localStorage.removeItem("kd_resolutions");
      renderResolutions();
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-window]"),
      function (b) {
        b.addEventListener("click", function () {
          setWindow(Number(b.getAttribute("data-window")));
        });
      });
    // Trade ticket + shared analysis renders
    if (T) {
      T.mountTicket($("tradeTicket"));
      T.renderAll();
    }
    renderResolutions();
    loadSeededResolutions();
    startTimers();
    if ($("discoveryTable")) {
      try {
        await discover();
        await scan();
      } catch (e) { showError(e); }
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
  /* Shared handle for assets/alerts.js (swing-alert engine): the live market
   * list for its watch set + a redraw hook so chart annotations refresh as
   * alerts arrive. Read-only for the alerts layer. */
  window.KalshiDash = { state: state, drawChart: drawChart };
})();
