/* Kalshi Demo Tracker — live swing alerting dashboard (alerts.html).
 *
 * Everything here is verifiable by construction:
 *   - data comes from the public Kalshi DEMO REST API documented at docs.kalshi.com;
 *   - every rendered alert keeps the exact request URL of the two observations that
 *     produced the delta, so a reader can re-fetch and confirm the number;
 *   - a swing is a change of >= $0.10 in `last_price_dollars` between two observations;
 *   - nothing is guessed: a missing field renders as a dash plus an "unverified" pill.
 *
 * Endpoints used (all public, no API key):
 *   GET /events?status=open&with_nested_markets=true&series_ticker=…   (discovery)
 *   GET /markets?tickers=…                                            (price polls)
 *   GET /markets/{ticker}/orderbook?depth=25                          (liquidity)
 *   GET /series/{series}/markets/{ticker}/candlesticks?…              (history)
 *   GET /markets?series_ticker=…&status=settled                        (resolutions)
 */
(function () {
  "use strict";

  var BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  var THRESHOLD = 0.10;            // $ per contract, the project's alert rule
  var ROI_MIN = 0.25;              // published high-ROI screen
  var ROI_MIN_SWING = 0.20;        // cushion so a 10c coin-flip is not "high ROI"
  var POLL_MS = 15000;
  // Minimum gap between requests. Unauthenticated requests are separately rate limited
  // (https://docs.kalshi.com/getting_started/rate_limits); the site self-check lowers
  // this to 0 so offline tests do not spend real seconds waiting.
  var MIN_GAP_MS = 250;
  var SAMPLE_KEEP = 900;           // observations kept per contract in memory
  var TOPIC_CAP = 8;               // events per topic (keeps polling inside rate limits)

  // Series seeds were observed on the demo exchange; the API's own tags/categories and
  // the published rules decide the final topic (see portfolio.html / sources.html).
  var SEEDS = {
    gas: ["KXAAAGASW", "KXAAAGASM"],
    elections: ["KXPRESNOMD", "KXHOUSE", "KXSENATE", "KXGOVCA"],
    culture: ["KXRT", "KXSHOWENDSIMPSONS"],
    crypto: ["KXBTCY", "KXBTC", "KXETHY"],
    golf: ["KXPGATOUR", "KXPGARYDER"]
  };
  var TOPIC_LABEL = { gas: "Gas prices", elections: "Elections", culture: "Culture",
                      crypto: "Crypto", golf: "Golf" };
  var TAG_TOPIC = { golf: "golf", crypto: "crypto", elections: "elections",
                    entertainment: "culture" };
  var CATEGORY_TOPIC = { crypto: "crypto", elections: "elections",
                         entertainment: "culture", culture: "culture" };
  var TITLE_RULES = [
    ["gas", /\b(gasoline|gas prices?|price of gas|aaa gas|gallon of gas)\b/i],
    ["golf", /\b(golf|pga|ryder cup|solheim|masters|lpga|open championship|liv golf)\b/i],
    ["crypto", /\b(bitcoin|btc|ethereum|solana|xrp|dogecoin|crypto|stablecoin)\b/i],
    ["elections", /\b(election|electoral|presidential nominee|senate seat|house seat|governorship|mayor of|referendum|parliamentary)\b/i],
    ["culture", /\b(oscar|emmy|grammy|golden globe|best picture|box office|rotten tomatoes|album|film|tv show)\b/i]
  ];

  var state = {
    events: [],            // {topic, event_ticker, title, markets:[{ticker,title,...}], sources, records:[]}
    contracts: {},         // ticker -> contract meta
    samples: {},           // ticker -> [{t, price, url}]
    alerts: [],            // unified alert rows
    seen: {},              // alert id -> true (dedupe across polls)
    orderbooks: {},        // ticker -> {levels, summary, url, at}
    resolutions: [],       // rows from the API
    selected: null,
    rangeSec: 900,
    winSec: 900,
    polling: false,
    paused: false,
    lastPoll: null,
    polls: 0,
    errors: 0,
    timer: null,
    stopped: false
  };

  /* ------------------------------------------------------------------ utils */
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function num(x) {
    if (x === null || x === undefined || x === "" || isNaN(Number(x))) return null;
    return Number(x);
  }
  function cents(x) {
    if (x === null || x === undefined || isNaN(Number(x))) return "—";
    return (Number(x) * 100).toFixed(1) + "¢";
  }
  function dollars(x, d) {
    if (x === null || x === undefined || isNaN(Number(x))) return "—";
    return "$" + Number(x).toLocaleString("en-US", {
      minimumFractionDigits: d === undefined ? 2 : d,
      maximumFractionDigits: d === undefined ? 2 : d
    });
  }
  function clock(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleTimeString("en-GB", { hour12: false });
  }
  function rel(iso) {
    if (!iso) return "";
    var s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (isNaN(s)) return "";
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    if (s < 86400) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  }
  function apiUrl(path, params) {
    var u = BASE + path;
    if (params) {
      var qs = Object.keys(params).filter(function (k) {
        return params[k] !== undefined && params[k] !== null && params[k] !== "";
      }).map(function (k) {
        return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]);
      }).join("&");
      if (qs) u += "?" + qs;
    }
    return u;
  }
  function src(url, label) {
    return "<a class='src' href='" + esc(url) + "' target='_blank' rel='noopener'>" +
      esc(label || "source") + "</a>";
  }
  function unverified(field) {
    return "<span class='pill warn' title='not reported by the API for this row'>" +
      esc(field) + " unverified</span>";
  }
  function banner(msg, kind) {
    var el = $("banner");
    if (!el) return;
    if (!msg) { el.hidden = true; return; }
    el.hidden = false;
    el.className = "banner " + (kind || "info");
    el.innerHTML = msg;
  }

  /* ------------------------------------------------------- rate-limit polite */
  var lastReq = 0, backoff = 0;
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function get(path, params) {
    var url = apiUrl(path, params);
    // Unauthenticated requests are separately limited; back off on 429.
    // https://docs.kalshi.com/getting_started/rate_limits
    var wait = Math.max(0, MIN_GAP_MS - (Date.now() - lastReq)) + backoff;
    if (wait > 0) await sleep(wait);
    lastReq = Date.now();
    var res = await fetch(url, { headers: { Accept: "application/json" } });
    if (res.status === 429) {
      backoff = Math.min(backoff ? backoff * 2 : 2000, 30000);
      throw new Error("429 rate limit — backing off " + backoff + "ms");
    }
    backoff = 0;
    if (!res.ok) throw new Error("HTTP " + res.status + " on " + path);
    return { json: await res.json(), url: url };
  }

  /* --------------------------------------------------------------- discovery */
  function topicFor(seriesTicker, tags, category, title) {
    var i;
    for (i = 0; i < (tags || []).length; i++) {
      var t = TAG_TOPIC[String(tags[i]).toLowerCase()];
      if (t) return { topic: t, rule: "api tag=" + tags[i] };
    }
    var ticker = String(seriesTicker || "").toUpperCase();
    var prefixes = {
      gas: /^(KXGAS|KXAAAGAS|KXAAA|KXNATGAS|KXHEATINGOIL|KXDIESEL|KXPROPANE)(?=[-_.]|$)/,
      golf: /^(KXGOLF|KXPGA|KXLPGA|KXPGATOUR|KXPGARYDER|KXPGASOLHEIM|KXRYDER|KXMASTERS|KXOPEN|KXUSOPEN|KXDPWORLD|KXLIVGOLF|KXTHRC)(?=[-_.]|$)/,
      crypto: /^(KXBTC|KXETH|KXSOL|KXXRP|KXDOGE|KXCRYPTO|KXADA|KXAVAX|KXBNB|KXLTC|KXSHIB|KXUSDC|KXUSDT|KXSTABLECOIN)(?=[-_.]|$)/,
      elections: /^(KXPRES|KXSENATE|KXHOUSE|KXGOV|KXMAYOR|KXPRIMARY|KXELECTION|KXNEXT[A-Z]*PRES|KXNOM|KXPRESNOM|KXPRESPERSON|KXPOLIT|KXPARTISAN|KXKNESS|KXPARL|KXNATOSECGEN|KXECCOMPACT|KXEUEXIT)(?=[-_.]|$)/,
      culture: /^(KXOSCAR|KXEMMY|KXGRAMMY|KXGOLDENGLOBE|KXBAFTA|KXFEATURE|KXBILLBOARD|KXBESTPICTURE|KXMOVIE|KXFILM|KXALBUM|KXSONG|KXCELEB|KXROYAL|KXMETGALA|KXCOACHELLA|KXRT|KXBOXOFFICE|KXSHOW|KXTV|KXSPOTIFY|KXBEYONCE|KXARTIST)(?=[-_.]|$)/
    };
    for (var k in prefixes) {
      if (prefixes[k].test(ticker)) return { topic: k, rule: "series ticker " + seriesTicker };
    }
    var cat = CATEGORY_TOPIC[String(category || "").toLowerCase()];
    if (cat) return { topic: cat, rule: "api category=" + category };
    for (i = 0; i < TITLE_RULES.length; i++) {
      if (TITLE_RULES[i][1].test(title || "")) {
        return { topic: TITLE_RULES[i][0], rule: "title keyword" };
      }
    }
    return null;
  }

  async function discover() {
    var found = [];
    var topics = Object.keys(SEEDS);
    for (var t = 0; t < topics.length; t++) {
      var topic = topics[t], got = 0;
      for (var s = 0; s < SEEDS[topic].length && got < TOPIC_CAP; s++) {
        var series = SEEDS[topic][s];
        var params = { status: "open", series_ticker: series,
                       with_nested_markets: "true", limit: 200 };
        var r;
        try { r = await get("/events", params); } catch (e) { continue; }
        var events = r.json.events || [];
        for (var i = 0; i < events.length && got < TOPIC_CAP; i++) {
          var ev = events[i];
          if (!ev || !(ev.markets || []).length) continue;
          var cls = topicFor(ev.series_ticker || series, ev.tags, ev.category, ev.title);
          if (!cls) continue;
          got++;
          var rec = {
            topic: cls.topic, topic_label: TOPIC_LABEL[cls.topic],
            event_ticker: ev.event_ticker, title: ev.title || ev.event_ticker,
            category: ev.category || "", rule: cls.rule,
            settlement_sources: ev.settlement_sources || [],
            discover_url: r.url,
            markets: (ev.markets || []).map(function (m) {
              return {
                ticker: m.ticker, event_ticker: m.event_ticker,
                title: m.title || ev.title, yes_sub_title: m.yes_sub_title || "",
                series_ticker: ev.series_ticker || series,
                volume: num(m.volume_fp), volume_24h: num(m.volume_24h_fp),
                open_interest: num(m.open_interest_fp),
                close_time: m.close_time, status: m.status
              };
            })
          };
          found.push(rec);
          rec.markets.forEach(function (m) {
            state.contracts[m.ticker] = {
              ticker: m.ticker, title: m.title, yes_sub_title: m.yes_sub_title,
              event_ticker: m.event_ticker, series_ticker: m.series_ticker,
              topic: rec.topic, topic_label: rec.topic_label,
              close_time: m.close_time,
              settlement_sources: rec.settlement_sources,
              event_url: apiUrl("/events", { series_ticker: m.series_ticker,
                                             status: "open" })
            };
            if (!state.samples[m.ticker]) state.samples[m.ticker] = [];
          });
        }
      }
    }
    state.events = found;
    return found;
  }

  /* ------------------------------------------------------ price poll + swing */
  function pushSample(ticker, price, url, at) {
    var arr = state.samples[ticker] || (state.samples[ticker] = []);
    arr.push({ t: at, price: price, url: url });
    if (arr.length > SAMPLE_KEEP) arr.splice(0, arr.length - SAMPLE_KEEP);
    return arr;
  }

  function roiScreen(oldP, newP) {
    var d = newP - oldP;
    var out = { passes: false, side: null, entry: null, roi: null, reason: "" };
    if (Math.abs(d) < ROI_MIN_SWING) {
      out.reason = "swing " + dollars(Math.abs(d)) + " < " + dollars(ROI_MIN_SWING) + " cushion";
      return out;
    }
    out.side = d > 0 ? "no" : "yes";
    var p = out.side === "yes" ? newP : 1 - newP;
    if (p <= 0 || p >= 1) { out.reason = "price not tradable (0 or $1)"; return out; }
    out.entry = p;
    out.roi = (1 - p) / p;
    if (out.roi < ROI_MIN) {
      out.reason = (out.roi * 100).toFixed(0) + "% ROI < " + (ROI_MIN * 100) + "%";
      return out;
    }
    out.passes = true;
    out.reason = "buy " + out.side.toUpperCase() + " at " + dollars(p) + " → " +
      (out.roi * 100).toFixed(0) + "% per $1";
    return out;
  }

  function alertKey(ticker, fromIso, toIso) {
    return ticker + "|" + fromIso + "|" + toIso;
  }

  function addAlert(row) {
    if (state.paused) return;
    if (state.seen[row.key]) return;
    state.seen[row.key] = true;
    state.alerts.push(row);
    if (state.alerts.length > 600) state.alerts.splice(0, state.alerts.length - 600);
    renderFeeds();
    if ($("soundChk") && $("soundChk").checked) beep();
  }

  function beep() {
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      var ctx = new Ctx(), o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880; o.type = "sine"; g.gain.value = 0.05;
      o.connect(g); g.connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + 0.12);
    } catch (e) { /* audio is a nicety, never fatal */ }
  }

  async function pollPrices() {
    var tickers = Object.keys(state.contracts);
    if (!tickers.length) return;
    var at = new Date().toISOString();
    var chunk = 60; // one request per 60 tickers keeps URLs readable
    for (var i = 0; i < tickers.length; i += chunk) {
      var slice = tickers.slice(i, i + chunk);
      var params = { tickers: slice.join(",") };
      var r;
      try { r = await get("/markets", params); }
      catch (e) {
        state.errors++;
        banner("<strong>Poll failed:</strong> " + esc(e.message) +
          " — the demo API may be blocking the browser request (CORS) or rate-limiting. " +
          "The pipeline snapshots on <a href='portfolio.html'>Strategy simulation</a> and " +
          "<a href='data-tracking.html'>Data tracking</a> stay available. " +
          src("https://docs.kalshi.com/getting_started/rate_limits", "rate-limit docs"),
          "error");
        return;
      }
      (r.json.markets || []).forEach(function (m) {
        var ticker = m.ticker;
        var price = num(m.last_price_dollars);
        if (price === null) return; // blank stays blank, never 0
        var marketUrl = apiUrl("/markets", { tickers: ticker });
        var prev = (state.samples[ticker] || []).slice(-1)[0];
        pushSample(ticker, price, marketUrl, at);
        var c = state.contracts[ticker] = state.contracts[ticker] || {
          ticker: ticker, title: m.title, topic: "unclassified",
          topic_label: "Unclassified", yes_sub_title: m.yes_sub_title
        };
        c.price = price;
        c.yes_bid = num(m.yes_bid_dollars);
        c.yes_ask = num(m.yes_ask_dollars);
        c.previous_price = num(m.previous_price_dollars);
        c.volume = num(m.volume_fp);
        c.volume_24h = num(m.volume_24h_fp);
        c.open_interest = num(m.open_interest_fp);
        c.close_time = m.close_time;
        c.at = at;
        c.market_url = marketUrl;
        if (prev && Math.abs(price - prev.price) >= THRESHOLD - 1e-9) {
          addAlert(buildAlert(c, prev, { t: at, price: price, url: marketUrl }));
        }
      });
    }
    state.lastPoll = at;
    state.polls++;
    renderStatus();
    renderMovers();
    if (state.selected) renderChart();
  }

  function buildAlert(c, prev, now) {
    var delta = now.price - prev.price;
    return {
      key: alertKey(c.ticker, prev.t, now.t),
      at: now.t,
      prev_at: prev.t,
      ticker: c.ticker, title: c.title, yes_sub_title: c.yes_sub_title,
      topic: c.topic, topic_label: c.topic_label,
      direction: delta > 0 ? "up" : "down",
      delta: delta,
      old: prev.price, new: now.price,
      prev_url: prev.url, url: now.url,
      volume_24h: c.volume_24h, open_interest: c.open_interest,
      sources: c.settlement_sources || [],
      screen: roiScreen(prev.price, now.price),
      origin: "browser"
    };
  }

  /* ------------------------------------------------------------------ feeds */
  function feedRow(a) {
    var dirCls = a.direction === "up" ? "up" : "down";
    var arrow = a.direction === "up" ? "▲" : "▼";
    var screen = a.screen || {};
    var badge = screen.passes
      ? "<span class='pill roi'>HIGH ROI</span>"
      : "<span class='pill mutedpill' title='" + esc(screen.reason || "") + "'>screen: no</span>";
    var sources = (a.sources || []).filter(function (s) { return s && s.url; })
      .slice(0, 3).map(function (s) {
        return "<a href='" + esc(s.url) + "' target='_blank' rel='noopener'>" +
          esc(s.name || "official source") + "</a>";
      }).join(" · ");
    return "<div class='msg " + dirCls + "' data-ticker='" + esc(a.ticker) + "'>" +
      "<div class='msghead'>" +
        "<span class='ts mono'>" + clock(a.at) + "</span>" +
        "<span class='topic'>" + esc(a.topic_label || a.topic) + "</span>" +
        "<span class='delta " + dirCls + "'>" + arrow + " " +
          dollars(Math.abs(a.delta)) + "</span>" + badge +
      "</div>" +
      "<div class='msgtitle'>" + esc(a.title || a.ticker) +
        (a.yes_sub_title ? " <span class='muted'>— " + esc(a.yes_sub_title) + "</span>" : "") +
      "</div>" +
      "<div class='msgbody'>" +
        "<span class='mono'>" + cents(a.old) + " → " + cents(a.new) + "</span>" +
        " <span class='muted'>(" + rel(a.at) + ", gap " +
          Math.max(1, Math.round((new Date(a.at) - new Date(a.prev_at)) / 1000)) + "s)</span>" +
      "</div>" +
      "<div class='msgfoot'>" +
        (sources ? "official sources: " + sources + " · " : "") +
        "verify: " + src(a.prev_url, "before") + " / " + src(a.url, "after") +
        " · " + src(apiUrl("/series/" + (a.ticker || "").split("-")[0] + "/markets/" +
             a.ticker + "/candlesticks", {}), "candles") +
        (screen.passes ? " · <em>" + esc(screen.reason) + "</em>" : "") +
      "</div></div>";
  }

  function emptyFeed(text) { return "<p class='muted pad'>" + esc(text) + "</p>"; }

  function feedTarget(list) {
    var filtered = list;
    var topic = $("topicFilter") ? $("topicFilter").value : "";
    if (topic) filtered = filtered.filter(function (a) { return a.topic === topic; });
    var winMs = state.winSec * 1000;
    var cutoff = Date.now() - winMs;
    var inWin = filtered.filter(function (a) {
      return new Date(a.at).getTime() >= cutoff;
    });
    return { rows: inWin, total: filtered.length };
  }

  function renderFeed(elId, countId, rows, emptyText) {
    var el = $(elId);
    if (!el) return;
    if (!rows.length) { el.innerHTML = emptyFeed(emptyText); }
    else {
      el.innerHTML = rows.slice().reverse().slice(0, 120).map(feedRow).join("");
    }
    if (countId && $(countId)) $(countId).textContent = rows.length + " in window";
  }

  function renderFeeds() {
    var all = feedTarget(state.alerts);
    var roi = feedTarget(state.alerts.filter(function (a) { return a.screen && a.screen.passes; }));
    renderFeed("bodyAll", "countAll", all.rows,
      "No ≥ $0.10 moves in the selected window yet. The demo book is thin — " +
      "leave the tab open; the feed fills as moves happen.");
    renderFeed("bodyRoi", "countRoi", roi.rows,
      "No high-ROI alerts in this window. Only alerts passing the $0.20 cushion and " +
      "25% ROI screen appear here.");
    renderTopicChats();
    renderNews();
    if ($("statAlerts")) {
      $("statAlerts").textContent = all.rows.length;
    }
  }

  function renderTopicChats() {
    var wrap = $("topicChats");
    if (!wrap) return;
    var topics = Object.keys(TOPIC_LABEL);
    wrap.innerHTML = topics.map(function (t) {
      var rows = feedTarget(state.alerts.filter(function (a) { return a.topic === t; })).rows;
      var body = rows.length
        ? rows.slice().reverse().slice(0, 40).map(function (a) {
            return "<div class='mini-msg " + a.direction + "'>" +
              "<span class='mono'>" + clock(a.at) + "</span> " +
              "<span class='" + a.direction + "'>" + (a.direction === "up" ? "▲" : "▼") +
              " " + dollars(Math.abs(a.delta)) + "</span> " +
              esc(a.title) + " (" + cents(a.old) + "→" + cents(a.new) + ") " +
              src(a.url, "src") + "</div>";
          }).join("")
        : "<p class='muted pad'>No ≥ $0.10 move yet.</p>";
      var count = (state.events.filter(function (e) { return e.topic === t; }) || []).length;
      return "<div class='chat small'><div class='chathead'><strong>" +
        esc(TOPIC_LABEL[t]) + "</strong><span class='small muted'>" + count +
        " events · " + rows.length + " alerts</span></div>" +
        "<div class='chatbody short'>" + body + "</div></div>";
    }).join("");
  }

  function renderNews() {
    var tbody = $("newsTable") ? $("newsTable").querySelector("tbody") : null;
    if (!tbody) return;
    var rows = state.alerts.slice().reverse().slice(0, 40);
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' class='muted'>No alerts yet.</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map(function (a) {
      var links = (a.sources || []).filter(function (s) { return s && s.url; })
        .map(function (s) {
          return "<a class='src' href='" + esc(s.url) + "' target='_blank' rel='noopener'>" +
            esc(s.name || s.url) + "</a>";
        }).join(" ");
      return "<tr><td><span class='mono'>" + clock(a.at) + "</span> " +
        esc(a.title) + " <span class='" + a.direction + "'>" +
        (a.direction === "up" ? "▲" : "▼") + dollars(Math.abs(a.delta)) + "</span></td>" +
        "<td>" + (links || unverified("settlement_sources")) + "</td>" +
        "<td>" + src(a.url, "GET /markets") + "</td></tr>";
    }).join("");
  }

  /* ----------------------------------------------------------------- movers */
  function moversNow() {
    // Largest *consecutive* price change inside the window -- the same definition the
    // feeds use. Comparing first-vs-last would hide a move that partly reverted.
    var cutoff = Date.now() - state.winSec * 1000;
    var out = [];
    Object.keys(state.samples).forEach(function (ticker) {
      var arr = state.samples[ticker].filter(function (s) {
        return new Date(s.t).getTime() >= cutoff;
      });
      if (arr.length < 2) return;
      var best = null;
      for (var i = 1; i < arr.length; i++) {
        var d = arr[i].price - arr[i - 1].price;
        if (!best || Math.abs(d) > Math.abs(best.delta)) {
          best = { delta: d, from: arr[i - 1], to: arr[i] };
        }
      }
      if (!best || Math.abs(best.delta) < THRESHOLD - 1e-9) return;
      var c = state.contracts[ticker] || {};
      out.push({
        ticker: ticker, title: c.title, topic_label: c.topic_label || "—",
        price: best.to.price, delta: best.delta, old: best.from.price,
        volume_24h: c.volume_24h, at: best.to.t, url: best.to.url,
        prev_url: best.from.url,
        direction: best.delta > 0 ? "up" : "down"
      });
    });
    out.sort(function (a, b) { return Math.abs(b.delta) - Math.abs(a.delta); });
    return out;
  }

  function renderMovers() {
    var table = $("moversTable");
    if (!table) return;
    var rows = moversNow();
    if ($("statNow")) $("statNow").textContent = rows.length;
    var tbody = table.querySelector("tbody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='7' class='muted'>No ≥ $0.10 moves in this " +
        state.winSec + "s window yet.</td></tr>";
      return;
    }
    tbody.innerHTML = rows.slice(0, 60).map(function (r) {
      return "<tr><td>" + esc(r.topic_label) + "</td>" +
        "<td><a href='#chart' data-track='" + esc(r.ticker) + "'>" + esc(r.title) +
        "</a></td><td class='mono'>" + cents(r.price) + "</td>" +
        "<td class='" + r.direction + " mono'>" + (r.direction === "up" ? "+" : "−") +
        dollars(Math.abs(r.delta)) + "</td>" +
        "<td class='mono'>" + (r.volume_24h === null ||
          r.volume_24h === undefined ? unverified("volume_24h") :
          r.volume_24h.toLocaleString("en-US")) + "</td>" +
        "<td class='mono'>" + clock(r.at) + "</td>" +
        "<td>" + src(r.prev_url, "before") + " / " + src(r.url, "after") + "</td></tr>";
    }).join("");
  }

  /* ------------------------------------------------------------- chart + book */
  function selectedSamples() {
    var t = state.selected;
    if (!t) return [];
    var cutoff = Date.now() - state.rangeSec * 1000;
    return (state.samples[t] || []).filter(function (s) {
      return new Date(s.t).getTime() >= cutoff;
    });
  }

  function drawChart() {
    var canvas = $("priceChart");
    if (!canvas) return;
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 800, H = 280;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var padL = 56, padR = 14, padT = 16, padB = 30;
    var pw = W - padL - padR, ph = H - padT - padB;
    ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
    if (!state.selected) {
      ctx.fillStyle = "#5b6577";
      ctx.fillText("Select a contract from a feed, the movers table, or the watch list.",
        padL, padT + 24);
      return;
    }
    var pts = selectedSamples();
    if (pts.length < 2) {
      ctx.fillStyle = "#5b6577";
      ctx.fillText("Collecting observations for " + state.selected + " — " + pts.length +
        " point(s) in this range. Keep the tab open.", padL, padT + 24);
      return;
    }
    var t0 = new Date(pts[0].t).getTime(), t1 = new Date(pts[pts.length - 1].t).getTime();
    if (t1 === t0) t1 = t0 + 1000;
    var yMin = 0, yMax = 1; // fixed 0-100c axis keeps movement readable across contracts
    function X(ms) { return padL + (ms - t0) / (t1 - t0) * pw; }
    function Y(v) { return padT + (1 - (v - yMin) / (yMax - yMin)) * ph; }

    // grid + y labels
    ctx.strokeStyle = "#e2e6ee"; ctx.fillStyle = "#5b6577"; ctx.lineWidth = 1;
    for (var i = 0; i <= 4; i++) {
      var v = i / 4, y = Y(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + pw, y); ctx.stroke();
      ctx.fillText(Math.round(v * 100) + "¢", 8, y + 4);
    }
    // x ticks: seconds / minutes / hours labels follow the range
    var span = t1 - t0;
    for (var k = 0; k <= 4; k++) {
      var ms = t0 + span * k / 4;
      var d = new Date(ms), lbl;
      if (state.rangeSec <= 60) {
        lbl = d.toLocaleTimeString("en-GB", { hour12: false }) + "." +
          String(d.getMilliseconds()).padStart(3, "0").slice(0, 1) + "s";
      } else if (state.rangeSec <= 21600) {
        lbl = d.toLocaleTimeString("en-GB", { hour12: false });
      } else {
        lbl = d.toLocaleTimeString("en-GB", { hour12: false }).slice(0, 5) + " " +
          d.getDate() + "/" + (d.getMonth() + 1);
      }
      ctx.fillText(lbl, X(ms) - 20, H - 10);
    }
    // swing bands: mark each pair of observations that produced an alert
    state.alerts.filter(function (a) { return a.ticker === state.selected; })
      .forEach(function (a) {
        var x1 = X(new Date(a.prev_at).getTime()), x2 = X(new Date(a.at).getTime());
        if (x2 < padL || x1 > padL + pw) return;
        ctx.fillStyle = a.direction === "up" ? "rgba(10,122,75,.10)" : "rgba(190,30,45,.10)";
        ctx.fillRect(Math.max(padL, x1), padT, Math.max(2, x2 - x1), ph);
      });
    // bid/ask band
    function lastQuote(key) {
      var c = state.contracts[state.selected] || {};
      return c[key];
    }
    var bid = lastQuote("yes_bid"), ask = lastQuote("yes_ask");
    if (bid !== null && bid !== undefined && ask !== null && ask !== undefined) {
      ctx.fillStyle = "rgba(91,101,119,.08)";
      ctx.fillRect(padL, Y(ask), pw, Math.max(1, Y(bid) - Y(ask)));
    }
    // price line + area
    ctx.beginPath();
    pts.forEach(function (p, idx) {
      var x = X(new Date(p.t).getTime()), y = Y(p.price);
      if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#0a7a4b"; ctx.lineWidth = 2; ctx.stroke();
    ctx.lineTo(X(t1), padT + ph); ctx.lineTo(X(t0), padT + ph); ctx.closePath();
    ctx.fillStyle = "rgba(10,122,75,.08)"; ctx.fill();

    // last point
    var last = pts[pts.length - 1];
    ctx.fillStyle = "#0a7a4b";
    ctx.beginPath(); ctx.arc(X(new Date(last.t).getTime()), Y(last.price), 3.5, 0, 7);
    ctx.fill();
    ctx.fillText(cents(last.price) + " @ " + clock(last.t), padL + 6, padT + 12);
    // threshold guides around the latest price
    [last.price - THRESHOLD, last.price + THRESHOLD].forEach(function (lv) {
      if (lv < 0 || lv > 1) return;
      ctx.strokeStyle = "rgba(190,30,45,.35)"; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(padL, Y(lv)); ctx.lineTo(padL + pw, Y(lv)); ctx.stroke();
      ctx.setLineDash([]);
    });
  }

  function drawDepth() {
    var canvas = $("depthChart");
    if (!canvas) return;
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 800, H = 200;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var padL = 56, padR = 14, padT = 16, padB = 30;
    var pw = W - padL - padR, ph = H - padT - padB;
    ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
    var ob = state.selected ? state.orderbooks[state.selected] : null;
    if (!ob) {
      ctx.fillStyle = "#5b6577";
      ctx.fillText("No recorded orderbook for this contract yet (refreshes with each poll " +
        "of the selected market).", padL, padT + 24);
      var tb = $("depthTable") ? $("depthTable").querySelector("tbody") : null;
      if (tb) tb.innerHTML = "<tr><td colspan='4' class='muted'>No orderbook recorded.</td></tr>";
      return;
    }
    var levels = (ob.yes || []).concat(ob.no || []);
    var maxC = Math.max.apply(null, levels.map(function (l) { return l.contracts; })
      .concat([1]));
    ctx.strokeStyle = "#e2e6ee"; ctx.fillStyle = "#5b6577";
    for (var i = 0; i <= 4; i++) {
      var y = padT + ph * i / 4;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + pw, y); ctx.stroke();
      ctx.fillText(Math.round(maxC * (1 - i / 4)).toLocaleString("en-US"), 8, y + 4);
    }
    for (var k = 0; k <= 4; k++) {
      ctx.fillText((k * 25) + "¢", padL + pw * k / 4 - 8, H - 10);
    }
    function bars(list, color) {
      list.forEach(function (l) {
        var x = padL + l.price * pw;
        var h = (l.contracts / maxC) * ph;
        ctx.fillStyle = color;
        ctx.fillRect(x - 2, padT + ph - h, 4, h);
      });
    }
    bars(ob.yes || [], "rgba(10,122,75,.85)");
    bars(ob.no || [], "rgba(157,184,210,.95)");
    ctx.fillStyle = "#0a7a4b"; ctx.fillText("YES bids", padL + 6, padT + 12);
    ctx.fillStyle = "#5b6577"; ctx.fillText("NO bids (mirror of YES offers)",
      padL + 76, padT + 12);
    // table of levels
    var tbody = $("depthTable") ? $("depthTable").querySelector("tbody") : null;
    if (tbody) {
      var rows = [];
      (ob.yes || []).slice().reverse().forEach(function (l) {
        rows.push("<tr><td>YES bid</td><td class='mono'>" + cents(l.price) +
          "</td><td class='mono'>" + l.contracts.toLocaleString("en-US") +
          "</td><td class='mono'>" + dollars(l.price * l.contracts) + "</td></tr>");
      });
      (ob.no || []).slice().reverse().forEach(function (l) {
        rows.push("<tr><td>NO bid</td><td class='mono'>" + cents(l.price) +
          "</td><td class='mono'>" + l.contracts.toLocaleString("en-US") +
          "</td><td class='mono'>" + dollars(l.price * l.contracts) + "</td></tr>");
      });
      tbody.innerHTML = rows.join("") +
        "<tr><td colspan='4' class='small muted'>Source: " + src(ob.url,
          "GET /markets/" + state.selected + "/orderbook") + " at " + clock(ob.at) +
        " · depth " + (levels.length) + " levels</td></tr>";
    }
    var note = $("depthSummary");
    if (note && ob.summary) {
      note.textContent = "Best YES bid " + cents(ob.summary.best_yes_bid) + " · " +
        "YES contracts " + ob.summary.yes_contracts_total.toLocaleString("en-US") + " · " +
        "NO contracts " + ob.summary.no_contracts_total.toLocaleString("en-US");
    }
  }

  function renderChart() {
    var c = state.contracts[state.selected] || {};
    if ($("chartTitle")) {
      $("chartTitle").textContent = c.title || state.selected;
    }
    if ($("chartMeta")) {
      $("chartMeta").innerHTML = (c.yes_sub_title ? esc(c.yes_sub_title) + " · " : "") +
        "last " + cents(c.price) + " at " + clock(c.at || state.lastPoll) +
        " · topic " + esc(c.topic_label || "—") +
        (c.market_url ? " · " + src(c.market_url, "API record") : "");
    }
    drawChart();
    drawDepth();
  }

  async function loadOrderbook(ticker) {
    if (!ticker) return;
    var params = { depth: 25 };
    var path = "/markets/" + encodeURIComponent(ticker) + "/orderbook";
    try {
      var r = await get(path, params);
      var ob = r.json.orderbook_fp || {};
      var levels = { yes: [], no: [] };
      [["yes", "yes_dollars"], ["no", "no_dollars"]].forEach(function (pair) {
        (ob[pair[1]] || []).forEach(function (lvl) {
          var p = num(lvl[0]), cnt = num(lvl[1]);
          if (p === null || cnt === null) return;
          levels[pair[0]].push({ price: p, contracts: cnt });
        });
        levels[pair[0]].sort(function (a, b) { return a.price - b.price; });
      });
      var yc = levels.yes.reduce(function (a, l) { return a + l.contracts; }, 0);
      var nc = levels.no.reduce(function (a, l) { return a + l.contracts; }, 0);
      var best = levels.yes.length
        ? levels.yes.reduce(function (a, b) { return a.price > b.price ? a : b; }) : null;
      state.orderbooks[ticker] = {
        yes: levels.yes, no: levels.no, at: new Date().toISOString(), url: r.url,
        summary: {
          best_yes_bid: best ? best.price : null,
          best_yes_bid_contracts: best ? best.contracts : null,
          yes_contracts_total: yc, no_contracts_total: nc
        }
      };
      drawDepth();
    } catch (e) {
      /* one failing book must not break the page */
    }
  }

  /* ------------------------------------------------------------ resolutions */
  async function loadResolutions() {
    var tbody = $("resTable") ? $("resTable").querySelector("tbody") : null;
    if (!tbody) return;
    var rows = [];
    var seriesSeen = {};
    state.events.forEach(function (e) {
      e.markets.forEach(function (m) { seriesSeen[m.series_ticker] = e; });
    });
    var series = Object.keys(seriesSeen).slice(0, 8);
    for (var i = 0; i < series.length; i++) {
      var params = { series_ticker: series[i], status: "settled", limit: 200 };
      var r;
      try { r = await get("/markets", params); } catch (e) { continue; }
      (r.json.markets || []).forEach(function (m) {
        var result = String(m.result || "").toLowerCase();
        if (result !== "yes" && result !== "no") return;
        var ev = seriesSeen[series[i]] || {};
        rows.push({
          topic: ev.topic, topic_label: ev.topic_label,
          ticker: m.ticker, title: m.title || (ev.title || m.ticker),
          yes_sub_title: m.yes_sub_title || "",
          result: result,
          settled: m.settlement_ts || "",
          close: m.close_time || "",
          value: num(m.settlement_value_dollars),
          url: apiUrl("/markets", { tickers: m.ticker })
        });
      });
    }
    rows.sort(function (a, b) { return (b.settled || "").localeCompare(a.settled || ""); });
    state.resolutions = rows;
    var topicSel = $("resTopic");
    if (topicSel && topicSel.options.length <= 1) {
      Object.keys(TOPIC_LABEL).forEach(function (t) {
        var o = document.createElement("option");
        o.value = t; o.textContent = TOPIC_LABEL[t]; topicSel.appendChild(o);
      });
    }
    renderResolutions();
  }

  function renderResolutions() {
    var tbody = $("resTable") ? $("resTable").querySelector("tbody") : null;
    if (!tbody) return;
    var t = $("resTopic") ? $("resTopic").value : "";
    var r = $("resResult") ? $("resResult").value : "";
    var rows = state.resolutions.filter(function (x) {
      return (!t || x.topic === t) && (!r || x.result === r);
    });
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='7' class='muted'>No settled markets with a " +
        "yes/no result recorded for the tracked series yet.</td></tr>";
      return;
    }
    tbody.innerHTML = rows.slice(0, 200).map(function (x) {
      return "<tr><td>" + esc(x.topic_label || "—") + "</td>" +
        "<td>" + esc(x.title) + (x.yes_sub_title ? " <span class='muted'>— " +
          esc(x.yes_sub_title) + "</span>" : "") + "</td>" +
        "<td><span class='pill " + (x.result === "yes" ? "yes" : "no") + "'>" +
          x.result.toUpperCase() + "</span></td>" +
        "<td class='mono'>" + clock(x.settled) + "</td>" +
        "<td class='mono'>" + clock(x.close) + "</td>" +
        "<td class='mono'>" + (x.value === null ? unverified("settlement_value") :
          dollars(x.value)) + "</td>" +
        "<td>" + src(x.url, "market") +
        " " + src("https://docs.kalshi.com/getting_started/market_settlement", "rule") +
        "</td></tr>";
    }).join("");
  }

  /* ------------------------------------------------------------- watch list */
  function renderStatus() {
    if ($("statPoll")) {
      $("statPoll").textContent = state.polls ? state.polls + " polls" : "—";
    }
    if ($("statMarkets")) $("statMarkets").textContent = Object.keys(state.contracts).length;
    if ($("livePill")) {
      $("livePill").textContent = state.errors ? "degraded" : "live";
      $("livePill").className = "pill live" + (state.errors ? " warn" : "");
    }
    if ($("statRun")) {
      $("statRun").textContent = state.lastPoll ? rel(state.lastPoll) : "—";
    }
  }

  /* --------------------------------------------- scheduled static snapshots */
  async function loadSnapshots() {
    var base = "data/alerts/";
    async function json(name) {
      try {
        var r = await fetch(base + name, { headers: { Accept: "application/json" } });
        if (!r.ok) return null;
        return await r.json();
      } catch (e) { return null; }
    }
    var results = await Promise.all([
      json("alerts.json"), json("status.json"), json("markets.json"),
      json("resolutions.json"), json("sim_portfolio.json"),
      json("prices.json"), json("orderbooks.json")
    ]);
    var alertData = results[0], status = results[1], markets = results[2];
    var resolutions = results[3], portfolio = results[4];
    var priceHistory = results[5], books = results[6];
    if (priceHistory && priceHistory.markets) {
      Object.keys(priceHistory.markets).forEach(function (ticker) {
        var entry = priceHistory.markets[ticker] || {};
        var c = state.contracts[ticker] || (state.contracts[ticker] = { ticker: ticker,
          topic: entry.topic || "", topic_label: TOPIC_LABEL[entry.topic] || entry.topic || "—" });
        state.samples[ticker] = state.samples[ticker] || [];
        (entry.points || []).forEach(function (point) {
          if (!point || num(point.price) === null || !point.t) return;
          var url = point.source_url;
          if (!url) return; // don't render a history point with no traceable source
          if (!state.samples[ticker].some(function (p) { return p.t === point.t; })) {
            state.samples[ticker].push({ t: point.t, price: Number(point.price), url: url });
          }
        });
        state.samples[ticker].sort(function (a, b) { return a.t.localeCompare(b.t); });
      });
    }
    if (books && books.orderbooks) {
      Object.keys(books.orderbooks).forEach(function (ticker) {
        var b = books.orderbooks[ticker];
        state.orderbooks[ticker] = { yes: b.yes || [], no: b.no || [],
          summary: b.summary || {}, url: b.source_url || "", at: b.observed_at || books.updated_at };
      });
    }
    if (alertData && Array.isArray(alertData.alerts)) {
      alertData.alerts.forEach(function (a) {
        var topic = a.topic || "";
        var row = {
          key: "pipeline|" + (a.alert_id || a.market_ticker + a.observed_at),
          at: a.observed_at, prev_at: a.prev_observed_at,
          ticker: a.market_ticker, title: a.title, yes_sub_title: a.yes_sub_title,
          topic: topic, topic_label: TOPIC_LABEL[topic] || topic,
          direction: a.direction, delta: num(a.delta_dollars),
          old: num(a.old_price), new: num(a.new_price),
          prev_url: a.prev_source_url, url: a.source_url,
          volume_24h: num(a.volume_24h), open_interest: num(a.open_interest),
          sources: a.settlement_sources || [],
          screen: { passes: !!a.high_roi, reason: a.roi_screen && a.roi_screen.reason },
          origin: "pipeline"
        };
        if (row.at && row.url && row.prev_url && !state.seen[row.key]) {
          state.seen[row.key] = true;
          state.alerts.push(row);
        }
      });
      state.alerts.sort(function (a, b) { return String(a.at).localeCompare(String(b.at)); });
      renderFeeds();
    }
    if (status) {
      var warnings = (status.warnings || []).filter(Boolean);
      var latest = status.updated_at ? new Date(status.updated_at).toLocaleString() : "";
      if ($("statRun")) $("statRun").textContent = latest || "snapshot";
      if ($("statMarkets")) $("statMarkets").textContent =
        status.markets_tracked === undefined ? "—" : status.markets_tracked;
      if ($("statPnl") && portfolio) {
        var pnl = portfolio.realised_pnl;
        $("statPnl").textContent = pnl === undefined || pnl === null ? "—" : dollars(pnl);
      }
      if (warnings.length) {
        banner("<strong>Pipeline warnings</strong> (" + esc(latest) + "): " +
          warnings.slice(0, 5).map(esc).join(" · ") +
          " · full machine-readable status: " + src(base + "status.json", "status.json"), "warn");
      }
    }
    if (markets && markets.by_topic) {
      // Pipeline ranking is based only on reported volume x price, with the formula
      // explicitly published in markets.json. Do not synthesize unavailable values.
      var ranked = [];
      Object.keys(markets.by_topic).forEach(function (topic) {
        (markets.by_topic[topic] || []).forEach(function (m) {
          ranked.push({ topic: topic, market: m });
        });
      });
      ranked.sort(function (a, b) {
        var av = num(a.market.est_dollar_volume), bv = num(b.market.est_dollar_volume);
        return (bv === null ? -1 : bv) - (av === null ? -1 : av);
      });
      var tb = $("moversTable") ? $("moversTable").querySelector("tbody") : null;
      if (tb && !moversNow().length && ranked.length) {
        tb.innerHTML = ranked.slice(0, 30).map(function (x) {
          var m = x.market;
          return "<tr><td>" + esc(TOPIC_LABEL[x.topic] || x.topic) + "</td>" +
            "<td><a href='#chart' data-track='" + esc(m.ticker) + "'>" +
              esc(m.title || m.ticker) + "</a></td>" +
            "<td class='mono'>" + cents(num(m.price)) + "</td>" +
            "<td class='muted'>no ≥$0.10 move</td>" +
            "<td class='mono'>" + (num(m.volume_24h) === null ? unverified("volume_24h") :
              num(m.volume_24h).toLocaleString("en-US")) + "</td>" +
            "<td class='mono'>" + esc(m.observed_at || latest || "—") + "</td>" +
            "<td>" + (m.source_url ? src(m.source_url, "API record") : unverified("source_url")) +
            "</td></tr>";
        }).join("");
      }
    }
    if (resolutions && resolutions.by_market) {
      // This dataset is cumulative and outlives open-event discovery.
      var resolutionRows = Array.isArray(resolutions.by_market)
        ? resolutions.by_market : Object.keys(resolutions.by_market).map(function (k) {
            return resolutions.by_market[k];
          });
      resolutionRows.forEach(function (x) {
        if (x.result !== "yes" && x.result !== "no") return;
        if (!state.resolutions.some(function (r) { return r.ticker === x.market_ticker; })) {
          state.resolutions.push({ topic: x.topic, topic_label: TOPIC_LABEL[x.topic] || x.topic,
            ticker: x.market_ticker, title: x.title || x.market_ticker, result: x.result,
            settled: x.settlement_ts || "", close: x.close_time || "",
            value: num(x.settlement_value_dollars), url: x.source_url });
        }
      });
      renderResolutions();
    }
  }

  /* ------------------------------------------------------------------- init */
  async function init() {
    // GitHub Pages is static; scheduled Actions snapshots supplement browser-live polling.
    // Use relative URLs so this also works when the repository is hosted beneath /Demo3/.
    loadSnapshots();
    var topicSel = $("topicFilter");
    if (topicSel) {
      Object.keys(TOPIC_LABEL).forEach(function (t) {
        var o = document.createElement("option");
        o.value = t; o.textContent = TOPIC_LABEL[t]; topicSel.appendChild(o);
      });
    }
    if ($("topicFilter")) $("topicFilter").addEventListener("change", renderFeeds);
    if ($("winSec")) {
      $("winSec").addEventListener("change", function () {
        state.winSec = Number(this.value); renderFeeds(); renderMovers();
      });
    }
    if ($("pauseChk")) {
      $("pauseChk").addEventListener("change", function () { state.paused = this.checked; });
    }
    if ($("refreshBtn")) {
      $("refreshBtn").addEventListener("click", function () { pollOnce(); });
    }
    Array.prototype.forEach.call(document.querySelectorAll("[data-clear]"), function (b) {
      b.addEventListener("click", function () {
        var which = b.getAttribute("data-clear");
        state.alerts = state.alerts.filter(function (a) {
          return which === "roi" ? !(a.screen && a.screen.passes) : false;
        });
        if (which === "roi") state.seen = {}; // allow re-detection later
        renderFeeds();
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-range]"), function (b) {
      b.addEventListener("click", function () {
        state.rangeSec = Number(b.getAttribute("data-range"));
        if ($("chartSec")) $("chartSec").value = String(state.rangeSec);
        Array.prototype.forEach.call(document.querySelectorAll("[data-range]"), function (x) {
          x.setAttribute("aria-pressed", x === b ? "true" : "false");
        });
        drawChart();
      });
    });
    if ($("chartSec")) {
      $("chartSec").addEventListener("change", function () {
        state.rangeSec = Number(this.value);
        Array.prototype.forEach.call(document.querySelectorAll("[data-range]"), function (x) {
          x.setAttribute("aria-pressed",
            Number(x.getAttribute("data-range")) === state.rangeSec ? "true" : "false");
        });
        drawChart();
      });
    }
    document.addEventListener("click", function (ev) {
      var link = ev.target.closest("[data-track]");
      if (!link) return;
      ev.preventDefault();
      selectContract(link.getAttribute("data-track"));
    });
    if ($("bodyAll")) {
      $("bodyAll").addEventListener("click", function (ev) {
        var msg = ev.target.closest(".msg");
        if (msg) selectContract(msg.getAttribute("data-ticker"));
      });
    }
    if ($("resTopic")) $("resTopic").addEventListener("change", renderResolutions);
    if ($("resResult")) $("resResult").addEventListener("change", renderResolutions);

    banner("Polling <span class='mono'>" + BASE +
      "</span> for open events in the five topics…", "info");
    try {
      var found = await discover();
      if (!found.length) {
        banner("The demo API returned no open in-scope events right now. That is a real " +
          "result, not an error (the demo exchange is a test environment with mock funds). " +
          "Retrying on the next poll cycle.", "warn");
      } else {
        banner("Tracking <strong>" + found.length + "</strong> open events · " +
          Object.keys(state.contracts).length + " contracts across " +
          Object.keys(TOPIC_LABEL).length + " topics. First observation recorded; " +
          "≥ $0.10 moves appear in the feeds as they happen.", "info");
      }
    } catch (e) {
      banner("<strong>Discovery failed:</strong> " + esc(e.message) +
        ". This is almost always browser CORS or a network block — the read-only " +
        "snapshots remain on <a href='portfolio.html'>Strategy simulation</a> and " +
        "<a href='data-tracking.html'>Data tracking</a>. " +
        src("https://docs.kalshi.com/getting_started/rate_limits", "rate limits"), "error");
    }
    if (state.stopped) return;
    await pollOnce();
    if (state.stopped) return;
    loadResolutions();
    state.timer = setInterval(pollOnce, POLL_MS);
    state.uiTimer = setInterval(function () { renderFeeds(); renderMovers(); }, 5000);
  }

  async function pollOnce() {
    if (state.polling) return;
    state.polling = true;
    try {
      await pollPrices();
      if (state.selected) await loadOrderbook(state.selected);
    } finally {
      state.polling = false;
    }
  }

  function selectContract(ticker) {
    state.selected = ticker;
    renderChart();
    loadOrderbook(ticker).then(drawDepth);
  }

  function stop() {
    if (state.timer) clearInterval(state.timer);
    if (state.uiTimer) clearInterval(state.uiTimer);
    state.timer = null; state.uiTimer = null;
    state.stopped = true;
  }

  window.KalshiAlerts = {
    // exposed for the site self-check and for readers who want to inspect state
    state: state, THRESHOLD: THRESHOLD, roiScreen: roiScreen, topicFor: topicFor,
    apiUrl: apiUrl, pollPrices: pollPrices, moversNow: moversNow,
    start: init, stop: stop, discover: discover,
    setMinGap: function (ms) { MIN_GAP_MS = Math.max(0, Number(ms) || 0); }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
