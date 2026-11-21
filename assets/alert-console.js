/*
 * Live swing-alert console (session 5ab18dc3, task A1/A3).
 *
 * Two scrolling chat feeds driven by the same rule the CI backtest uses:
 *   left  = every >= $0.10 swing across the tracked universe (all events)
 *   right = only the swings the ROI model likes (calibrated by data/swings/strategies.json)
 *
 * Data flow (all official demo endpoints, no key, read-only):
 *   universe   data/latest/markets_open.json  (committed collector snapshot; ranked by the
 *              labelled est. dollar volume) or a live rebuild via GET /markets?status=open
 *   prices     GET /markets?tickers=a,b,c          (batch poll, chunks of 50)
 *   liquidity  GET /markets/orderbooks?tickers=    (<= 100 tickers/request, documented)
 *   fills      GET /markets/trades?ticker=&limit=100
 *   history    GET /series/{series}/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval
 * Endpoints/fields per https://docs.kalshi.com/api-reference/market/get-markets.md,
 * .../get-multiple-market-orderbooks.md, .../get-market-candlesticks.md, and
 * https://docs.kalshi.com/getting_started/orderbook_responses.md (YES-bid = NO-ask mirror).
 *
 * Why polling and not the WebSocket: the WS handshake requires KALSHI-ACCESS-* auth headers
 * even for public channels, which a browser cannot attach (COORDINATION.md I-13, official
 * https://docs.kalshi.com/getting_started/quick_start_websockets.md). Unauthenticated public
 * REST has its own, unpublished limits
 * (https://docs.kalshi.com/getting_started/rate_limits.md), so this console defaults to a
 * 10-second cadence, pauses when the tab is hidden, and backs off exponentially on 429.
 */
(function () {
  "use strict";

  var Core = window.KalshiSwingCore;
  var API = "https://external-api.demo.kalshi.co/trade-api/v2";
  var SNAPSHOT = "data/latest/";
  var SWING_DATA = "data/swings/";
  var LS = { cfg: "kalshi.alerts.cfg.v1", log: "kalshi.alerts.log.v1" };

  var TOPICS = [
    { id: "gas", label: "Gas prices", color: "#e07a2f" },
    { id: "elections", label: "Elections", color: "#4f6df5" },
    { id: "culture", label: "Culture", color: "#a346c4" },
    { id: "crypto", label: "Crypto", color: "#0f9d6e" },
    { id: "golf", label: "Golf", color: "#b8860b" }
  ];

  var cfg = {
    running: false, pollMs: 10000, windowMinutes: 10, thresholdDollars: 0.10,
    perTopic: 10, topics: { gas: 1, elections: 1, culture: 1, crypto: 1, golf: 1 },
    sound: false, notify: false, seedFromCandles: true, onlyTradable: false,
    follow: true, chartWindow: 3600
  };
  var model = null;
  var state = {
    markets: {}, universeSource: "none", alerts: [], resolutions: [],
    requests: 0, errors: 0, lastPoll: 0, nextAllowed: 0, backoff: 1000,
    selected: null, selectedBook: null, selectedTrades: null, selectedCandles: null,
    ciSwings: [], ciStrategies: null, ciEvents: [], timer: null, byTopic: {}
  };

  // ------------------------------------------------------------------ utils
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function money(v, dp) {
    if (v === null || v === undefined || isNaN(v)) return "";
    return "$" + Number(v).toFixed(dp === undefined ? 4 : dp);
  }
  function pct(v) {
    if (v === null || v === undefined || isNaN(v)) return "";
    return (v >= 0 ? "+" : "") + (100 * v).toFixed(1) + "%";
  }
  function bigNum(v) {
    if (v === null || v === undefined || isNaN(v)) return "";
    var n = Number(v);
    if (Math.abs(n) >= 1e9) return "$" + (n / 1e9).toFixed(2) + "B";
    if (Math.abs(n) >= 1e6) return "$" + (n / 1e6).toFixed(2) + "M";
    if (Math.abs(n) >= 1e3) return "$" + (n / 1e3).toFixed(1) + "k";
    return "$" + n.toFixed(2);
  }
  function p2(x) { return (x < 10 ? "0" : "") + x; }
  function hhmmss(ts) {
    var d = new Date(ts);
    return p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
  }
  function ago(ms) {
    if (!ms) return "never";
    var s = Math.round((Date.now() - ms) / 1000);
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    return Math.round(s / 3600) + "h ago";
  }
  function save(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {} }
  function load(key, fallback) {
    try { var raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; }
    catch (e) { return fallback; }
  }
  function banner(msg, kind) {
    var box = $("banner");
    if (!box) return;
    box.innerHTML = "";
    if (!msg) { box.style.display = "none"; return; }
    box.style.display = "block";
    box.appendChild(el("p", "pill " + (kind || "warn"), msg));
  }

  async function getJSON(url, opts) {
    var o = opts || {};
    if (Date.now() < state.nextAllowed && !o.priority) {
      throw new Error("rate-guard: waiting " + Math.ceil((state.nextAllowed - Date.now()) / 1000) + "s");
    }
    state.requests++;
    var res = await fetch(url, { headers: { Accept: "application/json" } });
    if (res.status === 429 || res.status === 503) {
      state.errors++;
      state.backoff = Math.min(120000, state.backoff * 2);
      state.nextAllowed = Date.now() + state.backoff;
      throw new Error("HTTP " + res.status + " (rate limited) - backing off " + Math.round(state.backoff / 1000) + "s");
    }
    if (!res.ok) { state.errors++; throw new Error("HTTP " + res.status + " for " + url); }
    state.backoff = 1000;
    return res.json();
  }

  /* --------------------------------------------------------------- bootstrap */
  async function boot() {
    wire();
    Object.assign(cfg, load(LS.cfg, {}));
    applyCfgToUi();
    try {
      model = await getJSON("alerts/model.json", { priority: true });
      if (model && model.alert_rule) {
        $("modelStatus").textContent = "model: " + model.mode + " calibration generated " + model.generated_at +
          " | threshold $" + model.alert_rule.threshold_dollars.toFixed(2) +
          " | weights " + Object.keys(model.roi_model.weights).map(function (k) {
            return k + " " + model.roi_model.weights[k];
          }).join(", ") +
          " | buckets " + Object.keys(model.roi_model.buckets || {}).length;
      }
    } catch (e) {
      model = null;
      $("modelStatus").textContent = "model: alerts/model.json unreachable (" + e.message +
        ") - the ROI feed stays empty rather than guessing";
    }
    await loadCatalysts();
    await loadUniverse();
    await loadSeriesMeta(Object.keys(state.markets).map(function (t) {
      return state.markets[t].market.__series;
    }));
    await loadCiHistory();
    renderUniverse(); renderBacktest(); renderResolutions(); setStatus(); renderFeeds();
    if (cfg.running) start();
  }

  /** Series metadata = the exchange's own statement of what settles each market.
   *  GET /series/{series} -> settlement_sources[].{name,url}, fee_type, fee_multiplier,
   *  contract_terms_url, tags (shape verified 2026-11-20 against
   *  https://external-api.demo.kalshi.co/trade-api/v2/series/KXWTIMAX and documented at
   *  https://docs.kalshi.com/api-reference/market/get-series.md).
   * Prefer the committed CI copy; fetch only what is missing; cache locally. */
  async function loadSeriesMeta(seriesList) {
    state.seriesMeta = state.seriesMeta || load("kalshi.alerts.series.v1", {});
    try {
      var f = await getJSON(SWING_DATA + "series_meta.json", { priority: true });
      Object.assign(state.seriesMeta, f.by_series || {});
      save("kalshi.alerts.series.v1", state.seriesMeta);
      $("catalystStatus").textContent = "series metadata: " + Object.keys(state.seriesMeta).length +
        " series with the exchange's own settlement sources (generated " +
        (f.meta && f.meta.generated_at) + " from " + (f.meta && f.meta.endpoint) + ")";
    } catch (e) {
      $("catalystStatus").textContent = "committed series metadata unavailable (" + e.message +
        ") - fetching the first " + Math.min(20, seriesList.length) + " live instead";
    }
    var missing = seriesList.filter(function (x) { return x && !state.seriesMeta[x]; }).slice(0, 20);
    for (var i = 0; i < missing.length; i++) {
      try {
        var d = await getJSON(API + "/series/" + missing[i]);
        state.seriesMeta[missing[i]] = Object.assign({ series_ticker: missing[i] }, d.series || {},
          { source_url: API + "/series/" + missing[i], fetched_live: true });
      } catch (err) {
        state.seriesMeta[missing[i]] = { series_ticker: missing[i], error: err.message,
          source_url: API + "/series/" + missing[i] };
      }
    }
    save("kalshi.alerts.series.v1", state.seriesMeta);
    // redraw the chats so the settlement-source links appear on rows rendered before the
    // metadata arrived (they are rebuilt from state.alerts, nothing is re-polled)
    renderFeeds();
    Object.keys(state.markets).forEach(function (t) {
      var st = state.markets[t];
      st.series = state.seriesMeta[st.market.__series] || null;
    });
  }

  async function loadCatalysts() {
    try {
      var c = await getJSON("alerts/catalysts.json", { priority: true });
      state.catalysts = c;
      $("catalystStatus").textContent = "catalyst register: " + c.topics_count + " topics · " +
        c.entries_count + " official reference sources · verified " + c.verified_at;
    } catch (e) { state.catalysts = null; $("catalystStatus").textContent = "catalyst register unavailable"; }
  }

  async function loadUniverse() {
    var rows = [];
    try {
      var snap = await getJSON(SNAPSHOT + "markets_open.json", { priority: true });
      rows = (snap.markets || []).slice();
      state.universeSource = "snapshot " + (snap.retrieved_at || "") + " (" + SNAPSHOT + "markets_open.json)";
    } catch (e) {
      state.universeSource = "snapshot unavailable (" + e.message + ") - live rebuild used instead";
      rows = await liveUniverse();
    }
    var byTopic = {};
    rows.forEach(function (m) {
      var topic = m.topic || Core.classify(m);
      if (!topic || !cfg.topics[topic]) return;
      if (Core.isExcluded(m, (model && model.roi_model && model.roi_model.excluded_series_prefixes) || [])) return;
      (byTopic[topic] = byTopic[topic] || []).push(m);
    });
    Object.keys(byTopic).forEach(function (t) {
      byTopic[t].sort(function (a, b) { return (Core.estDollarVolume(b) || 0) - (Core.estDollarVolume(a) || 0); });
      byTopic[t] = byTopic[t].slice(0, cfg.perTopic);
    });
    state.byTopic = byTopic;
    state.markets = {};
    var tickers = [];
    Object.keys(byTopic).forEach(function (t) {
      byTopic[t].forEach(function (m) {
        m.__topic = t;
        m.__series = m.series_ticker || String(m.ticker || "").split("-")[0];
        state.markets[m.ticker] = {
          market: m, quote: Core.quoteOf(m), alerts: 0,
          tracker: Core.createTracker(cfg.windowMinutes, { thresholdBits: Math.round(cfg.thresholdDollars * Core.BIT) }),
          samples: [], openTime: Date.now(), sessionOpen: true
        };
        tickers.push(m.ticker);
      });
    });
    state.tickers = tickers;
    $("universeStatus").textContent = tickers.length + " markets across " + Object.keys(byTopic).length +
      " topics | source: " + state.universeSource;
    seedHistory(tickers);
  }

  /** Live universe rebuild: 3 pages x 1000 open markets, MVE combos excluded (documented filter). */
  async function liveUniverse() {
    var out = [], cursor = "";
    for (var page = 0; page < 3; page++) {
      var params = "status=open&limit=1000&mve_filter=exclude" + (cursor ? "&cursor=" + encodeURIComponent(cursor) : "");
      var data = await getJSON(API + "/markets?" + params, { priority: true });
      out = out.concat(data.markets || []);
      cursor = data.cursor || "";
      if (!cursor) break;
    }
    return out;
  }

  /** Seed each tracker with the last 3 hours of 1-minute candles so alerts have context now. */
  async function seedHistory(tickers) {
    if (!cfg.seedFromCandles) return;
    var now = Math.floor(Date.now() / 1000);
    var slice = tickers.slice(0, 24);
    for (var i = 0; i < slice.length; i++) {
      var t = slice[i], st = state.markets[t];
      if (!st) continue;
      try {
        var d = await getJSON(API + "/series/" + st.market.__series + "/markets/" + t +
          "/candlesticks?start_ts=" + (now - 3 * 3600) + "&end_ts=" + now + "&period_interval=1");
        var rows = Core.candleSeries(d.candlesticks || []);
        rows.forEach(function (r) { Core.observe(st.tracker, t, { ts: r.ts * 1000, price: r.price }); });
        st.samples = rows.map(function (r) { return { ts: r.ts * 1000, price: r.price }; });
        st.seeded = rows.length;
      } catch (e) { st.seedError = e.message; }
    }
    renderUniverse();
  }

  async function loadCiHistory() {
    try {
      var sw = await getJSON(SWING_DATA + "swings.json", { priority: true });
      state.ciSwings = sw.swings || [];
      state.ciMeta = sw.meta;
      var st = await getJSON(SWING_DATA + "strategies.json", { priority: true });
      state.ciStrategies = st;
      var ev = await getJSON(SWING_DATA + "events.json", { priority: true });
      state.ciEvents = ev.events || [];
      $("ciStatus").textContent = "CI scan " + sw.meta.generated_at + " | " + sw.meta.swings_found +
        " swings >= $" + sw.meta.threshold_dollars.toFixed(2) + " across " + sw.meta.markets_scanned +
        " markets | mode " + sw.meta.mode + " | " + (sw.meta.stats.requests || 0) + " API calls, " +
        (sw.meta.stats.errors || 0) + " errors";
    } catch (e) {
      $("ciStatus").textContent = "no CI scan data yet (" + e.message + ") - the swing-scan workflow publishes data/swings/*.json";
    }
  }

  /* --------------------------------------------------------------- polling */
  function start() {
    cfg.running = true; save(LS.cfg, cfg); applyCfgToUi();
    poll();
    clearInterval(state.timer);
    state.timer = setInterval(function () {
      if (document.hidden) { $("pollNote").textContent = "paused while the tab is hidden"; return; }
      poll();
    }, cfg.pollMs);
  }
  function stop() { cfg.running = false; save(LS.cfg, cfg); clearInterval(state.timer); applyCfgToUi(); }

  async function poll() {
    if (!state.tickers || !state.tickers.length) return;
    var chunks = [];
    for (var i = 0; i < state.tickers.length; i += 50) chunks.push(state.tickers.slice(i, i + 50));
    var ok = 0;
    for (var c = 0; c < chunks.length; c++) {
      try {
        var data = await getJSON(API + "/markets?tickers=" + chunks[c].join(",") + "&limit=200");
        (data.markets || []).forEach(function (m) { ingest(m); });
        ok++;
      } catch (e) { $("pollNote").textContent = "poll error: " + e.message; }
    }
    state.lastPoll = Date.now();
    $("pollNote").textContent = "poll " + ok + "/" + chunks.length + " chunks | " + state.requests +
      " requests | " + state.errors + " errors | " + ago(state.lastPoll);
    renderUniverse(); renderResolutions(); setStatus();
    if (state.selected) renderDetail(state.selected, true);
  }

  function ingest(m) {
    var st = state.markets[m.ticker];
    if (!st) return;
    // carry the snapshot's topic/series onto the fresh record BEFORE it is replaced: the
    // live /markets response has no `topic` field, so losing these turns every alert into
    // "unclassified" and makes the bucket lookup miss (caught by tests/alert_console.test.js)
    var prev = st.market || {};
    m.__topic = m.__topic || prev.__topic;
    m.__series = m.__series || prev.__series || m.series_ticker || String(m.ticker || "").split("-")[0];
    st.market = m; st.quote = Core.quoteOf(m); st.lastSeen = Date.now();
    var price = st.quote && st.quote.price;
    if (price === null || price === undefined) return;
    var sample = { ts: Date.now(), price: price, bid: st.quote.bid, ask: st.quote.ask };
    st.samples.push(sample);
    while (st.samples.length > 4000) st.samples.shift();
    var status = String(m.status || "");
    var resolved = status === "settled" || m.result === "yes" || m.result === "no";
    if (resolved && !st.reported) { st.reported = true; st.sessionOpen = false; pushResolution(m, st); }
    else if (status && status !== "open" && status !== "active" && st.sessionOpen) { st.sessionOpen = false; }
    var alert = Core.observe(st.tracker, m.ticker, sample);
    if (!alert) return;
    var score = Core.roiScore(m, alert, model || {}, Date.now());
    if (cfg.onlyTradable && !(score.components.executability > 0)) return;
    alert.ticker = m.ticker; alert.market = m; alert.score = score;
    alert.eventTicker = m.event_ticker;
    alert.title = m.title || m.yes_sub_title;
    alert.topic = m.__topic;
    st.alerts++;
    state.alerts.push(alert);
    if (state.alerts.length > 2000) state.alerts.shift();
    save(LS.log, state.alerts.slice(-400).map(stripMarket));
    renderFeeds();
    if (cfg.sound) beep(score.pass ? 880 : 620);
    if (cfg.notify && typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification((score.pass ? "High-ROI " : "") + alert.direction + " swing " + m.ticker + " " +
        money(alert.from) + " -> " + money(alert.to), { body: alert.title });
    }
  }

  function stripMarket(a) {
    var c = {};
    Object.keys(a).forEach(function (k) { if (k !== "market") c[k] = a[k]; });
    return c;
  }

  function pushResolution(m, st) {
    var rec = {
      ts: Date.now(), ticker: m.ticker, eventTicker: m.event_ticker,
      title: m.title || m.yes_sub_title, result: m.result || null,
      settlementTs: m.settlement_ts || null, settlementValue: m.settlement_value_dollars || null,
      topic: m.__topic, sourceUrl: API + "/markets?tickers=" + encodeURIComponent(m.ticker),
      lastSeenPrice: st.quote ? Core.toDollars(st.quote.price) : null
    };
    state.resolutions.push(rec);
    save("kalshi.alerts.resolutions.v1", state.resolutions.slice(-400));
    addChatMessage($("feedAll"), chatNode(rec, "resolution"));
    renderResolutions();   // otherwise the resolution table only updates on the next reload
  }

  /* ------------------------------------------------------------------ chats */
  function chatNode(alert, kind) {
    var li = el("li", "msg " + (kind === "resolution" ? "res" : alert.direction) +
      (alert.score && alert.score.pass ? " pick" : ""));
    var head = el("div", "msg-head");
    head.appendChild(el("span", "mono time", hhmmss(alert.ts || Date.now())));
    if (alert.topic) {
      var t = TOPICS.filter(function (x) { return x.id === alert.topic; })[0] || { label: alert.topic, color: "#666" };
      var badge = el("span", "badge", t.label);
      badge.style.background = t.color;
      head.appendChild(badge);
    }
    if (kind !== "resolution") {
      head.appendChild(el("span", "arrow " + alert.direction, alert.direction === "up" ? "▲" : "▼"));
      head.appendChild(el("span", "delta", (alert.direction === "up" ? "+" : "-") + "$" + Math.abs(alert.deltaDollars).toFixed(4)));
      head.appendChild(el("span", "mono", money(alert.from) + " -> " + money(alert.to)));
      if (alert.deltaPct) head.appendChild(el("span", "muted", "(" + pct(alert.deltaPct) + " in " + alert.windowMinutes + "m)"));
      if (alert.score) head.appendChild(el("span", "score" + (alert.score.pass ? " pass" : ""), "ROI " + (alert.score.score * 100).toFixed(0)));
    } else {
      head.appendChild(el("span", "arrow", "■"));
      head.appendChild(el("span", "delta", "RESOLVED " + String(alert.result || "?").toUpperCase()));
      head.appendChild(el("span", "mono", alert.settlementTs || ""));
    }
    li.appendChild(head);

    var body = el("div", "msg-body");
    body.appendChild(el("div", "title", alert.title || alert.ticker));
    body.appendChild(el("div", "mono sub", alert.ticker + (alert.eventTicker ? " | " + alert.eventTicker : "")));
    if (kind !== "resolution") {
      var detail = [];
      if (alert.market) {
        var q = Core.quoteOf(alert.market);
        if (q) {
          detail.push("book " + money(Core.toDollars(q.bid)) + "/" + money(Core.toDollars(q.ask)));
          detail.push("size at touch " + (q.bidSize === null ? "?" : Math.round(q.bidSize)) + "/" +
            (q.askSize === null ? "?" : Math.round(q.askSize)) + " contracts");
        }
        detail.push("est $vol " + bigNum(Core.estDollarVolume(alert.market)) + " (estimate)");
        if (alert.market.close_time) detail.push("closes " + alert.market.close_time.slice(0, 16) + "Z");
      }
      if (alert.score) detail.push("bucket " + alert.score.bucket + " (" + alert.score.evidence + ")");
      body.appendChild(el("div", "small muted", detail.join(" | ")));
      if (alert.score && alert.score.reasons && alert.score.reasons.length) {
        body.appendChild(el("div", "small reasons", "why: " + alert.score.reasons.join("; ")));
      }
    }
    li.appendChild(body);

    var links = el("div", "msg-links");
    var src = el("a", "src", "API source");
    src.href = API + "/markets?tickers=" + encodeURIComponent(alert.ticker);
    src.target = "_blank"; src.rel = "noopener";
    links.appendChild(src);
    var chart = el("a", "src", "chart");
    chart.href = "dashboard.html?ticker=" + encodeURIComponent(alert.ticker);
    links.appendChild(chart);
    var d2 = el("a", "src", "depth + catalysts");
    d2.href = "#detail";
    d2.onclick = function (e) { e.preventDefault(); select(alert.ticker); };
    links.appendChild(d2);
    var seriesKey = (alert.market && alert.market.__series) || String(alert.ticker).split("-")[0];
    var sm = (state.seriesMeta || {})[seriesKey];
    if (sm && (sm.settlement_sources || []).length) {
      (sm.settlement_sources || []).slice(0, 2).forEach(function (src) {
        var a = el("a", "src", "settles on " + (src.name || "source"));
        if (src.url) { a.href = src.url; a.target = "_blank"; a.rel = "noopener"; }
        a.title = "Official settlement source for series " + sm.series_ticker + " per " +
          (sm.source_url || ("GET /series/" + sm.series_ticker)) +
          " - the price tracks this feed, so it is the first place to look for a jump's cause.";
        links.appendChild(a);
      });
    }
    if (alert.title) {
      var news = el("a", "src cand", "candidate news search");
      news.href = "https://news.google.com/search?q=" + encodeURIComponent(alert.title + " when:1d");
      news.target = "_blank"; news.rel = "noopener";
      news.title = "A lookup link offered as a possible catalyst for the move. Not a verified cause.";
      links.appendChild(news);
    }
    li.appendChild(links);
    return li;
  }

  function addChatMessage(list, node) {
    if (!list) return;
    var follow = cfg.follow !== false && (list.scrollTop + list.clientHeight >= list.scrollHeight - 60);
    list.appendChild(node);
    while (list.children.length > 400) list.removeChild(list.firstChild);
    if (follow) list.scrollTop = list.scrollHeight; else bumpNew(list);
  }
  function bumpNew(list) {
    var pill = list.parentNode.querySelector(".newcount");
    if (pill) { pill.hidden = false; pill.textContent = "new messages (scroll to bottom)"; }
  }

  function renderFeeds() {
    var all = $("feedAll"), roi = $("feedRoi");
    if (!all || !roi) return;
    all.innerHTML = ""; roi.innerHTML = "";
    var picks = 0, near = 0;
    state.alerts.forEach(function (a) {
      addChatMessage(all, chatNode(a));
      if (a.score && a.score.pass) { addChatMessage(roi, chatNode(a)); picks++; }
      else if (a.score && (a.score.score >= 0.5 || a.score.evidence === "none")) {
        // Dimmed near-miss bar: passes are unpicked; anything scoring >= 0.5 without
        // passing is shown dimmed. Alerts with no calibrated bucket ("evidence: none" —
        // the model cannot quantify them) are also shown dimmed rather than hidden:
        // the ROI chat must not be empty while swings are live. The row carries the
        // reason ("no calibrated bucket for this setup") in the body text.
        var li = chatNode(a);
        li.className += " nearmiss";
        addChatMessage(roi, li); near++;
      }
    });
    $("countAll").textContent = state.alerts.length + " alerts";
    $("countRoi").textContent = picks + " picks | " + near + " below the bar (shown dimmed)";
    renderTicker();
  }

  function renderTicker() {
    var bar = $("ticker");
    if (!bar) return;
    bar.innerHTML = "";
    state.alerts.slice(-14).reverse().forEach(function (a) {
      var s = el("span", "tick " + a.direction, (a.direction === "up" ? "^" : "v") + " " +
        String(a.ticker).split("-").slice(-1)[0] + " " + (a.direction === "up" ? "+" : "-") +
        Math.abs(a.deltaDollars).toFixed(2));
      s.title = a.title + "  " + money(a.from) + " -> " + money(a.to);
      bar.appendChild(s);
    });
    if (!state.alerts.length) bar.appendChild(el("span", "muted small",
      "no swings >= " + money(cfg.thresholdDollars, 2) + " yet - press Start; the console polls " +
      (state.tickers ? state.tickers.length : 0) + " live markets every " + (cfg.pollMs / 1000) + "s"));
  }

  /* ------------------------------------------------------------- universe UI */
  function renderUniverse() {
    var box = $("universeTables");
    if (!box || !state.byTopic) return;
    box.innerHTML = "";
    TOPICS.forEach(function (t) {
      if (!cfg.topics[t.id]) return;
      var rows = (state.byTopic[t.id] || []).slice();
      var card = el("section", "topic-block");
      var h = el("h3", null, t.label + " - " + rows.length + " markets");
      h.style.borderLeft = "6px solid " + t.color;
      card.appendChild(h);
      if (!rows.length) {
        card.appendChild(el("p", "small muted", "no open markets matched this topic in the current snapshot; " +
          "see data/latest/meta.json and flagged.html for the demo-liquidity gaps"));
        box.appendChild(card);
        return;
      }
      var table = el("table", "compact");
      table.innerHTML = "<thead><tr><th>#</th><th>Event</th><th>Market</th><th>Last</th><th>Bid/Ask</th>" +
        "<th>Session change</th><th>Alerts</th><th>Est. $ volume (estimate)</th><th>Close (UTC)</th>" +
        "<th>Status</th><th>Source</th></tr></thead>";
      var tbody = el("tbody");
      rows.forEach(function (m, i) {
        var st = state.markets[m.ticker] || {};
        var q = st.quote || Core.quoteOf(m) || {};
        var tr = el("tr", st.alerts ? "has-alert" : "");
        if (state.selected === m.ticker) tr.className += " selected";
        var sessDelta = (st.samples && st.samples.length > 1 && q.price !== null && q.price !== undefined)
          ? (q.price - st.samples[0].price) / Core.BIT : null;
        var cells = [
          String(i + 1),
          m.event_ticker || "",
          String(m.title || m.yes_sub_title || "").slice(0, 68),
          money(q.price === null || q.price === undefined ? null : Core.toDollars(q.price)),
          money(q.bid === null || q.bid === undefined ? null : Core.toDollars(q.bid)) + " / " +
            money(q.ask === null || q.ask === undefined ? null : Core.toDollars(q.ask)),
          sessDelta === null ? "" : (sessDelta >= 0 ? "+" : "") + sessDelta.toFixed(4),
          String(st.alerts || 0),
          bigNum(Core.estDollarVolume(m)),
          m.close_time ? m.close_time.slice(0, 16) : "",
          String(m.status || "") + (m.result ? " - " + m.result : "")
        ];
        cells.forEach(function (c) { tr.appendChild(el("td", null, c === null ? "" : c)); });
        tr.cells[6].id = "alerts-" + m.ticker;
        var srcTd = el("td");
        var a = el("a", "src", "API");
        a.href = API + "/markets?tickers=" + encodeURIComponent(m.ticker);
        a.target = "_blank"; a.rel = "noopener";
        srcTd.appendChild(a);
        tr.appendChild(srcTd);
        tr.onclick = function () { select(m.ticker); };
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      card.appendChild(table);
      box.appendChild(card);
    });
  }

  /* ------------------------------------------------------------- detail panel */
  async function select(ticker) {
    state.selected = ticker;
    renderUniverse();
    $("detail").hidden = false;
    $("detailTitle").textContent = ticker;
    await renderDetail(ticker);
    if ($("detail").scrollIntoView) $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function renderDetail(ticker, quiet) {
    var st = state.markets[ticker];
    if (!st) return;
    var m = st.market;
    var now = Math.floor(Date.now() / 1000);
    var win = cfg.chartWindow;
    var interval = win <= 2 * 3600 ? 1 : (win <= 3 * 86400 ? 60 : 1440);
    var series = m.__series;
    var url = API + "/series/" + series + "/markets/" + ticker + "/candlesticks?start_ts=" +
      (now - win) + "&end_ts=" + now + "&period_interval=" + interval;
    $("detailMeta").textContent = (m.title || "") + " | event " + (m.event_ticker || "-") +
      " | series " + series + " | demo environment (simulated prices and liquidity: " +
      "https://docs.kalshi.com/getting_started/demo_env.md)";
    try {
      var d = await getJSON(url);
      state.selectedCandles = { url: url, candlesticks: d.candlesticks || [], interval: interval };
    } catch (e) {
      state.selectedCandles = { error: e.message, url: url, candlesticks: [] };
      if (!quiet) banner("candlesticks unavailable: " + e.message, "warn");
    }
    try {
      var ob = await getJSON(API + "/markets/orderbooks?tickers=" + encodeURIComponent(ticker));
      state.selectedBook = (ob.orderbooks || [])[0] || null;
    } catch (e) { state.selectedBook = { error: e.message }; }
    try {
      state.selectedTrades = await getJSON(API + "/markets/trades?ticker=" + encodeURIComponent(ticker) + "&limit=100");
    } catch (e) { state.selectedTrades = { error: e.message }; }
    drawChart(ticker); drawDepth(ticker); renderTrades(); renderCatalysts(ticker);
  }

  function drawChart(ticker) {
    var cv = $("chart"), st = state.markets[ticker];
    if (!cv || !st) return;
    var ctx = cv.getContext("2d");
    var W = cv.width = Math.max(600, cv.clientWidth) * 2, H = cv.height = 520;
    ctx.clearRect(0, 0, W, H);
    var pts = (st.samples || []).filter(function (p) { return Date.now() - p.ts <= cfg.chartWindow * 1000; })
      .map(function (p) { return { ts: Math.round(p.ts / 1000), price: p.price }; });
    var candles = Core.candleSeries((state.selectedCandles && state.selectedCandles.candlesticks) || []);
    var all = candles.concat(pts).sort(function (a, b) { return a.ts - b.ts; });
    if (!all.length) {
      ctx.fillStyle = "#888"; ctx.font = "28px system-ui";
      ctx.fillText("no prints inside this window - press Start, or widen the window", 40, H / 2);
      $("chartNote").textContent = "window " + fmtWin(cfg.chartWindow) + " | 0 points | " +
        ((state.selectedCandles && (state.selectedCandles.error || "empty candle response")) || "");
      return;
    }
    var lo = Infinity, hi = -Infinity;
    all.forEach(function (p) { if (p.price < lo) lo = p.price; if (p.price > hi) hi = p.price; });
    if (lo === hi) { lo -= 50; hi += 50; }
    var pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
    var t0 = all[0].ts, t1 = all[all.length - 1].ts;
    if (t1 === t0) t1 = t0 + 60;
    var L = 130, R = W - 30, T = 40, B = H - 80;
    function X(ts) { return L + (ts - t0) / (t1 - t0) * (R - L); }
    function Y(p) { return B - (p - lo) / (hi - lo) * (B - T); }
    ctx.strokeStyle = "#2a2f3a"; ctx.fillStyle = "#9aa4b2"; ctx.font = "22px ui-monospace, monospace";
    for (var g = 0; g <= 4; g++) {
      var pv = lo + (hi - lo) * g / 4, py = Y(pv);
      ctx.beginPath(); ctx.moveTo(L, py); ctx.lineTo(R, py); ctx.stroke();
      ctx.fillText("$" + (pv / Core.BIT).toFixed(4), 10, py + 8);
    }
    var span = t1 - t0, ticks = 6, step = span / ticks;
    for (var k = 0; k <= ticks; k++) {
      var tt = t0 + step * k, tx = X(tt);
      ctx.strokeStyle = "#20242d"; ctx.beginPath(); ctx.moveTo(tx, T); ctx.lineTo(tx, B); ctx.stroke();
      ctx.fillStyle = "#9aa4b2";
      ctx.fillText(span < 900 ? fmtSec(tt) : (span < 86400 ? fmtMin(tt) : fmtHour(tt)), tx - 46, B + 36);
    }
    ctx.strokeStyle = "#5b6b8c";
    candles.forEach(function (c) {
      var pb = (c.raw && c.raw.price) || {};
      var loB = Core.toBits(pb.low_dollars), hiB = Core.toBits(pb.high_dollars);
      if (loB === null || hiB === null) return;
      ctx.beginPath(); ctx.moveTo(X(c.ts), Y(loB)); ctx.lineTo(X(c.ts), Y(hiB)); ctx.stroke();
    });
    ctx.strokeStyle = "#39d98a"; ctx.lineWidth = 4; ctx.beginPath();
    all.forEach(function (p, i) { if (i === 0) ctx.moveTo(X(p.ts), Y(p.price)); else ctx.lineTo(X(p.ts), Y(p.price)); });
    ctx.stroke(); ctx.lineWidth = 1;
    state.alerts.filter(function (a) { return a.ticker === ticker; }).forEach(function (a) {
      var ax = X(Math.round(a.ts / 1000)), ay = Y(a.toBits);
      ctx.fillStyle = a.score && a.score.pass ? "#ffd166" : "#ff6b6b";
      ctx.beginPath();
      ctx.moveTo(ax, ay - (a.direction === "up" ? 26 : -26));
      ctx.lineTo(ax - 13, ay + (a.direction === "up" ? 6 : -6));
      ctx.lineTo(ax + 13, ay + (a.direction === "up" ? 6 : -6));
      ctx.closePath(); ctx.fill();
    });
    var last = all[all.length - 1];
    ctx.fillStyle = "#e6edf3"; ctx.font = "24px ui-monospace, monospace";
    ctx.fillText("last " + money(Core.toDollars(last.price)), R - 250, T - 10);
    ctx.fillStyle = "#c9d1e0"; ctx.font = "22px system-ui";
    ctx.fillText("y: contract price in $ | x: time in " + (span < 900 ? "seconds" : span < 86400 ? "minutes" : "hours") +
      " | window " + fmtWin(cfg.chartWindow) + " | markers = alerts", L, H - 22);
    $("chartNote").textContent = "source: " + ((state.selectedCandles && state.selectedCandles.url) || "live browser samples only") +
      " | " + candles.length + " candles @" + ((state.selectedCandles && state.selectedCandles.interval) || "?") +
      "m + " + pts.length + " live samples";
  }
  function fmtSec(ts) { return new Date(ts * 1000).toTimeString().slice(0, 8); }
  function fmtMin(ts) { return new Date(ts * 1000).toTimeString().slice(0, 5); }
  function fmtHour(ts) { var d = new Date(ts * 1000); return (d.getMonth() + 1) + "/" + d.getDate() + " " + p2(d.getHours()) + "h"; }
  function fmtWin(sec) {
    if (sec < 120) return sec + "s";
    if (sec < 7200) return Math.round(sec / 60) + "m";
    if (sec < 172800) return Math.round(sec / 3600) + "h";
    return Math.round(sec / 86400) + "d";
  }

  function drawDepth(ticker) {
    var cv = $("depth"), rows = $("depthTable");
    if (!cv) return;
    var ctx = cv.getContext("2d");
    var W = cv.width = Math.max(600, cv.clientWidth) * 2, H = cv.height = 460;
    ctx.clearRect(0, 0, W, H);
    if (rows) rows.innerHTML = "";
    var book = state.selectedBook;
    if (!book || book.error || !book.orderbook_fp) {
      ctx.fillStyle = "#888"; ctx.font = "26px system-ui";
      ctx.fillText("order book unavailable" + (book && book.error ? " (" + book.error + ")" : "") +
        " - empty books are common on the demo exchange", 20, H / 2);
      $("depthNote").textContent = "source: " + API + "/markets/orderbooks?tickers=" + ticker;
      return;
    }
    var yes = (book.orderbook_fp.yes_dollars || []).map(function (lvl) {
      return { price: parseFloat(lvl[0]), size: parseFloat(lvl[1]) };
    }).sort(function (a, b) { return b.price - a.price; });
    if (!yes.length) {
      ctx.fillStyle = "#888"; ctx.font = "26px system-ui";
      ctx.fillText("0 resting YES bids on this book right now (a real answer, not a gap in the data)", 20, H / 2);
    }
    var max = 1;
    yes.forEach(function (l) { if (l.size > max) max = l.size; });
    ctx.fillStyle = "#c9d1e0"; ctx.font = "24px system-ui";
    ctx.fillText("YES bid ladder - each YES bid at price p is also a NO ask at $1 - p", 20, 28);
    yes.slice(0, 14).forEach(function (lvl, i) {
      var y0 = 56 + i * 28;
      ctx.fillStyle = "#1f6f4a";
      ctx.fillRect(280, y0, (W - 330) * (lvl.size / max), 18);
      ctx.fillStyle = "#c9d1e0"; ctx.font = "22px ui-monospace, monospace";
      ctx.fillText("$" + lvl.price.toFixed(4) + "   " + Math.round(lvl.size).toLocaleString(), 20, y0 + 17);
    });
    if (rows) {
      var table = el("table", "compact");
      table.innerHTML = "<thead><tr><th>Price level ($)</th><th>Contracts at that price</th>" +
        "<th>Cumulative contracts</th><th>Mirrored NO ask ($)</th></tr></thead>";
      var tb = el("tbody"), cum = 0;
      yes.forEach(function (lvl) {
        cum += lvl.size;
        var tr = el("tr");
        [money(lvl.price, 4), Math.round(lvl.size).toLocaleString(), Math.round(cum).toLocaleString(),
          money(1 - lvl.price, 4)].forEach(function (c) { tr.appendChild(el("td", null, c)); });
        tb.appendChild(tr);
      });
      table.appendChild(tb);
      rows.appendChild(table);
    }
    $("depthNote").textContent = "source: " + API + "/markets/orderbooks?tickers=" + ticker +
      " | " + yes.length + " YES levels | documented [price, contracts] ladder, best bid last";
  }

  function renderTrades() {
    var box = $("tradesTable");
    if (!box) return;
    box.innerHTML = "";
    var t = state.selectedTrades;
    if (!t || t.error) {
      box.appendChild(el("p", "small muted", "no trades response: " + (t && t.error ? t.error : "empty")));
      return;
    }
    var trades = (t.trades || []).slice(0, 25);
    var table = el("table", "compact");
    // Field names are the ones the schema marks REQUIRED
    // (https://docs.kalshi.com/api-reference/market/get-trades.md): yes_price_dollars /
    // no_price_dollars / count_fp / taker_outcome_side / taker_book_side / created_time /
    // is_block_trade. The legacy `price`, `count` and `yes_no` names are NOT in that schema,
    // so nothing falls back to them; a missing required field prints blank with an unverified
    // flag rather than a guessed number.
    table.innerHTML = "<thead><tr><th>Time (UTC)</th><th>Yes $</th><th>No $</th><th>Contracts</th>" +
      "<th>Taker outcome / book side</th><th>Block</th><th>Source</th></tr></thead>";
    var tb = el("tbody");
    trades.forEach(function (x) {
      var tr = el("tr");
      [String(x.created_time || "").slice(0, 19),
        x.yes_price_dollars === undefined ? "" : "$" + Number(x.yes_price_dollars).toFixed(4),
        x.no_price_dollars === undefined ? "" : "$" + Number(x.no_price_dollars).toFixed(4),
        x.count_fp === undefined ? "" : String(Number(x.count_fp).toLocaleString()),
        (x.taker_outcome_side || "") + (x.taker_book_side ? " / " + x.taker_book_side : ""),
        x.is_block_trade === undefined ? "" : (x.is_block_trade ? "yes" : "no")].forEach(function (c) {
        var td0 = el("td");
        td0.appendChild(document.createTextNode(c));
        if (c === "") td0.appendChild(el("span", "pill unverified", "unverified"));
        tr.appendChild(td0);
      });
      var td = el("td");
      var a = el("a", "src", "trades");
      a.href = API + "/markets/trades?ticker=" + encodeURIComponent(state.selected) + "&limit=100";
      a.target = "_blank"; a.rel = "noopener";
      td.appendChild(a); tr.appendChild(td); tb.appendChild(tr);
    });
    table.appendChild(tb); box.appendChild(table);
    if (!trades.length) box.appendChild(el("p", "small muted", "0 prints for this market on the demo exchange (empty is the real answer)"));
  }

  function renderCatalysts(ticker) {
    var box = $("catalysts");
    if (!box) return;
    box.innerHTML = "";
    var st = state.markets[ticker], m = st && st.market;
    box.appendChild(el("p", "small muted", "What moves this market, per the exchange itself (rules_primary, verbatim), " +
      "plus the topic's official reference sources. News links are search deep-links offered as candidates: " +
      "timing proximity is never presented as proof of cause."));
    if (m && m.rules_primary) {
      var pre = el("div", "rules");
      pre.appendChild(el("div", "small", "Settlement rule - API field rules_primary"));
      pre.appendChild(el("div", "mono", String(m.rules_primary).slice(0, 900)));
      box.appendChild(pre);
    } else {
      box.appendChild(el("p", "small unverified", "rules_primary: blank in this API response - unverified, not filled in"));
    }
    var smd = (state.seriesMeta || {})[m && m.__series];
    if (smd) {
      box.appendChild(el("div", "small muted", "Series " + (smd.series_ticker || m.__series) +
        " | category " + (smd.category || "-") + " | tags " + ((smd.tags || []).join(", ") || "-") +
        " | fee " + (smd.fee_type || "-") + " x" +
        (smd.fee_multiplier === undefined ? "-" : smd.fee_multiplier) +
        ". What the exchange itself settles on:"));
      var ul0 = el("ul", "src-list");
      var srcs = smd.settlement_sources || [];
      if (!srcs.length) {
        ul0.appendChild(el("li", null, "this series carries no settlement_sources entry in the API response (left blank, not guessed)"));
      }
      srcs.forEach(function (src) {
        var li = el("li");
        li.appendChild(el("span", null, (src.name || "source") + " - "));
        if (src.url) {
          var a0 = el("a", "src", src.url);
          a0.href = src.url; a0.target = "_blank"; a0.rel = "noopener";
          li.appendChild(a0);
        } else {
          li.appendChild(el("span", "pill unverified", "no url on the API record"));
        }
        ul0.appendChild(li);
      });
      if (smd.contract_terms_url) {
        var li3 = el("li");
        li3.appendChild(el("span", null, "Contract terms (PDF) - "));
        var a3 = el("a", "src", smd.contract_terms_url);
        a3.href = smd.contract_terms_url; a3.target = "_blank"; a3.rel = "noopener";
        li3.appendChild(a3);
        ul0.appendChild(li3);
      }
      var li4 = el("li", "small muted");
      li4.appendChild(el("span", null, "source of this block: "));
      var sa = el("a", "src", smd.source_url || (API + "/series/" + m.__series));
      sa.href = smd.source_url || (API + "/series/" + m.__series);
      sa.target = "_blank"; sa.rel = "noopener";
      li4.appendChild(sa);
      if (smd.fetched_live) li4.appendChild(el("span", null, " (fetched live by your browser)"));
      if (smd.error) li4.appendChild(el("span", "pill unverified", "fetch failed: " + smd.error));
      ul0.appendChild(li4);
      box.appendChild(ul0);
    }
    var cat = state.catalysts && state.catalysts.topics && state.catalysts.topics[m && m.__topic];
    if (cat) {
      var ul = el("ul", "src-list");
      (cat.sources || []).forEach(function (s) {
        var li = el("li");
        li.appendChild(el("span", null, s.label + " - "));
        if (s.url) {
          var a = el("a", "src", s.url);
          a.href = s.url; a.target = "_blank"; a.rel = "noopener";
          li.appendChild(a);
        } else {
          li.appendChild(el("span", "pill unverified", "no verified link - see flagged.html"));
        }
        li.appendChild(el("span", "small muted", " | " + (s.verified_by ? "link fetched live by " +
          s.verified_by + " on " + s.checked_at + " (HTTP " + s.http_status + ")" : "unverified")));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    var alertsHere = state.alerts.filter(function (a) { return a.ticker === ticker; }).slice(-5);
    if (alertsHere.length) {
      box.appendChild(el("div", "small", "Jumps observed this session:"));
      var ul2 = el("ul", "jump-list");
      alertsHere.forEach(function (a) {
        var li = el("li", null, hhmmss(a.ts) + " | " + a.direction + " " + money(a.from) + " -> " + money(a.to) +
          " (" + (a.direction === "up" ? "+" : "-") + "$" + Math.abs(a.deltaDollars).toFixed(4) + ", " +
          pct(a.deltaPct) + ") | ROI " + (a.score ? (a.score.score * 100).toFixed(0) : "-"));
        var a2 = el("a", "src cand", " news search");
        a2.href = "https://news.google.com/search?q=" + encodeURIComponent((a.title || a.ticker) + " when:1d");
        a2.target = "_blank"; a2.rel = "noopener";
        li.appendChild(a2);
        ul2.appendChild(li);
      });
      box.appendChild(ul2);
    }
  }

  /* ------------------------------------------------------- backtest / model UI */
  function renderBacktest() {
    var box = $("backtestTable");
    if (!box) return;
    box.innerHTML = "";
    var data = state.ciStrategies;
    if (!data) {
      box.appendChild(el("p", "small unverified", "no scan file yet - data/swings/strategies.json is produced by the " +
        "'Swing scan (alert console data)' workflow"));
      return;
    }
    var meta = data.meta;
    box.appendChild(el("p", "small muted", "Simulated trades on demo candlesticks | window " + meta.window_minutes +
      " min | threshold $" + meta.threshold_dollars.toFixed(2) + " | " + meta.markets_scanned + " markets | " +
      meta.swings_found + " swings | re-poll for resolution included | fees = published Kalshi taker formula"));
    var table = el("table", "compact");
    table.innerHTML = "<thead><tr><th>Strategy</th><th>Swings</th><th>Quotable fills</th>" +
      "<th>Mean net $/contract</th><th>Hit rate</th><th>Mean fees $/contract</th><th>Mean ROI on paid</th>" +
      "<th>Up/Down</th><th>Source</th></tr></thead>";
    var tb = el("tbody");
    Object.keys(data.strategies).sort().forEach(function (name) {
      var o = data.strategies[name].overall;
      var tr = el("tr");
      [name, String(o.n), String(o.n_quotable),
        o.mean_net_dollars === null ? "" : money(o.mean_net_dollars),
        o.hit_rate === null ? "" : (100 * o.hit_rate).toFixed(1) + "%",
        o.mean_fees_dollars === null ? "" : money(o.mean_fees_dollars),
        o.mean_roi_on_paid === null ? "" : pct(o.mean_roi_on_paid),
        (o.direction_split.up || 0) + " / " + (o.direction_split.down || 0)].forEach(function (c) {
          tr.appendChild(el("td", null, c === null || c === undefined ? "" : String(c)));
        });
      var td = el("td");
      var a = el("a", "src", "strategies.json");
      a.href = SWING_DATA + "strategies.json";
      td.appendChild(a); tr.appendChild(td); tb.appendChild(tr);
    });
    table.appendChild(tb);
    box.appendChild(table);
    if (meta.caveats && meta.caveats.length) {
      var ul = el("ul", "small muted");
      meta.caveats.forEach(function (c) { ul.appendChild(el("li", null, c)); });
      box.appendChild(ul);
    }

    var evBox = $("ciEvents");
    if (evBox) {
      evBox.innerHTML = "";
      var byTopic = {};
      (state.ciEvents || []).forEach(function (e) { (byTopic[e.topic] = byTopic[e.topic] || []).push(e); });
      var any = false;
      TOPICS.forEach(function (t) {
        var rows = byTopic[t.id] || [];
        if (!rows.length) return;
        any = true;
        evBox.appendChild(el("h4", null, t.label));
        var table2 = el("table", "compact");
        table2.innerHTML = "<thead><tr><th>Event</th><th>Swings</th><th>Max move</th><th>Reversion rate</th>" +
          "<th>Resolution</th><th>Markets flagged</th><th>Source</th></tr></thead>";
        var tb2 = el("tbody");
        rows.forEach(function (e) {
          var tr = el("tr");
          [(e.title || e.event_ticker || ""), String(e.n_swings), money(e.max_abs_delta_dollars),
            (100 * e.reversion_rate).toFixed(0) + "%", e.resolution_outcome || "open",
            (e.markets_flagged || []).slice(0, 3).join(", ") +
            ((e.markets_flagged || []).length > 3 ? " +" + (e.markets_flagged.length - 3) + " more" : "")]
            .forEach(function (c) { tr.appendChild(el("td", null, c === null ? "" : String(c))); });
          var td = el("td");
          var urls = e.source_urls || [];
          if (!urls.length) td.appendChild(el("span", "pill unverified", "unverified"));
          urls.slice(0, 2).forEach(function (u, i) {
            var a = el("a", "src", i ? "settlement" : "candles");
            a.href = u; a.target = "_blank"; a.rel = "noopener";
            td.appendChild(a);
          });
          tr.appendChild(td); tb2.appendChild(tr);
        });
        table2.appendChild(tb2);
        evBox.appendChild(table2);
      });
      if (!any) evBox.appendChild(el("p", "small muted", "no >= $0.10 swings recorded by the last scan for the five topics"));
    }

    var spec = $("modelSpec");
    if (spec && model) {
      spec.innerHTML = "";
      var t3 = el("table", "compact");
      t3.innerHTML = "<thead><tr><th>Component</th><th>Weight</th><th>What it measures</th><th>Field(s) used</th><th>Source</th></tr></thead>";
      var body = el("tbody");
      var rows = [
        ["calibrated_edge", "what the CI backtest says a fade is worth in this exact bucket (price band x move size x time to close), shrunk toward the global rate",
          "data/swings/strategies.json buckets", SWING_DATA + "strategies.json"],
        ["relative_move", "swing measured against the price it moved from", "last_price_dollars path",
          "https://docs.kalshi.com/api-reference/market/get-markets.md"],
        ["executability", "quoted spread at the alert instant (25% of mid or worse scores 0)", "yes_bid_dollars, yes_ask_dollars",
          "https://docs.kalshi.com/api-reference/market/get-markets.md"],
        ["liquidity_depth", "contracts standing at the touch, log-scaled to 500", "yes_bid_size_fp, yes_ask_size_fp",
          "https://docs.kalshi.com/getting_started/orderbook_responses.md"],
        ["time_to_resolution", "log-symmetric around ~6h to close: needs room to revert, long-dated names carry information risk",
          "latest_expiration_time / close_time", "https://docs.kalshi.com/getting_started/market_lifecycle.md"]
      ];
      rows.forEach(function (r) {
        var tr = el("tr");
        [r[0], String(model.roi_model.weights[r[0]] || ""), r[1]].forEach(function (c) { tr.appendChild(el("td", null, c)); });
        tr.appendChild(el("td", "mono", r[2] === undefined ? "" : String(r[2])));
        var td = el("td");
        var a = el("a", "src", "source");
        a.href = r[3]; if (/^http/.test(r[3])) { a.target = "_blank"; a.rel = "noopener"; }
        td.appendChild(a); tr.appendChild(td); body.appendChild(tr);
      });
      t3.appendChild(body);
      spec.appendChild(t3);
      spec.appendChild(el("p", "small muted", "pass bar " + model.roi_model.pass_threshold_score +
        " of 1.0, and only when the bucket has >= " + model.roi_model.min_bucket_n + " swings in >= " +
        (model.roi_model.min_bucket_markets || "-") + " distinct markets. Heuristic screen for triage, not advice; " +
        "it is derived from demo (simulated) data."));
    }
  }

  function renderResolutions() {
    var box = $("resolutionTable");
    if (!box) return;
    box.innerHTML = "";
    var seeded = load("kalshi.alerts.resolutions.v1", []);
    var rows = state.resolutions.length ? state.resolutions : seeded;
    var table = el("table", "compact");
    table.innerHTML = "<thead><tr><th>Market</th><th>Topic</th><th>Result</th><th>Settlement (UTC)</th>" +
      "<th>Settlement value</th><th>Last price seen this session</th><th>Source</th></tr></thead>";
    var tb = el("tbody");
    rows.slice(-50).reverse().forEach(function (r) {
      var tr = el("tr");
      [r.ticker, r.topic || "", r.result ? String(r.result).toUpperCase() : "",
        r.settlementTs || "", r.settlementValue || "",
        (r.lastSeenPrice === null || r.lastSeenPrice === undefined) ? "" : money(r.lastSeenPrice)]
        .forEach(function (c) { tr.appendChild(el("td", null, c || "")); });
      var td = el("td");
      var a = el("a", "src", "API");
      a.href = r.sourceUrl || (API + "/markets?tickers=" + encodeURIComponent(r.ticker));
      a.target = "_blank"; a.rel = "noopener";
      td.appendChild(a); tr.appendChild(td); tb.appendChild(tr);
    });
    table.appendChild(tb);
    box.appendChild(table);
    if (!rows.length) box.appendChild(el("p", "small muted",
      "nothing resolved while this page was open; the collector records settlements continuously in " +
      SNAPSHOT + "resolutions.json (see data-tracking.html)"));
  }

  /* ------------------------------------------------------------------- misc */
  function beep(freq) {
    try {
      var Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) return;
      var c = beep.ctx || (beep.ctx = new Ctor());
      var o = c.createOscillator(), g = c.createGain();
      o.frequency.value = freq || 660; o.type = "sine";
      g.gain.value = 0.0001; o.connect(g); g.connect(c.destination);
      o.start();
      g.gain.exponentialRampToValueAtTime(0.08, c.currentTime + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + 0.3);
      o.stop(c.currentTime + 0.32);
    } catch (e) { /* audio blocked */ }
  }

  function setStatus() {
    var s = $("engineStatus");
    if (!s) return;
    s.textContent = cfg.running ? "LIVE - polling every " + (cfg.pollMs / 1000) + "s" : "STOPPED";
    s.className = "pill " + (cfg.running ? "ok" : "warn");
    $("lastPoll").textContent = "last poll " + ago(state.lastPoll);
    $("counts").textContent = (state.tickers ? state.tickers.length : 0) + " markets | " +
      state.alerts.length + " alerts | " + state.resolutions.length + " resolutions";
  }

  function applyCfgToUi() {
    if (!$("pollSel")) return;
    $("pollSel").value = String(cfg.pollMs);
    $("windowSel").value = String(cfg.windowMinutes);
    $("thresholdSel").value = String(cfg.thresholdDollars);
    $("depthSel").value = String(cfg.perTopic);
    $("chartWin").value = String(cfg.chartWindow);
    $("soundChk").checked = !!cfg.sound;
    $("notifyChk").checked = !!cfg.notify;
    $("seedChk").checked = !!cfg.seedFromCandles;
    $("tradableChk").checked = !!cfg.onlyTradable;
    $("followChk").checked = cfg.follow !== false;
    $("runBtn").textContent = cfg.running ? "Pause" : "Start";
    TOPICS.forEach(function (t) {
      var c = $("topic-" + t.id);
      if (c) c.checked = !!cfg.topics[t.id];
    });
    setStatus();
  }

  function wire() {
    $("runBtn").onclick = function () { if (cfg.running) stop(); else start(); };
    $("pollSel").onchange = function () { cfg.pollMs = +this.value; save(LS.cfg, cfg); if (cfg.running) start(); };
    $("windowSel").onchange = function () { cfg.windowMinutes = +this.value; save(LS.cfg, cfg); rebuildTrackers(); };
    $("thresholdSel").onchange = function () {
      cfg.thresholdDollars = +this.value; save(LS.cfg, cfg); rebuildTrackers(); renderTicker();
    };
    $("depthSel").onchange = function () {
      cfg.perTopic = +this.value; save(LS.cfg, cfg); loadUniverse().then(renderUniverse);
    };
    $("chartWin").onchange = function () {
      cfg.chartWindow = +this.value; save(LS.cfg, cfg); if (state.selected) renderDetail(state.selected);
    };
    [["soundChk", "sound"], ["notifyChk", "notify"], ["seedChk", "seedFromCandles"],
     ["tradableChk", "onlyTradable"], ["followChk", "follow"]].forEach(function (pair) {
      $(pair[0]).onchange = function () {
        cfg[pair[1]] = this.checked;
        if (pair[1] === "notify" && this.checked && typeof Notification !== "undefined") Notification.requestPermission();
        save(LS.cfg, cfg);
      };
    });
    TOPICS.forEach(function (t) {
      var node = $("topic-" + t.id);
      if (!node) return;
      node.checked = !!cfg.topics[t.id];
      node.onchange = function () {
        cfg.topics[t.id] = this.checked ? 1 : 0;
        save(LS.cfg, cfg);
        loadUniverse().then(function () { renderUniverse(); renderFeeds(); });
      };
    });
    $("rebuildUniverseBtn").onclick = function () {
      $("universeStatus").textContent = "rebuilding from live /markets?status=open&limit=1000&mve_filter=exclude ...";
      loadUniverse().then(function () { renderUniverse(); renderFeeds(); });
    };
    $("clearBtn").onclick = function () {
      state.alerts = [];
      $("feedAll").innerHTML = ""; $("feedRoi").innerHTML = "";
      save(LS.log, []); renderFeeds();
    };
    $("exportBtn").onclick = function () {
      var blob = new Blob([JSON.stringify({ generated_at: new Date().toISOString(), cfg: cfg,
        alerts: state.alerts.map(stripMarket), resolutions: state.resolutions }, null, 1)],
        { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "kalshi-alert-session-" + new Date().toISOString().slice(0, 16) + ".json";
      a.click();
    };
    $("copyBtn").onclick = function () {
      var txt = state.alerts.slice(-50).map(function (a) {
        return hhmmss(a.ts) + " " + (a.direction === "up" ? "^" : "v") + " " + a.ticker + " " +
          money(a.from) + " -> " + money(a.to) + " delta " + money(a.deltaDollars);
      }).join("\n");
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt);
    };
    $("jumpLatest").onclick = function () {
      $("feedAll").scrollTop = $("feedAll").scrollHeight;
      $("feedRoi").scrollTop = $("feedRoi").scrollHeight;
    };
    ["feedAll", "feedRoi"].forEach(function (id) {
      var list = $(id);
      if (!list) return;
      list.addEventListener("scroll", function () {
        var atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 60;
        if (atBottom) {
          var pill = list.parentNode.querySelector(".newcount");
          if (pill) pill.hidden = true;
        }
      });
    });
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && cfg.running && Date.now() - state.lastPoll > cfg.pollMs * 2) poll();
    });
    window.addEventListener("resize", function () {
      if (state.selected) { drawChart(state.selected); drawDepth(state.selected); }
    });
  }

  function rebuildTrackers() {
    Object.keys(state.markets).forEach(function (tk) {
      var st = state.markets[tk];
      st.tracker = Core.createTracker(cfg.windowMinutes, { thresholdBits: Math.round(cfg.thresholdDollars * Core.BIT) });
      (st.samples || []).slice(-2000).forEach(function (p) { Core.observe(st.tracker, tk, p); });
    });
  }

  state.alerts = load(LS.log, []);
  state.resolutions = load("kalshi.alerts.resolutions.v1", []);

  /* ---------------------------------------------------------------- test hooks
   * tests/alert_console.test.js drives the very same functions the poll timer drives, so the
   * harness cannot diverge from production code. Harmless in normal use. */
  if (typeof window !== "undefined") {
    window.__alerts = {
      state: state, cfg: cfg, get model() { return model; },
      ingest: ingest, select: select, renderFeeds: renderFeeds,
      track: function (m, topic) {
        m.__topic = topic || m.__topic || "crypto";
        m.__series = m.series_ticker || String(m.ticker || "").split("-")[0];
        state.markets[m.ticker] = {
          market: m, quote: Core.quoteOf(m), alerts: 0,
          tracker: Core.createTracker(cfg.windowMinutes,
            { thresholdBits: Math.round(cfg.thresholdDollars * Core.BIT) }),
          samples: [], openTime: Date.now(), sessionOpen: true
        };
        if (m.__series && !(state.seriesMeta || {})[m.__series]) {
          loadSeriesMeta([m.__series]).then(function () { renderUniverse(); });
        }
        return state.markets[m.ticker];
      }
    };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
