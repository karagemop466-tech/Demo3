/* Kalshi Live Alert Desk — dashboard page controller.
 *
 * Builds the two scrolling alert streams (all events / high-ROI model filter),
 * the click-through graph with selectable time windows, the liquidity panel and
 * the resolution tracker. All numbers come from Desk.get() snapshots that were
 * built from official API payloads, plus optional live polling of the demo API.
 */
(function () {
  "use strict";
  var D = window.Desk;
  if (!D) return;
  var state = {
    meta: null, markets: [], alerts: [], roi: [], candles: null, resolutions: null,
    selected: null, window: "1h", live: {}, poller: null, version: 0
  };
  var $ = function (id) { return document.getElementById(id); };
  var THRESHOLD = 0.10;

  /* ---------------------------------------------------------------- helpers */
  function newsLinks(a) {
    var q = encodeURIComponent((a.title || a.ticker).replace(/[?"]/g, "").slice(0, 90));
    var t = encodeURIComponent((a.ts || "").slice(0, 16));
    var tk = encodeURIComponent(a.ticker);
    return [
      '<a href="' + D.esc(a.source_url) + '" target="_blank" rel="noopener" title="Exact official candlestick request behind this row">candlestick API</a>',
      '<a href="' + D.esc(a.market_url) + '" target="_blank" rel="noopener">market record</a>',
      '<a href="https://news.google.com/search?q=' + q + '%20after%3A' + t.slice(0, 10) + '" target="_blank" rel="noopener" title="Headline search around this timestamp — association is unverified (flag L-08)">headlines ±</a>'
    ].join(" · ");
  }
  function alertMsg(a, opts) {
    opts = opts || {};
    var up = a.delta > 0;
    var why = opts.roi && a.roi
      ? '<div class="meta"><strong>model:</strong> EV ' + D.cents(a.roi.ev) + " per contract · " +
        "ROI " + D.pct(a.roi.roi_pct) + " on " + D.cents(a.roi.cost) + " · side <b>" +
        D.esc(a.roi.side.toUpperCase()) + "</b> · p̂ " + D.cents(a.roi.p_hat) + "</div>"
      : "";
    var badges = [
      a.zero_volume ? '<span class="chip warn" title="The exchange reported zero volume in this candle: the move is a quote move, not a trade.">no trades in window</span>' : "",
      D.envChip(a.environment),
      '<span class="chip">' + D.esc(a.kind) + " · " + D.esc(a.window) + "</span>"
    ].filter(Boolean).join(" ");
    return '<article class="msg ' + (up ? "up" : "down") + '">' +
      '<div class="row1"><span><span class="px ' + (up ? "up" : "down") + '">' +
      (up ? "▲ +" : "▼ −") + D.cents(a.abs_delta) + "</span> " +
      '<span class="tk">' + D.esc(a.ticker) + "</span> " + D.topicChip(a.topic, a.topic_label) +
      '</span><span class="t">' + D.esc(D.ts(a.ts)) + " · " + D.esc(D.ago(a.ts)) + "</span></div>" +
      '<div class="meta">' + D.esc(a.title || "") + (a.sub_title ? " — " + D.esc(a.sub_title) : "") + "</div>" +
      '<div class="meta">' + D.cents(a.from_price) + " → " + D.cents(a.to_price) +
      " over " + a.minutes + " min · volume " + D.num(a.volume_contracts, 0) + " contracts · OI " +
      D.num(a.open_interest, 0) + " " + badges + "</div>" + why +
      '<div class="links">' + newsLinks(a) + "</div></article>";
  }

  /* ------------------------------------------------------------------- init */
  async function init() {
    if ($("deskVersion")) $("deskVersion").textContent = "loading snapshots…";
    var [meta, markets, alerts, roi, candles, resolutions] = await Promise.all([
      D.get("data/meta.json"), D.get("data/markets.json"), D.get("data/alerts.json"),
      D.get("data/alerts_roi.json"), D.get("data/candles_index.json"),
      D.get("data/resolutions.json")
    ]);
    state.meta = meta; state.markets = markets.markets || [];
    state.alerts = alerts.alerts || []; state.roi = roi.alerts || [];
    state.candles = candles; state.resolutions = resolutions;

    // each page mounts only the panels it owns; render the ones that exist
    if ($("thresholdNote") || $("snapshotNote")) renderHeader();
    if ($("statGrid")) renderStats();
    if ($("chatAll")) { renderChats(); renderTopicTables(); renderResolutions(); }
    if ($("windowSeg")) wireChart();
    if ($("obTicker")) wireLiquidity();
    if ($("liveStatus")) startPolling();
    if ($("deskVersion")) {
      $("deskVersion").textContent = "snapshot built " + D.ts(meta.generated_at) +
        " · " + state.markets.length + " tracked lines · " + state.alerts.length + " alerts";
    }
  }

  function set(id, html) { var e = $(id); if (e) e.innerHTML = html; }
  function renderHeader() {
    var m = state.meta;
    set("thresholdNote", "Alert rule: |move| ≥ $" + m.threshold_dollars.toFixed(2) +
      " (step close-to-close or intrabar high-to-low)");
    set("roiNote", "Model filter: EV ≥ $" + m.roi_min_ev.toFixed(2) +
      " per contract and ROI ≥ " + m.roi_min_roi_pct + "%");
    var snap = m.snapshots || {};
    set("snapshotNote", "Snapshots: markets retrieved " +
      D.esc(D.ts(snap.markets_open_retrieved_at)) + " (" + D.num(snap.markets_open_count, 0) +
      " open markets, " + D.num(snap.markets_settled_count, 0) + " settled). " +
      'Sources: <a href="' + D.esc(m.sources.get_markets) + '" target="_blank" rel="noopener">Get Markets</a> · ' +
      '<a href="' + D.esc(m.sources.get_candlesticks) + '" target="_blank" rel="noopener">Get Market Candlesticks</a> · ' +
      '<a href="' + D.esc(m.sources.get_orderbook) + '" target="_blank" rel="noopener">Get Market Orderbook</a>.');
  }

  function renderStats() {
    var m = state.meta, a = state.alerts;
    if (!$("statGrid")) return;
    var up = a.filter(function (x) { return x.delta > 0; }).length;
    var top = state.markets.slice().sort(function (x, y) {
      return (y.volume_dollars_derived || 0) - (x.volume_dollars_derived || 0);
    })[0];
    var cards = [
      ["Tracked lines", D.num(state.markets.length, 0), "top-dollar lines per topic + every contract with committed candles"],
      ["Swing alerts", D.num(a.length, 0), "≥ $0.10 moves in committed candlesticks"],
      ["Up / down", D.num(up, 0) + " / " + D.num(a.length - up, 0), "direction of the alert moves"],
      ["Model high-ROI", D.num(state.roi.length, 0), "passed the EV + ROI filter"],
      ["Highest derived $ volume", top ? D.dollars(top.volume_dollars_derived) : "—",
        top ? D.esc(top.ticker) + " (derived)" : ""],
      ["Candle coverage", D.num(state.candles.count, 0), "contracts with committed candlestick history"]
    ];
    $("statGrid").innerHTML = cards.map(function (c) {
      return '<div class="card tight"><div class="label">' + c[0] + '</div><div class="stat sm">' +
        c[1] + '</div><div class="note">' + c[2] + "</div></div>";
    }).join("");
    var cov = Object.keys(m.alerts_by_topic || {}).map(function (t) {
      return t + " " + m.alerts_by_topic[t];
    }).join(" · ");
    $("coverageNote").innerHTML = "Alerts by topic: " + D.esc(cov) +
      ". Topics with 0 alerts had no ≥ $0.10 move in the committed windows — the largest move " +
      "observed per topic is shown in the topic tables (never labelled as an alert). See " +
      '<a href="flagged.html">Flagged for review</a> (L-12).';
  }

  /* ------------------------------------------------------------ chat streams */
  function renderChats() {
    var all = D.Chat($("chatAll"), {
      id: "chatAll", title: "All swing alerts (≥ $0.10)",
      empty: "No ≥ $0.10 moves in the committed candlestick windows yet.",
      render: function (a) { return alertMsg(a); }
    });
    var roiChat = D.Chat($("chatRoi"), {
      id: "chatRoi", title: "Model high-ROI alerts (selective filter)",
      empty: "No alert has passed the EV ≥ $0.03 and ROI ≥ 10% filter yet.",
      render: function (a) { return alertMsg(a, { roi: true }); }
    });
    state.chatAll = all; state.chatRoi = roiChat;
    all.set(state.alerts);
    roiChat.set(state.roi);
    all.status(D.num(state.alerts.length, 0) + " alerts · snapshot", "warn");
    roiChat.status(D.num(state.roi.length, 0) + " high-ROI · snapshot", "warn");
    if (!$("chatTopicFilter")) return;

    // topic filters for the "all" stream
    var sel = $("chatTopicFilter");
    sel.addEventListener("change", function () {
      var t = sel.value;
      all.set(t === "all" ? state.alerts : state.alerts.filter(function (a) { return a.topic === t; }));
      all.status(D.num(all.size(), 0) + (t === "all" ? " alerts" : " " + t + " alerts") + " · snapshot", "warn");
    });
  }

  /* --------------------------------------------------------- topic grouping */
  function renderTopicTables() {
    if (!$("topicTables")) return;
    var order = ["gas", "elections", "culture", "crypto", "golf"];
    var labels = { gas: "Gas prices", elections: "Elections", culture: "Culture", crypto: "Crypto", golf: "Golf" };
    var html = order.map(function (t) {
      var rows = state.markets.filter(function (m) { return m.topic === t; })
        .sort(function (a, b) {
          if (a.is_top_dollar_in_topic !== b.is_top_dollar_in_topic) return a.is_top_dollar_in_topic ? -1 : 1;
          return (b.volume_dollars_derived || 0) - (a.volume_dollars_derived || 0);
        });
      var alerts = state.alerts.filter(function (a) { return a.topic === t; });
      var biggest = (state.meta.largest_move_by_topic || {})[t];
      var body = rows.map(function (m) {
        return "<tr>" +
          '<td><a href="#" data-ticker="' + D.esc(m.ticker) + '" class="tick">' + D.esc(m.ticker) + "</a>" +
          (m.environment === "production" ? " " + D.envChip("production") : "") +
          '<div class="small muted">' + D.esc(m.sub_title || m.event_title || "") + "</div></td>" +
          '<td class="mono">' + D.cents(m.price) + "</td>" +
          '<td class="num">' + D.dollars(m.volume_dollars_derived) + '<div class="small muted">' + D.num(m.volume, 0) + " contracts</div></td>" +
          '<td class="num">' + (m.liquidity ? D.num(m.liquidity.top_of_book_contracts, 0) : "—") + '<div class="small muted">top-of-book</div></td>' +
          '<td class="mono small">' + D.esc((m.close_time || "").slice(0, 16).replace("T", " ")) + "</td>" +
          '<td class="small">' + D.esc(m.status || "") + "</td>" +
          '<td class="small"><a href="' + D.esc(m.market_url) + '" target="_blank" rel="noopener">API</a> · ' +
          '<a href="' + D.esc(m.orderbook_url) + '" target="_blank" rel="noopener">book</a></td>' +
          "</tr>";
      }).join("");
      if (!rows.length) body = '<tr><td colspan="7" class="muted">No open lines collected for this topic.</td></tr>';
      return '<section class="card" id="topic-' + t + '">' +
        "<h2>" + D.topicChip(t, labels[t]) + " " + labels[t] +
        ' <span class="small muted">' + rows.length + " lines · " + alerts.length + " alerts</span></h2>" +
        (biggest ? '<p class="small muted">Largest 1-hour move observed: ' +
          '<span class="mono">' + D.cents(biggest.from_price) + " → " + D.cents(biggest.to_price) +
          " (" + (biggest.delta > 0 ? "+" : "−") + D.cents(Math.abs(biggest.delta)) + ")</span> on " +
          '<a href="#" data-ticker="' + D.esc(biggest.ticker) + '" class="tick">' + D.esc(biggest.ticker) + "</a> at " +
          D.ts(biggest.ts) + " · " + D.envChip(biggest.environment) +
          ' <a href="' + D.esc(biggest.source_url) + '" target="_blank" rel="noopener">source</a>' +
          (Math.abs(biggest.delta) < THRESHOLD ? " — below the $0.10 alert threshold, so no alert" : "") +
          "</p>" : "") +
        '<div class="table-scroll"><table><thead><tr><th>Ticker / contract</th><th>Price</th>' +
        '<th class="num">Derived $ volume</th><th class="num">Liquidity</th><th>Closes</th>' +
        "<th>Status</th><th>Source</th></tr></thead><tbody>" + body + "</tbody></table></div></section>";
    }).join("");
    $("topicTables").innerHTML = html;
    $("topicTables").addEventListener("click", function (e) {
      var a = e.target.closest("[data-ticker]");
      if (!a) return;
      e.preventDefault();
      selectTicker(a.getAttribute("data-ticker"), true);
    });
  }

  /* ------------------------------------------------------------- resolutions */
  function renderResolutions() {
    if (!$("resolutionBody")) return;
    var r = state.resolutions;
    var totals = r.totals_by_topic || {};
    var head = '<div class="grid g4">' + Object.keys(totals).map(function (t) {
      var x = totals[t];
      return '<div class="card tight"><div class="label">' + D.esc(x.topic_label) + '</div>' +
        '<div class="stat sm">' + D.num(x.markets, 0) + '</div><div class="note">' +
        D.num(x.yes, 0) + " resolved YES · " + D.num(x.no, 0) + " NO</div></div>";
    }).join("") + "</div>";
    var openRows = (r.open_events || []).slice(0, 60).map(function (g) {
      return "<tr><td>" + D.topicChip(g.topic, g.topic_label) + " " + D.esc(g.event_title || g.event_ticker) +
        '<div class="small muted mono">' + D.esc(g.event_ticker) + "</div></td><td class=\"num\">" +
        D.num(g.markets, 0) + '</td><td class="mono small">' + D.esc((g.next_close || "").slice(0, 16).replace("T", " ")) +
        '</td><td class="small"><a href="' + D.esc(D.BASE + "/events/" + (g.event_ticker || "")) +
        '" target="_blank" rel="noopener">event API</a></td></tr>';
    }).join("");
    var resRows = (r.resolved_events || []).slice(0, 80).map(function (g) {
      var m = g.markets[0] || {};
      return "<tr><td>" + D.topicChip(g.topic, g.topic_label) + " " + D.esc(g.event_title || g.event_ticker) +
        '<div class="small muted mono">' + D.esc(g.event_ticker) + "</div></td>" +
        '<td><span class="chip ' + (g.outcome_side === "yes" ? "yes" : "no") + '">' + D.esc(g.outcome_side.toUpperCase()) +
        "</span><div class=\"small muted\">" + g.yes_count + " YES / " + g.no_count + " NO markets</div></td>" +
        '<td class="num">' + D.num(g.market_count, 0) + '</td><td class="mono small">' +
        D.esc((g.settled_time || "").slice(0, 16).replace("T", " ")) + "</td>" +
        '<td class="small"><a href="' + D.esc(m.market_url || D.BASE + "/markets?tickers=" + (m.ticker || "")) +
        '" target="_blank" rel="noopener">market</a> · <a href="' + D.esc(D.base_settlement || "https://docs.kalshi.com/getting_started/market_settlement") +
        '" target="_blank" rel="noopener">settlement rule</a></td></tr>';
    }).join("");
    var recent = (r.resolved_markets || []).slice(0, 120).map(function (m) {
      return "<tr><td>" + D.topicChip(m.topic, m.topic_label) + ' <span class="mono small">' + D.esc(m.ticker) + "</span>" +
        '<div class="small muted">' + D.esc(m.sub_title || m.title) + "</div></td>" +
        '<td><span class="chip ' + m.result + '">' + D.esc(m.result.toUpperCase()) + "</span></td>" +
        '<td class="mono">' + D.cents(m.last_price) + "</td><td class=\"num\">" + D.num(m.volume_contracts, 0) + "</td>" +
        '<td class="mono small">' + D.esc((m.settled_time || "").slice(0, 16).replace("T", " ")) + "</td>" +
        '<td class="small"><a href="' + D.esc(m.source_url) + '" target="_blank" rel="noopener">API</a></td></tr>';
    }).join("");
    $("resolutionBody").innerHTML = head +
      '<h3>Live events still open (tracked until they resolve)</h3>' +
      '<div class="table-scroll"><table><thead><tr><th>Event (grouped by topic)</th><th class="num">Markets</th>' +
      "<th>Next close</th><th>Source</th></tr></thead><tbody>" + (openRows || '<tr><td colspan="4" class="muted">none</td></tr>') +
      "</tbody></table></div>" +
      '<h3>Resolved events (how each resolved: YES or NO)</h3>' +
      '<div class="table-scroll"><table><thead><tr><th>Event</th><th>Outcome</th><th class="num">Markets</th>' +
      "<th>Settled</th><th>Source</th></tr></thead><tbody>" + (resRows || '<tr><td colspan="5" class="muted">none</td></tr>') +
      "</tbody></table></div>" +
      '<h3>Resolved markets (newest per topic)</h3><p class="small muted">' + D.esc(r.note || "") +
      ' · <a href="../data-tracking.html">see the full settlement snapshot</a></p>' +
      '<div class="table-scroll"><table><thead><tr><th>Market</th><th>Result</th><th>Last price</th>' +
      '<th class="num">Volume</th><th>Settled</th><th>Source</th></tr></thead><tbody>' + recent +
      "</tbody></table></div>";
  }

  /* --------------------------------------------------------------- graph */
  function candleSeries(ticker, windowId) {
    var m = state.candles.markets[ticker];
    if (!m) return Promise.resolve(null);
    return D.get(m.path.replace(/^data\//, "data/")).then(function (p) {
      return { payload: p, meta: m };
    });
  }

  function pointsFor(ticker, windowSecs) {
    var m = state.candles.markets[ticker];
    if (!m) return Promise.resolve([]);
    return D.get(m.path).then(function (p) {
      var s = p.series || {};
      var now = Math.max(m.last_ts || 0, Math.floor(Date.now() / 1000));
      var interval = windowSecs <= 3600 ? "1" : "60";
      var rows = s[interval] || s["60"] || s["1440"] || [];
      var pts = rows.map(function (r) { return [r[0], r[4]]; })   // [ts, close]
        .filter(function (r) { return r[1] !== null && r[1] !== undefined; });
      var cut = now - windowSecs;
      var sel = pts.filter(function (r) { return r[0] >= cut; });
      if (sel.length < 2) {
        // widen to the tail of available history and say so in the caption
        sel = pts.slice(-Math.max(2, Math.min(240, pts.length)));
        sel.widened = true;
      }
      return sel;
    });
  }

  function selectTicker(ticker, scroll) {
    if (!state.candles.markets[ticker]) {
      $("detailTitle").innerHTML = D.esc(ticker) + ' <span class="chip warn">no committed candlestick history</span>';
      $("detailMeta").innerHTML = 'Price history for this contract is not in the committed store. ' +
        'The exact official request to check it: <a href="' + D.esc(D.BASE + "/markets?tickers=" + ticker) +
        '" target="_blank" rel="noopener">GET /markets?tickers=' + D.esc(ticker) + "</a>. " +
        "Coverage is declared in the data manifest (<a href=\"data/candles_index.json\">candles_index.json</a>).";
      D.priceChart($("priceChart"), [], { empty: "No candle history for this contract." });
      return;
    }
    state.selected = ticker;
    var mk = state.markets.filter(function (x) { return x.ticker === ticker; })[0] || {};
    var cm = state.candles.markets[ticker];
    $("detailTitle").innerHTML = '<span class="mono">' + D.esc(ticker) + "</span> " +
      D.topicChip(mk.topic || "", mk.topic_label || "") + " " + D.envChip(cm.environment) +
      '<span class="small muted"> ' + D.esc(mk.sub_title || mk.title || "") + "</span>";
    var live = state.live[ticker];
    $("detailMeta").innerHTML = "Price " + D.cents(live ? live.price : mk.price) +
      (live ? ' <span class="chip up">live quote ' + D.esc(D.ts(live.ts)) + "</span>" : "") +
      " · derived $ volume " + D.dollars(mk.volume_dollars_derived) +
      " · " + (cm.intervals ? Object.keys(cm.intervals).map(function (k) {
        return k + "m: " + D.num(cm.intervals[k], 0) + " candles";
      }).join(" · ") : "") +
      ' · <a href="' + D.esc(cm.source_url) + '" target="_blank" rel="noopener">source request</a>' +
      ' · <a href="#" id="openOb">load orderbook</a>';
    drawPrice();
    if (scroll) $("graph").scrollIntoView({ behavior: "smooth", block: "start" });
    var ob = $("openOb");
    if (ob) ob.addEventListener("click", function (e) { e.preventDefault(); loadOrderbook(ticker); });
    loadOrderbook(ticker);
    renderTradesNearest(ticker);
  }

  function drawPrice() {
    var ticker = state.selected;
    if (!ticker) return;
    var w = D.WINDOWS.filter(function (x) { return x.id === state.window; })[0] || D.WINDOWS[4];
    pointsFor(ticker, w.secs).then(function (pts) {
      var caption = "x: time (" + w.label + " window) · y: contract price (¢) · " +
        (pts.widened ? "window widened to full committed history" : "committed candlesticks");
      var live = state.live[ticker];
      var pts2 = pts.slice();
      if (live && pts2.length) {
        var last = pts2[pts2.length - 1];
        pts2.push([Math.floor(Date.now() / 1000), live.price]);
      }
      D.priceChart($("priceChart"), pts2, { caption: caption });
      $("chartCaption").textContent = "Ticker " + ticker + " · window " + w.label +
        " · " + pts2.length + " points · source: " + (state.candles.markets[ticker].source_url || "n/a");
    });
  }

  function wireChart() {
    var seg = $("windowSeg");
    seg.innerHTML = D.WINDOWS.map(function (w) {
      return '<button class="btn' + (w.id === state.window ? " on" : " secondary") +
        '" data-w="' + w.id + '">' + w.label + "</button>";
    }).join("");
    seg.addEventListener("click", function (e) {
      var b = e.target.closest("[data-w]");
      if (!b) return;
      state.window = b.getAttribute("data-w");
      Array.prototype.forEach.call(seg.querySelectorAll("button"), function (x) {
        x.className = "btn" + (x.getAttribute("data-w") === state.window ? " on" : " secondary");
      });
      drawPrice();
    });
  }

  /* ------------------------------------------------------------ liquidity */
  function loadOrderbook(ticker) {
    if (!ticker) return;
    var el = $("obSummary");
    el.textContent = "orderbook: loading from the demo API…";
    fetch(D.BASE + "/markets/" + encodeURIComponent(ticker) + "/orderbook?depth=20",
      { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (j) {
        var ob = j.orderbook_fp || {};
        renderOrderbook(ticker, ob.yes_dollars || [], ob.no_dollars || [], "live", D.BASE + "/markets/" + ticker + "/orderbook?depth=20");
      })
      .catch(function (e) {
        // fall back to the committed snapshot, clearly labelled
        D.get("../data/latest/orderbooks.json").then(function (snap) {
          var b = (snap.orderbooks || {})[ticker];
          if (!b) {
            el.innerHTML = '<span class="chip warn">orderbook unavailable</span> live request failed (' +
              D.esc(e.message) + ") and no committed snapshot exists for this ticker.";
            D.depthChart($("depthChart"), [], [], {});
            return;
          }
          renderOrderbook(ticker, (b.orderbook_fp || {}).yes_dollars || [], (b.orderbook_fp || {}).no_dollars || [],
            "snapshot " + D.ts(b.retrieved_at), b.source_url);
        });
      });
  }
  function renderOrderbook(ticker, yes, no, label, srcUrl) {
    D.depthChart($("depthChart"), yes, no, {});
    var bid = yes.length ? D.f(yes[yes.length - 1][0]) : null;
    var ask = no.length ? 1 - D.f(no[no.length - 1][0]) : null;
    var yesTotal = yes.reduce(function (s, l) { return s + D.f(l[1]); }, 0);
    var noTotal = no.reduce(function (s, l) { return s + D.f(l[1]); }, 0);
    $("obSummary").innerHTML = '<span class="chip">' + D.esc(label) + "</span> best YES bid " + D.cents(bid) +
      " · best YES ask " + D.cents(ask) + " · spread " + (bid !== null && ask !== null ? D.cents(ask - bid) : "—") +
      " · contracts on YES bids " + D.num(yesTotal, 0) + " · on NO bids (YES-equivalent) " + D.num(noTotal, 0) +
      ' · <a href="' + D.esc(srcUrl) + '" target="_blank" rel="noopener">source</a> · ' +
      '<a href="https://docs.kalshi.com/api-reference/market/get-market-orderbook" target="_blank" rel="noopener">field docs</a>';
    var rows = [];
    for (var i = yes.length - 1; i >= 0 && rows.length < 12; i--) {
      rows.push(["YES bid", D.f(yes[i][0]), D.f(yes[i][1])]);
    }
    for (var k = no.length - 1; k >= 0 && rows.length < 24; k--) {
      rows.push(["NO bid = YES ask " + D.cents(1 - D.f(no[k][0])), D.f(no[k][0]), D.f(no[k][1])]);
    }
    $("obTable").innerHTML = '<div class="table-scroll"><table><thead><tr><th>Level</th><th class="num">Price</th>' +
      '<th class="num">Contracts available</th></tr></thead><tbody>' + rows.map(function (r) {
        return "<tr><td>" + D.esc(r[0]) + '</td><td class="mono">' + D.cents(r[1]) + '</td><td class="num">' +
          D.num(r[2], 0) + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }
  function wireLiquidity() {
    $("obTicker").addEventListener("change", function () { loadOrderbook(this.value); });
    var withCandles = state.markets.filter(function (m) {
      return state.candles.markets[m.ticker];
    });
    var opts = (withCandles.length ? withCandles : state.markets).slice(0, 80);
    $("obTicker").innerHTML = opts.map(function (m) {
      return '<option value="' + D.esc(m.ticker) + '">' + D.esc(m.ticker) + " · " + D.esc(m.topic) + "</option>";
    }).join("");
    if (opts.length) {
      selectTicker(opts[0].ticker, false);
      $("obTicker").value = opts[0].ticker;
    }
  }
  function renderTradesNearest(ticker) {
    $("tradesTable").innerHTML = '<p class="small muted">Recent trades for ' + D.esc(ticker) + ": " +
      '<a href="' + D.esc(D.BASE + "/markets/trades?ticker=" + encodeURIComponent(ticker) + "&limit=50") +
      '" target="_blank" rel="noopener">open the official trades endpoint</a> ' +
      "(public, no key). Trades are not cached in this build, so nothing is shown that was not fetched.</p>";
  }

  /* ------------------------------------------------------------ live polling */
  function startPolling() {
    var tickers = state.markets.map(function (m) { return m.ticker; }).slice(0, 40);
    var status = $("liveStatus");
    if (!tickers.length) return;
    var first = true;
    function update(byTicker) {
      var changed = 0;
      Object.keys(byTicker).forEach(function (t) {
        var m = byTicker[t];
        var bid = D.f(m.yes_bid_dollars, null), ask = D.f(m.yes_ask_dollars, null);
        var price = (bid !== null && ask !== null && ask > 0 && ask < 1) ? (bid + ask) / 2 : D.f(m.last_price_dollars, null);
        if (price === null) return;
        var prev = state.live[t];
        state.live[t] = { price: price, ts: new Date().toISOString(), bid: bid, ask: ask };
        if (prev && Math.abs(price - prev.price) >= THRESHOLD - 1e-9) {
          changed++;
          syntheticAlert(t, m, prev.price, price);
        }
      });
      if (first) {
        status.innerHTML = '<span class="pulse"></span>live · demo API reachable (first poll ok) — ' +
          Object.keys(byTicker).length + " quotes";
        first = false;
      }
      if (state.selected && $("priceChart")) drawPrice();
      if ($("liveCount")) {
        $("liveCount").textContent = Object.keys(state.live).length + " live quotes · " +
          changed + " live swings since load";
      }
    }
    if (!status) return;
    D.pollTickers(tickers, update, {
      interval: 20000,
      onError: function (msg) {
        status.innerHTML = '<span class="pulse warn"></span>live polling blocked (' + D.esc(msg) +
          ") — showing the committed snapshot, timestamps visible";
      }
    });
  }

  function syntheticAlert(ticker, m, fromPrice, toPrice) {
    var mk = state.markets.filter(function (x) { return x.ticker === ticker; })[0] || {};
    var a = {
      ts: new Date().toISOString(), sort_ts: Math.floor(Date.now() / 1000),
      ticker: ticker, topic: mk.topic || "other", topic_label: mk.topic_label || "",
      title: m.title || mk.title || "", sub_title: m.yes_sub_title || "",
      kind: "live poll", window: "since page load", minutes: 0,
      from_price: fromPrice, to_price: toPrice, delta: toPrice - fromPrice,
      abs_delta: Math.abs(toPrice - fromPrice), volume_contracts: D.f(m.volume_24h_fp, 0),
      open_interest: D.f(m.open_interest_fp, 0), zero_volume: false,
      environment: "demo", source_url: D.BASE + "/markets?tickers=" + ticker,
      market_url: D.BASE + "/markets?tickers=" + ticker, live: true
    };
    if (state.chatAll) state.chatAll.prepend(a);
    if (state.chatAll) state.chatAll.status('<span class="pulse"></span>live polling — new alert above', "");
  }

  /* index page: live reachability check with an explicit snapshot fallback */
  function wireStatusWidget() {
    var el = $("liveStatus");
    if (!el || $("chatAll")) return;
    fetch(D.BASE + "/exchange/status", { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (j) {
        el.parentNode.querySelector(".pulse").className = "pulse";
        el.textContent = "demo API reachable · trading " +
          (j.trading_active ? "active" : "inactive") + " · the dashboard polls live quotes";
      })
      .catch(function (e) {
        el.parentNode.querySelector(".pulse").className = "pulse warn";
        el.textContent = "live API not reachable from this browser (" + e.message +
          ") — every panel below shows the committed snapshot with its timestamp";
      });
  }

  /* ------------------------------------------------------------------- boot */
  document.addEventListener("DOMContentLoaded", function () {
    wireStatusWidget();
    init().catch(function (e) {
      if (window.console) console.error("desk init failed", e);
      var b = $("banner");
      if (!b) {
        b = document.createElement("div");
        b.id = "banner";
        var m = document.querySelector("main");
        if (m) m.insertBefore(b, m.firstChild);
      }
      b.style.display = "block";
      b.className = "banner err";
      b.textContent = "Some panels could not initialise: " + (e && e.message) +
        " — the snapshot links on the Sources page still work.";
    });
  });
})();
