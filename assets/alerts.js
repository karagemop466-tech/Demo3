/* Kalshi Demo Tracker — live swing-alert system (project brief):
 *   * alert on sudden contract-price swings >= $0.10 in EITHER direction;
 *   * two simplified scrolling chats: "All events" and "High-ROI model" (a
 *     labelled heuristic screen, not validated alpha);
 *   * jump annotations (>= $0.10) drawn on the price chart and listed under it,
 *     with links that MAY relate to the move — causation is never asserted.
 *
 * Data: only the public, key-less market-data endpoints of the Kalshi DEMO API
 * via the shared client in assets/app.js (K.apiGet, 400ms spacing + 429 backoff).
 * Field/parameter facts verified 2026-11-20 against
 * https://docs.kalshi.com/api-reference/market/get-markets.md :
 *   - `tickers` = comma-separated market tickers (only-filter => single response,
 *     no paging); `event_ticker` = single event filter;
 *   - market fields: last_price_dollars, yes_bid_dollars, yes_ask_dollars,
 *     volume_fp, status (initialized|inactive|active|closed|determined|disputed|
 *     amended|finalized), result ('yes'|'no'|'scalar'|'');
 *   - docs warn responses are cached "so prices, sizes and status can lag the
 *     exchange by several seconds" — alert latency is therefore best-effort.
 * WebSocket streaming needs signed handshake headers (I-13), so this layer polls.
 */
(function () {
  "use strict";
  var K = window.KalshiDemo;
  if (!K) return;

  /* ---------- configuration ---------- */
  var THRESH = 0.10;        /* $0.10 swing threshold (fixed by the brief) */
  var POLL_MS = 10000;      /* price poll cadence */
  var LOOKBACK = 150;       /* s: swing measured against the oldest sample ... */
  var MINAGE = 20;          /* s: ... at least this old (instant jumps also fire) */
  var COOLDOWN = 300;       /* s: one alert per ticker+direction per 5 min */
  var BATCH = 50;           /* tickers per request (URL-length safety) */
  var WATCH_MAX = 80;       /* markets tracked for swings */
  var HIST_MAX = 240;       /* samples per ticker (~40 min at 10 s) */
  var ALERTS_MAX = 300;     /* kept + rendered per feed */
  var LS_ALERTS = "kd_alerts_v1";
  var LS_RESOLVED = "kd_alerts_resolved_v1";

  var $ = function (id) { return document.getElementById(id); };
  var chatAll = $("chatAll");
  if (!chatAll) return;      /* alert card only exists on dashboard.html */
  var chatRoi = $("chatRoi");

  var samples = {};          /* ticker -> [{t, px, last, bid, ask, vol}] */
  var cooldown = {};         /* ticker:dir -> untilTs(sec) */
  var marketCache = {};      /* ticker -> last known row (title, event, status) */
  var resolvedSeen = {};     /* ticker -> result */
  try { resolvedSeen = JSON.parse(localStorage.getItem(LS_RESOLVED) || "{}"); }
  catch (e) { resolvedSeen = {}; }
  var alerts = [];
  try { alerts = JSON.parse(localStorage.getItem(LS_ALERTS) || "[]") || []; }
  catch (e) { alerts = []; }
  var seq = alerts.length ? alerts[alerts.length - 1].id + 1 : 1;
  var running = false, errors = 0, lastPoll = null, selectedTicker = null;

  /* ---------- price + rules ---------- */
  /* Tracked price: YES bid/ask mid when a two-sided book exists, otherwise the
   * last traded price. Both fields are documented Get Markets fields. */
  function trackedPx(row) {
    var bid = num(row.yes_bid_dollars !== undefined ? row.yes_bid_dollars : row.yes_bid);
    var ask = num(row.yes_ask_dollars !== undefined ? row.yes_ask_dollars : row.yes_ask);
    var last = num(row.last_price_dollars !== undefined ? row.last_price_dollars :
      row.last_price);
    if (bid !== null && ask !== null && bid > 0 && ask > bid) return (bid + ask) / 2;
    return last;
  }
  function num(x) {
    if (x === null || x === undefined || x === "") return null;
    var v = Number(x);
    return isFinite(v) ? v : null;
  }
  /* High-ROI screen (heuristic, documented on the page + Methodology):
   * HR-1 two-sided book exists (trader could actually transact);
   * HR-1b YES/NO pair is a valid market: ask > bid on the YES side;
   * HR-2 quoted spread <= $0.10 (move happened in a real market, not noise);
   * HR-3 at least one trade has occurred (volume_fp >= 1);
   * HR-4 post-move price still in [0.02, 0.98] (event not already decided). */
  function roiCheck(row) {
    var bid = num(row.yes_bid_dollars !== undefined ? row.yes_bid_dollars : row.yes_bid);
    var ask = num(row.yes_ask_dollars !== undefined ? row.yes_ask_dollars : row.yes_ask);
    var vol = num(row.volume_fp !== undefined ? row.volume_fp : row.volume);
    var px = trackedPx(row);
    var checks = [
      { id: "HR-1", pass: bid !== null && ask !== null && bid > 0 && ask > 0 },
      { id: "HR-1b", pass: bid !== null && ask !== null && ask > bid },
      { id: "HR-2", pass: bid !== null && ask !== null && (ask - bid) <= THRESH },
      { id: "HR-3", pass: vol !== null && vol >= 1 },
      { id: "HR-4", pass: px !== null && px >= 0.02 && px <= 0.98 }
    ];
    var all = checks.every(function (c) { return c.pass; });
    return { roi: all, checks: checks };
  }

  /* ---------- links per alert ---------- */
  function linksFor(a) {
    /* Exact API URLs (per-row source discipline) + a GENERATED news-search
     * link. The search link is only a way for the reader to look for possible
     * causes; it is not a claim that any article caused the move — the Kalshi
     * API publishes no news/attribution field. */
    return [
      { label: "API row", href: K.BASE + "/markets/" + encodeURIComponent(a.ticker),
        title: "Exact Get Markets response that produced this alert" },
      { label: "event rows", href: K.BASE + "/markets?event_ticker=" +
        encodeURIComponent(a.event || a.ticker),
        title: "All markets in the same event (GET /markets?event_ticker=…)" },
      { label: "news search?", href: "https://news.google.com/search?q=" +
        encodeURIComponent(a.title || a.ticker),
        title: "Generated search for possible causes (market title as query). " +
          "UNVERIFIED: no source asserts causation.", unverified: true }
    ];
  }
  function linksHtml(a) {
    return linksFor(a).map(function (l) {
      return "<a href='" + K.esc(l.href) + "' target='_blank' rel='noopener'" +
        (l.unverified ? " class='unv'" : "") + " title='" + K.esc(l.title) + "'>" +
        K.esc(l.label) + "</a>";
    }).join(" · ");
  }

  /* ---------- alert creation ---------- */
  function pushAlert(a) {
    alerts.push(a);
    if (alerts.length > ALERTS_MAX) alerts.splice(0, alerts.length - ALERTS_MAX);
    try { localStorage.setItem(LS_ALERTS, JSON.stringify(alerts.slice(-ALERTS_MAX))); }
    catch (e) { /* quota — keep in-memory only */ }
    renderChats();
    if (window.KalshiDash && window.KalshiDash.drawChart) window.KalshiDash.drawChart();
    renderAnnotations();
  }
  function makeSwing(row, basePx, curPx, t) {
    var dir = curPx > basePx ? "up" : "down";
    var key = row.ticker + ":" + dir + ":" + Math.floor(t / COOLDOWN);
    if (cooldown[key]) return;
    cooldown[key] = true;
    var rc = roiCheck(row);
    pushAlert({
      id: seq++, ts: t, kind: "swing", dir: dir,
      ticker: row.ticker, event: row.event_ticker || "",
      title: row.title || (marketCache[row.ticker] || {}).title || row.ticker,
      topic: row._topic || (marketCache[row.ticker] || {}).topic || "",
      from: basePx, to: curPx, delta: Math.abs(curPx - basePx),
      roi: rc.roi, checks: rc.checks.map(function (c) {
        return { id: c.id, pass: c.pass };
      })
    });
  }

  /* ---------- polling + detection ---------- */
  function watchSet() {
    var ids = {}, out = [];
    var D = window.KalshiDash;
    var list = (D && D.state && D.state.markets) ? D.state.markets.slice() : [];
    list.sort(function (a, b) { return (b.volDollars || 0) - (a.volDollars || 0); });
    list.slice(0, WATCH_MAX).forEach(function (m) {
      ids[m.ticker] = true; out.push(m.ticker);
      marketCache[m.ticker] = { title: m.title, topic: m.topic,
        event: m.event_ticker, status: m.status, result: m.result };
    });
    if (selectedTicker && !ids[selectedTicker] && out.length < WATCH_MAX + 20) out.push(selectedTicker);
    var now = Math.floor(Date.now() / 1000);
    alerts.slice(-ALERTS_MAX).forEach(function (a) {
      if (a.kind === "swing" && now - a.ts < 1800 && !ids[a.ticker] &&
          out.length < WATCH_MAX + 20) {
        out.push(a.ticker);
      }
    });
    return out;
  }
  async function poll() {
    if (running) return;
    running = true;
    try {
      var tickers = watchSet();
      if (!tickers.length) {
        setStatus("waiting for the first dashboard scan (it discovers series, then " +
          "markets — alerts start as markets come into view)");
        return;
      }
      var nowSec = Math.floor(Date.now() / 1000);
      for (var i = 0; i < tickers.length; i += BATCH) {
        var batch = tickers.slice(i, i + BATCH);
        /* official Get Markets `tickers` filter (comma-separated; as the only
         * filter it returns every match in one response — see docs.kalshi.com) */
        var q = batch.map(function (t) { return encodeURIComponent(t); }).join(",");
        var j = await K.apiGet("/markets?tickers=" + q, null);
        var rows = j.markets || [];
        rows.forEach(function (row) {
          var D = window.KalshiDash;
          var scanned = D && D.state && D.state.markets.find(function (m) {
            return m.ticker === row.ticker;
          });
          if (scanned) row._topic = scanned._topic || scanned.topic;
          else if (marketCache[row.ticker]) row._topic = marketCache[row.ticker].topic;
          marketCache[row.ticker] = { title: row.title || row.ticker,
            topic: row._topic || "", event: row.event_ticker,
            status: row.status, result: row.result || "" };
          var px = trackedPx(row);
          var arr = samples[row.ticker] || (samples[row.ticker] = []);
          var prev = arr[arr.length - 1];
          if (!prev || prev.px !== px) {
            arr.push({ t: nowSec, px: px, last: num(row.last_price_dollars),
              bid: num(row.yes_bid_dollars), ask: num(row.yes_ask_dollars),
              vol: num(row.volume_fp) });
            if (arr.length > HIST_MAX) arr.splice(0, arr.length - HIST_MAX);
          }
          if (px === null) return;
          /* swing vs baseline (oldest sample within LOOKBACK, MINAGE+ old) */
          var base = null;
          for (var b = 0; b < arr.length - 1; b++) {
            if (nowSec - arr[b].t <= LOOKBACK && nowSec - arr[b].t >= MINAGE) {
              base = arr[b]; break;
            }
          }
          if (base && base.px !== null && Math.abs(px - base.px) >= THRESH) {
            makeSwing(row, base.px, px, nowSec);
          } else if (prev && prev.px !== null && prev.t !== nowSec &&
                     Math.abs(px - prev.px) >= THRESH) {
            makeSwing(row, prev.px, px, nowSec);
          }
          /* resolution notice: transition to closed/determined/finalized */
          var res = String(row.result || "").toLowerCase();
          var done = row.status === "closed" || row.status === "determined" ||
            row.status === "finalized";
          if (res && (res === "yes" || res === "no") && done &&
              resolvedSeen[row.ticker] !== res + ":" + row.status) {
            resolvedSeen[row.ticker] = res + ":" + row.status;
            try { localStorage.setItem(LS_RESOLVED, JSON.stringify(resolvedSeen)); }
            catch (e) { /* ignore */ }
            pushAlert({ id: seq++, ts: nowSec, kind: "resolved", dir: res,
              ticker: row.ticker, event: row.event_ticker || "",
              title: row.title || row.ticker,
              topic: row._topic || "", result: res, status: row.status });
          }
        });
      }
      errors = 0;
      lastPoll = new Date();
      setStatus("watching " + tickers.length + " markets · poll every " +
        (POLL_MS / 1000) + " s · threshold ≥ $" + THRESH.toFixed(2) +
        " (10¢) either direction · last poll " +
        lastPoll.toLocaleTimeString("en-GB") +
        " · API responses are cached server-side and can lag by several seconds" +
        " (official Get Markets note).");
    } catch (e) {
      errors++;
      setStatus("last poll failed: " + K.esc(e.message || String(e)) +
        " · attempts continue every " + (POLL_MS / 1000) + " s");
    } finally {
      running = false;
    }
  }
  function setStatus(txt) {
    var el = $("alertStatus");
    if (el) el.textContent = txt;
  }

  /* ---------- chat rendering (simplified scrolling chat) ---------- */
  function fmtPx(x) { return x === null || x === undefined ? "—" : K.cents(x); }
  function msgHtml(a) {
    var cls = a.kind === "resolved" ? "msg sys" :
      (a.kind === "note" ? "msg note" : "msg " + (a.dir === "up" ? "up" : "down"));
    var head;
    if (a.kind === "resolved") {
      head = "<span class='msgarrow'>✓</span> <strong>RESOLVED " +
        K.esc(String(a.result).toUpperCase()) + "</strong> · " + K.esc(a.title);
    } else if (a.kind === "note") {
      head = K.esc(a.text);
    } else {
      head = "<span class='msgarrow'>" + (a.dir === "up" ? "▲" : "▼") + "</span> " +
        "<strong>" + (a.dir === "up" ? "+" : "−") + (a.delta * 100).toFixed(2) + "¢</strong> · " +
        K.esc(a.title);
    }
    var meta = "";
    if (a.kind === "swing") {
      meta = "<div class='msgmeta'>" + fmtPx(a.from) + " → " + fmtPx(a.to) +
        " · YES last/mid</div>";
    }
    if (a.kind === "resolved") {
      meta = "<div class='msgmeta'>status " + K.esc(a.status) +
        " · settled markets pay $1.00 to the winning side" +
        " · <a href='https://docs.kalshi.com/getting_started/market_settlement' " +
        "target='_blank' rel='noopener'>Market Settlement</a></div>";
    }
    var tags = (a.topic ? "<span class='mtag'>" + K.esc(a.topic) + "</span> " : "") +
      "<span class='monosm'>" + K.esc(a.ticker) + "</span>";
    var roi = "";
    if (a.kind === "swing") {
      roi = "<div class='msgroi'>" + (a.roi ?
        "<span class='pill roi'>high-ROI pick</span>" : "<span class='muted small'>not a high-ROI pick</span>") +
        " " + (a.checks || []).map(function (c) {
          return "<span class='" + (c.pass ? "hrpass" : "hrfail") + "' title='" +
            c.id + (c.pass ? " passed" : " failed") + "'>" + c.id +
            (c.pass ? " ✓" : " ✗") + "</span>";
        }).join(" ") + "</div>";
    }
    return "<div class='" + cls + "'><div class='msgtop'><span class='msgtime'>" +
      new Date(a.ts * 1000).toLocaleTimeString("en-GB") + "</span> " + tags +
      "</div><div>" + head + "</div>" + meta + roi +
      "<div class='msglinks'>" + linksHtml(a) + "</div></div>";
  }
  function renderFeed(el, list) {
    if (!el) return;
    var nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    el.innerHTML = list.length ? list.map(msgHtml).join("") :
      "<div class='msg note'><div>" + (el.id === "chatRoi" ?
        "No high-ROI picks yet. A swing ≥ $0.10 must also pass all five screen " +
        "rules HR-1…HR-4 (see card header). Swings that fail the screen still " +
        "appear in the All-events chat." :
        "No alerts yet. The feed fills as polled YES prices/bid-ask mids move by " +
        "≥ $0.10, or when tracked markets resolve (yes/no).") + "</div></div>";
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }
  function renderChats() {
    var recent = alerts.slice(-ALERTS_MAX);
    renderFeed(chatAll, recent);
    renderFeed(chatRoi, recent.filter(function (a) {
      return a.kind === "resolved" ? false : a.roi === true;
    }));
    var all = $("alertCountAll"), roi = $("alertCountRoi");
    if (all) all.textContent = String(recent.filter(function (a) {
      return a.kind === "swing"; }).length);
    if (roi) roi.textContent = String(recent.filter(function (a) {
      return a.kind === "swing" && a.roi; }).length);
  }

  /* ---------- chart annotations + per-market jump list ---------- */
  function annotationsFor(ticker) {
    if (!ticker) return [];
    return alerts.filter(function (a) {
      return a.kind === "swing" && a.ticker === ticker;
    }).slice(-12).map(function (a) {
      return { t: a.ts, price: a.to, dir: a.dir };
    });
  }
  function renderAnnotations() {
    var el = $("chartAnnotations");
    if (!el) return;
    if (!selectedTicker) {
      el.innerHTML = "<p class='muted small'>Select a market to see its " +
        "≥ $0.10 jumps here.</p>";
      return;
    }
    var list = alerts.filter(function (a) {
      return (a.kind === "swing" || a.kind === "resolved") &&
        a.ticker === selectedTicker;
    }).slice(-20).reverse();
    if (!list.length) {
      el.innerHTML = "<p class='muted small'>No ≥ $0.10 swing recorded for " +
        "<span class='mono'>" + K.esc(selectedTicker) + "</span> while this page " +
        "has been open (alerts start from page load; the API itself offers no " +
        "intraday alert history — see <a href='flagged.html'>Flagged</a>).</p>";
      return;
    }
    el.innerHTML = list.map(function (a) {
      if (a.kind === "resolved") {
        return "<div class='jumprow'><span class='msgtime'>" +
          new Date(a.ts * 1000).toLocaleTimeString("en-GB") + "</span> " +
          "<strong>resolved " + K.esc(String(a.result).toUpperCase()) + "</strong> · " +
          K.esc(a.title) + " · " + linksHtml(a) + "</div>";
      }
      return "<div class='jumprow'><span class='msgtime'>" +
        new Date(a.ts * 1000).toLocaleTimeString("en-GB") + "</span> " +
        "<span class='" + (a.dir === "up" ? "up" : "down") + "'>" +
        (a.dir === "up" ? "▲" : "▼") + " " + (a.delta * 100).toFixed(2) + "¢</span> " +
        fmtPx(a.from) + " → " + fmtPx(a.to) + " · possible related links: " +
        linksHtml(a) + " " + (a.roi ? "<span class='pill roi'>high-ROI</span>" : "") +
        "</div>";
    }).join("") +
      "<p class='small muted'>“news search?” is a query generated from the market " +
      "title so a trader can chase a cause — it is NOT an assertion that anything " +
      "caused the move; the API has no attribution field. The API links are the " +
      "verifiable sources.</p>";
  }

  /* ---------- hooks used by assets/dashboard.js ---------- */
  window.KalshiAlerts = {
    annotationsFor: annotationsFor,
    onSelected: function (ticker) {
      selectedTicker = ticker;
      renderAnnotations();
    },
    alerts: function () { return alerts.slice(); },
    threshold: THRESH
  };

  /* ---------- controls ---------- */
  var clearBtn = $("clearAlertsBtn");
  if (clearBtn) clearBtn.addEventListener("click", function () {
    alerts = [];
    try { localStorage.removeItem(LS_ALERTS); } catch (e) { /* */ }
    renderChats(); renderAnnotations();
    if (window.KalshiDash && window.KalshiDash.drawChart) window.KalshiDash.drawChart();
  });
  var exportBtn = $("exportAlertsBtn");
  if (exportBtn) exportBtn.addEventListener("click", function () {
    var blob = new Blob([JSON.stringify(alerts, null, 2)],
      { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "kalshi-swing-alerts.json";
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  });
  var pauseBtn = $("pauseAlertsBtn");
  var timer = null;
  function start() {
    if (timer) clearInterval(timer);
    timer = setInterval(poll, POLL_MS);
    poll();
    if (pauseBtn) pauseBtn.textContent = "⏸ Pause alerts";
  }
  if (pauseBtn) pauseBtn.addEventListener("click", function () {
    if (timer) { clearInterval(timer); timer = null; pauseBtn.textContent = "▶ Resume alerts";
      setStatus("paused by user"); }
    else start();
  });
  renderChats();
  renderAnnotations();
  start();
})();
