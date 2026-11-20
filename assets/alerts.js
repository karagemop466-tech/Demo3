/* Live swing alerts page (session 6d201d19; resolution + cause links added by session 13603ac5).
 * Requires assets/alerts-core.js (loaded first).
 * 1. Seeds both chats and the snapshot table from data/latest/alerts.json (committed collector output).
 * 2. Polls the official demo REST endpoint in the browser:
 *      GET {API}/markets?tickers=...&limit=1000   every N seconds
 *    (docs: https://docs.kalshi.com/api-reference/market/get-markets.md).
 *    A swing is a change of >= $0.10 in either direction. Two detection paths:
 *      - exchange path: |last_price_dollars - previous_price_dollars| >= $0.10, so a swing can
 *        be raised on the very first read of a market;
 *      - baseline path: |last_price_dollars - previous sample| >= $0.10.
 * 3. Resolution feed: a tracked market that returns status "finalized"/"settled" with
 *    result "yes" or "no" posts a RESOLVED message (how the event resolved).
 *    (docs: https://docs.kalshi.com/getting_started/market_settlement)
 * 4. Cause / event links: for each swing the official event record is read once and its
 *    settlement_sources (name + url, the sites Kalshi names as the settlement reference)
 *    are shown. These are reference links, NOT an attribution of the move.
 * Nothing is inferred: missing values are shown as "unverified - not inferred".
 */
(function () {
  var API = "https://external-api.demo.kalshi.co/trade-api/v2";
  var CHUNK = 20;
  var MAX_MSGS = 300;
  var LIMIT = 1000;              // official maximum for Get Markets (docs)
  var C = AlertsCore;
  var st = { interval: 15, paused: false, timer: null, prev: {}, meta: {}, watch: [],
             polls: 0, marketsSeen: 0, errors: 0, lastOk: null, topic: "all",
             announced: {}, events: {} };
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function hms(d) { return d.toISOString().slice(11, 19) + " UTC"; }
  function utcFromIso(ts) { var d = new Date(ts); isNaN(d) ? (ts = String(ts)) : (ts = hms(d)); return ts; }
  function link(url, label) {
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(label) + "</a>";
  }

  /* ---------- event metadata (official settlement sources) ---------- */
  function eventUrl(eventTicker) {
    return API + "/events/" + encodeURIComponent(eventTicker);
  }
  function loadEventSources(eventTicker) {
    if (!eventTicker) return Promise.resolve(null);
    if (st.events[eventTicker]) return Promise.resolve(st.events[eventTicker]);
    return fetch(eventUrl(eventTicker), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (j) {
        var ev = (j && j.event) || {};
        var rec = { title: ev.title || "", url: eventUrl(eventTicker),
                    sources: C.settlementSourceLinks(ev.settlement_sources || []) };
        st.events[eventTicker] = rec;
        return rec;
      })
      .catch(function () { st.events[eventTicker] = null; return null; });
  }
  function causeHtml(a) {
    var parts = [];
    if (a.eventUrl) parts.push("event: " + link(a.eventUrl, a.eventTitle || "official event record"));
    (a.sources || []).forEach(function (s) {
      parts.push("settlement source: " + link(s.url, s.name || s.url));
    });
    if (!parts.length) {
      return '<span class="pill warn">cause link unverified - not inferred</span>';
    }
    return parts.join(" &middot; ");
  }

  /* ---------- message rendering ---------- */
  function line(a) {
    var arrow = a.direction === "up" ? "&#9650;" : (a.direction === "down" ? "&#9660;" : "&#9679;");
    var titleHtml = a.title
      ? "<strong>" + esc(a.title) + "</strong>"
      : '<span class="pill warn">title unverified</span>';
    var html = '<span class="mono">' + esc(a.timeLabel) + "</span> " +
      '<span class="pill">' + esc(a.topic || "unknown topic") + "</span> " + titleHtml +
      ' <span class="mono small">' + esc(a.ticker) + "</span>" +
      (a.synthetic ? ' <span class="pill warn">synthetic exchange-test series (I-15)</span>' : "");
    if (a.kind === "resolution") {
      html += '<div class="small">RESOLVED &mdash; the event resolved <strong>' + esc(a.result) + "</strong>" +
        (a.settlementTs ? ' <span class="mono">settled ' + esc(a.settlementTs) + "</span>" : "") +
        (a.settlementValue ? ' &middot; settlement value ' + esc(a.settlementValue) : "") +
        " &middot; " + link(a.sourceUrl, "API source") + "</div>";
    } else {
      html += '<div class="small">' + arrow + " " + esc(a.fromLabel) + " &rarr; " + esc(a.toLabel) +
        " (" + esc(C.fmtSigned(a.deltaTicks)) + ")" +
        (a.bidLabel ? " &middot; bid/ask " + esc(a.bidLabel) : "") +
        " &middot; " + link(a.sourceUrl, "API source") + "</div>" +
        '<div class="small">cause: ' + causeHtml(a) + "</div>" +
        '<div class="small muted">' + esc(a.persist) + "</div>";
    }
    if (a.roi) {
      html += '<div class="small muted">High-ROI screen (placeholder): ' +
        (a.roi.passes ? "passes" : "does not pass") + " - would buy " + esc(a.roi.side) + " at " +
        esc(C.fmtDollars(a.roi.boughtTicks)) + ", gross payout multiple " +
        (a.roi.multiple === null ? "n/a" : a.roi.multiple.toFixed(4)) + "x</div>";
    }
    return html;
  }

  function push(chatId, a) {
    var chat = $(chatId);
    if (!chat) return;
    var el = document.createElement("div");
    el.className = "msg " + (a.direction || "") + (a.synthetic ? " synthetic" : "") +
      (a.kind === "resolution" ? " resolved" : "");
    el.dataset.topic = a.topic || "";
    el.innerHTML = line(a);
    var atBottom = chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 40;
    var empty = chat.querySelector(".empty");
    if (empty) empty.remove();
    chat.appendChild(el);
    while (chat.children.length > MAX_MSGS) chat.removeChild(chat.firstChild);
    if (atBottom) chat.scrollTop = chat.scrollHeight;
    if (st.topic !== "all" && el.dataset.topic !== st.topic) el.hidden = true;
  }

  function emit(a) {
    push("chatAll", a);
    if (a.kind === "resolution") {
      push("chatRoi", a);          // a resolution closes the position -> both chats show it
    } else if (a.roi && a.roi.passes) {
      push("chatRoi", a);
    }
    setCount();
  }

  function setCount() {
    var n = document.querySelectorAll("#chatAll .msg").length;
    var r = document.querySelectorAll("#chatRoi .msg").length;
    var rid = $("countRes");
    if (rid) rid.textContent = String(st.resolvedCount || 0);
    $("countAll").textContent = n;
    $("countRoi").textContent = r;
  }

  function applyTopic() {
    ["chatAll", "chatRoi"].forEach(function (id) {
      document.querySelectorAll("#" + id + " .msg").forEach(function (el) {
        el.hidden = st.topic !== "all" && el.dataset.topic !== st.topic;
      });
    });
  }

  function persistLabel(a) {
    if (!a.next_reading_dollars) return "no later reading yet";
    return a.next_reading_dollars + (a.reverted_next_reading ? " - reverted (single print)" : " - held");
  }
  function persistText(a) {
    if (!a.next_reading_dollars) return "Persistence: no later reading yet (not confirmed).";
    return a.reverted_next_reading
      ? "Persistence: next reading " + a.next_reading_dollars + " moved back toward the old price - treat as a single print, not a sustained move."
      : "Persistence: next reading " + a.next_reading_dollars + " held near the new level.";
  }

  /* ---------- snapshot (committed collector output) ---------- */
  function loadSnapshot() {
    return fetch("data/latest/alerts.json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (snap) {
        st.watch = snap.watchlist || [];
        st.watch.forEach(function (w) { st.meta[w.ticker] = w; });
        $("snapMeta").textContent = "Snapshot generated " + (snap.generated_at || "?") +
          " from " + (snap.snapshot_samples || 0) + " collector samples of " +
          (snap.snapshot_tickers || 0) + " markets. Swings found: " + (snap.counts ? snap.counts.alerts : 0) +
          " (high-ROI screen passes: " + (snap.counts ? snap.counts.high_roi : 0) +
          ", resolved markets tracked: " + (snap.counts ? (snap.counts.resolved || 0) : 0) + ").";
        var tb = $("snapRows");
        tb.innerHTML = "";
        (snap.alerts || []).forEach(function (a) {
          var from = C.toTicks(a.from_dollars), to = C.toTicks(a.to_dollars);
          var item = {
            timeLabel: utcFromIso(a.ts), topic: a.topic, title: a.title, ticker: a.ticker,
            synthetic: !!a.synthetic, direction: a.direction, fromLabel: C.fmtDollars(from),
            toLabel: C.fmtDollars(to), deltaTicks: to - from, sourceUrl: a.source_url,
            bidLabel: (a.to_bid_dollars || a.to_ask_dollars)
              ? (a.to_bid_dollars || "?") + " / " + (a.to_ask_dollars || "?") : "",
            persist: persistText(a),
            eventUrl: a.event_url || "", eventTitle: a.event_title || "",
            sources: a.settlement_sources || [],
            origin: "snapshot " + a.ts, roi: { passes: !!a.high_roi, side: a.roi_side,
              boughtTicks: C.toTicks(a.roi_bought_price_dollars), multiple: parseFloat(a.roi_multiple) }
          };
          var tr = document.createElement("tr");
          tr.innerHTML = '<td class="mono">' + esc(a.ts) + "</td><td>" + esc(a.topic) + "</td><td>" +
            (a.title ? esc(a.title) : '<span class="pill warn">title unverified</span>') +
            '<div class="mono small">' + esc(a.ticker) + "</div></td><td class=\"mono\">" +
            esc(a.from_dollars) + " &rarr; " + esc(a.to_dollars) + '</td><td class="mono">' +
            esc(a.delta_dollars) + '</td><td class="mono">' +
            esc(a.to_bid_dollars || "") + " / " + esc(a.to_ask_dollars || "") +
            "</td><td>" + esc(persistLabel(a)) + "</td><td>" + (a.high_roi ? "yes" : "no") + "</td><td>" +
            link(a.source_url, "API source") + "</td><td>" +
            (a.event_url
              ? link(a.event_url, "event") +
                ((a.settlement_sources || []).length
                  ? " &middot; " + a.settlement_sources.map(function (s) {
                      return link(s.url, s.name || s.url); }).join(", ")
                  : ' <span class="pill warn">no settlement source published</span>')
              : '<span class="pill warn">cause link unverified - not inferred</span>') + "</td>" +
            "<td>" + (a.resolution
              ? "resolved <strong>" + esc(a.resolution.result) + "</strong>" +
                (a.resolution.settlement_ts ? ' <span class="mono">' + esc(a.resolution.settlement_ts) + "</span>" : "")
              : "not resolved yet") + "</td>";
          tb.appendChild(tr);
          emit(item);
        });
        if (!(snap.alerts || []).length) {
          tb.innerHTML = '<tr><td colspan="11" class="muted">No snapshot swings of &ge; $0.10.</td></tr>';
        }
        // Seed resolution messages from the committed resolution log.
        (snap.resolutions || []).forEach(function (r) {
          if (st.announced[r.ticker]) return;
          st.announced[r.ticker] = true;
          st.resolvedCount = (st.resolvedCount || 0) + 1;
          emit({
            kind: "resolution", timeLabel: utcFromIso(r.settlement_ts || r.ts), topic: r.topic,
            title: r.title || "", ticker: r.ticker, synthetic: !!r.synthetic, direction: "",
            fromLabel: "", toLabel: "", deltaTicks: 0, sourceUrl: r.source_url || "",
            result: r.result, settlementTs: r.settlement_ts || "", settlementValue: r.settlement_value_dollars || "",
            eventUrl: r.event_url || "", eventTitle: r.event_title || "", sources: r.settlement_sources || []
          });
        });
        // Resolution table: how each tracked event resolved (yes / no).
        var rtb = $("resRows");
        if (rtb) {
          rtb.innerHTML = "";
          (snap.recent_resolutions || []).forEach(function (r) {
            var tr = document.createElement("tr");
            tr.innerHTML = '<td class="mono">' + esc(r.settlement_ts || "") + "</td><td>" +
              esc(r.topic || "") + "</td><td>" +
              (r.title ? esc(r.title) : '<span class="pill warn">title unverified</span>') +
              '<div class="mono small">' + esc(r.ticker) + "</div></td><td><strong>" +
              esc(r.result || "") + "</strong></td><td class=\"mono\">" +
              esc(r.settlement_value_dollars || "") + "</td><td>" +
              link(r.source_url, "API source") + "</td>";
            rtb.appendChild(tr);
          });
          if (!(snap.recent_resolutions || []).length) {
            rtb.innerHTML = '<tr><td colspan="6" class="muted">No settled markets in the committed snapshot yet.</td></tr>';
          }
        }
        applyTopic();
      });
  }

  /* ---------- live poll (browser -> official demo API) ---------- */
  function fetchChunk(tickers) {
    var url = API + "/markets?tickers=" + tickers.map(encodeURIComponent).join(",") +
      "&limit=" + LIMIT;
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (j) { return j.markets || []; });
  }

  function poll() {
    if (st.paused) return;
    var tickers = st.watch.map(function (w) { return w.ticker; });
    if (!tickers.length) { status("No watchlist loaded - live polling idle."); return; }
    var chunks = [];
    for (var i = 0; i < tickers.length; i += CHUNK) chunks.push(tickers.slice(i, i + CHUNK));
    st.polls += 1;
    Promise.all(chunks.map(function (c) {
      return fetchChunk(c).then(function (m) { return { ok: true, markets: m }; },
                                function (e) { st.errors += 1; return { ok: false, err: String(e) }; });
    })).then(function (results) {
      var okAny = false, errMsg = "";
      results.forEach(function (res) {
        if (!res.ok) { errMsg = res.err; return; }
        okAny = true;
        res.markets.forEach(function (m) { handleMarket(m); });
      });
      if (okAny) {
        st.lastOk = new Date();
        status("LIVE - polled " + tickers.length + " markets every " + st.interval + "s (poll #" +
               st.polls + ", " + st.marketsSeen + " quotes read, " + (st.resolvedCount || 0) +
               " resolutions posted, errors " + st.errors + "). Last OK " + hms(st.lastOk) + ".", "ok");
      } else {
        status("Browser could not read the demo API (" + esc(errMsg) + "). Snapshot alerts only - see F-6D-04.", "warn");
      }
      setCount();
    });
  }

  function handleMarket(m) {
    var t = m.ticker;
    if (!t) return;
    st.marketsSeen += 1;
    var w = st.meta[t] || {};
    var topic = w.topic || "";

    /* resolution first: a market that has settled is reported as resolved yes/no */
    var res = C.resolutionOf(m);
    if (res.resolved && !st.announced[t]) {
      st.announced[t] = true;
      st.resolvedCount = (st.resolvedCount || 0) + 1;
      var ev = m.event_ticker ? loadEventSources(m.event_ticker) : Promise.resolve(null);
      ev.then(function (rec) {
        emit({
          kind: "resolution", timeLabel: hms(new Date()), topic: topic,
          title: m.title || w.title || "", ticker: t, synthetic: C.isSynthetic(t), direction: "",
          fromLabel: "", toLabel: "", deltaTicks: 0,
          sourceUrl: API + "/markets?tickers=" + encodeURIComponent(t),
          result: res.result, settlementTs: res.settlementTs, settlementValue: res.settlementValue,
          eventUrl: rec ? rec.url : (m.event_ticker ? eventUrl(m.event_ticker) : ""),
          eventTitle: rec ? rec.title : "", sources: rec ? rec.sources : []
        });
      });
    }

    var ticks = C.toTicks(m.last_price_dollars);
    if (ticks === null) return;
    var baseline = st.prev.hasOwnProperty(t) ? st.prev[t] : undefined;
    var exchangePrev = C.toTicks(m.previous_price_dollars);

    var sw = null, fromTicks = null;
    if (exchangePrev !== null && exchangePrev !== undefined) {
      sw = C.detectSwingFromPrevious(ticks, exchangePrev);
      if (sw) fromTicks = exchangePrev;
    }
    if (!sw && baseline !== undefined && baseline !== null) {
      sw = C.detectSwing(baseline, ticks);
      if (sw) fromTicks = baseline;
    }
    if (sw) {
      var roi = C.roiScreen(ticks, m.volume_fp, t, sw.direction);
      var bidAsk = (m.yes_bid_dollars || m.yes_ask_dollars)
        ? (m.yes_bid_dollars || "?") + " / " + (m.yes_ask_dollars || "?") : "";
      var evTicker = m.event_ticker || w.event_ticker || "";
      loadEventSources(evTicker).then(function (rec) {
        emit({
          timeLabel: hms(new Date()), topic: topic, title: m.title || w.title || "",
          ticker: t, synthetic: C.isSynthetic(t), direction: sw.direction,
          fromLabel: C.fmtDollars(fromTicks), toLabel: C.fmtDollars(ticks),
          deltaTicks: sw.deltaTicks, bidLabel: bidAsk,
          sourceUrl: API + "/markets?tickers=" + encodeURIComponent(t),
          persist: "Live reading (not yet confirmed by a later reading - persistence check pending).",
          eventUrl: rec ? rec.url : (evTicker ? eventUrl(evTicker) : ""),
          eventTitle: rec ? rec.title : "", sources: rec ? rec.sources : [],
          roi: { passes: roi.passes, side: roi.side, boughtTicks: roi.boughtTicks, multiple: roi.multiple }
        });
      });
    }
    st.prev[t] = ticks;
  }

  function status(text, kind) {
    var el = $("alertStatus");
    if (!el) return;
    el.className = "pill " + (kind === "ok" ? "ok" : kind === "warn" ? "warn" : "");
    el.textContent = text;
  }

  function schedule() {
    if (st.timer) clearInterval(st.timer);
    st.timer = setInterval(poll, st.interval * 1000);
  }

  function init() {
    $("intervalSel").addEventListener("change", function () {
      st.interval = parseInt(this.value, 10) || 15; schedule();
    });
    $("pauseBtn").addEventListener("click", function () {
      st.paused = !st.paused;
      this.textContent = st.paused ? "Resume live polling" : "Pause live polling";
      if (st.paused) status("Paused - no requests are being sent.", "");
      else poll();
    });
    $("topicSel").addEventListener("change", function () { st.topic = this.value; applyTopic(); });
    loadSnapshot().then(function () {
      if (!st.watch.length) { status("No watchlist in snapshot - live polling idle.", "warn"); return; }
      status("Starting live polling...", "");
      poll();
      schedule();
    }).catch(function (e) {
      status("Could not load data/latest/alerts.json (" + esc(String(e)) + ").", "warn");
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
