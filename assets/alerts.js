/* Live swing alerts page (session 6d201d19). Requires assets/alerts-core.js (loaded first).
 * 1. Seeds both chats and the snapshot table from data/latest/alerts.json (committed collector output).
 * 2. Polls the official demo REST endpoint in the browser: GET {API}/markets?tickers=... every N seconds
 *    (docs: https://docs.kalshi.com/api-reference/market/get-markets.md). The first observation of a
 *    market only sets the baseline; a swing is a later change of >= $0.10 in either direction.
 * 3. Two scrolling chats: "All swings" and "High-ROI screen" (placeholder rule, see alerts.html).
 * Nothing is inferred: cause links stay blank and flagged; missing titles are shown as unverified.
 */
(function () {
  var API = "https://external-api.demo.kalshi.co/trade-api/v2";
  var CHUNK = 20;
  var MAX_MSGS = 300;
  var C = AlertsCore;
  var st = { interval: 15, paused: false, timer: null, prev: {}, meta: {}, watch: [],
             polls: 0, marketsSeen: 0, errors: 0, lastOk: null, topic: "all" };
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function hms(d) { return d.toISOString().slice(11, 19) + " UTC"; }
  function utcFromIso(ts) { var d = new Date(ts); return isNaN(d) ? String(ts) : hms(d); }

  function line(a) {
    var arrow = a.direction === "up" ? "&#9650;" : "&#9660;";
    var titleHtml = a.title
      ? "<strong>" + esc(a.title) + "</strong>"
      : '<span class="pill warn">title unverified</span>';
    var html = '<span class="mono">' + esc(a.timeLabel) + "</span> " +
      '<span class="pill">' + esc(a.topic || "unknown topic") + "</span> " + titleHtml +
      ' <span class="mono small">' + esc(a.ticker) + "</span>" +
      (a.synthetic ? ' <span class="pill warn">synthetic exchange-test series (I-15)</span>' : "") +
      '<div class="small">' + arrow + " " + esc(a.fromLabel) + " &rarr; " + esc(a.toLabel) +
      " (" + esc(C.fmtSigned(a.deltaTicks)) + ") &middot; " +
      '<a href="' + esc(a.sourceUrl) + '" target="_blank" rel="noopener">API source</a> &middot; ' +
      'cause link: <span class="pill warn">unverified - not inferred</span> &middot; ' +
      '<span class="muted">' + esc(a.origin) + "</span></div>";
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
    el.className = "msg " + a.direction + (a.synthetic ? " synthetic" : "");
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

  function emit(a, origin) {
    push("chatAll", a);
    if (a.roi && a.roi.passes) push("chatRoi", a);
    setCount();
  }

  function setCount() {
    var n = document.querySelectorAll("#chatAll .msg").length;
    var r = document.querySelectorAll("#chatRoi .msg").length;
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

  // ---------------------------------------------------------------- snapshot (committed)
  function loadSnapshot() {
    return fetch("data/latest/alerts.json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (snap) {
        st.watch = snap.watchlist || [];
        st.watch.forEach(function (w) { st.meta[w.ticker] = w; });
        $("snapMeta").textContent = "Snapshot generated " + (snap.generated_at || "?") +
          " from " + (snap.snapshot_samples || 0) + " collector samples of " +
          (snap.snapshot_tickers || 0) + " markets. Swings found: " + (snap.counts ? snap.counts.alerts : 0) +
          " (high-ROI screen passes: " + (snap.counts ? snap.counts.high_roi : 0) + ").";
        var tb = $("snapRows");
        tb.innerHTML = "";
        (snap.alerts || []).forEach(function (a) {
          var from = C.toTicks(a.from_dollars), to = C.toTicks(a.to_dollars);
          var item = {
            timeLabel: utcFromIso(a.ts), topic: a.topic, title: a.title, ticker: a.ticker,
            synthetic: !!a.synthetic, direction: a.direction, fromLabel: C.fmtDollars(from),
            toLabel: C.fmtDollars(to), deltaTicks: to - from, sourceUrl: a.source_url,
            origin: "snapshot " + a.ts, roi: { passes: !!a.high_roi, side: a.roi_side,
              boughtTicks: C.toTicks(a.roi_bought_price_dollars), multiple: parseFloat(a.roi_multiple) }
          };
          var tr = document.createElement("tr");
          tr.innerHTML = "<td class=\"mono\">" + esc(a.ts) + "</td><td>" + esc(a.topic) + "</td><td>" +
            (a.title ? esc(a.title) : '<span class="pill warn">title unverified</span>') +
            "<div class=\"mono small\">" + esc(a.ticker) + "</div></td><td class=\"mono\">" +
            esc(a.from_dollars) + " &rarr; " + esc(a.to_dollars) + "</td><td class=\"mono\">" +
            esc(a.delta_dollars) + "</td><td>" + (a.high_roi ? "yes" : "no") + "</td><td>" +
            '<a href="' + esc(a.source_url) + '" target="_blank" rel="noopener">API source</a></td><td>' +
            '<span class="pill warn">unverified - not inferred</span></td>';
          tb.appendChild(tr);
          emit(item);
        });
        if (!(snap.alerts || []).length) {
          tb.innerHTML = '<tr><td colspan="8" class="muted">No snapshot swings of &ge; $0.10.</td></tr>';
        }
        applyTopic();
      });
  }

  // ---------------------------------------------------------------- live poll (browser -> demo API)
  function fetchChunk(tickers) {
    var url = API + "/markets?tickers=" + tickers.map(encodeURIComponent).join(",");
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
               st.polls + ", " + st.marketsSeen + " quotes read, errors " + st.errors + "). Last OK " + hms(st.lastOk) + ".", "ok");
      } else {
        status("Browser could not read the demo API (" + esc(errMsg) + "). Snapshot alerts only - see F-6D-04.", "warn");
      }
      setCount();
    });
  }

  function handleMarket(m) {
    var t = m.ticker;
    if (!t) return;
    var ticks = C.toTicks(m.last_price_dollars);
    st.marketsSeen += 1;
    var prev = st.prev.hasOwnProperty(t) ? st.prev[t] : undefined;
    if (ticks !== null) {
      if (prev !== undefined && prev !== null) {
        var sw = C.detectSwing(prev, ticks);
        if (sw) {
          var w = st.meta[t] || {};
          var roi = C.roiScreen(ticks, m.volume_fp, t, sw.direction);
          emit({
            timeLabel: hms(new Date()), topic: w.topic || "", title: w.title || m.title || "",
            ticker: t, synthetic: C.isSynthetic(t), direction: sw.direction,
            fromLabel: C.fmtDollars(prev), toLabel: C.fmtDollars(ticks), deltaTicks: sw.deltaTicks,
            sourceUrl: API + "/markets?tickers=" + t, origin: "live (browser)",
            roi: { passes: roi.passes, side: roi.side, boughtTicks: roi.boughtTicks, multiple: roi.multiple }
          });
        }
      }
      st.prev[t] = ticks;
    }
  }

  function status(text, kind) {
    var el = $("alertStatus");
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
