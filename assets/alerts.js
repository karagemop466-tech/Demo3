/* Kalshi Demo Tracker — price-swing alert chats (integrated engine, session f428c4bd).
 *
 * Detects live contract price swings >= $0.10 (10 cents) in either direction and
 * publishes them to two scrolling chats rendered side by side ("Split" default):
 *   - "All events": every swing alert + yes/no resolution notices
 *   - "High ROI model": the selective filter (see roiSignal below)
 *
 * Integration contract preserved from the engine merged by session 6ebc1cb7 (PR #28):
 * window.KD namespace, onSample/onMarkets sinks (called from assets/dashboard.js),
 * row ids alertsAll/alertsROI/chatAll/chatROI/tabAll/tabROI/alertsEnabled/
 * clearAlertsBtn/alertCount, localStorage key kd_alerts_v1, alert row shape
 * {id, ts, ticker, title, topic, series, oldPrice, newPrice, change, dir, api,
 *  roiSignal}, and the KalshiTrade.onSwingAlert automation entry point
 * (paper/SIMULATED automation in assets/trade.js).
 *
 * Added by this integration (brief items the earlier engine did not cover):
 *   1. book-aware tracked price: YES bid/ask mid when a two-sided book exists,
 *      otherwise last trade (demo markets trade rarely; last-only misses book moves);
 *   2. a 10 s batch poll (GET /markets?tickers=…, comma-separated, official single-
 *      response behavior for that filter) layered on the 20 s dashboard scan;
 *   3. lookback-baseline detection + cooldown (one alert per ticker+direction per
 *      5-minute bucket) to stop duplicate chat spam;
 *   4. resolution notices (status closed/determined/finalized + result yes/no);
 *   5. chart jump annotations: KD.annotationsFor(ticker) consumed by drawChart in
 *      assets/dashboard.js (markers via K.drawPriceChart opts.annotations) and a
 *      per-market jump list in #chartAnnotations;
 *   6. per-alert links: exact API row + same-event query + a GENERATED news-search
 *      link (labelled unverified; causation is never asserted — the API has no
 *      attribution field);
 *   7. HR-1..HR-4 tradability screen combined with the relative-move rule for the
 *      high-ROI feed. Heuristic — not validated alpha (see Methodology §6).
 *
 * Field/parameter facts verified 2026-11-20 against
 *   https://docs.kalshi.com/api-reference/market/get-markets.md (tickers, event_ticker,
 *   last_price_dollars, yes_bid_dollars, yes_ask_dollars, volume_fp, status/result
 *   enums, and the official note that responses are cached and "can lag the exchange
 *   by several seconds"), https://docs.kalshi.com/api-reference/market/get-market.md,
 *   https://docs.kalshi.com/getting_started/market_settlement (settlement semantics).
 * WebSocket push would need signed handshake headers browsers cannot attach (I-13),
 * so this layer polls public, key-less endpoints only. No values are invented.
 */
(function () {
  "use strict";

  var KD = window.KD = window.KD || {};
  var BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  var ALERT_KEY = "kd_alerts_v1";
  var RESOLVED_KEY = "kd_alerts_resolved_v1";
  var SWING = 0.10;          /* $0.10 threshold, fixed by the brief */
  var MAX_ALERTS = 300;
  var COOLDOWN = 300;        /* s: one alert per ticker+direction per bucket */
  var POLL_MS = 10000;       /* dedicated batch poll cadence */
  var BATCH = 50;            /* tickers per request (URL-length safety) */
  var WATCH_MAX = 80;        /* markets tracked between scans */
  var LOOKBACK = 150;        /* s: baseline window */
  var MINAGE = 20;           /* s: baseline minimum age */
  var HIST_MAX = 240;        /* samples per ticker */

  var state = {
    alerts: [],                  /* swings, newest first (same key/shape as before) */
    notices: [],                 /* resolution notices, newest first */
    track: {},                   /* ticker -> {price, ts} (was lastPrice) */
    hist: {},                    /* ticker -> [{t, px}] for the lookback baseline */
    seeded: [],                  /* market rows from the latest dashboard scan */
    byTicker: {},                /* ticker -> latest known row-ish object */
    cooldown: {},                /* ticker:dir:bucket -> 1 */
    resolvedSeen: {},          /* ticker -> result:status (dedupe notices) */
    visible: "split",            /* "split" | "all" | "roi" */
    enabled: true,
    selected: null,
    errors: 0,
    lastPoll: null,
    dirty: true
  };
  try { state.alerts = JSON.parse(localStorage.getItem(ALERT_KEY) || "[]"); }
  catch (e) { state.alerts = []; }
  try { state.resolvedSeen = JSON.parse(localStorage.getItem(RESOLVED_KEY) || "{}"); }
  catch (e) { state.resolvedSeen = {}; }
  if (!Array.isArray(state.alerts)) state.alerts = [];

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function cents(x) {
    if (x === null || x === undefined || x === "" || isNaN(Number(x))) return "—";
    return (Number(x) * 100).toFixed(2) + "\u00a2";
  }
  function fmtTs(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    return d.toLocaleTimeString("en-GB");
  }
  /* Market rows live at GET /markets/{ticker} (Get Market). The previous engine
   * linked "/series/{s}/markets/{t}" here, which is not a documented market-row
   * endpoint (only …/candlesticks exists under /series) — corrected here. */
  function apiUrl(ticker) {
    return BASE + "/markets/" + encodeURIComponent(ticker);
  }
  function num(x) {
    if (x === null || x === undefined || x === "") return null;
    var v = Number(x);
    return isFinite(v) ? v : null;
  }
  function book(row, sample) {
    /* normalized {bid, ask, last, vol} from either a dashboard marketRow
     * (yb/ya/last/vol numbers) or an API market row (*_dollars strings) */
    if (sample) {
      return { bid: num(sample.bid), ask: num(sample.ask),
        last: num(sample.price), vol: row && row.vol !== undefined ? num(row.vol) : null };
    }
    return {
      bid: num(row.yes_bid_dollars !== undefined ? row.yes_bid_dollars : row.yb),
      ask: num(row.yes_ask_dollars !== undefined ? row.yes_ask_dollars : row.ya),
      last: num(row.last_price_dollars !== undefined ? row.last_price_dollars : row.last),
      vol: num(row.volume_fp !== undefined ? row.volume_fp : row.vol)
    };
  }
  function tracked(b) {
    if (b.bid !== null && b.ask !== null && b.bid > 0 && b.ask > b.bid) {
      return (b.bid + b.ask) / 2;
    }
    return b.last;
  }

  /* ---------- high-ROI screen (heuristic — NOT validated alpha) ----------
   * Relative rule from the merged 6ebc1cb7 engine: swing >= $0.10 AND >= 10% of
   * the prior price. Tradability screen added by this integration:
   *   HR-1 two-sided book exists (bid>0 and ask>0)
   *   HR-1b ask > bid (a valid quote, not a stale single side)
   *   HR-2 quoted spread <= $0.10
   *   HR-3 at least one trade (volume_fp >= 1)
   *   HR-4 post-move price inside [0.02, 0.98] (event not already decided)
   * A swing is a "pick" only if the relative rule AND all HR rules pass. */
  function roiCheck(b, px, change, prior) {
    var rel = Math.abs(change) >= SWING && (prior ? Math.abs(change) / prior >= 0.10 : false);
    var checks = [
      { id: "rel", pass: rel },
      { id: "HR-1", pass: b.bid !== null && b.ask !== null && b.bid > 0 && b.ask > 0 },
      { id: "HR-1b", pass: b.bid !== null && b.ask !== null && b.ask > b.bid },
      { id: "HR-2", pass: b.bid !== null && b.ask !== null && (b.ask - b.bid) <= SWING },
      { id: "HR-3", pass: b.vol !== null && b.vol >= 1 },
      { id: "HR-4", pass: px !== null && px >= 0.02 && px <= 0.98 }
    ];
    return { roi: checks.every(function (c) { return c.pass; }), checks: checks, rel: rel };
  }

  /* ---------- swing detection ---------- */
  function observe(ticker, ctx) {
    /* ctx: {t, px, bid, ask, vol, title, topic, series, event} */
    var prev = state.track[ticker];
    var hist = state.hist[ticker] || (state.hist[ticker] = []);
    if (!prev || prev.price !== ctx.px) {
      hist.push({ t: ctx.t, px: ctx.px });
      if (hist.length > HIST_MAX) hist.splice(0, hist.length - HIST_MAX);
    }
    state.track[ticker] = { price: ctx.px, ts: ctx.t };
    state.byTicker[ticker] = Object.assign(state.byTicker[ticker] || {}, ctx);
    if (!state.enabled || ctx.px === null) return;
    if (prev && prev.price !== null && Math.abs(ctx.px - prev.price) >= SWING) {
      fire(ticker, ctx, prev.price, ctx.t);
    }
    var base = null;
    for (var b = 0; b < hist.length - 1; b++) {
      var age = ctx.t - hist[b].t;
      if (age <= LOOKBACK && age >= MINAGE) { base = hist[b]; break; }
    }
    if (base && base.px !== null && Math.abs(ctx.px - base.px) >= SWING) {
      fire(ticker, ctx, base.px, ctx.t);
    }
  }
  function fire(ticker, ctx, basePx, t) {
    var change = ctx.px - basePx;
    var dir = change > 0 ? "up" : change < 0 ? "down" : "flat";
    var key = ticker + ":" + dir + ":" + Math.floor(t / COOLDOWN);
    if (state.cooldown[key]) return;
    state.cooldown[key] = 1;
    var rc = roiCheck({ bid: ctx.bid, ask: ctx.ask, vol: ctx.vol }, ctx.px, change, basePx);
    var alert = {
      id: "a" + t + Math.random().toString(36).slice(2, 6),
      ts: t, ticker: ticker,
      title: ctx.title || ticker,
      topic: ctx.topic || "",
      series: ctx.series || "",
      event: ctx.event || "",
      rules: ctx.rules || "",
      oldPrice: basePx, newPrice: ctx.px, change: change, dir: dir,
      api: apiUrl(ticker),
      roiSignal: rc.roi, rel: rc.rel,
      hr: rc.checks.map(function (c) { return { id: c.id, pass: c.pass }; })
    };
    pushAlert(alert);
    loadEvent(alert.event);
    return alert;
  }

  /* ---------- sharp-jump context: official event record (df50b92f feature,
   * kept by this integration) ----------
   * GET /events/{event_ticker} (Get Event) returns settlement_sources[{name,url}]:
   * the official sources the exchange uses to determine the event. These are
   * context links only — they do NOT prove what caused a price move; each row
   * says "Cause not verified". Verified against
   * https://docs.kalshi.com/api-reference/events/get-event (fetched 2026-11-20:
   * EventData.settlement_sources, "The official sources used for the
   * determination of markets within this event"). */
  KD.events = {};                   // event_ticker -> {status, sources, title, api}
  function eventUrl(evt) {
    return BASE + "/events/" + encodeURIComponent(evt);
  }
  function loadEvent(evt) {
    if (!evt || KD.events[evt] || typeof fetch !== "function") return;
    KD.events[evt] = { status: "loading", sources: [], title: "", api: eventUrl(evt) };
    fetch(eventUrl(evt), { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (j) {
        var ev = j.event || {};
        KD.events[evt] = {
          status: "ok", title: ev.title || "", api: eventUrl(evt),
          sources: (ev.settlement_sources || []).filter(function (s) {
            return s && typeof s.url === "string" && /^https:\/\//.test(s.url);
          })
        };
        render();
      })
      .catch(function () {
        KD.events[evt] = { status: "error", sources: [], title: "", api: eventUrl(evt) };
        render();
      });
  }
  function contextCell(a) {
    if (!a.event) return "<span class='muted small'>event not recorded (older alert)</span>";
    var ev = KD.events[a.event];
    var out = "<a class='src' href='" + esc(eventUrl(a.event)) + "' target='_blank' rel='noopener'>event API</a>";
    if (!ev || ev.status === "loading") return out + " <span class='muted small'>loading settlement sources…</span>";
    if (ev.status === "error") return out + " <span class='muted small'>event record unavailable (browser/API blocked) — not inferred</span>";
    if (!ev.sources.length) return out + " <span class='muted small'>API lists no settlement sources</span>";
    out += ev.sources.map(function (s) {
      return " <a class='src' href='" + esc(s.url) + "' target='_blank' rel='noopener'>" + esc(s.name || s.url) + "</a>";
    }).join("");
    return out;
  }
  function rulesCell(a) {
    if (!a.rules) return "";
    return "<details class='rules'><summary class='small'>rules (Get Market rules_primary)</summary><div class='small'>" +
      esc(a.rules) + "</div></details>";
  }
  function pushAlert(alert) {
    state.alerts.unshift(alert);
    if (state.alerts.length > MAX_ALERTS) state.alerts.length = MAX_ALERTS;
    try { localStorage.setItem(ALERT_KEY, JSON.stringify(state.alerts)); } catch (e) {}
    state.dirty = true;
    render();
    if (window.KalshiTrade && window.KalshiTrade.onSwingAlert) {
      try { window.KalshiTrade.onSwingAlert(alert); } catch (e) { /* automation must not break alerts */ }
    }
    if (window.KalshiDash && window.KalshiDash.drawChart) {
      try { window.KalshiDash.drawChart(); } catch (e) { /* redraw is best-effort */ }
    }
    renderJumpList();
  }

  /* ---------- dashboard hooks (contract from PR #28) ---------- */
  KD.onSample = function (m, sample) {
    if (!m) return;
    var b = book(m, sample);
    observe(m.ticker, {
      t: (sample && sample.t) || Math.floor(Date.now() / 1000),
      px: tracked(b), bid: b.bid, ask: b.ask, vol: b.vol,
      title: m.title, topic: m.topic, series: m.series_ticker,
      event: m.event_ticker, rules: m.rules_primary || ""
    });
    resolutionCheck({ ticker: m.ticker, status: m.status, result: m.result,
      title: m.title, topic: m.topic, event_ticker: m.event_ticker });
  };
  KD.onMarkets = function (markets) {
    /* Seed from each full scan; expose the list for the watch set. */
    var now = Math.floor(Date.now() / 1000);
    state.seeded = markets || [];
    state.seeded.forEach(function (m) {
      var b = book(m, null);
      var px = tracked(b);
      if (px !== null && !state.track[m.ticker]) {
        state.track[m.ticker] = { price: px, ts: now };
      }
      state.byTicker[m.ticker] = Object.assign(state.byTicker[m.ticker] || {}, {
        title: m.title, topic: m.topic, series: m.series_ticker, event: m.event_ticker
      });
      resolutionCheck({ ticker: m.ticker, status: m.status, result: m.result,
        title: m.title, topic: m.topic, event_ticker: m.event_ticker });
    });
    state.dirty = true;
  };

  /* ---------- resolution notices (yes / no) ---------- */
  function resolutionCheck(row) {
    var res = String(row.result || "").toLowerCase();
    var done = row.status === "closed" || row.status === "determined" ||
      row.status === "finalized";
    if (!res || (res !== "yes" && res !== "no") || !done) return;
    var seen = res + ":" + row.status;
    if (state.resolvedSeen[row.ticker] === seen) return;
    state.resolvedSeen[row.ticker] = seen;
    try { localStorage.setItem(RESOLVED_KEY, JSON.stringify(state.resolvedSeen)); }
    catch (e) {}
    state.notices.unshift({
      ts: Math.floor(Date.now() / 1000), kind: "resolved",
      ticker: row.ticker, title: row.title || row.ticker,
      topic: row.topic || "", result: res, status: row.status,
      event: row.event_ticker || "", api: apiUrl(row.ticker), dir: res
    });
    if (state.notices.length > 120) state.notices.length = 120;
    state.dirty = true;
    render();
    renderJumpList();
  }

  /* ---------- dedicated 10 s batch poll ---------- */
  function watchList() {
    var ids = {}, out = [];
    state.seeded.slice().sort(function (a, b) {
      return (b.volDollars || 0) - (a.volDollars || 0);
    }).forEach(function (m) {
      if (out.length < WATCH_MAX && !ids[m.ticker]) { ids[m.ticker] = 1; out.push(m.ticker); }
    });
    if (state.selected && !ids[state.selected]) out.push(state.selected);
    var now = Math.floor(Date.now() / 1000);
    state.alerts.forEach(function (a) {
      if (out.length < WATCH_MAX + 20 && now - a.ts < 1800 && !ids[a.ticker]) {
        ids[a.ticker] = 1; out.push(a.ticker);
      }
    });
    return out;
  }
  var polling = false;
  function poll() {
    if (!state.enabled || polling || !window.KalshiDemo || !window.KalshiDemo.apiGet) return;
    var tickers = watchList();
    if (!tickers.length) {
      setStatus("waiting for the first dashboard scan (discovery + market scan); " +
        "the 10 s alert poll starts as markets come into view");
      return;
    }
    polling = true;
    var t0 = Math.floor(Date.now() / 1000);
    function fetchBatch(i) {
      if (i >= tickers.length) return Promise.resolve();
      var q = tickers.slice(i, i + BATCH).map(function (x) {
        return encodeURIComponent(x);
      }).join(",");
      return window.KalshiDemo.apiGet("/markets?tickers=" + q, null).then(function (j) {
        (j.markets || []).forEach(function (row) {
          var cached = state.byTicker[row.ticker] || {};
          var b = book(row, null);
          observe(row.ticker, {
            t: t0, px: tracked(b), bid: b.bid, ask: b.ask, vol: b.vol,
            title: cached.title || row.title || row.ticker,
            topic: cached.topic || "", series: cached.series || row.series_ticker || "",
            event: row.event_ticker || cached.event || "",
            rules: row.rules_primary || cached.rules || ""
          });
          resolutionCheck(row);
        });
        return fetchBatch(i + BATCH);
      });
    }
    fetchBatch(0).then(function () {
      state.errors = 0;
      state.lastPoll = new Date();
      setStatus("watching " + tickers.length + " markets · scan + 10 s poll · " +
        "tracked price = YES bid/ask mid when two-sided, else last trade · " +
        "responses are exchange-cached and can lag by several seconds (official " +
        "Get Markets note) · last poll " + fmtTs(Math.floor(Date.now() / 1000)));
    })["catch"](function (e) {
      state.errors++;
      setStatus("alert poll failed: " + esc(e && e.message || String(e)) +
        " (scan-driven detection still active)");
    }).then(function () { polling = false; });
  }
  function setStatus(txt) {
    var el = document.getElementById("alertStatus");
    if (el) el.textContent = txt;
  }

  /* ---------- rendering: two scrolling chats ---------- */
  function hrChips(hr) {
    if (!hr) return "";
    return "<div class='small'>" + hr.map(function (c) {
      return "<span class='" + (c.pass ? "hrpass" : "hrfail") + "' title='" + c.id +
        (c.pass ? " passed" : " failed") + "'>" + c.id + (c.pass ? " \u2713" : " \u2717") +
        "</span>";
    }).join(" ") + "</div>";
  }
  function linkCell(a) {
    /* per-row source discipline: exact API row + same-event query + generated
     * (labelled unverified) news search. Causation is never asserted. */
    var ev = BASE + "/markets?event_ticker=" + encodeURIComponent(a.event || a.ticker);
    var news = "https://news.google.com/search?q=" + encodeURIComponent(a.title || a.ticker);
    return "<a class='src' href='" + esc(a.api) + "' target='_blank' rel='noopener'>market API</a> · " +
      "<a class='src' href='" + esc(ev) + "' target='_blank' rel='noopener'>event rows</a> · " +
      "<a class='src unv' href='" + esc(news) + "' target='_blank' rel='noopener' " +
      "title='Generated query from the market title — possible cause, UNVERIFIED: no source asserts causation'>news search?</a>";
  }
  function alertRow(a) {
    var cls = "alert " + (a.dir === "up" ? "up" : a.dir === "down" ? "down" : "flat");
    var arrow = a.dir === "up" ? "\u25b2" : a.dir === "down" ? "\u25bc" : "\u25b6";
    var dirLabel = a.dir === "up" ? "up" : a.dir === "down" ? "down" : "flat";
    var roiBadge = a.roiSignal
      ? " <span class='roi'>high-ROI pick (heuristic)</span>" : "";
    return "<tr class='" + esc(cls) + "'><td class='mono small muted'>" + fmtTs(a.ts) + "</td>" +
      "<td><span class='pill topic'>" + esc(a.topic) + "</span></td>" +
      "<td class='mono'>" + esc(a.ticker) + "</td>" +
      "<td>" + esc(a.title) + hrChips(a.hr) + "</td>" +
      "<td class='num'>" + cents(a.oldPrice) + " &rarr; " + cents(a.newPrice) + "</td>" +
      "<td class='num " + esc(dirLabel) + "'>" + arrow + " " + cents(Math.abs(a.change)) + "</td>" +
      "<td>" + linkCell(a) + roiBadge + "</td>" +
      "<td class='ctx'>" + contextCell(a) +
      "<div class='small muted'>Cause not verified: a listed source is not proof that it moved the price.</div>" +
      rulesCell(a) + "</td></tr>";
  }
  function noticeRow(n) {
    var a = { ticker: n.ticker, title: n.title, event: n.event, api: n.api };
    return "<tr class='alert flat'><td class='mono small muted'>" + fmtTs(n.ts) + "</td>" +
      "<td><span class='pill topic'>" + esc(n.topic) + "</span></td>" +
      "<td class='mono'>" + esc(n.ticker) + "</td>" +
      "<td><strong>RESOLVED " + esc(String(n.result).toUpperCase()) + "</strong> · " +
      esc(n.title) + "</td>" +
      "<td class='num'>—</td>" +
      "<td class='num'>✓ " + esc(String(n.result).toUpperCase()) + "</td>" +
      "<td>" + linkCell(a) + " · <a class='src' href='https://docs.kalshi.com/getting_started/market_settlement' " +
      "target='_blank' rel='noopener'>settlement doc</a></td>" +
      "<td class='ctx'>" + contextCell(a) + "</td></tr>";
  }
  function renderPanel(el, rowsHtml, label, emptyHint) {
    if (!el) return;
    var wrap = el.closest ? el.closest(".chat-wrap") : null;
    var nearBottom = !wrap || (wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 60);
    var empty = rowsHtml ? "" :
      "<tr><td colspan='8' class='muted'>No " + label + " yet. " + emptyHint + "</td></tr>";
    el.innerHTML =
      "<table class='alerts'><thead><tr><th>Time</th><th>Topic</th><th>Ticker</th><th>Event</th>" +
      "<th>Price move</th><th>Swing</th><th>Source &amp; possible-cause links</th><th>Context (official links)</th></tr></thead>" +
      "<tbody>" + rowsHtml + empty + "</tbody></table>";
    if (nearBottom && wrap) wrap.scrollTop = wrap.scrollHeight;
  }
  function render() {
    var swings = state.alerts;
    var allHtml = swings.map(alertRow).join("") + state.notices.map(noticeRow).join("");
    renderPanel(document.getElementById("alertsAll"), allHtml, "swing alerts",
      "A tracked YES price moving by \u2265 $0.10 (or a market resolving yes/no) shows here.");
    renderPanel(document.getElementById("alertsROI"),
      swings.filter(function (a) { return a.roiSignal; }).map(alertRow).join(""),
      "high-ROI picks",
      "Rule: swing \u2265 $0.10 AND \u2265 10% of the prior price AND the HR-1\u2026HR-4 " +
      "tradability screen all pass (heuristic \u2014 not validated alpha; see Methodology \u00a76).");
    applyFilter();
    var countEl = document.getElementById("alertCount");
    if (countEl) {
      countEl.textContent = swings.length + " swing" + (swings.length === 1 ? "" : "s") +
        " · " + state.notices.length + " resolution" + (state.notices.length === 1 ? "" : "s") +
        (state.enabled ? "" : " (paused)");
    }
    var c1 = document.getElementById("alertCountAll");
    if (c1) c1.textContent = String(swings.length);
    var c2 = document.getElementById("alertCountRoi");
    if (c2) c2.textContent = String(swings.filter(function (a) { return a.roiSignal; }).length);
    var c3 = document.getElementById("noticeCountAll");
    if (c3) c3.textContent = String(state.notices.length);
    state.dirty = false;
  }
  function applyFilter() {
    var all = document.getElementById("chatAll");
    var roi = document.getElementById("chatROI");
    if (all) all.style.display = state.visible === "roi" ? "none" : "";
    if (roi) roi.style.display = state.visible === "all" ? "none" : "";
    ["tabAll", "tabROI", "tabSplit"].forEach(function (id) {
      var t = document.getElementById(id);
      if (!t) return;
      var v = t.getAttribute("data-chat");
      t.classList.toggle("active", v === state.visible);
      t.setAttribute("aria-pressed", String(v === state.visible));
    });
  }

  /* ---------- row selection / filters / clear / toggle ---------- */
  KD.allRows = function () { return state.alerts; };
  KD.roiRows = function () { return state.alerts.filter(function (a) { return a.roiSignal; }); };
  KD.noticeRows = function () { return state.notices; };
  KD.setFilter = function (v) { state.visible = v || "split"; render(); };
  KD.clear = function () {
    state.alerts = [];
    state.notices = [];
    try { localStorage.removeItem(ALERT_KEY); } catch (e) {}
    state.dirty = true;
    render();
    renderJumpList();
  };
  KD.toggle = function () { state.enabled = !state.enabled; render(); };
  KD.enabled = function () { return state.enabled; };
  KD.renderAlerts = render;

  /* ---------- chart annotations + jump list (added by this integration) ---------- */
  KD.annotationsFor = function (ticker) {
    if (!ticker) return [];
    return state.alerts.filter(function (a) { return a.ticker === ticker; })
      .slice(0, 12).reverse().map(function (a) {
        return { t: a.ts, price: a.newPrice, dir: a.dir };
      });
  };
  KD.onSelected = function (ticker) {
    state.selected = ticker;
    renderJumpList();
  };
  function renderJumpList() {
    var el = document.getElementById("chartAnnotations");
    if (!el) return;
    if (!state.selected) {
      el.innerHTML = "<p class='muted small'>Select a market to see its " +
        "\u2265 $0.10 jumps and resolutions here.</p>";
      return;
    }
    var rows = [];
    state.alerts.forEach(function (a) {
      if (a.ticker === state.selected) {
        rows.push("<div class='jumprow'><span class='msgtime'>" + fmtTs(a.ts) + "</span> " +
          "<span class='" + (a.dir === "down" ? "down" : "up") + "'>" +
          (a.dir === "up" ? "\u25b2" : "\u25bc") + " " + cents(Math.abs(a.change)) + "</span> " +
          cents(a.oldPrice) + " \u2192 " + cents(a.newPrice) + " " +
          (a.roiSignal ? "<span class='roi'>high-ROI pick</span>" : "") +
          " · possible-cause links: " + linkCell(a) +
          " · official event record: " + contextCell(a) + "</div>");
      }
    });
    state.notices.forEach(function (n) {
      if (n.ticker === state.selected) {
        rows.push("<div class='jumprow'><span class='msgtime'>" + fmtTs(n.ts) + "</span> " +
          "<strong>RESOLVED " + esc(String(n.result).toUpperCase()) + "</strong> · " +
          esc(n.title) + " · " + linkCell({ ticker: n.ticker, title: n.title,
            event: n.event, api: n.api }) + "</div>");
      }
    });
    el.innerHTML = (rows.length ? rows.slice(0, 20).join("") :
      "<p class='muted small'>No \u2265 $0.10 swing recorded for <span class='mono'>" +
      esc(state.selected) + "</span> while this page has been open (detection starts at " +
      "page load; the API offers no intraday alert history — see " +
      "<a href='flagged.html'>Flagged</a>).</p>") +
      "<p class='small muted'>\u201cnews search?\u201d is a query generated from the market " +
      "title so a trader can look for a cause \u2014 it is NOT an assertion that anything " +
      "caused the move; the API exposes no attribution field. The API links are the " +
      "verifiable sources.</p>";
  }

  /* alias for the annotation hooks wired in assets/dashboard.js */
  window.KalshiAlerts = {
    annotationsFor: KD.annotationsFor,
    onSelected: KD.onSelected,
    alerts: function () { return state.alerts.slice(); },
    threshold: SWING
  };

  /* ---------- UI wiring ---------- */
  function wireUI() {
    function bind(id, ev, fn) {
      var el = document.getElementById(id);
      if (el) el.addEventListener(ev, fn);
      return el;
    }
    bind("tabAll", "click", function () { KD.setFilter("all"); });
    bind("tabROI", "click", function () { KD.setFilter("roi"); });
    bind("tabSplit", "click", function () { KD.setFilter("split"); });
    var clear = bind("clearAlertsBtn", "click", KD.clear);
    if (!clear) { /* page without the card: still safe */ }
    bind("exportAlertsBtn", "click", function () {
      var blob = new Blob([JSON.stringify({ alerts: state.alerts, notices: state.notices },
        null, 2)], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "kalshi-swing-alerts.json";
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
    });
    var enabled = bind("alertsEnabled", "change", function () { KD.toggle(); });
    if (enabled) enabled.checked = state.enabled;
    state.visible = document.getElementById("tabSplit") ? "split" : "all";
    render();
  }
  wireUI();
  setInterval(render, 2000);       /* keep chats current while the page is open (as in PR #28) */
  setInterval(poll, POLL_MS);      /* dedicated 10 s batch poll (added by this integration) */
  poll();
})();
