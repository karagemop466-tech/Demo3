/* Data-tracking page logic: renders committed snapshots from data/*.json.
   No external dependencies. Same-origin fetches only. */
(function () {
  "use strict";

  var state = { events: null, meta: null, resolutions: null, tracked: null,
                topic: "all", selectedMarket: null, history: null, range: "60m" };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function srcLink(url, label) {
    var a = document.createElement("a");
    a.className = "src"; a.href = url; a.target = "_blank";
    a.rel = "noopener";
    a.textContent = label || "API";
    return a;
  }
  function money(v) {
    return (v === null || v === undefined) ? "" :
      "$" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  function num(v) { return (v === null || v === undefined) ? "" : Number(v).toLocaleString("en-US"); }
  function fetchJSON(rel) {
    return fetch(rel, { headers: { "Accept": "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status + " for " + rel);
        return r.json();
      });
  }

  /* ---------------------------------------------------------- status banner */
  function renderStatus(meta) {
    var pill = $("statusPill"), body = $("statusBody");
    if (!meta) {
      pill.textContent = "no snapshot yet";
      pill.className = "status-pill pill-warn";
      body.textContent = "data/meta.json not found — the collector has not produced a snapshot " +
        "in this branch yet. It runs on every push and on schedule (collect.yml).";
      return;
    }
    var errs = meta.error_count || 0;
    pill.textContent = "last run " + (meta.generated_at || "?") +
      " · " + (meta.request_count || 0) + " requests · " + errs + " errors";
    pill.className = "status-pill " + (errs === 0 ? "pill-ok" : (errs < 10 ? "pill-warn" : "pill-bad"));
    while (body.firstChild) body.removeChild(body.firstChild);
    var facts = [
      "API root: " + meta.api_root,
      "Ranking: " + (meta.ranking_method || ""),
      "Open-event categories seen this run: " + Object.keys(meta.category_counts_open_exchange || {}).length
    ];
    facts.forEach(function (f) { body.appendChild(el("div", null, f)); });
    var warns = meta.warnings || [];
    var warnBox = el("div", null, warns.length ? ("Collector warnings: " + warns.length + " (newest first)") :
      "Collector warnings: none");
    warnBox.style.marginTop = "6px";
    body.appendChild(warnBox);
    (warns.slice(-5).reverse() || []).forEach(function (w) {
      var line = el("div", "muted", "· " + w);
      body.appendChild(line);
    });
  }

  /* ------------------------------------------------------------ events table */
  var TOPICS = [
    ["all", "All"], ["gas", "Gas prices"], ["elections", "Elections"],
    ["culture", "Culture"], ["crypto", "Crypto"], ["golf", "Golf"]
  ];

  function allEvents(events) {
    var rows = [];
    Object.keys(events.topics || {}).forEach(function (t) {
      (events.topics[t] || []).forEach(function (e) { rows.push(e); });
    });
    rows.sort(function (a, b) { return (b.est_dollar_volume || 0) - (a.est_dollar_volume || 0); });
    return rows;
  }

  function renderEvents() {
    var events = state.events;
    var body = $("eventsBody");
    while (body.firstChild) body.removeChild(body.firstChild);
    if (!events) {
      body.appendChild(el("tr", null, "")).appendChild(el("td", "muted",
        "data/events.json not found — waiting for the first collector run."));
      return;
    }
    var rows = allEvents(events).filter(function (e) {
      return state.topic === "all" || e.topic === state.topic;
    });
    rows.forEach(function (e, i) {
      var tr = el("tr", "event-row");
      tr.appendChild(el("td", null, String(i + 1)));
      var titleTd = el("td", null, e.title || e.event_ticker);
      titleTd.style.maxWidth = "380px";
      tr.appendChild(titleTd);
      tr.appendChild(el("td", null, e.topic_label || e.topic || ""));
      tr.appendChild(el("td", null, money(e.est_dollar_volume)));
      tr.appendChild(el("td", null, money(e.est_dollar_volume_24h)));
      tr.appendChild(el("td", null, num(e.open_interest)));
      tr.appendChild(el("td", null, num(e.market_count)));
      tr.appendChild(el("td", null, e.category || ""));
      var srcTd = el("td", null, "");
      srcTd.appendChild(srcLink(e.source_url || ("../trade-api/v2/events/" + e.event_ticker), "events/" + e.event_ticker));
      tr.appendChild(srcTd);
      tr.addEventListener("click", function () { selectEvent(e); });
      body.appendChild(tr);
    });
    if (!rows.length) {
      var tr = el("tr", null, "");
      tr.appendChild(el("td", "muted", "No in-scope live events in this snapshot."));
      body.appendChild(tr);
    }
  }

  function renderTopicFilters() {
    var wrap = $("topicFilters");
    TOPICS.forEach(function (pair) {
      var b = el("button", state.topic === pair[0] ? "active" : null, pair[1]);
      b.addEventListener("click", function () {
        state.topic = pair[0];
        renderTopicFilters();
        renderEvents();
      });
      wrap.appendChild(b);
    });
  }

  /* ---------------------------------------------------------- event detail */
  function selectEvent(e) {
    var markets = e.markets || [];
    markets.sort(function (a, b) {
      return (b.volume || 0) * (b.last_price || 0) - (a.volume || 0) * (a.last_price || 0);
    });
    var top = markets[0];
    document.querySelectorAll(".event-row.selected").forEach(function (n) {
      n.classList.remove("selected");
    });
    var pane = $("detailPane");
    pane.style.display = "block";
    $("detailTitle").textContent = (e.title || e.event_ticker) + " — top market";
    if (top) { state.selectedMarket = top; loadDetail(top); }
    else {
      $("detailTitle").textContent = e.title + " — no open markets in snapshot";
      state.selectedMarket = null;
    }
  }

  function loadDetail(market) {
    var ticker = market.ticker;
    fetchJSON("data/history/" + encodeURIComponent(ticker) + ".json")
      .then(function (h) { state.history = h; renderChart(); })
      .catch(function () {
        state.history = null;
        $("chartNote").textContent = "No candlestick history for this market in the latest snapshot " +
          "(collector fetches history for the top markets only). Source: " +
          "/series/{series}/markets/" + ticker + "/candlesticks (docs: docs.kalshi.com/api-reference/market/get-market-candlesticks.md)";
        drawEmptyChart();
      });
    fetchJSON("data/orderbooks/" + encodeURIComponent(ticker) + ".json")
      .then(renderLadders)
      .catch(function () { renderLadders(null); });
    renderMarketMeta(market);
  }

  var RANGES = [
    ["1m", "1-min · 24h"], ["60m", "1-hour · 30d"], ["1440m", "1-day · 180d"]
  ];

  function renderRangeButtons() {
    var wrap = $("rangeBtns");
    wrap.textContent = "";
    RANGES.forEach(function (r) {
      var b = el("button", state.range === r[0] ? "active" : null, r[1]);
      b.addEventListener("click", function () {
        state.range = r[0];
        renderRangeButtons();
        renderChart();
      });
      wrap.appendChild(b);
    });
  }

  function historyArray() {
    if (!state.history) return [];
    return state.history[state.range] || [];
  }

  function drawEmptyChart() {
    var c = $("priceChart");
    var ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.fillStyle = "#f7f9fc"; ctx.fillRect(0, 0, c.width, c.height);
    ctx.fillStyle = "#67748e";
    ctx.font = "13px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("no history data", c.width / 2, c.height / 2);
  }

  /* Chart: y = YES price ($0-$1), x = time. X axis adapts: seconds/minutes/hours/days
     spacing chosen from the selected candle interval + span. */
  function renderChart() {
    renderRangeButtons();
    var data = historyArray();
    var note = $("chartNote");
    if (!state.history) { drawEmptyChart(); return; }
    var label = { "1m": "1-minute candlesticks, trailing 24 h (finest the API provides; "
                        + "sub-minute ticks would need the WebSocket feed — see Flagged for Review)",
                  "60m": "1-hour candlesticks, trailing 30 days",
                  "1440m": "1-day candlesticks, trailing 180 days" }[state.range];
    note.textContent = "Y: YES trade-price close ($) · X: UTC time · " +
      data.length + " bars · " + label +
      " · endpoint: GET /series/{series}/markets/{ticker}/candlesticks";
    var c = $("priceChart");
    var dpr = window.devicePixelRatio || 1;
    var w = c.clientWidth || 800, h = 260;
    c.width = w * dpr; c.height = h * dpr;
    var ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#fbfcfe"; ctx.fillRect(0, 0, w, h);
    var padL = 44, padR = 12, padT = 14, padB = 34;
    var iw = w - padL - padR, ih = h - padT - padB;
    if (!data.length) { drawEmptyChart(); return; }
    var ts0 = data[0][0], ts1 = data[data.length - 1][0] || ts0;
    if (!ts1 || ts1 === ts0) ts1 = ts0 + 1;
    var yMin = 0, yMax = 1;

    // grid + y labels
    ctx.strokeStyle = "#e3e9f2"; ctx.fillStyle = "#67748e";
    ctx.font = "11px system-ui, sans-serif"; ctx.textAlign = "right";
    for (var g = 0; g <= 5; g++) {
      var gy = padT + ih * (1 - g / 5);
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(w - padR, gy); ctx.stroke();
      ctx.fillText("$" + (g / 5).toFixed(2), padL - 6, gy + 3);
    }
    // x labels: pick unit so ~6 labels fit
    var spanSec = ts1 - ts0;
    var units = [[1, "s", 1], [60, "m", 60], [3600, "h", 3600], [86400, "d", 86400]];
    var unit = units[3];
    for (var u = 0; u < units.length; u++) {
      if (spanSec / units[u][0] <= 30) { unit = units[u]; break; }
    }
    var nTicks = 6;
    ctx.textAlign = "center";
    for (var t = 0; t <= nTicks; t++) {
      var ts = ts0 + (spanSec * t) / nTicks;
      var x = padL + iw * (t / nTicks);
      var d = new Date(ts * 1000);
      var label = unit[0] === 1 ? d.toISOString().substr(14, 5)
        : unit[0] === 60 ? d.toISOString().substr(11, 5)
        : unit[0] === 3600 ? d.toISOString().substr(11, 5)
        : d.toISOString().substr(5, 5);
      ctx.fillText(label, x, h - 12);
    }
    // price line
    ctx.strokeStyle = "#3352cc"; ctx.lineWidth = 1.6;
    ctx.beginPath();
    data.forEach(function (row, i) {
      var close = row[2];
      if (close === null || close === undefined) return;
      var x = padL + iw * ((row[0] - ts0) / (ts1 - ts0));
      var y = padT + ih * (1 - (close - yMin) / (yMax - yMin));
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    // last point marker
    var last = data[data.length - 1];
    if (last && last[2] !== null) {
      var lx = padL + iw * ((last[0] - ts0) / (ts1 - ts0));
      var ly = padT + ih * (1 - (last[2] - yMin) / (yMax - yMin));
      ctx.fillStyle = "#3352cc";
      ctx.beginPath(); ctx.arc(lx, ly, 3, 0, Math.PI * 2); ctx.fill();
      ctx.textAlign = "left";
      ctx.fillText("$" + last[2].toFixed(2), lx + 5, ly - 5);
    }
  }

  /* -------------------------------------------------------------- ladders */
  function renderLadders(book) {
    var yesBody = $("yesLadder").querySelector("tbody");
    var noBody = $("noLadder").querySelector("tbody");
    yesBody.textContent = ""; noBody.textContent = "";
    var src = $("detailMeta");
    src.textContent = "";
    if (!book) {
      var tr = yesBody.appendChild(el("tr", null, ""));
      tr.appendChild(el("td", "muted", "No orderbook snapshot for this market (collector fetches top markets only)."));
      var tr2 = noBody.appendChild(el("tr", null, ""));
      tr2.appendChild(el("td", "muted", "—"));
      return;
    }
    function fill(tbody, rows, bestLast) {
      rows.slice().reverse().forEach(function (pair) {
        var tr = el("tr", null, "");
        tr.appendChild(el("td", null, "$" + pair[0]));
        tr.appendChild(el("td", null, num(parseFloat(pair[1]))));
        tbody.appendChild(tr);
      });
      if (!rows.length) {
        var tr = el("tr", null, "");
        tr.appendChild(el("td", "muted", "empty book"));
        tbody.appendChild(tr);
      }
      if (bestLast) {
        var btr = el("tr", null, "");
        btr.appendChild(el("td", null, "best"));
        btr.appendChild(el("td", null, "$" + bestLast.price + " × " + num(parseFloat(bestLast.contracts))));
        tbody.appendChild(btr);
      }
    }
    fill(yesBody, book.yes_bids || [], book.best_yes_bid);
    fill(noBody, book.no_bids || [], book.best_no_bid);
    var p = el("div", null, "Fetched " + book.fetched_at + " · ");
    p.appendChild(srcLink(book.source_url, "GET /markets/" + book.ticker + "/orderbook"));
    p.appendChild(el("span", "muted",
      "  · bids only (a YES bid at $X = a NO ask at $(1−X)); best bid is the deepest price shown."));
    src.appendChild(p);
  }

  function renderMarketMeta(m) {
    var box = $("detailMeta");
    var line = el("div", "muted", "");
    var bits = [];
    if (m.last_price !== undefined) bits.push("last: $" + m.last_price.toFixed(2));
    if (m.yes_bid !== undefined && m.yes_ask !== undefined)
      bits.push("yes bid/ask: $" + m.yes_bid.toFixed(2) + "/$" + m.yes_ask.toFixed(2));
    if (m.yes_bid_size !== undefined) bits.push("yes bid size: " + num(m.yes_bid_size) + " contracts");
    if (m.volume !== undefined) bits.push("volume: " + num(m.volume));
    if (m.volume_24h !== undefined) bits.push("24h volume: " + num(m.volume_24h));
    if (m.open_interest !== undefined) bits.push("open interest: " + num(m.open_interest));
    if (m.close_time) bits.push("closes: " + m.close_time);
    bits.forEach(function (b, i) {
      if (i) line.appendChild(el("span", null, " · "));
      line.appendChild(el("span", null, b));
    });
    box.insertBefore(line, box.firstChild);
  }

  /* ---------------------------------------------------------- resolutions */
  function renderResolutions() {
    var body = $("resBody");
    body.textContent = "";
    var tracked = (state.tracked && state.tracked.events) || {};
    var resolved = (state.resolutions && state.resolutions.resolved) || {};
    var openRows = Object.keys(tracked).filter(function (t) { return !tracked[t].resolved; });
    var resolvedRows = Object.keys(resolved);
    openRows.sort(function (a, b) { return (tracked[b].last_seen || "").localeCompare(tracked[a].last_seen || ""); });
    openRows.slice(0, 40).forEach(function (t) {
      var r = tracked[t];
      var tr = el("tr", null, "");
      tr.appendChild(el("td", null, r.title || t));
      tr.appendChild(el("td", null, r.topic || ""));
      var st = el("td", null, ""); st.appendChild(el("span", "status-pill pill-neutral", "live — tracking"));
      tr.appendChild(st);
      tr.appendChild(el("td", "muted", "—"));
      tr.appendChild(el("td", "muted", "last seen " + (r.last_seen || "")));
      tr.appendChild(el("td", "muted", "—"));
      tr.appendChild(el("td", "muted", "—"));
      var src = el("td", null, "");
      src.appendChild(srcLink("../trade-api/v2/events/" + encodeURIComponent(t), "events/" + t));
      tr.appendChild(src);
      body.appendChild(tr);
    });
    resolvedRows.sort(function (a, b) {
      return (resolved[b].resolved_at || "").localeCompare(resolved[a].resolved_at || "");
    });
    resolvedRows.slice(0, 60).forEach(function (t) {
      var r = resolved[t];
      var tr = el("tr", null, "");
      tr.appendChild(el("td", null, r.title || t));
      tr.appendChild(el("td", null, r.topic || ""));
      var st = el("td", null, ""); st.appendChild(el("span", "status-pill pill-ok", "settled"));
      tr.appendChild(st);
      tr.appendChild(el("td", null, r.outcome_side ? ("resolved " + r.outcome_side.toUpperCase()) : ""));
      tr.appendChild(el("td", null, r.resolved_at || ""));
      var winners = (r.winners || []).map(function (w) { return w.title || w.ticker; }).join("; ");
      tr.appendChild(el("td", null, winners || "—"));
      var srcName = ((r.settlement_sources || [])[0] || {}).name || "—";
      tr.appendChild(el("td", null, srcName));
      var src = el("td", null, "");
      src.appendChild(srcLink(r.event_source_url || "../trade-api/v2/events/" + encodeURIComponent(t), "events/" + t));
      tr.appendChild(src);
      body.appendChild(tr);
    });
    if (!openRows.length && !resolvedRows.length) {
      var tr = el("tr", null, "");
      tr.appendChild(el("td", "muted", "No tracked events yet."));
      body.appendChild(tr);
    }
  }

  /* -------------------------------------------------------------- portfolio */
  function renderPortfolio() {
    var box = $("portfolioBody");
    box.textContent = "";
    fetchJSON("data/portfolio.json").then(function (p) {
      var head = el("div", null, "");
      var pill = el("span", "status-pill pill-ok", "live demo account");
      head.appendChild(pill);
      head.appendChild(el("span", null,
        "  balance: " + money(p.account && p.account.balance_dollars) +
        " · positions: " + num(p.position_count) +
        " · orders: " + num(p.orders_count) +
        " · fills: " + num(p.fills_count) +
        "  (snapshot " + p.generated_at + ")"));
      box.appendChild(head);
      var tbl = el("table", "dt", "");
      var thead = el("thead", null, "");
      var htr = el("tr", null, "");
      ["Ticker", "Position", "Unrealized PnL", "Realized PnL", "Source"].forEach(function (h) {
        htr.appendChild(el("th", null, h));
      });
      thead.appendChild(htr); tbl.appendChild(thead);
      var tbody = el("tbody", null, "");
      (p.positions || []).slice(0, 50).forEach(function (pos) {
        var tr = el("tr", null, "");
        tr.appendChild(el("td", null, pos.ticker || ""));
        tr.appendChild(el("td", null, num(pos.position)));
        tr.appendChild(el("td", null, (pos.unrealized_pnl !== undefined && pos.unrealized_pnl !== null) ? money(pos.unrealized_pnl / 100) : ""));
        tr.appendChild(el("td", null, (pos.realized_pnl !== undefined && pos.realized_pnl !== null) ? money(pos.realized_pnl / 100) : ""));
        var td = el("td", null, "");
        td.appendChild(srcLink("../trade-api/v2/portfolio/positions", "portfolio/positions"));
        tr.appendChild(td);
        tbody.appendChild(tr);
      });
      if (!(p.positions || []).length) {
        var tr = el("tr", null, "");
        tr.appendChild(el("td", "muted", "No open positions reported by the demo account."));
        tbody.appendChild(tr);
      }
      tbl.appendChild(tbody);
      box.appendChild(tbl);
    }).catch(function () {
      var pill = el("span", "status-pill pill-warn", "awaiting demo credentials");
      box.appendChild(pill);
      box.appendChild(el("p", "muted",
        "No data/portfolio.json snapshot. The demo-account pipeline (trading/kalshi_trade.py + the " +
        "“Demo trade / portfolio” workflow) is implemented and offline-tested, but no demo-account API " +
        "credentials exist in this environment — account sign-up at demo.kalshi.co requires human registration. " +
        "Once KALSHI_DEMO_API_KEY_ID and KALSHI_DEMO_PRIVATE_KEY are added as repository secrets, this section " +
        "populates automatically. This is a flagged unverified item, not an inference."));
    });
  }

  /* ----------------------------------------------------------------- trades */
  function renderTrades() {
    var box = $("tradesBody");
    box.textContent = "";
    fetchJSON("data/trades.json").then(function (t) {
      var s = t.summary || {};
      var head = el("div", null, num(s.open_trades || 0) + " open · " + num(s.settled_trades || 0) +
        " settled · updated " + (t.updated_at || ""));
      box.appendChild(head);
      var byTopic = s.by_topic || {};
      var tbl = el("table", "dt", "");
      var thead = el("thead", null, "");
      var htr = el("tr", null, "");
      ["Bucket", "Trades", "Wins", "Losses", "Win rate", "Realized PnL"].forEach(function (h) {
        htr.appendChild(el("th", null, h));
      });
      thead.appendChild(htr); tbl.appendChild(thead);
      var tbody = el("tbody", null, "");
      Object.keys(byTopic).forEach(function (k) {
        var b = byTopic[k];
        var tr = el("tr", null, "");
        tr.appendChild(el("td", null, "topic: " + k));
        tr.appendChild(el("td", null, num(b.trades)));
        tr.appendChild(el("td", null, num(b.wins)));
        tr.appendChild(el("td", null, num(b.losses)));
        tr.appendChild(el("td", null, b.win_rate === null ? "" : (Math.round(b.win_rate * 100) + "%")));
        tr.appendChild(el("td", null, money(b.realized_pnl_dollars)));
        tbody.appendChild(tr);
      });
      Object.keys(s.by_structure || {}).forEach(function (k) {
        var b = s.by_structure[k];
        var tr = el("tr", null, "");
        tr.appendChild(el("td", null, "structure: " + k));
        tr.appendChild(el("td", null, num(b.trades)));
        tr.appendChild(el("td", null, num(b.wins)));
        tr.appendChild(el("td", null, num(b.losses)));
        tr.appendChild(el("td", null, b.win_rate === null ? "" : (Math.round(b.win_rate * 100) + "%")));
        tr.appendChild(el("td", null, money(b.realized_pnl_dollars)));
        tbody.appendChild(tr);
      });
      tbl.appendChild(tbody);
      box.appendChild(tbl);
      var list = el("div", "muted", "Recent trades:");
      box.appendChild(list);
      (t.trades || []).slice(-10).reverse().forEach(function (r) {
        var line = el("div", "muted", (r.mode === "dry-run" ? "[dry-run] " : "") +
          r.placed_at + " · " + r.action + " " + r.side + " ×" + r.count + " @ $" +
          (r.price_dollars !== undefined ? r.price_dollars.toFixed(2) : "?") +
          " · " + (r.ticker || "") +
          (r.realized_pnl_dollars !== undefined && r.realized_pnl_dollars !== null ?
            " · realized " + money(r.realized_pnl_dollars) : ""));
        box.appendChild(line);
      });
    }).catch(function () {
      var pill = el("span", "status-pill pill-neutral", "no trades recorded yet");
      box.appendChild(pill);
      box.appendChild(el("p", "muted",
        "Trade records appear after a run of the “Demo trade / portfolio” workflow (manual dispatch). " +
        "Without demo credentials the workflow records nothing rather than inventing values — " +
        "see the Flagged for Review page."));
    });
  }

  /* --------------------------------------------------------------- strategies */
  var STRATEGIES = [
    ["Favorite confirmation", "elections, crypto", "Buy YES in a trending favorite only when best yes_bid_size ≥ 50 contracts and spread ≤ 2c; exit on category-specific stop.", "mean-reversion of long favorites after news spikes", "framework default — no live performance record yet"],
    ["Gas-price mean reversion", "gas", "Daily gas-price markets: when price deviates >15c from the 60-minute VWAP band, trade toward the band; stand down within 2h of close.", "settlement-time whipsaw; thin books near expiry", "framework default — no live performance record yet"],
    ["Crypto momentum continuation", "crypto", "On 1-minute candles, ride 3 consecutive higher highs for BTC/ETH above/below markets; reverse on volume climax > 3× 20-bar average.", "24/7 series with fast mean reversion; fees compound on churn", "framework default — no live performance record yet"],
    ["Golf leaderboard value", "golf", "Mid-tournament: buy co-leaders priced below 25c when weather delay compresses finishing variance; hedge with the field on Sunday.", "single-outcome variance is extreme in small fields", "framework default — no live performance record yet"],
    ["Culture crossover", "culture", "Multi-outcome award shows: back the 2nd-odds nominee if combined top-2 prices < $0.95 (longshot basket); avoid markets with open interest < $1k.", "mutually-exclusive event legs settle one winner only", "framework default — no live performance record yet"],
    ["Cross-book arb guard", "*", "Monitor yes_bid + no_bid > $1.00 on the same market; buy both sides when net > 1c after fees; report, never chase < 1c.", "fee schedule erodes thin edges", "framework default — no live performance record yet"]
  ];
  function renderStrategies() {
    var body = $("stratBody");
    STRATEGIES.forEach(function (s) {
      var tr = el("tr", null, "");
      s.forEach(function (cell, i) { tr.appendChild(el("td", i === 0 ? null : "muted", cell)); });
      body.appendChild(tr);
    });
  }

  /* ------------------------------------------------------------------- init */
  function init() {
    renderTopicFilters();
    renderStrategies();
    fetchJSON("data/meta.json")
      .then(function (m) { state.meta = m; renderStatus(m); })
      .catch(function () { renderStatus(null); });
    fetchJSON("data/events.json")
      .then(function (e) { state.events = e; renderEvents(); })
      .catch(function () { state.events = null; renderEvents(); });
    fetchJSON("data/tracked.json")
      .then(function (t) { state.tracked = t; return fetchJSON("data/resolutions.json"); })
      .then(function (r) { state.resolutions = r; renderResolutions(); })
      .catch(function () { state.resolutions = null; renderResolutions(); });
    renderPortfolio();
    renderTrades();
    window.addEventListener("resize", function () {
      if (state.history) renderChart();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
