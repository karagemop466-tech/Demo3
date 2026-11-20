/* Live price-swing alerts (Kalshi DEMO API, public market data, no credentials).
 *
 * Every POLL_MS the browser requests the official demo market objects for a watchlist
 * taken from the committed snapshot ../data/events.json, and compares each market's
 * last_price_dollars with the previous sample from this page session.
 *   - |move| >= $0.10 (integer-cent arithmetic) -> alert in "All events" feed
 *   - alerts that pass the ROI screen (model.js)  -> "High-ROI screen" feed
 *   - market reaches a yes/no result             -> resolution row, then tracking stops
 * The first sample of each market is a baseline only; it never fires an alert.
 * No prices are invented: if the API cannot be reached, nothing is shown as live.
 *
 * Works in the browser (window.AlertsEngine) and offline in tests (see tests/).
 */
(function (root) {
  "use strict";

  var DEMO_API = "https://external-api.demo.kalshi.co/trade-api/v2";
  var THRESHOLD_CENTS = 10;
  var POLL_MS = 20000;
  var SNAPSHOT_RELOAD_MS = 600000;
  var BATCH = 20;
  var PER_TOPIC = 8;
  var MAX_FEED = 300;
  var TOPICS = [
    ["gas", "Gas prices"], ["elections", "Elections"], ["culture", "Culture"],
    ["crypto", "Crypto"], ["golf", "Golf"]
  ];

  function num(v) {
    if (v === null || v === undefined || v === "") return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }
  // Dollar strings ("0.5600") -> integer cents, so 0.10 vs 0.09 compares exactly.
  function cents(v) {
    var n = num(v);
    return n === null ? null : Math.round(n * 100);
  }
  function marketURL(ticker) { return DEMO_API + "/markets/" + encodeURIComponent(ticker); }
  function newsURL(query) { return "https://www.google.com/search?tbm=nws&q=" + encodeURIComponent(query); }
  function topicLabel(key) {
    for (var i = 0; i < TOPICS.length; i++) if (TOPICS[i][0] === key) return TOPICS[i][1];
    return key;
  }

  // Snapshot -> watchlist: the PER_TOPIC open markets with the largest open interest per topic.
  function buildWatchlist(snapshot) {
    var out = [];
    TOPICS.forEach(function (tp) {
      var events = (snapshot && snapshot.topics && snapshot.topics[tp[0]]) || [];
      var markets = [];
      events.forEach(function (e) {
        (e.markets || []).forEach(function (m) {
          if (!m || !m.ticker) return;
          if (m.status && m.status !== "active" && m.status !== "open") return;
          markets.push({
            ticker: m.ticker,
            event_ticker: e.event_ticker || m.event_ticker || "",
            event_title: e.title || "",
            title: m.title || m.ticker,
            topic: tp[0],
            topic_label: tp[1],
            oi: num(m.open_interest) || 0
          });
        });
      });
      markets.sort(function (a, b) { return b.oi - a.oi; });
      out = out.concat(markets.slice(0, PER_TOPIC));
    });
    return out;
  }

  // Returns null when no alert; otherwise the direction and signed move in integer cents.
  function classifyMove(prevCents, nowCents, thresholdCents) {
    if (prevCents === null || prevCents === undefined || nowCents === null || nowCents === undefined) return null;
    var d = nowCents - prevCents;
    if (Math.abs(d) >= thresholdCents) return { direction: d > 0 ? "up" : "down", delta_cents: d };
    return null;
  }

  // Official market object -> the fields this page uses.
  function parseMarket(m) {
    var bid = cents(m.yes_bid_dollars), ask = cents(m.yes_ask_dollars);
    var result = (m.result === "yes" || m.result === "no") ? m.result : null;
    return {
      ticker: m.ticker,
      title: m.title || m.ticker,
      status: m.status || "",
      result: result,
      lastC: cents(m.last_price_dollars),
      bidC: bid,
      askC: ask,
      spreadC: (bid !== null && ask !== null) ? ask - bid : null,
      oi: num(m.open_interest_fp),
      volume: num(m.volume_fp)
    };
  }

  // Batch request by ticker; any ticker missing from the batch is re-requested singly.
  async function fetchMarkets(tickers, fetchImpl) {
    var found = {}, errors = [], requests = 0;
    async function get(url) {
      requests++;
      var r = await fetchImpl(url, { method: "GET", headers: { Accept: "application/json" }, cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }
    for (var i = 0; i < tickers.length; i += BATCH) {
      var chunk = tickers.slice(i, i + BATCH);
      var missing = [];
      try {
        var j = await get(DEMO_API + "/markets?limit=1000&tickers=" + chunk.map(encodeURIComponent).join(","));
        (j.markets || []).forEach(function (m) { if (m && m.ticker) found[m.ticker] = m; });
        // Batch succeeded: a ticker absent from the reply is reported, not re-requested.
        chunk.forEach(function (t) {
          if (!found[t]) errors.push({ ticker: t, error: "not returned by the batch request (market absent or closed)" });
        });
      } catch (e) {
        errors.push({ ticker: "(batch of " + chunk.length + ")", error: String(e && e.message || e) });
        missing = chunk; // batch itself failed: retry these tickers one by one
      }
      for (var k = 0; k < missing.length; k++) {
        try {
          var s = await get(marketURL(missing[k]));
          if (s && s.market) found[missing[k]] = s.market;
          else errors.push({ ticker: missing[k], error: "no market object in response" });
        } catch (e2) {
          errors.push({ ticker: missing[k], error: String(e2 && e2.message || e2) });
        }
      }
    }
    var rateLimited = errors.some(function (e) { return /HTTP 429/.test(e.error); });
    return { found: found, errors: errors, requests: requests, rateLimited: rateLimited };
  }

  function createEngine(opts) {
    opts = opts || {};
    var fetchImpl = opts.fetch;
    var nowFn = opts.now || function () { return new Date(); };
    var screenFn = opts.screen || (root.AlertModel && root.AlertModel.screen);
    var st = {
      watch: {}, order: [], resolvedSet: {},
      feedAll: [], feedROI: [], alerts: [], resolved: [],
      polls: 0, requests: 0, errorCount: 0, lastPoll: null, lastSnapshot: null,
      lastPollFound: 0, lastPollWatched: 0, lastErrors: []
    };

    function addFeed(list, item) {
      list.push(item);
      if (list.length > MAX_FEED) list.splice(0, list.length - MAX_FEED);
    }

    function setWatchlist(items) {
      items.forEach(function (it) {
        if (st.watch[it.ticker] || st.resolvedSet[it.ticker]) return;
        st.watch[it.ticker] = { meta: it, last: null, status: null, latest: null };
        st.order.push(it.ticker);
      });
    }

    async function loadSnapshot(url) {
      var r = await fetchImpl(url, { cache: "no-store", headers: { Accept: "application/json" } });
      if (!r.ok) throw new Error("snapshot HTTP " + r.status);
      var snap = await r.json();
      st.lastSnapshot = snap.generated_at || null;
      setWatchlist(buildWatchlist(snap));
      return snap;
    }

    async function poll() {
      var ts = nowFn().toISOString();
      var tickers = st.order.filter(function (t) { return !!st.watch[t]; });
      var res = await fetchMarkets(tickers, fetchImpl);
      st.polls++;
      st.requests += res.requests;
      st.errorCount += res.errors.length;
      st.lastPoll = ts;
      st.lastErrors = res.errors;
      st.lastPollWatched = tickers.length;
      st.lastPollFound = 0;

      tickers.forEach(function (t) {
        var w = st.watch[t];
        var m = res.found[t];
        if (!w || !m) return;
        st.lastPollFound++;
        var p = parseMarket(m);
        var meta = w.meta;

        if (w.status !== null && p.status !== w.status) {
          addFeed(st.feedAll, { kind: "system", ts: ts, topic: meta.topic, topic_label: meta.topic_label,
            title: p.title, ticker: t, text: "status " + w.status + " → " + (p.status || "(none)"),
            source_url: marketURL(t) });
        }
        w.status = p.status;
        w.latest = p;

        if (p.result) {
          st.resolvedSet[t] = true;
          var row = { kind: "resolved", ts: ts, topic: meta.topic, topic_label: meta.topic_label,
            title: p.title, ticker: t, event_title: meta.event_title, result: p.result,
            source_url: marketURL(t) };
          st.resolved.push(row);
          addFeed(st.feedAll, row);
          delete st.watch[t];
          return;
        }

        if (p.lastC !== null) {
          var c = classifyMove(w.last, p.lastC, THRESHOLD_CENTS);
          if (c) {
            var alert = {
              kind: "alert", ts: ts, ticker: t, topic: meta.topic, topic_label: meta.topic_label,
              event_ticker: meta.event_ticker, event_title: meta.event_title, title: p.title,
              direction: c.direction, from_cents: w.last, to_cents: p.lastC, delta_cents: c.delta_cents,
              bid_cents: p.bidC, ask_cents: p.askC, spread_cents: p.spreadC,
              open_interest: p.oi, volume: p.volume,
              source_url: marketURL(t), news_url: newsURL(p.title)
            };
            st.alerts.push(alert);
            addFeed(st.feedAll, alert);
            if (screenFn) {
              alert.screen = screenFn(alert);
              if (alert.screen.pass) addFeed(st.feedROI, alert);
            }
          }
          w.last = p.lastC;
        }
      });

      return { ts: ts, watched: tickers.length, found: st.lastPollFound, errors: res.errors.length,
        rateLimited: !!res.rateLimited };
    }

    return { state: st, loadSnapshot: loadSnapshot, poll: poll, setWatchlist: setWatchlist };
  }

  var api = {
    DEMO_API: DEMO_API, THRESHOLD_CENTS: THRESHOLD_CENTS, POLL_MS: POLL_MS,
    SNAPSHOT_RELOAD_MS: SNAPSHOT_RELOAD_MS, PER_TOPIC: PER_TOPIC, BATCH: BATCH, MAX_FEED: MAX_FEED,
    TOPICS: TOPICS, cents: cents, marketURL: marketURL, newsURL: newsURL, topicLabel: topicLabel,
    buildWatchlist: buildWatchlist, classifyMove: classifyMove, parseMarket: parseMarket,
    fetchMarkets: fetchMarkets, createEngine: createEngine
  };
  root.AlertsEngine = api;

  /* ---------------- browser UI (only when the page has the feed containers) ---------------- */
  if (typeof document === "undefined" || !document.getElementById("feed-all")) return;

  var $ = function (id) { return document.getElementById(id); };
  var paused = false;
  var nextAt = Date.now();
  var topicFilter = "all";
  var engine = createEngine({ fetch: root.fetch.bind(root), screen: root.AlertModel && root.AlertModel.screen });
  var SNAP_URL = "../data/events.json";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function link(href, text) {
    var a = el("a", "src", text);
    a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  }
  function fmtTime(iso) { return iso && iso.length >= 19 ? iso.slice(11, 19) : "—"; }
  function money(c) { return c === null || c === undefined ? "—" : "$" + (c / 100).toFixed(2); }
  function signed(c) { return (c > 0 ? "+" : c < 0 ? "−" : "±") + "$" + (Math.abs(c) / 100).toFixed(2); }

  function feedRow(item, roi) {
    var cls = "row " + (item.kind === "alert" ? (item.direction === "up" ? "up" : "down") : item.kind);
    var row = el("div", cls);
    var head = el("div", "row-head");
    head.appendChild(el("span", "time", fmtTime(item.ts)));
    head.appendChild(el("span", "tag", item.topic_label || ""));
    row.appendChild(head);
    if (item.kind === "alert") {
      var arrow = item.direction === "up" ? "▲" : "▼";
      row.appendChild(el("div", "msg", arrow + " " + signed(item.delta_cents) + "  " +
        money(item.from_cents) + " → " + money(item.to_cents) + "  " + item.title));
      var meta = el("div", "meta");
      meta.appendChild(link(item.source_url, "Official market record ↗"));
      meta.appendChild(document.createTextNode("  ·  "));
      meta.appendChild(link(item.news_url, "News search (not a verified cause) ↗"));
      row.appendChild(meta);
      if (roi && item.screen) {
        var g = root.AlertModel.grossPayoutRatio(item.ask_cents);
        row.appendChild(el("div", "screen", "Stand-in screen " + item.screen.passed + "/" + item.screen.total +
          (g !== null ? " · gross payout if YES at ask " + g.toFixed(2) + ":1 (before fees)" : "")));
      }
    } else if (item.kind === "resolved") {
      row.appendChild(el("div", "msg", "RESOLVED " + String(item.result).toUpperCase() + "  " + item.title));
      var rm = el("div", "meta");
      rm.appendChild(link(item.source_url, "Official market record ↗"));
      row.appendChild(rm);
    } else {
      row.appendChild(el("div", "msg muted", item.text + "  " + item.title));
    }
    return row;
  }

  function renderFeed(containerId, list, roi) {
    var box = $(containerId);
    var atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    box.textContent = "";
    var rows = list.filter(function (i) { return topicFilter === "all" || i.topic === topicFilter; });
    if (!rows.length) {
      box.appendChild(el("div", "empty", roi ? "No alert has passed the stand-in screen yet." :
        "No alerts yet. Alerts appear when a market moves $0.10 or more between two polls."));
    }
    rows.forEach(function (r) { box.appendChild(feedRow(r, roi)); });
    if (atBottom) box.scrollTop = box.scrollHeight;
  }

  function renderWatch() {
    var body = $("watch-body");
    body.textContent = "";
    var st = engine.state;
    var any = false;
    st.order.forEach(function (t) {
      var w = st.watch[t];
      if (!w) return;
      any = true;
      var lat = w.latest || {};
      var tr = el("tr");
      function td(text, cls) { var c = el("td", cls, text); tr.appendChild(c); return c; }
      td(w.meta.topic_label);
      td(w.meta.event_title || w.meta.event_ticker);
      td(w.meta.title);
      td(money(lat.lastC), "num");
      td(money(lat.bidC), "num");
      td(money(lat.askC), "num");
      td(lat.spreadC === null || lat.spreadC === undefined ? "—" : money(lat.spreadC), "num");
      td(lat.oi === null || lat.oi === undefined ? "—" : Math.round(lat.oi).toLocaleString("en-US"), "num");
      td(lat.status || "—");
      var srcCell = el("td");
      srcCell.appendChild(link(root.AlertsEngine.marketURL(w.meta.ticker), "API record ↗"));
      tr.appendChild(srcCell);
      body.appendChild(tr);
    });
    if (!any) {
      var tr2 = el("tr"); var c2 = el("td", "empty", "Watchlist is empty or still loading from the snapshot.");
      c2.colSpan = 10; tr2.appendChild(c2); body.appendChild(tr2);
    }
  }

  function renderStatus(extra) {
    var st = engine.state;
    $("s-requests").textContent = st.requests;
    $("s-watch").textContent = st.lastPollWatched + " watched · " + st.lastPollFound + " priced last poll";
    $("s-alerts").textContent = st.alerts.length;
    $("s-roi").textContent = st.feedROI.length;
    $("s-resolved").textContent = st.resolved.length;
    $("s-errors").textContent = st.errorCount;
    $("s-last").textContent = st.lastPoll ? fmtTime(st.lastPoll) + " UTC" : "waiting for first poll";
    var live = $("live-status");
    if (extra) { live.textContent = extra; live.className = "pill bad"; }
    else if (st.polls && st.lastPollFound) { live.textContent = "LIVE · demo API reachable"; live.className = "pill ok"; }
    else if (st.polls) { live.textContent = "Demo API not reachable from this browser — no live prices shown"; live.className = "pill bad"; }
    else { live.textContent = "starting…"; live.className = "pill"; }
    var ef = $("errors-list");
    ef.textContent = "";
    st.lastErrors.slice(0, 5).forEach(function (e) {
      ef.appendChild(el("li", "", e.ticker + ": " + e.error));
    });
  }

  function renderAll(extra) {
    renderFeed("feed-all", engine.state.feedAll, false);
    renderFeed("feed-roi", engine.state.feedROI, true);
    renderWatch();
    renderStatus(extra);
  }

  async function reloadSnapshot() {
    try { await engine.loadSnapshot(SNAP_URL); }
    catch (e) { /* keep the current watchlist; status shows the error on next render */ }
  }

  var inFlight = false;
  async function tick() {
    if (paused || inFlight) return;
    inFlight = true;
    var extra = null;
    var wait = POLL_MS;
    try {
      var r = await engine.poll();
      // 429: back off (3x interval) before the next poll, per the official rate-limit guidance.
      if (r && r.rateLimited) { wait = POLL_MS * 3; extra = "Rate limited (HTTP 429): backing off."; }
    } catch (e) {
      extra = "Poll failed: " + (e && e.message || e);
    }
    inFlight = false;
    renderAll(extra);
    nextAt = Date.now() + wait;
  }

  function startLoops() {
    setInterval(function () {
      var s = Math.max(0, Math.round((nextAt - Date.now()) / 1000));
      $("s-next").textContent = paused ? "paused" : s + " s";
    }, 500);
    setInterval(function () { if (!paused) reloadSnapshot().then(renderAll); }, SNAPSHOT_RELOAD_MS);
    setInterval(function () { if (!paused && Date.now() >= nextAt) tick(); }, 1000);
  }

  function wireControls() {
    $("topic-filter").addEventListener("change", function (e) { topicFilter = e.target.value; renderAll(null); });
    $("pause-btn").addEventListener("click", function (e) {
      paused = !paused;
      e.target.textContent = paused ? "Resume" : "Pause";
      if (!paused) { nextAt = Date.now(); tick(); }
      renderAll(null);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireControls();
    renderAll(null);
    reloadSnapshot().then(function () { renderAll(null); tick(); startLoops(); });
  });
})(typeof window !== "undefined" ? window : globalThis);
