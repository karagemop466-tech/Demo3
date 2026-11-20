/* Kalshi demo dashboard — shared runtime.
 *
 * Design rules enforced here:
 *  1. Nothing is invented. Every value comes from a JSON artifact that was written by the
 *     collector, and every table cell can show the URL it came from.
 *  2. A missing value renders as "—" with a "not returned by the API" tooltip and the
 *     .blankcell class, never as 0 and never as a guess.
 *  3. Each view prints the capture time of the snapshot it is showing, so a stale page is
 *     obvious rather than misleading.
 */
(function () {
  "use strict";

  const DATA = "data/";
  const cache = new Map();

  async function loadJSON(name) {
    if (cache.has(name)) return cache.get(name);
    const p = fetch(DATA + name, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(name + ": HTTP " + r.status);
      return r.json();
    });
    cache.set(name, p);
    return p;
  }

  // ---------------------------------------------------------------- formatting
  const NBSP = "\u00a0";
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function isBlank(v) {
    return v === null || v === undefined || v === "" || (typeof v === "number" && !isFinite(v));
  }
  function dash(reason) {
    return '<span class="blankcell" title="' + esc(reason || "not returned by the API") + '">—</span>';
  }
  function num(v, digits, reason) {
    if (isBlank(v)) return dash(reason);
    return Number(v).toLocaleString(undefined, {
      minimumFractionDigits: digits == null ? 0 : digits,
      maximumFractionDigits: digits == null ? 0 : digits,
    });
  }
  function money(v, digits, reason) {
    if (isBlank(v)) return dash(reason);
    return "$" + Number(v).toLocaleString(undefined, {
      minimumFractionDigits: digits == null ? 2 : digits,
      maximumFractionDigits: digits == null ? 2 : digits,
    });
  }
  function cents(v, reason) {
    if (isBlank(v)) return dash(reason);
    return (Number(v) * 100).toFixed(Number(v) < 0.1 ? 1 : 0) + "¢";
  }
  function pct(v, digits, reason) {
    if (isBlank(v)) return dash(reason);
    return (Number(v) * 100).toFixed(digits == null ? 1 : digits) + "%";
  }
  function src(link) {
    if (!link) return dash("no source URL recorded for this value");
    let host = "";
    try { host = new URL(link, location.href).host; } catch (e) { host = ""; }
    return '<a class="src" href="' + esc(link) + '" target="_blank" rel="noopener" title="' + esc(link) + '">source' +
      (host ? "<br><span class=\"dim\">" + esc(host) + "</span>" : "") + "</a>";
  }
  function when(iso) {
    if (!iso) return dash("no timestamp in the artifact");
    const d = new Date(iso);
    if (isNaN(d)) return esc(iso);
    return esc(d.toISOString().replace("T", " ").replace(".000Z", "Z")) +
      ' <span class="dim">(' + ageText(d) + ")</span>";
  }
  function ageText(d) {
    const m = Math.floor((Date.now() - d.getTime()) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    const h = Math.floor(m / 60);
    if (h < 48) return h + " h ago";
    return Math.floor(h / 24) + " d ago";
  }
  function topicLabel(t) {
    return ({ gas: "Gas prices", elections: "Elections", culture: "Culture", crypto: "Crypto", golf: "Golf" })[t] || t;
  }
  function resultPill(r) {
    if (!r) return '<span class="pill blank">blank</span>';
    if (r === "yes") return '<span class="pill yes">YES</span>';
    if (r === "no") return '<span class="pill no">NO</span>';
    if (r === "scalar") return '<span class="pill blank">scalar</span>';
    return '<span class="pill">' + esc(r) + "</span>";
  }

  // ------------------------------------------------------------------ chrome
  const PAGES = [
    ["index.html", "Overview"],
    ["gas.html", "Gas"],
    ["elections.html", "Elections"],
    ["culture.html", "Culture"],
    ["crypto.html", "Crypto"],
    ["golf.html", "Golf"],
    ["resolutions.html", "Resolutions"],
    ["liquidity.html", "Liquidity & charts"],
    ["portfolio.html", "Portfolio"],
    ["strategy.html", "Strategy"],
    ["suggestions.html", "Suggestions"],
    ["questions.html", "Decision log"],
    ["flagged.html", "Flagged for review"],
    ["sources.html", "Sources"],
  ];

  function renderChrome(active) {
    const here = location.pathname.split("/").pop() || "index.html";
    const inSub = location.pathname.indexOf("/categories/") !== -1;
    const root = inSub ? "../" : "";
    const nav = PAGES.map(function (p) {
      const href = root + (p[0] === "gas.html" || p[0] === "elections.html" || p[0] === "culture.html" ||
        p[0] === "crypto.html" || p[0] === "golf.html" ? "categories/" + p[0] : p[0]);
      const cur = (active || here) === p[0] ? ' aria-current="page"' : "";
      return '<a href="' + href + '"' + cur + ">" + esc(p[1]) + "</a>";
    }).join("");
    const head = document.querySelector("header.top");
    if (head) {
      head.innerHTML = '<div class="wrap"><a class="brand" href="' + root + 'index.html">Kalshi <span>demo</span> dashboard</a>' +
        '<nav class="main">' + nav + "</nav></div>";
    }
    const foot = document.querySelector("footer.foot");
    if (foot) {
      foot.innerHTML = '<div class="wrap"><p>Market data from the Kalshi demo API ' +
        '(<code class="mono">external-api.demo.kalshi.co</code>), with a labelled production comparison. ' +
        "Every table row carries the request URL it came from; blank cells are values the API did not return " +
        "and are never filled in.</p>" +
        '<p><a href="' + root + 'flagged.html">Flagged for review</a> · <a href="' + root +
        'sources.html">Sources</a> · <a href="https://docs.kalshi.com/getting_started/api_environments.md" ' +
        'target="_blank" rel="noopener">Kalshi API docs</a></p></div>';
    }
  }

  function freshBanner(target, meta) {
    if (!target) return;
    const demo = (meta && (meta.demo_run || meta.demo)) || {};
    const prod = (meta && (meta.prod_run || meta.prod)) || {};
    const whenIso = demo.started_at_utc || demo.when;
    target.innerHTML =
      '<div class="banner"><span class="t">Snapshot, not a live socket.</span> ' +
      "Demo collection: <strong>" + when(whenIso) + "</strong> · run <code class=\"mono\">" +
      esc(demo.run_id || "n/a") + "</code>. Production: <strong>" + when(prod.started_at_utc) + "</strong>. " +
      "Kalshi's WebSocket needs a signed handshake, so a static page cannot stream; see " +
      '<a href="' + (location.pathname.indexOf("/categories/") !== -1 ? "../" : "") + 'questions.html">D7</a>.</div>';
  }

  // ------------------------------------------------------------------- charts
  /* Minimal canvas line chart: time on X, contract price on Y.
     No external library so the page works offline and has no supply-chain surface. */
  function drawPriceChart(canvas, series, opts) {
    opts = opts || {};
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth || 600;
    const H = canvas.clientHeight || 320;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const pad = { l: 52, r: 14, t: 12, b: 28 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;

    // collect points
    let pts = [];
    series.forEach(function (s) {
      (s.points || []).forEach(function (p) {
        if (p.t == null) return;
        pts.push({ t: Number(p.t) * 1000, y: s.value(p), s: s });
      });
    });
    pts = pts.filter(function (p) { return p.y != null && isFinite(p.y); });

    ctx.fillStyle = "#0e141c";
    ctx.fillRect(pad.l, pad.t, plotW, plotH);
    ctx.strokeStyle = "#22303f";
    ctx.lineWidth = 1;
    ctx.strokeRect(pad.l, pad.t, plotW, plotH);

    if (!pts.length) {
      ctx.fillStyle = "#6b7d92";
      ctx.font = "13px sans-serif";
      ctx.fillText("No candlestick points in this window (the API returned none).", pad.l + 12, pad.t + 26);
      return;
    }
    const xs = pts.map(function (p) { return p.t; });
    const ys = pts.map(function (p) { return p.y; });
    let x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    let y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (x1 === x0) { x1 = x0 + 60000; }
    const padY = Math.max((y1 - y0) * 0.12, 0.01);
    y0 = Math.max(0, y0 - padY); y1 = Math.min(1, y1 + padY);
    if (y1 === y0) { y1 = Math.min(1, y0 + 0.02); }

    const sx = function (t) { return pad.l + ((t - x0) / (x1 - x0)) * plotW; };
    const sy = function (v) { return pad.t + plotH - ((v - y0) / (y1 - y0)) * plotH; };

    // grid + y labels (price in dollars)
    ctx.font = "11px ui-monospace, monospace";
    ctx.fillStyle = "#93a4b8";
    ctx.strokeStyle = "#1a2431";
    for (let i = 0; i <= 4; i++) {
      const v = y0 + ((y1 - y0) * i) / 4;
      const y = sy(v);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + plotW, y); ctx.stroke();
      ctx.fillText("$" + v.toFixed(3), 6, y + 4);
    }
    // x labels (time)
    const fmt = opts.timeFormat || function (t) {
      const d = new Date(t);
      return d.toISOString().slice(11, 16);
    };
    for (let i = 0; i <= 4; i++) {
      const t = x0 + ((x1 - x0) * i) / 4;
      ctx.fillText(fmt(t), sx(t) - 16, H - 8);
    }

    // lines
    series.forEach(function (s) {
      const sp = pts.filter(function (p) { return p.s === s; })
        .sort(function (a, b) { return a.t - b.t; });
      if (!sp.length) return;
      ctx.strokeStyle = s.color || "#58a6ff";
      ctx.lineWidth = s.width || 1.8;
      ctx.beginPath();
      sp.forEach(function (p, i) {
        const X = sx(p.t), Y = sy(p.y);
        if (i === 0) ctx.moveTo(X, Y); else ctx.lineTo(X, Y);
      });
      ctx.stroke();
      if (s.fill) {
        ctx.lineTo(sx(sp[sp.length - 1].t), pad.t + plotH);
        ctx.lineTo(sx(sp[0].t), pad.t + plotH);
        ctx.closePath();
        ctx.fillStyle = s.fill;
        ctx.fill();
      }
    });

    // legend
    let lx = pad.l + 8;
    series.forEach(function (s) {
      ctx.fillStyle = s.color || "#58a6ff";
      ctx.fillRect(lx, pad.t + 6, 10, 3);
      ctx.fillStyle = "#93a4b8";
      ctx.fillText(s.label, lx + 14, pad.t + 10);
      lx += ctx.measureText(s.label).width + 34;
    });
  }

  // ------------------------------------------------------------------- export
  window.KD = {
    loadJSON: loadJSON,
    esc: esc, num: num, money: money, cents: cents, pct: pct, src: src, when: when,
    dash: dash, isBlank: isBlank, topicLabel: topicLabel, resultPill: resultPill,
    renderChrome: renderChrome, freshBanner: freshBanner, drawPriceChart: drawPriceChart,
  };
})();
