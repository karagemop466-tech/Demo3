/* Kalshi Demo Tracker — live swing-alert system (two scrolling chats).
 *
 * Watches open markets in the five tracked topics, polled live from the Kalshi
 * Demo Trade API (public market data needs no key — docs.kalshi.com/getting_started/
 * quick_start_market_data), and posts a message to two scrolling chats whenever a
 * contract price moves by a chosen threshold (default $0.10 = 10¢) in either
 * direction between polls:
 *
 *   Chat 1 "All events"      — every detected swing on every watched market.
 *   Chat 2 "Model picks"     — only swings the published heuristic ROI model likes.
 *
 * Every message carries per-row official sources: the exact market API URL, the
 * event API URL, the event's official settlement-source links when known, and a
 * clearly labeled news-search link used only to investigate what may have caused
 * the jump (an investigation link, never a claim of cause).
 *
 * Markets are tracked until they resolve: when a watched market settles, its
 * result (yes / no) is posted to both chats and stored in the same localStorage
 * resolution log the dashboard uses (kd_resolutions). Settlement semantics per
 * docs.kalshi.com/getting_started/market_settlement.
 *
 * The high-ROI filter is a deterministic heuristic evaluated from fields of the
 * official /markets response (yes/no ask, top-of-book ask size, spread, 24h
 * volume). It is labeled as an UNVERIFIED ESTIMATE everywhere (flag F-99E28-01);
 * it is not a verified Kalshi metric and not investment advice.
 */
(function () {
  "use strict";
  var K = window.KalshiDemo;
  var $ = function (id) { return document.getElementById(id); };

  /* =====================================================================
   * Pure engine (exported for tests as window.KalshiAlerts).
   * ===================================================================== */
  var Engine = {};

  /* detectSwing — compare two poll snapshots of one market.
   * prev/cur: { price } in dollars (as returned by /markets last_price_dollars,
   * a verified response field). thresholdCents: alert when |move| >= threshold.
   * Prices are rounded to whole cents first (Kalshi price increments are 1¢)
   * so floating-point drift can never swallow an exact 10¢ move.
   * Returns null when no swing (or a side is missing); first sighting (prev
   * null) only establishes the baseline — never alerts. */
  Engine.detectSwing = function (prev, cur, thresholdCents) {
    if (!prev || !cur) return null;
    if (prev.price === null || prev.price === undefined ||
        cur.price === null || cur.price === undefined) return null;
    var cents = Math.round((Number(cur.price) - Number(prev.price)) * 100);
    if (!isFinite(cents)) return null;
    if (Math.abs(cents) < thresholdCents) return null;
    return { dir: cents > 0 ? "up" : "down", deltaCents: Math.abs(cents),
             from: Number(prev.price), to: Number(cur.price) };
  };

  /* The published heuristic ROI model (v1). Gates, in order — every one must
   * pass for a swing to be a "model pick":
   *   1. liquidity — contracts resting at the entry (swung side) ask must be
   *      >= minAskContracts (from yes/no ask *_size_fp of the same response).
   *   2. tradeable — the YES bid/ask spread must be known and <= maxSpreadCents.
   *   3. upside    — potential ROI of holding the swung side to a $1 settlement
   *      ( (1 - entry) / entry ) must be >= minRoi (default 100%+).
   *   4. activity  — the market must have traded >= minVolume24h contracts in
   *      the last 24h (volume_24h_fp) so dead books don't flood picks.
   * score = roi * log10(1 + contractsAtAsk)  (bigger = deeper book x bigger ROI).
   * Returns { liked, score, entry, roi, contractsAtAsk, failed:[gate...] }. */
  Engine.MODEL = {
    minAskContracts: 100,   // contracts at the entry ask (top-of-book size)
    maxSpreadCents: 20,     // YES bid/ask spread must not exceed this
    minRoi: 1.0,            // (1-entry)/entry must be at least 100%
    minVolume24h: 1000      // contracts traded in last 24h
  };
  Engine.modelLike = function (m, swing) {
    var gates = Engine.MODEL;
    var failed = [];
    var sideAsk = swing.dir === "up" ? m.yes_ask : m.no_ask;
    var askSize = swing.dir === "up" ? m.yes_ask_size : m.no_ask_size;
    if (sideAsk === null || sideAsk === undefined) failed.push("entry-ask-unknown");
    if (askSize === null || askSize === undefined || Number(askSize) < gates.minAskContracts) {
      failed.push("liquidity");
    }
    if (m.yes_bid === null || m.yes_ask === null ||
        (m.yes_ask - m.yes_bid) * 100 > gates.maxSpreadCents) {
      failed.push("spread");
    }
    var roi = null;
    if (sideAsk !== null && sideAsk !== undefined && Number(sideAsk) > 0) {
      roi = (1 - Number(sideAsk)) / Number(sideAsk);
      if (roi < gates.minRoi) failed.push("upside");
    }
    if (m.volume_24h === null || m.volume_24h === undefined ||
        Number(m.volume_24h) < gates.minVolume24h) {
      failed.push("activity");
    }
    var score = null;
    if (roi !== null && askSize !== null && Number(askSize) > 0) {
      score = roi * Math.log10(1 + Number(askSize));
    }
    return { liked: failed.length === 0, failed: failed, entry: sideAsk,
             roi: roi, contractsAtAsk: askSize === null ? null : Number(askSize),
             score: score };
  };

  /* normalizeMarket — /markets response row -> engine snapshot (verified fields
   * only; anything the API did not return stays null and is shown blank). */
  Engine.normalizeMarket = function (m, topic) {
    function f(v) {
      return (v === undefined || v === null || v === "") ? null : Number(v);
    }
    return {
      ticker: m.ticker, event_ticker: m.event_ticker,
      series_ticker: m.series_ticker || "", title: m.title || m.ticker,
      status: m.status, result: m.result || "",
      price: f(m.last_price_dollars !== undefined ? m.last_price_dollars : m.last_price),
      yes_bid: f(m.yes_bid_dollars !== undefined ? m.yes_bid_dollars : m.yes_bid),
      yes_ask: f(m.yes_ask_dollars !== undefined ? m.yes_ask_dollars : m.yes_ask),
      no_ask: f(m.no_ask_dollars !== undefined ? m.no_ask_dollars : m.no_ask),
      yes_ask_size: f(m.yes_ask_size_fp), no_ask_size: f(m.no_ask_size_fp),
      volume_24h: f(m.volume_24h_fp !== undefined ? m.volume_24h_fp : m.volume_24h),
      volume: f(m.volume_fp !== undefined ? m.volume_fp : m.volume),
      open_interest: f(m.open_interest_fp !== undefined ? m.open_interest_fp : m.open_interest),
      close_time: m.close_time, topic: topic || m._topic || ""
    };
  };

  Engine.estDollars = K.estDollars; // contracts x price (labeled estimate)

  /* =====================================================================
   * UI wiring (alerts.html only; every id is guarded so this file never
   * breaks other pages).
   * ===================================================================== */
  var state = {
    running: false, polls: 0, requests: 0, alertsSent: 0,
    seriesByTopic: {}, markets: [], watched: {},   // ticker -> snapshot
    everWatched: {}, watchedSeries: {},
    windowSec: 3600, selected: null, samples: {}, orderbook: null,
    eventCache: {}, resolutions: [], lastAlertAt: {},
    timers: []
  };
  try { state.resolutions = JSON.parse(localStorage.getItem("kd_resolutions") || "[]"); }
  catch (e) { state.resolutions = []; }
  var ALERTS_KEY = "kd_alerts_v1";
  var messages = [];
  try { messages = JSON.parse(localStorage.getItem(ALERTS_KEY) || "[]"); }
  catch (e) { messages = []; }
  if (!Array.isArray(messages)) messages = [];

  /* Exposed for tests and power users: the pure engine, plus the live ingest /
   * sweep steps and state (tests drive them directly without timers). */
  window.KalshiAlerts = Engine;
  window.KalshiAlerts.ingest = ingest;
  window.KalshiAlerts.settleSweep = settleSweep;
  window.KalshiAlerts.state = state;

  function saveMessages() {
    try {
      if (messages.length > 200) messages = messages.slice(0, 200);
      localStorage.setItem(ALERTS_KEY, JSON.stringify(messages));
    } catch (e) { /* storage full — session-only then */ }
  }
  function banner(kind, html) {
    var el = $("banner");
    if (!el) return;
    el.className = kind; el.innerHTML = html; el.style.display = html ? "block" : "none";
  }
  function statusLine() {
    var el = $("alertStatus");
    if (!el) return;
    var mode = state.running ? "Polling live" : "Paused";
    el.textContent = mode + " · " + state.polls + " scans · " + state.requests +
      " API requests · " + Object.keys(state.watched).length + " markets watched · " +
      messages.length + " alert messages";
    if (state.lastScan) {
      el.textContent += " · last scan " + new Date(state.lastScan).toLocaleTimeString();
    }
  }

  /* ---------- message construction ---------- */
  function buildSwingMessage(mkt, swing, model) {
    var now = Math.floor(Date.now() / 1000);
    var msg = {
      type: "swing", ts: now, ticker: mkt.ticker, title: mkt.title,
      topic: mkt.topic, dir: swing.dir, deltaCents: swing.deltaCents,
      from: swing.from, to: swing.to,
      yes_bid: mkt.yes_bid, yes_ask: mkt.yes_ask,
      contractsAtAsk: model ? model.contractsAtAsk : null,
      modelLiked: !!(model && model.liked), modelScore: model ? model.score : null,
      modelEntry: model ? model.entry : null, modelRoi: model ? model.roi : null,
      modelFailed: model ? model.failed : [],
      src: K.BASE + "/markets/" + encodeURIComponent(mkt.ticker),
      eventSrc: mkt.series_ticker ? K.BASE + "/events?series_ticker=" +
        encodeURIComponent(mkt.series_ticker) : "",
      news: "https://news.google.com/search?q=" + encodeURIComponent(mkt.title),
      settlementLinks: []
    };
    return msg;
  }
  function buildResolutionMessage(mkt) {
    var now = Math.floor(Date.now() / 1000);
    return {
      type: "resolution", ts: now, ticker: mkt.ticker, title: mkt.title,
      topic: mkt.topic, result: String(mkt.result).toLowerCase(), status: mkt.status,
      src: K.BASE + "/markets/" + encodeURIComponent(mkt.ticker),
      eventSrc: mkt.series_ticker ? K.BASE + "/events?series_ticker=" +
        encodeURIComponent(mkt.series_ticker) : "",
      settlementLinks: []
    };
  }
  function postMessage(msg, toModel) {
    messages.unshift(msg);
    saveMessages();
    renderMessage(msg, "chatAll");
    if (toModel) renderMessage(msg, "chatModel");
    state.alertsSent++;
    statusLine();
    if (msg.type === "resolution") {
      state.resolutions.push({ ticker: msg.ticker, title: msg.title,
        topic: msg.topic, result: msg.result, status: msg.status, ts: msg.ts });
      try { localStorage.setItem("kd_resolutions", JSON.stringify(state.resolutions)); }
      catch (e) { /* */ }
      renderResolutions();
    }
  }
  function linkRow(msg) {
    var html = K.srcLink(msg.src.replace(K.BASE, ""), msg.ticker + " API") + " ";
    if (msg.eventSrc) {
      html += K.srcLink(msg.eventSrc.replace(K.BASE, ""), "event API") + " ";
    }
    (msg.settlementLinks || []).forEach(function (s) {
      html += "<a class='src' href='" + K.esc(s.url) + "' target='_blank' rel='noopener'>" +
        K.esc(s.name || "settlement source") + "</a> ";
    });
    if (msg.type === "swing") {
      html += "<a class='src' href='" + K.esc(msg.news) +
        "' target='_blank' rel='noopener' title='Search news for this market title — an investigation link, not a claim of cause'>investigate cause? (news search — unverified)</a>";
    }
    return html;
  }
  function renderMessage(msg, chatId) {
    var el = $(chatId);
    if (!el) return;
    var html;
    if (msg.type === "resolution") {
      html = "<div class='chatmsg res'>" +
        "<span class='badge " + (msg.result === "yes" ? "up" : "down") + "'>RESOLVED " +
        K.esc(String(msg.result).toUpperCase()) + "</span> " +
        "<span class='mono small'>" + K.timeStr(msg.ts) + "</span> " +
        "<span class='pill'>" + K.esc(msg.topic) + "</span> <strong>" + K.esc(msg.title) +
        "</strong> <span class='mono small muted'>" + K.esc(msg.ticker) + "</span>" +
        "<div class='small muted'>Pays $1 per YES contract if resolved yes — " +
        "<a href='https://docs.kalshi.com/getting_started/market_settlement' target='_blank' rel='noopener'>Market Settlement</a></div>" +
        "<div class='small'>" + linkRow(msg) + "</div></div>";
    } else {
      var arrow = msg.dir === "up" ? "&#9650;" : "&#9660;";
      var cls = msg.dir === "up" ? "up" : "down";
      var modelHtml = "";
      if (msg.modelLiked) {
        modelHtml = "<div class='small'>Model pick — entry " + K.cents(msg.modelEntry) +
          " · potential ROI if right: " + (msg.modelRoi === null ? "—" :
            Math.round(msg.modelRoi * 100) + "%") + " · contracts at entry ask: " +
          K.num(msg.contractsAtAsk, 0) + " · score " +
          (msg.modelScore === null ? "—" : msg.modelScore.toFixed(2)) +
          " <span class='pill warn'>unverified heuristic</span></div>";
      }
      html = "<div class='chatmsg" + (msg.modelLiked ? " liked" : "") + "'>" +
        "<span class='badge " + cls + "'>" + arrow + " " + msg.deltaCents.toFixed(2) + "¢</span> " +
        "<span class='mono small'>" + K.timeStr(msg.ts) + "</span> " +
        "<span class='pill'>" + K.esc(msg.topic) + "</span> <strong>" + K.esc(msg.title) +
        "</strong> <span class='mono small muted'>" + K.esc(msg.ticker) + "</span>" +
        "<div class='small'>" + K.cents(msg.from) + " → <strong>" + K.cents(msg.to) +
        "</strong> · YES bid/ask " + K.cents(msg.yes_bid) + " / " + K.cents(msg.yes_ask) +
        (msg.contractsAtAsk !== null && msg.contractsAtAsk !== undefined ?
          " · contracts at swung-side ask: " + K.num(msg.contractsAtAsk, 0) : "") +
        "</div>" + modelHtml +
        "<div class='small'>" + linkRow(msg) + "</div></div>";
    }
    el.insertAdjacentHTML("afterbegin", html);
    // cap DOM length (localStorage already capped at 200)
    while (el.children.length > 120) el.removeChild(el.lastChild);
  }
  function renderAllMessages() {
    ["chatAll", "chatModel"].forEach(function (id) {
      var el = $(id); if (el) el.innerHTML = "";
    });
    messages.slice().reverse().forEach(function (msg) {
      renderMessage(msg, "chatAll");
      if (msg.type === "resolution" || msg.modelLiked) renderMessage(msg, "chatModel");
    });
  }

  /* ---------- resolutions table (per-row sources) ---------- */
  function renderResolutions() {
    var el = $("resolutionsTable");
    if (!el) return;
    var html = "<table><thead><tr><th>Market</th><th>Topic</th><th>Result</th>" +
      "<th>Status</th><th>Logged at</th><th>Source</th></tr></thead><tbody>";
    if (!state.resolutions.length) {
      html += "<tr><td colspan='6' class='muted'>No resolutions logged yet in this " +
        "browser. Watched markets post their yes/no result here when they settle. " +
        "Seeded rows below come from the collector snapshot instead.</td></tr>";
    }
    state.resolutions.slice().reverse().slice(0, 50).forEach(function (r) {
      html += "<tr><td>" + K.esc(r.title) + "<br><span class='mono small muted'>" +
        K.esc(r.ticker) + "</span></td><td>" + K.esc(r.topic) + "</td>" +
        "<td><span class='pill'>" + K.esc(r.result) + "</span></td><td>" +
        K.esc(r.status) + "</td><td>" + K.timeStr(r.ts) + "</td>" +
        "<td>" + K.srcLink("/markets/" + encodeURIComponent(r.ticker), "market API") +
        "</td></tr>";
    });
    html += "</tbody></table><p class='small muted'>Settlement pays $1 per winning " +
      "contract — <a href='https://docs.kalshi.com/getting_started/market_settlement' " +
      "target='_blank' rel='noopener'>Market Settlement</a>. Collector-seeded rows below " +
      "carry their own captured API URLs.</p>";
    html += seededResolutionsHtml();
    el.innerHTML = html;
  }
  var seededRows = [];
  function seededResolutionsHtml() {
    if (!seededRows.length) return "";
    var html = "<h3>Seeded resolutions (collector snapshot <a href='data/latest/resolutions.json'>resolutions.json</a>)</h3>";
    html += "<table><thead><tr><th>Market</th><th>Topic</th><th>Result</th>" +
      "<th>Settled</th><th>Source</th></tr></thead><tbody>";
    seededRows.slice(0, 40).forEach(function (r) {
      html += "<tr><td>" + K.esc(r.title) + "<br><span class='mono small muted'>" +
        K.esc(r.ticker) + "</span></td><td>" + K.esc(r.topic) + "</td>" +
        "<td><span class='pill'>" + K.esc(r.result) + "</span></td><td>" +
        K.esc(r.settlement_ts || r.close_time || "") + "</td><td>" +
        (r.source_url ? "<a class='src' href='" + K.esc(r.source_url) +
          "' target='_blank' rel='noopener'>captured API URL</a>" :
          "<span class='pill warn'>unverified</span>") + "</td></tr>";
    });
    html += "</tbody></table>";
    return html;
  }
  async function loadSeededResolutions() {
    try {
      var j = await (await fetch("data/latest/resolutions.json")).json();
      seededRows = (j.resolutions || []).filter(function (r) { return r.result; });
    } catch (e) { seededRows = []; }
    renderResolutions();
  }

  /* ---------- event cache: official settlement sources per series ---------- */
  async function attachSettlementSources(msg, series) {
    if (!series || state.eventCache[series]) {
      if (state.eventCache[series]) {
        msg.settlementLinks = state.eventCache[series];
        refreshMessageLinks(msg);
      }
      return;
    }
    state.eventCache[series] = []; // placeholder to avoid duplicate fetches
    try {
      state.requests++;
      var j = await K.apiGet("/events", { series_ticker: series, limit: 200 });
      var links = [];
      (j.events || []).forEach(function (ev) {
        (ev.settlement_sources || []).forEach(function (s) {
          if (s && s.url && !links.find(function (x) { return x.url === s.url; })) {
            links.push({ name: s.name || "settlement source", url: s.url });
          }
        });
      });
      state.eventCache[series] = links;
      msg.settlementLinks = links;
      refreshMessageLinks(msg);
    } catch (e) { /* settlement-source fetch is optional; alert already posted */ }
  }
  function refreshMessageLinks(msg) {
    // update the stored copy so reloads keep the links
    var stored = messages.find(function (x) {
      return x.ts === msg.ts && x.ticker === msg.ticker && x.type === msg.type;
    });
    if (stored) { stored.settlementLinks = msg.settlementLinks; saveMessages(); }
    // re-render topmost matching node (simplest: re-render both chats)
    renderAllMessages();
  }

  /* ---------- polling ---------- */
  function selectValues() {
    return {
      thresholdCents: Number(($("thresholdSel") || {}).value || 10),
      pollSec: Number(($("pollSel") || {}).value || 20),
      watchLimit: Number(($("watchSel") || {}).value || 150),
      depth: Number(($("depthSel") || {}).value || 15)
    };
  }
  async function discover() {
    var st = $("alertStatus");
    if (st) st.textContent = "Discovering series from GET /series …";
    var all = await K.discoverSeries();
    var byTopic = {};
    K.TOPICS.forEach(function (t) { byTopic[t.id] = []; });
    all.forEach(function (s) { if (s.topic) byTopic[s.topic].push(s); });
    state.seriesByTopic = byTopic;
  }
  async function scan() {
    var cfg = selectValues();
    state.polls++;
    var markets = [];
    var topics = Object.keys(state.seriesByTopic);
    for (var i = 0; i < topics.length; i++) {
      var series = state.seriesByTopic[topics[i]].slice(0, cfg.depth || 15);
      for (var j = 0; j < series.length; j++) {
        try {
          state.requests++;
          var page = await K.apiGetAll("/markets",
            { series_ticker: series[j].ticker, status: "open", limit: 200 }, 2);
          page.forEach(function (m) { markets.push(Engine.normalizeMarket(m, topics[i])); });
        } catch (e) { /* one series failing must not kill the scan */ }
      }
    }
    // rank by estimated dollar volume (contracts x last price — labeled estimate)
    markets.forEach(function (m) {
      m.estDollars = Engine.estDollars(
        m.volume !== null ? m.volume : (m.open_interest || 0), m.price);
    });
    markets.sort(function (a, b) { return (b.estDollars || 0) - (a.estDollars || 0); });
    var watched = markets.slice(0, cfg.watchLimit || 150);
    ingest(watched, cfg.thresholdCents);
    state.lastScan = Date.now();
    statusLine();
    renderWatched();
    // resolution sweep every 5th scan: the open-market query above never
    // returns settled rows, so the watch list's series are re-polled with
    // status=settled (the collector's verified per-series sweep pattern).
    if (state.polls % 5 === 0) {
      await settleSweep();
    }
  }

  /* settleSweep — re-poll the series of the current watch list with
   * status=settled and post yes/no resolutions for our markets. Sweep reads the
   * most recent settled markets per series (limit 200); a settled market
   * outside that window is picked up by a later sweep, never inferred. */
  async function settleSweep() {
    var settled = [];
    var seriesList = Object.keys(state.watchedSeries);
    for (var i = 0; i < seriesList.length; i++) {
      try {
        state.requests++;
        var j = await K.apiGet("/markets",
          { series_ticker: seriesList[i], status: "settled", limit: 200 });
        (j.markets || []).forEach(function (m) {
          var n = Engine.normalizeMarket(m, m._topic || "tracked");
          if (state.everWatched[n.ticker]) {
            n.topic = state.everWatched[n.ticker].topic;
            settled.push(n);
          }
        });
      } catch (e) { /* one series failing must not kill the sweep */ }
    }
    settled.forEach(function (m) {
      if (m.result &&
          !state.resolutions.find(function (r) { return r.ticker === m.ticker; })) {
        var res = buildResolutionMessage(m);
        postMessage(res, true); // both chats follow their tracked picks to resolution
        attachSettlementSources(res, m.series_ticker);
        delete state.watched[m.ticker]; // resolved: end the active watch
        statusLine();
        renderWatched();
      }
    });
  }

  /* ingest — pure-ish step separated for tests: given the current poll's
   * snapshots, detect swings, evaluate the model, post messages, track
   * resolutions. */
  function ingest(watched, thresholdCents) {
    var now = Math.floor(Date.now() / 1000);
    watched.forEach(function (m) {
      var prev = state.watched[m.ticker];
      state.everWatched[m.ticker] = m; // remember for the settled sweep
      if (m.series_ticker) state.watchedSeries[m.series_ticker] = true;
      // resolution: settled rows normally arrive via settleSweep (the open
      // query never returns them); this branch covers rows that flip status
      // inside a poll response.
      var isSettled = m.status && m.status !== "active" && m.status !== "open";
      if (prev && isSettled && m.result &&
          !state.resolutions.find(function (r) { return r.ticker === m.ticker; })) {
        var res = buildResolutionMessage(m);
        postMessage(res, true); // both chats follow their tracked picks to resolution
        attachSettlementSources(res, m.series_ticker);
        delete state.watched[m.ticker];
        return;
      }
      var swing = Engine.detectSwing(prev, m, thresholdCents);
      if (swing && !isSettled) {
        var lastAt = state.lastAlertAt[m.ticker] || 0;
        if (now - lastAt >= 15) { // suppress oscillation spam
          var model = Engine.modelLike(m, swing);
          var msg = buildSwingMessage(m, swing, model);
          postMessage(msg, model.liked);
          state.lastAlertAt[m.ticker] = now;
          if (model.liked) { renderModelNote(msg); }
          attachSettlementSources(msg, m.series_ticker);
        }
      }
      state.watched[m.ticker] = m;
      // price samples (chart history) for every watched market, capped
      if (m.price !== null) {
        var arr = state.samples[m.ticker] || (state.samples[m.ticker] = []);
        if (!arr.length || now - arr[arr.length - 1].t >= 5) {
          arr.push({ t: now, price: m.price, bid: m.yes_bid, ask: m.yes_ask });
          if (arr.length > 4000) arr.splice(0, arr.length - 4000);
        }
      }
    });
    renderWatched(); // keeps the watch list in sync on every poll (guarded when headless)
  }
  function renderModelNote(msg) {
    var el = $("modelCount");
    if (el) {
      var n = messages.filter(function (x) { return x.modelLiked; }).length;
      el.textContent = n + " model pick" + (n === 1 ? "" : "s") + " this session";
    }
  }
  function renderWatched() {
    var el = $("watchedTable");
    if (!el) return;
    var rows = Object.values(state.watched).slice(0, 25);
    var html = "<table><thead><tr><th>#</th><th>Topic</th><th>Market</th>" +
      "<th class='num'>Last</th><th class='num'>YES bid/ask</th>" +
      "<th class='num'>Est. $ volume (unverified estimate)</th><th>Status</th><th></th>" +
      "</tr></thead><tbody>";
    rows.forEach(function (m, i) {
      var sel = state.selected === m.ticker;
      html += "<tr" + (sel ? " style='background:#e6f4ec'" : "") + "><td class='num'>" +
        (i + 1) + "</td>" +
        "<td><span class='pill'>" + K.esc(m.topic) + "</span></td>" +
        "<td>" + K.esc(m.title) + "<br><span class='mono small muted'>" +
        K.srcLink("/markets/" + encodeURIComponent(m.ticker), m.ticker) + "</span></td>" +
        "<td class='num'>" + K.cents(m.price) + "</td>" +
        "<td class='num'>" + K.cents(m.yes_bid) + " / " + K.cents(m.yes_ask) + "</td>" +
        "<td class='num'>" + (m.estDollars === null || m.estDollars === undefined ?
          "—" : K.money(m.estDollars)) + "</td>" +
        "<td>" + K.esc(m.status) + "</td>" +
        "<td><button class='btn secondary' data-ticker='" + K.esc(m.ticker) +
        "'>Track</button></td></tr>";
    });
    html += "</tbody></table><p class='muted'>Watch list = top " +
      Object.keys(state.watched).length + " open markets by estimated dollar volume " +
      "(contracts × last price — an <strong>unverified estimate</strong>). Each ticker " +
      "links its exact API URL; <em>Track</em> feeds the chart + orderbook ladder below. " +
      "Source: " +
      "<a href='https://docs.kalshi.com/api-reference/market/get-markets' target='_blank' rel='noopener'>Get Markets</a>.</p>";
    el.innerHTML = html;
    Array.prototype.forEach.call(el.querySelectorAll("button[data-ticker]"),
      function (b) {
        b.addEventListener("click", function () {
          selectMarket(b.getAttribute("data-ticker"));
        });
      });
  }

  /* ---------- alert detail: chart + orderbook ---------- */
  function periodFor(windowSec) { return windowSec > 21600 ? 60 : 1; }
  async function selectMarket(ticker) {
    state.selected = ticker;
    var m = state.watched[ticker];
    if ($("detailTitle")) {
      $("detailTitle").textContent = m ? (m.title + " (" + ticker + ")") : ticker;
    }
    await loadCandles();
    await loadOrderbook();
    drawChart();
  }
  async function loadCandles() {
    var m = state.watched[state.selected];
    var start = Math.floor(Date.now() / 1000) - state.windowSec;
    if (!m || !m.series_ticker) {
      state.candles = (state.samples[state.selected] || [])
        .filter(function (p) { return p.t >= start; });
      return;
    }
    try {
      state.requests++;
      var j = await K.apiGet("/series/" + encodeURIComponent(m.series_ticker) +
        "/markets/" + encodeURIComponent(state.selected) + "/candlesticks",
        { start_ts: start, end_ts: Math.floor(Date.now() / 1000),
          period_interval: periodFor(state.windowSec) });
      var candles = (j.candlesticks || []).map(function (c) {
        var p = c.price || {};
        return { t: c.end_period_ts, price: Number(p.close_dollars),
          bid: c.yes_bid ? Number(c.yes_bid.close_dollars) : null,
          ask: c.yes_ask ? Number(c.yes_ask.close_dollars) : null };
      }).filter(function (p) { return !isNaN(p.price); });
      var byT = {};
      candles.forEach(function (p) { byT[p.t] = p; });
      (state.samples[state.selected] || []).forEach(function (p) {
        if (p.t >= start) byT[p.t] = p;
      });
      state.candles = Object.keys(byT).map(Number)
        .sort(function (a, b) { return a - b; }).map(function (t) { return byT[t]; });
    } catch (e) {
      state.candles = (state.samples[state.selected] || [])
        .filter(function (p) { return p.t >= start; });
    }
  }
  function drawChart() {
    if (!$("priceChart")) return;
    K.drawPriceChart($("priceChart"), state.candles || [],
      { windowLabel: "window: " + windowLabel() });
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
      state.requests++;
      var j = await K.apiGet("/markets/" + encodeURIComponent(state.selected) +
        "/orderbook", {});
      var ob = j.orderbook_fp || j.orderbook || {};
      function levels(arr) {
        return (arr || []).map(function (l) {
          return { price: Number(l[0]), count: Number(l[1]) };
        }).filter(function (l) { return !isNaN(l.price) && !isNaN(l.count); });
      }
      var yes = levels(ob.yes_dollars), no = levels(ob.no_dollars);
      state.orderbook = { yes: yes, no: no };
      if ($("depthChart")) K.drawDepthChart($("depthChart"), yes, no);
      if ($("obTable")) {
        var html = "<table><thead><tr><th>YES price</th><th class='num'>YES contracts</th>" +
          "<th>NO price</th><th class='num'>NO contracts</th></tr></thead><tbody>";
        var n = Math.max(yes.length, no.length);
        if (!n) {
          html += "<tr><td>—</td><td class='num'><span class='pill warn'>unverified</span></td>" +
            "<td>—</td><td class='num'><span class='pill warn'>unverified</span></td></tr>";
        }
        for (var i = n - 1; i >= 0; i--) {
          var y = yes[i], noL = no[i];
          html += "<tr><td>" + (y ? K.cents(y.price) : "—") + "</td><td class='num'>" +
            (y ? K.num(y.count, 0) : "—") + "</td><td>" + (noL ? K.cents(noL.price) : "—") +
            "</td><td class='num'>" + (noL ? K.num(noL.count, 0) : "—") + "</td></tr>";
        }
        html += "</tbody></table><p class='small muted'>Contracts available at each " +
          "price (best bids at the top). Source: " +
          K.srcLink("/markets/" + encodeURIComponent(state.selected) + "/orderbook",
            "orderbook API") + " · " +
          "<a href='https://docs.kalshi.com/getting_started/orderbook_responses' target='_blank' rel='noopener'>Orderbook Responses</a>.</p>";
        $("obTable").innerHTML = html;
      }
    } catch (e) {
      if ($("obTable")) {
        $("obTable").innerHTML = "<p class='muted'>Orderbook fetch failed (" +
          K.esc(e.message || String(e)) + "). Source: " +
          K.srcLink("/markets/" + encodeURIComponent(state.selected) + "/orderbook",
            "orderbook API") + "</p>";
      }
    }
  }

  /* ---------- wiring ---------- */
  function startTimers() {
    state.timers.forEach(clearInterval);
    var cfg = selectValues();
    state.timers = [
      setInterval(function () {
        if (state.running) scan().catch(function (e) {
          banner("error", "<strong>Scan failed:</strong> " + K.esc(e.message || String(e)));
        });
      }, cfg.pollSec * 1000)
    ];
  }
  function setWindow(sec) {
    state.windowSec = sec;
    Array.prototype.forEach.call(document.querySelectorAll("[data-window]"),
      function (b) {
        b.setAttribute("aria-pressed",
          String(Number(b.getAttribute("data-window")) === sec));
      });
    if (state.selected) loadCandles().then(drawChart);
  }
  async function init() {
    if (!$("chatAll")) return;
    renderAllMessages();
    renderResolutions();
    loadSeededResolutions();
    Array.prototype.forEach.call(document.querySelectorAll("[data-window]"),
      function (b) {
        b.addEventListener("click", function () {
          setWindow(Number(b.getAttribute("data-window")));
        });
      });
    if ($("startBtn")) $("startBtn").addEventListener("click", async function () {
      if (!state.running) {
        state.running = true;
        $("startBtn").textContent = "Pause alerts";
        try {
          if (!state.polls) await discover();
          startTimers();
          await scan();
          banner("", "");
        } catch (e) {
          banner("error", "<strong>Could not reach the demo API:</strong> " +
            K.esc(e.message || String(e)) + " — this usually means the browser blocked " +
            "the request. Static snapshots remain on the category pages; see " +
            "<a href='flagged.html'>Flagged for review</a>. Source: " +
            "https://docs.kalshi.com/getting_started/demo_env");
        }
        statusLine();
      } else {
        state.running = false;
        $("startBtn").textContent = "Resume alerts";
        statusLine();
      }
    });
    if ($("clearBtn")) $("clearBtn").addEventListener("click", function () {
      messages = []; saveMessages(); renderAllMessages(); statusLine();
    });
    if ($("clearResBtn")) $("clearResBtn").addEventListener("click", function () {
      state.resolutions = []; localStorage.removeItem("kd_resolutions");
      renderResolutions();
    });
    ["thresholdSel", "pollSel", "watchSel", "depthSel"].forEach(function (id) {
      if ($(id)) $(id).addEventListener("change", startTimers);
    });
    statusLine();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
