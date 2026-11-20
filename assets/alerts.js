/* Kalshi Demo Tracker — live swing alerts page (alerts.html).
 *
 * Browser -> Kalshi DEMO trade API (no key; public market data):
 *   GET https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=1000&tickers=T1,T2,...
 *   Source: https://docs.kalshi.com/api-reference/market/get-markets (query param `tickers`).
 * Tracked tickers come from data/latest/top_events.json (collector output, official API records).
 * Backfill comes from data/history/prices.jsonl (collector snapshots, ~10-minute cadence).
 * Pure logic lives in assets/alerts-core.js.
 */
(function () {
  "use strict";
  var A = window.KalshiAlerts;
  var API = "https://external-api.demo.kalshi.co/trade-api/v2";
  var TOPICS = [
    { id: "gas", label: "Gas prices" }, { id: "elections", label: "Elections" },
    { id: "culture", label: "Culture" }, { id: "crypto", label: "Crypto" },
    { id: "golf", label: "Golf" }
  ];
  var EVENTS_PER_TOPIC = 5, MARKETS_PER_EVENT = 3, BATCH = 25, MAX_MSG = 400;
  var DOCS_GET_MARKETS = "https://docs.kalshi.com/api-reference/market/get-markets";
  var DOCS_ENV = "https://docs.kalshi.com/getting_started/demo_env";

  var state = {
    tickerInfo: {}, batches: [], tickerCount: 0,
    all: [], roi: [], topic: "all", paused: false, timer: null, intervalSec: 30,
    polls: 0, okReq: 0, failReq: 0, lastPoll: null, lastError: "", historyRows: 0,
    historyBad: 0, netBanner: false, tracker: new A.LiveTracker(A.SWING_UNITS)
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c];
    });
  }
  function topicLabel(id) {
    var t = TOPICS.filter(function (x) { return x.id === id; })[0];
    return t ? t.label : (id || "Unassigned");
  }
  function timeUTC(ts) {
    var d = new Date(ts);
    return isNaN(d.getTime()) ? "—" : d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
  }
  function banner(kind, html) {
    var el = $("banner");
    if (!el) return;
    el.className = kind;
    el.innerHTML = html;
    el.style.display = html ? "block" : "none";
  }

  // ---- 1. tracked tickers from the collector's ranked snapshot (official API records)
  function loadTracked() {
    return fetch("data/latest/top_events.json", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("top_events.json HTTP " + r.status);
      return r.json();
    }).then(function (j) {
      var byTopic = j.by_topic || {};
      TOPICS.forEach(function (t) {
        (byTopic[t.id] || []).slice(0, EVENTS_PER_TOPIC).forEach(function (ev) {
          (ev.top_markets || []).slice(0, MARKETS_PER_EVENT).forEach(function (m) {
            if (!m || !m.ticker || state.tickerInfo[m.ticker]) return;
            state.tickerInfo[m.ticker] = {
              topic: t.id, eventTitle: ev.title || ev.event_ticker || "",
              eventTicker: ev.event_ticker || "", marketTitle: m.title || m.ticker
            };
          });
        });
      });
      var tickers = Object.keys(state.tickerInfo);
      state.tickerCount = tickers.length;
      state.batches = [];
      for (var i = 0; i < tickers.length; i += BATCH) state.batches.push(tickers.slice(i, i + BATCH));
      return j.retrieved_at || "";
    });
  }

  // ---- 2. backfill: consecutive collector snapshots (10-minute gaps)
  function loadHistory() {
    return fetch("data/history/prices.jsonl", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("prices.jsonl HTTP " + r.status);
      return r.text();
    }).then(function (text) {
      var parsed = A.parseJsonl(text);
      state.historyRows = parsed.rows.length;
      state.historyBad = parsed.bad;
      A.snapshotSwings(parsed.rows, A.SWING_UNITS).forEach(function (ev) {
        var info = state.tickerInfo[ev.ticker] || {};
        ev.topic = ev.topic || info.topic || "";
        ev.title = info.marketTitle || ev.ticker;
        ev.eventTitle = info.eventTitle || "";
        ev.apiUrl = API + "/markets?tickers=" + encodeURIComponent(ev.ticker);
        ev.gap = ev.prev_ts + " → " + ev.ts;
        push(ev);
      });
    });
  }

  // ---- 3. live polling
  function push(ev) {
    state.all.push(ev);
    if (ev.kind === "resolved" || (ev.roi && ev.roi.pass)) state.roi.push(ev);
    if (state.all.length > MAX_MSG) state.all.shift();
    if (state.roi.length > MAX_MSG) state.roi.shift();
  }

  function pollOnce() {
    if (state.paused || !state.batches.length) return Promise.resolve();
    var ts = new Date().toISOString();
    var chain = Promise.resolve();
    var fresh = [];
    var failedThisPoll = 0;
    state.batches.forEach(function (batch) {
      chain = chain.then(function () {
        var url = API + "/markets?limit=1000&tickers=" + batch.map(encodeURIComponent).join(",");
        return fetch(url, { headers: { accept: "application/json" } }).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status + " from GET /markets");
          return r.json();
        }).then(function (j) {
          state.okReq++;
          (j.markets || []).forEach(function (m) {
            var info = state.tickerInfo[m.ticker] || {};
            state.tracker.ingest(m, ts).forEach(function (ev) {
              ev.topic = info.topic || "";
              ev.title = info.marketTitle || m.title || m.ticker;
              ev.eventTitle = info.eventTitle || "";
              ev.apiUrl = API + "/markets?tickers=" + encodeURIComponent(m.ticker);
              if (ev.kind === "swing") ev.gap = "since last poll (" + ev.prev_ts + ")";
              fresh.push(ev);
            });
          });
        }).catch(function (e) {
          state.failReq++;
          failedThisPoll++;
          state.lastError = String(e && e.message ? e.message : e);
          // Any failed request (network/CORS block, HTTP error, unreadable body) is surfaced.
          // Not using instanceof TypeError: realm-independent and covers every failure mode.
          state.netBanner = true;
          banner("error", "<strong>Browser could not load live data from the demo API</strong> (" + esc(state.lastError) +
            "). This is usually CORS or network blocking. Snapshot swings below still come from the collector. " +
            "Environment: <a href=\"" + DOCS_ENV + "\" target=\"_blank\" rel=\"noopener\">demo_env</a> · " +
            "see <a href=\"flagged.html\">Flagged for review</a>.");
        });
      });
    });
    return chain.then(function () {
      state.polls++;
      state.lastPoll = new Date();
      fresh.forEach(push);
      if (failedThisPoll === 0 && state.netBanner) { state.netBanner = false; banner("", ""); }
      render();
      status();
    });
  }

  // ---- 4. rendering (DOM-safe: all dynamic text goes through esc())
  function visible(ev) { return state.topic === "all" || ev.topic === state.topic; }

  function msgHTML(ev) {
    var isRes = ev.kind === "resolved";
    var cls = isRes ? "resolved" : (ev.dir === "up" ? "up" : "down");
    var head = "<div class=\"meta\"><time>" + esc(timeUTC(ev.ts)) + "</time> " +
      "<span class=\"pill\">" + esc(topicLabel(ev.topic)) + "</span> " +
      "<span class=\"pill " + (ev.source === "snapshot" ? "warn" : "") + "\">" +
      (ev.source === "snapshot" ? "snapshot (collector)" : "live poll") + "</span></div>";
    var titleLine = "<div class=\"body\"><strong>" + esc(ev.eventTitle || ev.title) + "</strong><br>" +
      "<span class=\"small\">" + esc(ev.title) + "</span> · <span class=\"mono\">" + esc(ev.ticker) + "</span></div>";
    var body;
    if (isRes) {
      body = "<div class=\"move\"><span class=\"pill " + (ev.result === "yes" ? "" : "bad") + "\">RESOLVED: " +
        esc(String(ev.result).toUpperCase()) + "</span> (API field <span class=\"mono\">result</span>)</div>";
    } else {
      var arrow = ev.dir === "up" ? "▲" : "▼";
      body = "<div class=\"move\">" + esc(A.fmtUnits(ev.from)) + " → " + esc(A.fmtUnits(ev.to)) +
        " <strong>" + arrow + " " + esc(A.fmtDelta(ev.delta)) + "</strong></div>" +
        "<div class=\"small muted\">" + esc(ev.gap || "") + "</div>";
    }
    var roiLine = "";
    if (!isRes && ev.roi) {
      var p = ev.payoff;
      roiLine = "<div class=\"small\">Rule screen: " + (ev.roi.pass ? "<span class=\"pill\">pass</span>" :
        "<span class=\"pill warn\">" + esc(ev.roi.reasons.join("; ")) + "</span>") +
        (p !== null && p !== undefined ? " · arithmetic payoff if YES at ask: +" + (p * 100).toFixed(1) +
          "% before fees (unverified fee schedule)" : "") + "</div>";
    }
    var links = "<div class=\"small\"><a class=\"src\" href=\"" + esc(ev.apiUrl) +
      "\" target=\"_blank\" rel=\"noopener\">API record ↗</a> · cause link: " +
      "<span class=\"pill warn\">unverified — none recorded</span></div>";
    return "<div class=\"msg " + cls + "\">" + head + titleLine + body + roiLine + links + "</div>";
  }

  function paint(el, items) {
    var pinned = !el.childNodes.length || (el.scrollHeight - el.scrollTop - el.clientHeight < 40);
    var shown = items.filter(visible);
    el.innerHTML = shown.length ? shown.map(msgHTML).join("") :
      "<p class=\"muted small\">No messages yet for this filter. Swings appear here when a tracked market moves by $0.10 or more between observations.</p>";
    if (pinned) el.scrollTop = el.scrollHeight;
  }

  function render() {
    var a = $("chatAll"), r = $("chatRoi");
    if (a) paint(a, state.all);
    if (r) paint(r, state.roi);
    var ca = $("countAll"), cr = $("countRoi");
    if (ca) ca.textContent = state.all.filter(visible).length;
    if (cr) cr.textContent = state.roi.filter(visible).length;
  }

  function status() {
    var el = $("statusLine");
    if (!el) return;
    el.textContent = (state.paused ? "PAUSED · " : "LIVE · ") +
      "tracking " + state.tickerCount + " markets in " + state.batches.length + " request(s) every " +
      state.intervalSec + " s · polls " + state.polls + " · last poll " +
      (state.lastPoll ? timeUTC(state.lastPoll.toISOString()) : "—") +
      " · requests ok " + state.okReq + " / failed " + state.failReq +
      " · snapshot rows " + state.historyRows + (state.historyBad ? " (" + state.historyBad + " malformed)" : "");
  }

  function schedule() {
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(function () { pollOnce(); }, state.intervalSec * 1000);
  }

  function wire() {
    var topicSel = $("topicSel");
    if (topicSel) topicSel.addEventListener("change", function () {
      state.topic = topicSel.value; render();
    });
    var intSel = $("intervalSel");
    if (intSel) intSel.addEventListener("change", function () {
      state.intervalSec = Number(intSel.value) || 30; schedule(); status();
    });
    var pauseBtn = $("pauseBtn");
    if (pauseBtn) pauseBtn.addEventListener("click", function () {
      state.paused = !state.paused;
      pauseBtn.textContent = state.paused ? "Resume" : "Pause";
      status();
    });
  }

  function init() {
    if (!$("chatAll") || !$("chatRoi")) return;
    wire();
    loadTracked().then(function (retrieved) {
      var note = $("sourceNote");
      if (note) note.textContent = "Tracked set: " + state.tickerCount + " markets from the collector snapshot retrieved " +
        (retrieved || "unknown time") + ".";
      return loadHistory().catch(function (e) {
        banner("error", "Snapshot backfill unavailable: " + esc(e.message || e));
      });
    }).catch(function (e) {
      banner("error", "Tracked-market list unavailable: " + esc(e.message || e) +
        ". Live polling needs data/latest/top_events.json.");
    }).then(function () {
      render();
      status();
      return pollOnce();
    }).then(function () { schedule(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
