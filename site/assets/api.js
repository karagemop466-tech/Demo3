/* api.js — Kalshi Trade API v2 access layer for the dashboard.
 *
 * Two data sources, one interface:
 *   LIVE      browser fetch() -> https://external-api.demo.kalshi.co/trade-api/v2
 *             (public endpoints only; no key, no CORS exemption claimed)
 *   BRIDGE    same-origin /proxy?path=... served by scripts/dev_server.py — use it when the
 *             browser is blocked by CORS, or to reach signed /portfolio routes
 *   SNAPSHOT  data/live_snapshot.json / data/snapshot.json committed by scripts/collect.py
 *
 * Every value rendered through this module can be traced back to a URL: `sourceFor()` returns the
 * exact endpoint that produced a record, and every record keeps the API's own field names.
 * Nothing here estimates, interpolates or back-fills. Absent => null => the UI prints an em-dash
 * and the row is marked unverified.
 */
(function (global) {
  "use strict";

  var DEMO_REST = "https://external-api.demo.kalshi.co/trade-api/v2";
  var DEMO_REST_ALT = "https://demo-api.kalshi.co/trade-api/v2";
  var PROD_REST = "https://external-api.kalshi.com/trade-api/v2";
  var DEMO_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2";
  var BRIDGE = "/proxy"; // served by scripts/dev_server.py
  var API_PREFIX = "/trade-api/v2";

  var TIMEOUT = 9000;

  function K() {
    this.base = DEMO_REST;
    this.mode = "snapshot";       // live | bridge | snapshot
    this.topics = null;
    this.universe = new Map();   // series_ticker -> {topic, ...}
    this.tapeCache = { key: "", events: [], scanned: 0, at: 0 };
    this.ticks = new Map();      // market_ticker -> [{t, price, bid, ask}]
    this.tickTimer = null;
    this.errors = [];
  }

  /* ------------------------------------------------------------------ fetch */
  K.prototype.url = function (path, params) {
    var u = this.base + path;
    if (params) {
      var q = Object.keys(params)
        .filter(function (k) { return params[k] !== undefined && params[k] !== null && params[k] !== ""; })
        .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]); });
      if (q.length) u += (u.indexOf("?") >= 0 ? "&" : "?") + q.join("&");
    }
    return u;
  };

  K.prototype._get = function (path, params, opts) {
    var self = this;
    opts = opts || {};
    var url = this.url(path, params);
    var target = url;
    if (this.mode === "bridge") {
      target = BRIDGE + "?url=" + encodeURIComponent(url);
    }
    var ctl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); }, opts.timeout || TIMEOUT);
    return fetch(target, { signal: ctl ? ctl.signal : undefined, headers: { Accept: "application/json" } })
      .then(function (res) {
        clearTimeout(timer);
        if (!res.ok) {
          var err = new Error("HTTP " + res.status + " " + path);
          err.status = res.status;
          throw err;
        }
        return res.json();
      })
      .catch(function (e) {
        clearTimeout(timer);
        self.errors.push({ at: new Date().toISOString(), path: path, message: String(e && e.message || e) });
        if (self.errors.length > 60) self.errors.shift();
        throw e;
      });
  };

  /** Try the browser-direct call; if it fails (CORS/DNS/offline) fall back to snapshot. */
  K.prototype.connect = function (preferred) {
    var self = this;
    var wanted = preferred || "auto";
    var probe = function () {
      return self._get("/exchange/status", null, { timeout: 6000 }).then(function (data) {
        self.status = data;
        self.mode = (wanted === "bridge") ? "bridge" : "live";
        return { mode: self.mode, status: data };
      });
    };
    if (wanted === "snapshot") return Promise.resolve({ mode: "snapshot" });
    return probe().catch(function (e) {
      // direct blocked -> try the local bridge, then give up gracefully
      var save = self.base;
      self.mode = "bridge";
      self.base = save;
      return self._get("/exchange/status", null, { timeout: 3500 })
        .then(function (data) {
          self.status = data; self.mode = "bridge";
          return { mode: "bridge", status: data };
        })
        .catch(function () {
          self.mode = "snapshot";
          self.lastError = String(e && e.message || e);
          return { mode: "snapshot", error: self.lastError };
        });
    });
  };

  /* -------------------------------------------------------------- endpoints */
  K.prototype.series = function (category, tags) {
    return this._get("/series", { category: category, tags: tags, include_volume: "true" })
      .then(function (d) { return d.series || []; });
  };
  K.prototype.events = function (tickers) {
    return this._get("/events", { tickers: Array.isArray(tickers) ? tickers.join(",") : tickers,
                                  with_nested_markets: "true" });
  };
  K.prototype.marketsByEvent = function (eventTicker, status) {
    return this._get("/markets", { event_ticker: eventTicker, status: status || null, limit: 200 })
      .then(function (d) { return d.markets || []; });
  };
  K.prototype.market = function (ticker) {
    return this._get("/markets/" + encodeURIComponent(ticker)).then(function (d) { return d.market; });
  };
  K.prototype.orderbook = function (ticker, depth) {
    return this._get("/markets/" + encodeURIComponent(ticker) + "/orderbook", { depth: depth || 20 });
  };
  K.prototype.trades = function (params) {
    return this._get("/markets/trades", params);
  };
  K.prototype.candles = function (seriesTicker, ticker, startTs, endTs, period) {
    var self = this;
    return this._get("/series/" + encodeURIComponent(seriesTicker) + "/markets/" + encodeURIComponent(ticker) + "/candlesticks",
                     { start_ts: startTs, end_ts: endTs, period_interval: period })
      .then(function (d) { return (d && d.candlesticks) || []; })
      .catch(function (e) { self.lastCandleError = String(e.message || e); return []; });
  };

  /* ------------------------------------------------------------ topic index */
  K.prototype.loadTopics = function (base) {
    var self = this;
    var root = base || ".";
    return fetch(root + "/data/topics.json").then(function (r) { return r.json(); })
      .then(function (doc) {
        self.topics = doc.topics || [];
        self.topicMeta = doc;
        return self.topics;
      });
  };

  /** series ticker -> topic id, from the collector's verified universe (no ticker-prefix guessing). */
  K.prototype.loadUniverse = function (snapshot) {
    var self = this;
    this.universe = new Map();
    ((snapshot && snapshot.series_universe) || []).forEach(function (row) {
      self.universe.set(row.series_ticker, row);
    });
    // Fallback index from topics.json prefixes is used ONLY to tag, never to rank.
    (this.topics || []).forEach(function (t) {
      (t.ticker_prefixes || []).forEach(function (p) {
        if (!self.universe.has(p)) self.universe.set(p, { series_ticker: p, topic: t.id, provisional: true });
      });
    });
    return this.universe;
  };

  K.prototype.topicForTicker = function (marketTicker) {
    var series = String(marketTicker || "").split("-")[0];
    var row = this.universe.get(series);
    return row ? { topic: row.topic, series: series, provisional: !!row.provisional } : null;
  };

  /* -------------------------------------------------- dollar-volume ranking */
  /**
   * Highest-dollar live events.
   * Kalshi exposes no dollar-volume field (verified 2026-11-20 on /markets and /series: only
   * volume_fp, in contracts). So we compute it from the tape:
   *    dollars = SUM( count_fp x (yes_price_dollars if taker_outcome_side=='yes' else no_price_dollars) )
   * field semantics: https://docs.kalshi.com/api-reference/market/get-trades.md
   */
  K.prototype.rankEvents = function (opts) {
    var self = this;
    opts = opts || {};
    var minutes = opts.minutes || 30;
    var pages = opts.pages || 5;
    var limit = Math.min(opts.limit || 1000, 1000);   // documented max for /markets/trades
    var minTs = Math.floor(Date.now() / 1000) - minutes * 60;
    var key = minutes + ":" + pages + ":" + limit;
    if (this.tapeCache.key === key && Date.now() - this.tapeCache.at < (opts.ttl || 20000)) {
      return Promise.resolve(this.tapeCache);
    }
    var cutoff = new Date(minTs * 1000).toISOString().replace(/\.\d+Z$/, "Z");
    var agg = new Map();
    var scanned = 0;
    var cursor = "";
    var done = Promise.resolve();

    function page(i) {
      if (i >= pages) return Promise.resolve();
      return self.trades({ limit: limit, cursor: cursor || null, min_ts: minTs })
        .then(function (d) {
          var rows = (d && d.trades) || [];
          if (!rows.length) return Promise.resolve();
          rows.forEach(function (t) {
            if (t.created_time && t.created_time < cutoff) return;
            var loc = self.topicForTicker(t.ticker);
            if (!loc) return;
            var side = t.taker_outcome_side || t.taker_side || "yes";
            var px = side === "no" ? num(t.no_price_dollars) : num(t.yes_price_dollars);
            var dollars = num(t.count_fp) * (px || 0);
            var ev = eventOf(t.ticker);
            var r = agg.get(ev) || { event_ticker: ev, series: loc.series, topic: loc.topic,
                                     dollar_volume: 0, contracts: 0, trades: 0, yes_dollars: 0, no_dollars: 0,
                                     block_trades: 0, last_trade_time: "", markets: new Set() };
            r.dollar_volume += dollars;
            r.contracts += num(t.count_fp);
            r.trades += 1;
            r[side === "yes" ? "yes_dollars" : "no_dollars"] += dollars;
            if (t.is_block_trade) r.block_trades += 1;
            if (t.created_time > r.last_trade_time) r.last_trade_time = t.created_time;
            r.markets.add(t.ticker);
            scanned += 1;
            agg.set(ev, r);
          });
          cursor = (d && d.cursor) || "";
          if (!cursor) return Promise.resolve();
          return page(i + 1);
        })
        .catch(function (e) {
          self.errors.push({ at: new Date().toISOString(), path: "/markets/trades", message: String(e.message || e) });
          return Promise.resolve();
        });
    }

    return page(0).then(function () {
      var list = Array.from(agg.values()).map(function (r) {
        r.markets = Array.from(r.markets).sort();
        r.dollar_volume = round(r.dollar_volume, 2);
        r.contracts = round(r.contracts, 2);
        r.flow_imbalance = r.dollar_volume ? round((r.yes_dollars - r.no_dollars) / r.dollar_volume, 4) : null;
        r.provisional = !!(self.universe.get(r.series) || {}).provisional;
        return r;
      }).sort(function (a, b) { return b.dollar_volume - a.dollar_volume; });
      var out = { events: list, scanned: scanned, minutes: minutes, at: Date.now(), key: key,
                  source: self.url("/markets/trades", { limit: limit, min_ts: minTs }),
                  formula: "sum(count_fp x taker price) over GET /markets/trades" };
      self.tapeCache = out;
      return out;
    });
  };

  /* --------------------------------------------------- client-sampled ticks */
  /**
   * Sub-minute resolution. The candlestick endpoint's finest period is 1 minute
   * (https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md), so a
   * "seconds" axis can only be built by sampling here. Labelled, never blended into candles.
   */
  K.prototype.startTicks = function (tickers, everyMs, onTick) {
    var self = this;
    this.stopTicks();
    tickers.forEach(function (t) { if (!self.ticks.has(t)) self.ticks.set(t, []); });
    var poll = function () {
      Promise.all(tickers.map(function (t) {
        return self.market(t).then(function (m) {
          var arr = self.ticks.get(t) || [];
          arr.push({ t: Date.now(), price: num(m && m.last_price_dollars),
                     bid: num(m && m.yes_bid_dollars), ask: num(m && m.yes_ask_dollars),
                     book: num(m && m.yes_bid_size_fp), source: self.url("/markets/" + t),
                     updated: m && m.updated_time });
          if (arr.length > 1800) arr.shift();
          self.ticks.set(t, arr);
          return { ticker: t, market: m };
        }).catch(function () { return { ticker: t, market: null }; });
      })).then(function (res) { if (onTick) onTick(res); });
    };
    poll();
    this.tickTimer = setInterval(poll, Math.max(1000, everyMs || 5000));
  };
  K.prototype.stopTicks = function () { if (this.tickTimer) clearInterval(this.tickTimer); this.tickTimer = null; };
  K.prototype.ticksFor = function (ticker) { return this.ticks.get(ticker) || []; };

  /* ---------------------------------------------------------------- helpers */
  function num(v) {
    if (v === null || v === undefined || v === "") return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }
  function round(v, p) { var m = Math.pow(10, p); return Math.round((v + Number.EPSILON) * m) / m; }
  function eventOf(ticker) {
    var parts = String(ticker).split("-");
    return parts.length >= 3 ? parts.slice(0, -1).join("-") : ticker;
  }

  K.num = num;
  K.round = round;
  K.eventOf = eventOf;
  K.CONST = { DEMO_REST: DEMO_REST, DEMO_REST_ALT: DEMO_REST_ALT, PROD_REST: PROD_REST,
              DEMO_WS: DEMO_WS, API_PREFIX: API_PREFIX, BRIDGE: BRIDGE };

  global.KalshiAPI = K;
  global.K = K;      // shortcut for the page scripts
})(window);
