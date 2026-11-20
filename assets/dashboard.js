/* Kalshi Demo Dashboard — page logic. All data live from the Demo Trade API. */
(function () {
  "use strict";
  var K = window.KalshiDemo;
  var $ = function (id) { return document.getElementById(id); };
  var state = {
    seriesByTopic: {}, markets: [], selected: null,
    samples: {}, orderbook: null, trades: [],
    windowSec: 900, scanSec: 20, obSec: 10,
    timers: [], resolutions: [], journal: [], fills: [],
    connected: false, lastScan: null, errors: 0
  };
  try { state.resolutions = JSON.parse(localStorage.getItem("kd_resolutions") || "[]"); }
  catch (e) { state.resolutions = []; }
  try { state.journal = JSON.parse(localStorage.getItem("kd_journal") || "[]"); }
  catch (e) { state.journal = []; }

  function banner(kind, html) {
    var el = $("banner");
    el.className = kind; el.innerHTML = html; el.style.display = html ? "block" : "none";
  }
  function showError(e) {
    state.errors++;
    var msg = K.esc(e.message || String(e));
    if (e instanceof TypeError) {
      msg += " — This usually means the browser blocked the request (CORS/network). " +
        "Check your connection and see the Flagged for Review page. " +
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

  /* ---------- 1. Discovery ---------- */
  async function discover() {
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
        html += "<p class='muted'>No series matched the keywords. " +
          "Discovery is keyword-based (see Methodology); add a series manually below.</p>";
        return;
      }
      html += "<table><thead><tr><th>Series ticker</th><th>Title</th>" +
        "<th>Matched keyword</th><th>Category</th><th>Frequency</th></tr></thead><tbody>";
      list.slice(0, 40).forEach(function (s) {
        html += "<tr><td class='mono'>" + K.esc(s.ticker) + "</td><td>" +
          K.esc(s.title) + "</td><td>" + K.esc(s.matched) + "</td><td>" +
          K.esc(s.category) + "</td><td>" + K.esc(s.frequency) + "</td></tr>";
      });
      html += "</tbody></table>";
    });
    html += "<p class='muted'>" + all.length + " series returned by the API; " +
      unmatched + " unmatched (not in the 5 tracked topics). " +
      "Source: <a href='https://docs.kalshi.com/api-reference/market/get-series-list'>Get Series List</a>.</p>";
    $("discoveryTable").innerHTML = html;
    $("discoveryStatus").textContent = "Discovery complete — " + new Date().toLocaleTimeString();
  }

  /* ---------- 2. Market scan + ranking ---------- */
  async function scan() {
    try {
      var markets = [];
      var topics = Object.keys(state.seriesByTopic);
      for (var i = 0; i < topics.length; i++) {
        var topic = topics[i];
        var series = state.seriesByTopic[topic].slice(0, 15); // rate-limit guard
        for (var j = 0; j < series.length; j++) {
          try {
            var page = await K.apiGetAll("/markets",
              { series_ticker: series[j].ticker, status: "open", limit: 200 }, 3);
            page.forEach(function (m) { m._topic = topic; markets.push(m); });
          } catch (e) { /* one series failing must not kill the scan */ }
        }
      }
      // Manual series (optional override)
      var manual = ($("manualSeries").value || "").split(",").map(function (s) {
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
      // Rank by estimated dollar volume (contracts × last price), then OI dollars.
      state.markets.sort(function (a, b) {
        return (b.volDollars || 0) - (a.volDollars || 0) ||
          (b.oiDollars || 0) - (a.oiDollars || 0);
      });
      state.lastScan = Date.now();
      renderRanking();
      recordSamples();
      trackResolutions();
      $("scanStatus").textContent = "Last scan: " + new Date().toLocaleTimeString() +
        " — " + state.markets.length + " open markets across 5 topics.";
      banner("", "");
    } catch (e) { showError(e); }
  }
  function renderRanking() {
    var top = state.markets.slice(0, 25);
    var html = "<table><thead><tr><th>#</th><th>Topic</th><th>Market</th>" +
      "<th class='num'>Last</th><th class='num'>Yes bid/ask</th>" +
      "<th class='num'>Volume (contracts)</th><th class='num'>Est. $ volume</th>" +
      "<th class='num'>Open interest</th><th class='num'>Est. $ OI</th>" +
      "<th>Closes</th><th>Status</th><th></th></tr></thead><tbody>";
    top.forEach(function (m, i) {
      var sel = state.selected === m.ticker;
      html += "<tr" + (sel ? " style='background:#e6f4ec'" : "") + ">" +
        "<td class='num'>" + (i + 1) + "</td>" +
        "<td><span class='pill'>" + K.esc(m.topic) + "</span></td>" +
        "<td>" + K.esc(m.title) + "<br><span class='mono small muted'>" +
        K.esc(m.ticker) + "</span></td>" +
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
    html += "</tbody></table><p class='muted'>Estimated $ = contracts × last price " +
      "(the API reports contracts, not dollars). Methodology: " +
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
        if (arr.length > 2000) arr.splice(0, arr.length - 2000);
      }
    });
  }

  /* ---------- 3. Detail: chart + orderbook + trades ---------- */
  async function selectMarket(ticker) {
    state.selected = ticker;
    renderRanking();
    var m = state.markets.find(function (x) { return x.ticker === ticker; });
    $("detailTitle").textContent = m ? (m.title + " (" + ticker + ")") : ticker;
    $("detailMeta").textContent = m ?
      ("Topic: " + m.topic + " · Status: " + m.status + " · Last: " + K.cents(m.last) +
       " · Yes bid/ask: " + K.cents(m.yb) + "/" + K.cents(m.ya) +
       " · Volume: " + K.num(m.vol, 0) + " contracts · OI: " + K.num(m.oi, 0)) : "";
    $("tradeTicker").value = ticker;
    await loadCandles();
    await loadOrderbook();
    await loadTrades();
    drawChart();
  }
  async function loadCandles() {
    var m = state.markets.find(function (x) { return x.ticker === state.selected; });
    if (!m || !m.series_ticker) return;
    var end = Math.floor(Date.now() / 1000);
    var start = end - state.windowSec;
    try {
      var j = await K.apiGet("/series/" + encodeURIComponent(m.series_ticker) +
        "/markets/" + encodeURIComponent(state.selected) + "/candlesticks",
        { start_ts: start, end_ts: end, period_interval: 1 });
      var candles = (j.candlesticks || []).map(function (c) {
        var p = c.price || {};
        return { t: c.end_period_ts, price: Number(p.close_dollars),
          bid: c.yes_bid ? Number(c.yes_bid.close_dollars) : null,
          ask: c.yes_ask ? Number(c.yes_ask.close_dollars) : null };
      }).filter(function (p) { return !isNaN(p.price); });
      // Merge with live samples (dedupe by timestamp, keep latest).
      var byT = {};
      (state.samples[state.selected] || []).forEach(function (p) { byT[p.t] = p; });
      candles.forEach(function (p) { if (!byT[p.t]) byT[p.t] = p; });
      state.candles = Object.keys(byT).map(Number).sort(function (a, b) { return a - b; })
        .map(function (t) { return byT[t]; })
        .filter(function (p) { return p.t >= start; });
    } catch (e) {
      state.candles = (state.samples[state.selected] || [])
        .filter(function (p) { return p.t >= start; });
    }
  }
  function drawChart() {
    var pts = state.candles || [];
    var label = "window: " + windowLabel();
    K.drawPriceChart($("priceChart"), pts, { windowLabel: label });
  }
  function windowLabel() {
    var s = state.windowSec;
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
      K.drawDepthChart($("depthChart"), yes, no);
      var bestY = yes.length ? yes[yes.length - 1] : null;
      var bestN = no.length ? no[no.length - 1] : null;
      var spread = (bestY && bestN) ? (1 - bestN.price) - bestY.price : null;
      var liq = yes.reduce(function (a, l) { return a + l.count * l.price; }, 0) +
        no.reduce(function (a, l) { return a + l.count * l.price; }, 0);
      var totContracts = yes.reduce(function (a, l) { return a + l.count; }, 0) +
        no.reduce(function (a, l) { return a + l.count; }, 0);
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
        "Source: <a href='https://docs.kalshi.com/getting_started/orderbook_responses'>Orderbook Responses</a>.";
      var html = "<table><thead><tr><th>YES price</th><th class='num'>YES contracts</th>" +
        "<th>NO price</th><th class='num'>NO contracts</th></tr></thead><tbody>";
      var n = Math.max(yes.length, no.length);
      for (var i = n - 1; i >= 0; i--) {
        var y = yes[i], noL = no[i];
        html += "<tr><td>" + (y ? K.cents(y.price) : "—") + "</td><td class='num'>" +
          (y ? K.num(y.count, 0) : "—") + "</td><td>" + (noL ? K.cents(noL.price) : "—") +
          "</td><td class='num'>" + (noL ? K.num(noL.count, 0) : "—") + "</td></tr>";
      }
      html += "</tbody></table>";
      $("obTable").innerHTML = html;
    } catch (e) { showError(e); }
  }
  async function loadTrades() {
    if (!state.selected) return;
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
        "<a href='https://docs.kalshi.com/api-reference/market/get-trades'>Get Trades</a> (live).</p>";
      $("tradesTable").innerHTML = html;
    } catch (e) { showError(e); }
  }

  /* ---------- 4. Resolution tracking ---------- */
  function trackResolutions() {
    var changed = false;
    state.markets.forEach(function (m) {
      if ((m.status === "closed" || m.status === "settled") && m.result &&
          !state.resolutions.find(function (r) { return r.ticker === m.ticker; })) {
        state.resolutions.push({ ticker: m.ticker, title: m.title, topic: m.topic,
          result: m.result, status: m.status, ts: Math.floor(Date.now() / 1000) });
        changed = true;
      }
    });
    if (changed) {
      localStorage.setItem("kd_resolutions", JSON.stringify(state.resolutions));
      renderResolutions();
    }
  }
  function renderResolutions() {
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

  /* ---------- 5. Portfolio (optional demo key) ---------- */
  async function connect() {
    try {
      var keyId = $("keyId").value.trim();
      var pem = $("keyPem").value;
      if (!keyId || !pem.trim()) throw new Error("Enter both Key ID and private key PEM.");
      var alg = await K.Auth.load(keyId, pem);
      localStorage.setItem("kd_key", JSON.stringify({ keyId: keyId, pem: pem }));
      state.connected = true;
      $("connStatus").innerHTML = "<span class='pill'>Connected (" + K.esc(alg) + ")</span>";
      await refreshPortfolio();
    } catch (e) { showError(e); }
  }
  function disconnect() {
    localStorage.removeItem("kd_key");
    state.connected = false;
    $("keyId").value = ""; $("keyPem").value = "";
    $("connStatus").innerHTML = "<span class='pill warn'>Not connected</span>";
    $("portfolioBody").innerHTML = "<p class='muted'>Disconnected.</p>";
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
      renderStrategy();
    } catch (e) { showError(e); }
  }
  function renderPortfolio(bal, pos, orders) {
    var html = "<div class='grid'>" +
      "<div class='card'><div class='muted'>Available balance</div><div class='stat'>" +
      K.money(bal.balance_dollars !== undefined ? bal.balance_dollars :
        (bal.balance / 100)) + "</div></div>" +
      "<div class='card'><div class='muted'>Portfolio value</div><div class='stat'>" +
      K.money(bal.portfolio_value / 100) + "</div></div>" +
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
      "<a href='https://docs.kalshi.com/api-reference/portfolio/get-balance'>Get Balance</a>, " +
      "<a href='https://docs.kalshi.com/api-reference/portfolio/get-positions'>Get Positions</a>, " +
      "<a href='https://docs.kalshi.com/api-reference/portfolio/get-fills'>Get Fills</a>, " +
      "<a href='https://docs.kalshi.com/api-reference/orders/get-orders'>Get Orders</a> (live, demo account).</p>";
    $("portfolioBody").innerHTML = html;
  }

  /* ---------- 6. Trading ---------- */
  async function placeOrder() {
    if (!state.connected) { showError(new Error("Connect a demo API key first.")); return; }
    var body = {
      ticker: $("tradeTicker").value.trim(),
      side: $("tradeSide").value,
      count: $("tradeCount").value,
      price: $("tradePrice").value,
      time_in_force: $("tradeTif").value,
      self_trade_prevention_type: "taker_at_cross",
      post_only: $("tradePostOnly").checked
    };
    if (!body.ticker || !body.count || !body.price) {
      showError(new Error("Ticker, count and price are required.")); return;
    }
    if (!confirm("Place demo order?\n" + JSON.stringify(body, null, 2) +
      "\nDemo funds only. This sends a real order to the Kalshi demo exchange.")) return;
    try {
      var res = await K.Auth.request("POST", "/portfolio/events/orders", {}, body);
      state.journal.push({ ts: Math.floor(Date.now() / 1000), kind: "order", body: body,
        response: res });
      localStorage.setItem("kd_journal", JSON.stringify(state.journal));
      $("tradeResult").innerHTML = "<div class='ok'><strong>Order accepted (201).</strong> " +
        "A 201 means accepted, not resting — check remaining_count. " +
        K.esc(JSON.stringify(res)) + "</div>";
      await refreshPortfolio();
      renderStrategy();
    } catch (e) { showError(e); }
  }
  async function cancelOrder() {
    if (!state.connected) { showError(new Error("Connect a demo API key first.")); return; }
    var orderId = $("cancelOrderId").value.trim();
    var ticker = $("tradeTicker").value.trim();
    if (!orderId) { showError(new Error("Enter an order ID to cancel.")); return; }
    try {
      var res = await K.Auth.request("DELETE",
        "/portfolio/events/orders/" + encodeURIComponent(orderId),
        { market_ticker: ticker });
      $("tradeResult").innerHTML = "<div class='ok'><strong>Cancelled.</strong> " +
        K.esc(JSON.stringify(res)) + "</div>";
      await refreshPortfolio();
    } catch (e) { showError(e); }
  }

  /* ---------- 7. Strategy analysis ---------- */
  function topicOf(ticker) {
    var m = state.markets.find(function (x) { return x.ticker === ticker; });
    if (m) return m.topic;
    for (var t in state.seriesByTopic) {
      var s = state.seriesByTopic[t].find(function (x) {
        return ticker.indexOf(x.ticker) === 0;
      });
      if (s) return t;
    }
    return "unknown";
  }
  function priceBand(p) {
    if (p === null || p === undefined || isNaN(p)) return "unknown";
    if (p < 0.3) return "cheap (<30¢)";
    if (p <= 0.7) return "mid (30–70¢)";
    return "expensive (>70¢)";
  }
  function renderStrategy() {
    var rows = {};
    function add(key, f) {
      var r = rows[key] || (rows[key] = { key: key, fills: 0, contracts: 0,
        fees: 0, wins: 0, losses: 0 });
      r.fills++; r.contracts += Number(f.count_fp || 0);
      r.fees += Number(f.fee_cost || 0);
      var res = state.resolutions.find(function (x) {
        return x.ticker === (f.ticker || f.market_ticker);
      });
      if (res) {
        var side = f.outcome_side || f.side;
        if (side === res.result) r.wins++; else r.losses++;
      }
    }
    state.fills.forEach(function (f) {
      var t = topicOf(f.ticker || f.market_ticker || "");
      add(t + " · " + (f.outcome_side || f.side || "?") + " · " +
        priceBand(f.yes_price_dollars) + (f.is_taker ? " · taker" : " · maker"), f);
    });
    var keys = Object.keys(rows);
    var html = "<table><thead><tr><th>Category (topic · side · price band · role)</th>" +
      "<th class='num'>Fills</th><th class='num'>Contracts</th><th class='num'>Fees</th>" +
      "<th class='num'>Wins</th><th class='num'>Losses</th><th class='num'>Win rate</th>" +
      "</tr></thead><tbody>";
    if (!keys.length) {
      html += "<tr><td colspan='7' class='muted'>No fills yet. Connect a demo key and trade, " +
        "or wait for fills. Win rate uses logged resolutions (yes/no) vs fill side.</td></tr>";
    }
    keys.sort(function (a, b) { return rows[b].fills - rows[a].fills; }).forEach(function (k) {
      var r = rows[k], tot = r.wins + r.losses;
      html += "<tr><td>" + K.esc(k) + "</td><td class='num'>" + r.fills + "</td>" +
        "<td class='num'>" + K.num(r.contracts, 0) + "</td><td class='num'>" +
        K.num(r.fees, 2) + "</td><td class='num'>" + r.wins + "</td><td class='num'>" +
        r.losses + "</td><td class='num'>" +
        (tot ? Math.round(100 * r.wins / tot) + "%" : "—") + "</td></tr>";
    });
    html += "</tbody></table>";
    html += "<h3>Trade journal (" + state.journal.length + " entries)</h3>";
    if (!state.journal.length) {
      html += "<p class='muted'>No orders placed from this browser yet.</p>";
    } else {
      html += "<table><thead><tr><th>Time</th><th>Ticker</th><th>Side</th>" +
        "<th class='num'>Count</th><th class='num'>Price</th><th>Topic</th></tr>" +
        "</thead><tbody>";
      state.journal.slice().reverse().forEach(function (j) {
        html += "<tr><td>" + K.timeStr(j.ts) + "</td><td class='mono'>" +
          K.esc(j.body.ticker) + "</td><td>" + K.esc(j.body.side) + "</td>" +
          "<td class='num'>" + K.esc(j.body.count) + "</td><td class='num'>" +
          K.cents(j.body.price) + "</td><td>" + K.esc(topicOf(j.body.ticker)) +
          "</td></tr>";
      });
      html += "</tbody></table>";
    }
    html += "<p class='muted'>Strategy notes are generated from these categories. " +
      "Review candidates on the <a href='suggestions.html'>Suggestions</a> page before acting. " +
      "Demo prices may not reflect real markets — " +
      "<a href='https://docs.kalshi.com/getting_started/demo_env'>Demo Environment</a>.</p>";
    $("strategyBody").innerHTML = html;
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
      setInterval(scan, state.scanSec * 1000),
      setInterval(function () {
        if (state.selected) { loadOrderbook(); loadTrades(); }
      }, state.obSec * 1000),
      setInterval(function () {
        if (state.selected) { recordSamples(); loadCandles().then(drawChart); }
      }, 15000)
    ];
  }
  async function init() {
    // Restore saved key (browser-only)
    try {
      var saved = JSON.parse(localStorage.getItem("kd_key") || "null");
      if (saved && saved.keyId && saved.pem) {
        $("keyId").value = saved.keyId; $("keyPem").value = saved.pem;
        await K.Auth.load(saved.keyId, saved.pem);
        state.connected = true;
        $("connStatus").innerHTML = "<span class='pill'>Connected (" +
          K.esc(K.Auth.alg) + ")</span>";
        refreshPortfolio();
      }
    } catch (e) { /* key may be stale; user can reconnect */ }
    $("connectBtn").addEventListener("click", connect);
    $("disconnectBtn").addEventListener("click", disconnect);
    $("refreshPortfolioBtn").addEventListener("click", refreshPortfolio);
    $("discoverBtn").addEventListener("click", function () {
      discover().then(scan);
    });
    $("scanBtn").addEventListener("click", scan);
    $("refreshObBtn").addEventListener("click", function () {
      loadOrderbook(); loadTrades();
    });
    $("placeOrderBtn").addEventListener("click", placeOrder);
    $("cancelOrderBtn").addEventListener("click", cancelOrder);
    $("clearResolutionsBtn").addEventListener("click", function () {
      state.resolutions = []; localStorage.removeItem("kd_resolutions");
      renderResolutions();
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-window]"),
      function (b) {
        b.addEventListener("click", function () {
          setWindow(Number(b.getAttribute("data-window")));
        });
      });
    renderResolutions();
    renderStrategy();
    startTimers();
    try {
      await discover();
      await scan();
    } catch (e) { showError(e); }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
