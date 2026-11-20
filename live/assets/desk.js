/* Kalshi Live Alert Desk — shared runtime.
 *
 * Data comes from two places, and every number keeps its source:
 *   1. committed snapshots in live/data/*.json  (built from official API
 *      payloads by scripts/build_live_data.py — see the file header there)
 *   2. optional live REST polling of the Kalshi DEMO API
 *      https://external-api.demo.kalshi.co/trade-api/v2 (public market data
 *      needs no key: https://docs.kalshi.com/getting_started/quick_start_market_data)
 *
 * If polling fails (browser CORS / offline) the page says so and keeps showing
 * the snapshot with its timestamp — it never presents snapshot data as live.
 */
window.Desk = (function () {
  "use strict";

  var BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  var THRESHOLD = 0.10;
  var cache = {};
  var health = { live: false, lastOk: null, lastErr: null, polls: 0, updates: 0, mode: "snapshot" };

  function f(x, d) { var n = parseFloat(x); return isFinite(n) ? n : (d === undefined ? 0 : d); }
  function esc(s) {
    return String(s === undefined || s === null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(x, d) {
    if (x === null || x === undefined || x === "" || !isFinite(x)) return "—";
    return Number(x).toLocaleString("en-US", { minimumFractionDigits: d || 0, maximumFractionDigits: d === undefined ? 2 : d });
  }
  function cents(x) { return (x === null || x === undefined || !isFinite(x)) ? "—" : (x * 100).toFixed(1) + "¢"; }
  function dollars(x) {
    if (x === null || x === undefined || !isFinite(x)) return "—";
    var a = Math.abs(x);
    if (a >= 1e9) return "$" + (x / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return "$" + (x / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return "$" + (x / 1e3).toFixed(1) + "k";
    return "$" + x.toFixed(2);
  }
  function pct(x) { return (x === null || x === undefined || !isFinite(x)) ? "—" : x.toFixed(1) + "%"; }
  function ts(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d)) return esc(iso);
    return d.toISOString().replace("T", " ").replace(".000Z", "Z").replace("Z", " UTC");
  }
  function ago(iso) {
    if (!iso) return "—";
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!isFinite(s)) return "—";
    if (s < 0) s = 0;
    if (s < 60) return Math.round(s) + "s ago";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    if (s < 86400) return (s / 3600).toFixed(1) + "h ago";
    return (s / 86400).toFixed(1) + "d ago";
  }
  function getJSON(path) {
    if (!cache[path]) {
      cache[path] = fetch(path, { headers: { Accept: "application/json" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status + " " + path); return r.json(); });
    }
    return cache[path];
  }
  function topicChip(t, label) {
    return '<span class="chip t-' + esc(t) + '">' + esc(label || t) + "</span>";
  }
  function envChip(env) {
    return env === "production"
      ? '<span class="chip prod" title="Collected from the production endpoint api.elections.kalshi.com. The desk targets the demo exchange; this row is labelled so the two are never confused.">production data</span>'
      : "";
  }

  /* ---------------- live polling (public endpoints, no auth) -------------- */
  function pollTickers(tickers, onUpdate, opts) {
    opts = opts || {};
    var interval = opts.interval || 15000;
    var url = BASE + "/markets?tickers=" + encodeURIComponent(tickers.join(",")).slice(0, 1500);
    var stopped = false, backoff = 0;
    async function once() {
      if (stopped) return;
      try {
        var r = await fetch(url, { headers: { Accept: "application/json" } });
        if (r.status === 429) { backoff = Math.min(backoff ? backoff * 2 : 15000, 120000); throw new Error("429 rate limited"); }
        if (!r.ok) throw new Error("HTTP " + r.status);
        var j = await r.json();
        backoff = 0;
        health.live = true; health.lastOk = new Date().toISOString(); health.mode = "live";
        health.polls++;
        var byTicker = {};
        (j.markets || []).forEach(function (m) { byTicker[m.ticker] = m; });
        onUpdate(byTicker, j);
      } catch (e) {
        health.lastErr = String(e.message || e);
        health.mode = health.lastOk ? "live-degraded" : "snapshot";
        if (opts.onError) opts.onError(health.lastErr);
      }
      setTimeout(once, interval + backoff);
    }
    once();
    return { stop: function () { stopped = true; } };
  }

  /* ---------------- charts (no libraries) -------------------------------- */
  var WINDOWS = [
    { id: "30s", label: "30 s", secs: 30 },
    { id: "2m", label: "2 min", secs: 120 },
    { id: "10m", label: "10 min", secs: 600 },
    { id: "30m", label: "30 min", secs: 1800 },
    { id: "1h", label: "1 h", secs: 3600 },
    { id: "6h", label: "6 h", secs: 21600 },
    { id: "24h", label: "24 h", secs: 86400 },
    { id: "7d", label: "7 d", secs: 604800 },
    { id: "30d", label: "30 d", secs: 2592000 }
  ];

  function setupCanvas(canvas) {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth || canvas.parentNode.clientWidth || 600;
    var h = parseInt(canvas.getAttribute("height") || "240", 10);
    canvas.width = Math.max(320, Math.round(w * dpr));
    canvas.height = Math.round(h * dpr);
    canvas.style.height = h + "px";
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: canvas.width / dpr, h: h };
  }

  function tlab(sec) {
    if (sec <= 120) return "seconds";
    if (sec <= 7200) return "minutes";
    if (sec <= 172800) return "hours";
    return "days";
  }
  function timeAxis(tsSec, label) {
    var d = new Date(tsSec * 1000);
    if (label === "seconds") return d.toISOString().substr(17, 5);
    if (label === "minutes" || label === "hours") return d.toISOString().substr(11, 5);
    return d.toISOString().substr(5, 5);
  }

  /* Price line chart: x = time, y = contract price in cents. */
  function priceChart(canvas, points, opts) {
    opts = opts || {};
    var s = setupCanvas(canvas), ctx = s.ctx, W = s.w, H = s.h;
    var padL = 44, padR = 10, padT = 12, padB = 22;
    ctx.clearRect(0, 0, W, H);
    if (!points || points.length === 0) {
      ctx.fillStyle = "#5d6f85"; ctx.font = "13px sans-serif";
      ctx.fillText(opts.empty || "No price samples in this window.", padL, H / 2);
      return;
    }
    var xs = points.map(function (p) { return p[0]; });
    var ys = points.map(function (p) { return p[1]; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    if (x1 === x0) x1 = x0 + 1;
    var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    var span = Math.max(0.02, hi - lo), pad = span * 0.15;
    lo = Math.max(0, lo - pad); hi = Math.min(1, hi + pad);
    if (hi - lo < 0.02) { var mid = (hi + lo) / 2; lo = Math.max(0, mid - 0.01); hi = Math.min(1, mid + 0.01); }
    function X(t) { return padL + (t - x0) / (x1 - x0) * (W - padL - padR); }
    function Y(v) { return padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB); }
    // grid + y labels (cents)
    ctx.strokeStyle = "#1e2a3a"; ctx.fillStyle = "#8ea0b6"; ctx.font = "11px ui-monospace,monospace";
    for (var i = 0; i <= 4; i++) {
      var v = lo + (hi - lo) * i / 4, y = Y(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.fillText((v * 100).toFixed(1) + "¢", 4, y + 4);
    }
    // threshold band from the alert level
    if (opts.threshold && points.length > 1) {
      ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = "#33465f";
      [lo].forEach(function () {});
      ctx.restore();
    }
    // x labels
    var lab = tlab(x1 - x0);
    for (var k = 0; k <= 4; k++) {
      var t = x0 + (x1 - x0) * k / 4;
      ctx.fillText(timeAxis(t, lab), Math.min(W - padR - 46, Math.max(padL, X(t) - 18)), H - 6);
    }
    // area + line
    var grad = ctx.createLinearGradient(0, padT, 0, H - padB);
    var rising = ys[ys.length - 1] >= ys[0];
    grad.addColorStop(0, rising ? "rgba(34,197,94,.28)" : "rgba(239,68,68,.28)");
    grad.addColorStop(1, "rgba(11,15,20,0)");
    ctx.beginPath();
    points.forEach(function (p, idx) { idx ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1])); });
    var lastX = X(points[points.length - 1][0]);
    ctx.lineTo(lastX, H - padB); ctx.lineTo(X(points[0][0]), H - padB); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath();
    points.forEach(function (p, idx) { idx ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1])); });
    ctx.strokeStyle = rising ? "#22c55e" : "#ef4444"; ctx.lineWidth = 1.8; ctx.stroke();
    // last point marker
    var lp = points[points.length - 1];
    ctx.beginPath(); ctx.arc(X(lp[0]), Y(lp[1]), 3, 0, Math.PI * 2);
    ctx.fillStyle = rising ? "#22c55e" : "#ef4444"; ctx.fill();
    ctx.fillStyle = "#e6edf6"; ctx.font = "11px ui-monospace,monospace";
    ctx.fillText((lp[1] * 100).toFixed(1) + "¢", Math.min(W - 52, X(lp[0]) + 6), Math.max(12, Y(lp[1]) - 6));
    if (opts.caption) { ctx.fillStyle = "#5d6f85"; ctx.font = "11px sans-serif"; ctx.fillText(opts.caption, padL, 11); }
  }

  /* Liquidity bar chart: contracts available at each price (orderbook depth). */
  function depthChart(canvas, yesLevels, noLevels, opts) {
    var s = setupCanvas(canvas), ctx = s.ctx, W = s.w, H = s.h;
    var padL = 44, padR = 10, padT = 14, padB = 24;
    ctx.clearRect(0, 0, W, H);
    var levels = [];
    (yesLevels || []).forEach(function (l) { levels.push({ side: "yes", price: f(l[0]), n: f(l[1]) }); });
    (noLevels || []).forEach(function (l) { levels.push({ side: "no", price: 1 - f(l[0]), n: f(l[1]) }); });
    if (!levels.length) {
      ctx.fillStyle = "#5d6f85"; ctx.font = "13px sans-serif";
      ctx.fillText(opts && opts.empty || "No orderbook levels returned for this market.", padL, H / 2);
      return;
    }
    var maxN = Math.max.apply(null, levels.map(function (l) { return l.n; })) || 1;
    var bw = Math.max(2, (W - padL - padR) / levels.length - 1);
    ctx.strokeStyle = "#1e2a3a";
    ctx.beginPath(); ctx.moveTo(padL, H - padB); ctx.lineTo(W - padR, H - padB); ctx.stroke();
    levels.forEach(function (l, i) {
      var x = padL + i * ((W - padL - padR) / levels.length);
      var h = (l.n / maxN) * (H - padT - padB);
      ctx.fillStyle = l.side === "yes" ? "rgba(34,197,94,.75)" : "rgba(239,68,68,.7)";
      ctx.fillRect(x, H - padB - h, Math.max(1, bw), h);
    });
    ctx.fillStyle = "#8ea0b6"; ctx.font = "11px ui-monospace,monospace";
    ctx.fillText(num(maxN, 0) + " max", 4, padT + 4);
    ctx.fillText("YES bids (green) · NO bids shown as YES-equivalent price (red)", padL, H - 6);
    ctx.fillStyle = "#5d6f85";
    ctx.fillText(cents(levels[0].price), padL, padT);
    ctx.fillText(cents(levels[levels.length - 1].price), W - padR - 36, padT);
  }

  /* Portfolio equity sparkline (simulated). */
  function equityChart(canvas, curve, start) {
    var s = setupCanvas(canvas), ctx = s.ctx, W = s.w, H = s.h;
    var padL = 52, padR = 10, padT = 12, padB = 20;
    ctx.clearRect(0, 0, W, H);
    if (!curve || !curve.length) {
      ctx.fillStyle = "#5d6f85"; ctx.font = "13px sans-serif";
      ctx.fillText("No closed trades yet for this strategy.", padL, H / 2);
      return;
    }
    var ys = curve.map(function (p) { return p.equity; });
    var lo = Math.min.apply(null, ys.concat([start])), hi = Math.max.apply(null, ys.concat([start]));
    var sp = Math.max(1, hi - lo);
    lo -= sp * 0.1; hi += sp * 0.1;
    var x0 = new Date(curve[0].ts).getTime() || 0, x1 = new Date(curve[curve.length - 1].ts).getTime() || x0 + 1;
    if (x1 === x0) x1 = x0 + 1;
    function X(t) { return padL + (t - x0) / (x1 - x0) * (W - padL - padR); }
    function Y(v) { return padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB); }
    ctx.strokeStyle = "#1e2a3a"; ctx.fillStyle = "#8ea0b6"; ctx.font = "11px ui-monospace,monospace";
    for (var i = 0; i <= 3; i++) {
      var v = lo + (hi - lo) * i / 3, y = Y(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.fillText("$" + Math.round(v).toLocaleString(), 4, y + 4);
    }
    ctx.beginPath();
    ctx.moveTo(X(x0), Y(start));
    curve.forEach(function (p) { ctx.lineTo(X(new Date(p.ts).getTime() || x0), Y(p.equity)); });
    ctx.strokeStyle = "#3b82f6"; ctx.lineWidth = 1.8; ctx.stroke();
    ctx.lineTo(X(x1), H - padB); ctx.lineTo(X(x0), H - padB); ctx.closePath();
    ctx.fillStyle = "rgba(59,130,246,.16)"; ctx.fill();
  }

  /* ---------------- chat stream ------------------------------------------ */
  function Chat(mount, opts) {
    opts = opts || {};
    var list = [], paused = false, rendered = 0, el = mount, body, foot;
    el.className = "chat";
    el.innerHTML =
      '<div class="chat-head"><h2>' + esc(opts.title || "Stream") + "</h2>" +
      '<div class="small muted" id="' + opts.id + 'status">loading…</div></div>' +
      '<div class="chat-body" id="' + opts.id + 'body" aria-live="polite"></div>' +
      '<div class="chat-foot">' +
      '<button class="btn secondary" data-act="pause">Pause scroll</button>' +
      '<button class="btn secondary" data-act="top">Jump to newest</button>' +
      '<span class="small muted" data-act="count"></span></div>';
    body = el.querySelector(".chat-body");
    foot = el.querySelector(".chat-foot");

    function render() {
      if (!list.length) {
        body.innerHTML = '<div class="chat-empty">' + esc(opts.empty || "No alerts yet.") + "</div>";
        return;
      }
      var html = list.slice(0, 220).map(function (m) { return opts.render(m, rendered); }).join("");
      body.innerHTML = html;
      rendered = list.length;
      foot.querySelector("[data-act=count]").textContent = list.length + " messages · newest first";
      if (!paused) body.scrollTop = 0;
    }
    function setStatus(txt, cls) {
      var s = el.querySelector("#" + opts.id + "status");
      if (s) s.innerHTML = (cls ? '<span class="pulse ' + cls + '"></span>' : "") + txt;
    }
    foot.addEventListener("click", function (e) {
      var a = e.target.getAttribute("data-act");
      if (a === "pause") {
        paused = !paused;
        e.target.textContent = paused ? "Resume scroll" : "Pause scroll";
        e.target.classList.toggle("on", paused);
      }
      if (a === "top") { body.scrollTop = 0; }
    });
    return {
      set: function (items) {
        list = items || [];
        // newest first for display; items arrive sorted per the data builder
        list = list.slice().sort(function (a, b) {
          return (b.sort_ts || new Date(b.ts).getTime() / 1000) - (a.sort_ts || new Date(a.ts).getTime() / 1000);
        });
        render();
      },
      prepend: function (item) {
        list.unshift(item);
        if (list.length > 1200) list.pop();
        render();
        if (!paused) body.scrollTop = 0;
      },
      status: setStatus,
      size: function () { return list.length; }
    };
  }

  return {
    BASE: BASE, THRESHOLD: THRESHOLD, WINDOWS: WINDOWS,
    get: getJSON, f: f, esc: esc, num: num, cents: cents, dollars: dollars, pct: pct,
    ts: ts, ago: ago, topicChip: topicChip, envChip: envChip,
    pollTickers: pollTickers, health: health,
    priceChart: priceChart, depthChart: depthChart, equityChart: equityChart,
    Chat: Chat, setupCanvas: setupCanvas
  };
})();
