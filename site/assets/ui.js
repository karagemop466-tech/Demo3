/* ui.js — shared chrome, data loading and formatting for the Kalshi demo dashboard.
 *
 * Contract used by every page:
 *   UI.boot({ page, onReady(state) })
 * state = { mode:'live'|'bridge'|'snapshot', api, snapshot, topics, problems, banner }
 *
 * Rendering rule that keeps the site honest: a cell is only ever filled from a field that the
 * cited API response actually contained. Missing => '—' + class .unverified. There is no
 * default, no carry-forward, no "0" for unknown.
 */
(function (global) {
  "use strict";

  var NAV = [
    ["index", "Landing", "index.html"],
    ["dashboard", "Live Dashboard", "dashboard.html"],
    ["events", "Live Events", "events.html"],
    ["topics", "Topics", "topics.html"],
    ["portfolio", "Portfolio", "portfolio.html"],
    ["strategies", "Strategies", "strategies.html"],
    ["suggestions", "Suggestions", "suggestions.html"],
    ["questions", "Open Questions", "questions.html"],
    ["flagged", "Flagged for Review", "flagged.html"],
    ["api", "API Reference", "api.html"],
    ["sources", "Sources", "sources.html"]
  ];

  var UI = {};
  UI.NAV = NAV;
  UI.state = { mode: "snapshot", problems: [], api: null, snapshot: null, topics: null };

  /* --------------------------------------------------------------- chrome */
  UI.mount = function (page) {
    var host = document.getElementById("chrome");
    if (!host) return;
    var links = NAV.map(function (n) {
      return '<a href="' + n[2] + '"' + (n[0] === page ? ' class="on"' : "") + ">" + n[1] + "</a>";
    }).join("");
    host.innerHTML =
      '<header class="top"><div class="bar">' +
      '<span class="brand"><span class="dot" id="live-dot"></span>Kalshi Demo <small>analytics &amp; trading</small></span>' +
      '<nav class="main">' + links + "</nav></div></header>";
    var foot = document.getElementById("foot");
    if (foot) {
      foot.innerHTML = '<div class="row"><span>Data source: Kalshi demo Trade API <span class="mono">' +
        K.CONST.DEMO_REST + '</span> — public endpoints only, no key.</span><span class="spacer"></span>' +
        '<a class="small" href="https://docs.kalshi.com/getting_started/demo_env.md">official demo docs</a>' +
        '<a class="small" href="https://github.com/karagemop466-tech/Demo3">repo</a></div>';
    }
  };

  UI.banner = function (extra) {
    var el = document.getElementById("modebar");
    if (!el) return;
    var s = UI.state;
    var cls = s.mode === "live" ? "live" : s.mode === "bridge" ? "live" : s.mode === "error" ? "err" : "snap";
    var label = { live: "LIVE · browser → demo API", bridge: "LIVE · local signed bridge",
                  snapshot: "SNAPSHOT · collector output", error: "UNAVAILABLE" }[s.mode];
    var dot = document.getElementById("live-dot");
    if (dot) dot.style.background = (s.mode === "live" || s.mode === "bridge") ? "#31c463" : s.mode === "error" ? "#e05656" : "#e2a33a";
    var stamp = s.snapshot && s.snapshot._meta && s.snapshot._meta.generated_at_utc
      ? "snapshot " + s.snapshot._meta.generated_at_utc : "no snapshot";
    el.innerHTML =
      '<span class="pill ' + cls + '">' + label + "</span>" +
      '<span class="pill dim">' + stamp + "</span>" +
      (extra || "") +
      '<span class="spacer"></span>' +
      '<span class="small">refresh</span>' +
      '<select id="refresh-interval">' +
      [0, 5000, 15000, 60000].map(function (v) {
        return '<option value="' + v + '"' + (v === (s.interval || 0) ? " selected" : "") + ">" +
          (v ? v / 1000 + "s" : "off") + "</option>";
      }).join("") + "</select>" +
      '<button class="inp" id="recheck">Re-probe live</button>';
    var sel = document.getElementById("refresh-interval");
    if (sel) sel.onchange = function () { s.interval = Number(sel.value); UI.banner(extra); UI.schedule(); };
    var btn = document.getElementById("recheck");
    if (btn) btn.onclick = function () { location.href = location.pathname + "?mode=live&t=" + Date.now(); };
    var note = document.getElementById("modenote");
    if (note) {
      note.innerHTML = s.mode === "live"
        ? '<div class="callout good">Live mode: the browser is reading the demo API directly. Polling is ' +
          'unauthenticated, so it is subject to Kalshi\'s separate public limits — keep the interval at 15s or slower ' +
          '(<a href="https://docs.kalshi.com/getting_started/rate_limits.md">rate limits</a>).</div>'
        : '<div class="callout warn">Showing the archived collector snapshot. A page hosted on GitHub Pages may be ' +
          'blocked from calling the demo API by CORS — Kalshi publishes no CORS statement, so this is expected and ' +
          'unresolved (see <a href="questions.html#q-08">Q-08</a>). For true live mode run <code>python3 scripts/dev_server.py</code> ' +
          'and open <code>http://localhost:8081/dashboard.html?mode=bridge</code>. ' +
          'Every number below is still traceable: each row links to the API call that produced it.</div>';
    }
  };

  UI.schedule = function () {
    var s = UI.state;
    if (s.timer) clearInterval(s.timer);
    if (s.interval && s.mode !== "snapshot") {
      s.timer = setInterval(function () { if (s.refresh) s.refresh(); }, s.interval);
    }
  };

  /* ------------------------------------------------------------- loading */
  UI.json = function (path) {
    return fetch(path, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(path + " -> " + r.status);
      return r.json();
    });
  };

  /**
   * Where is the data directory? Two layouts must work with one copy of the code:
   *   built/Pages site  ->  <site>/index.html  + <site>/data/live_snapshot.json
   *   raw checkout      ->  site/index.html    + ../data/live_snapshot.json
   * We try "./data" then "../data" and remember the winner. No guessing, no default document.
   */
  UI.basePromise = null;
  UI.resolveBase = function () {
    if (UI.basePromise) return UI.basePromise;
    var forced = new URLSearchParams(location.search).get("dataBase");
    if (forced) { UI.base = forced.replace(/\/$/, ""); return (UI.basePromise = Promise.resolve(forced.replace(/\/$/, ""))); }
    var candidates = ["./data", "../data"];
    UI.basePromise = candidates.reduce(function (chain, cand) {
      return chain.then(function (found) {
        if (found) return found;
        return fetch(cand + "/live_snapshot.json", { method: "GET", cache: "no-store" })
          .then(function (r) { return r.ok ? cand : null; })
          .catch(function () { return null; });
      });
    }, Promise.resolve(null)).then(function (base) {
      UI.base = base || "./data";
      return UI.base;
    });
    return UI.basePromise;
  };

  UI.load = function (opts) {
    opts = opts || {};
    var q = new URLSearchParams(location.search);
    var want = q.get("mode") || (q.get("live") === "0" ? "snapshot" : "auto");
    return UI.resolveBase().then(function () { return UI._load(opts, want); });
  };

  UI._load = function (opts, want) {
    var b = (opts.dataBase || UI.base || "./data").replace(/\/$/, "");
    // data dir resolution: the assembled document lives beside the HTML in a built site;
    // in a raw checkout (running from site/) it lives one level up in ../data/.
    function opt(name) { return UI.json(b + "/" + name).catch(function () { return null; }); }
    var p = {
      live: UI.json(b + "/live_snapshot.json").then(function (d) { return { kind: "live-collector", doc: d}; })
        .catch(function () { return UI.json(b + "/snapshot.json").then(function (d) { return { kind: "session-snapshot", doc: d }; }); }),
      topics: UI.json(b + "/topics.json").catch(function () { return { topics: [] }; }),
      // the extra artifacts are embedded in the assembled document by scripts/publish_snapshot.py,
      // so a deployed site needs one request; these fallbacks only apply to a raw checkout.
      ledger: opt("portfolio_ledger.json"), analysis: opt("analysis.json"),
      tapeAnalysis: opt("analysis_tape.json"), tape: opt("tape_analysis.json"),
      resolutions: opt("resolutions.json"), orders: opt("orders.json")
    };
    var api = new K();
    UI.state.api = api;
    return Promise.all([p.live, p.topics, p.ledger, p.analysis, p.tapeAnalysis, p.tape, p.resolutions, p.orders]).then(function (res) {
      var snap = res[0] || { kind: "none", doc: {} };
      UI.state.snapshotKind = snap.kind;
      UI.state.snapshot = snap.doc;
      UI.state.problems = (snap.doc && snap.doc.problems) || [];
      UI.state.topics = (res[1] && res[1].topics) || (snap.doc.topics) || [];
      api.loadTopics = api.loadTopics; // no-op: topics already loaded
      api.topics = UI.state.topics;
      api.loadUniverse(snap.doc);
      UI.state.ledger = snap.doc.portfolio || res[2] || null;
      UI.state.analysis = snap.doc.trade_analysis || res[3] || null;
      UI.state.tapeAnalysis = snap.doc.tape_trade_analysis || res[4] || null;
      UI.state.tape = snap.doc.tape_analysis || res[5] || null;
      UI.state.resolutions = (snap.doc.resolutions && { resolutions: snap.doc.resolutions }) || res[6] || null;
      UI.state.orders = snap.doc.order_log ? { orders: snap.doc.order_log } : (res[7] || null);
      UI.state.manifest = snap.doc._meta && snap.doc._meta.provenance ? snap.doc._meta.provenance : null;
      UI.state.dataBaseResolved = b;
      // a snapshot-mode page can still show its own freshness, not only the collector's
      UI.state.snapshotHasLedger = !!res[2];
      return api.connect(want).then(function (conn) {
        UI.state.mode = conn.mode || "snapshot";
        UI.state.liveStatus = conn.status || null;
        if (conn.mode === "snapshot" && snap.kind !== "live-collector") {
          UI.state.mode = "snapshot";
        }
        if (conn.mode === "snapshot" && snap.kind === "live-collector") UI.state.mode = "snapshot";
        return UI.state;
      });
    });
  };

  /* ------------------------------------------------------------- formats */
  var fmt = UI.fmt = {
    dash: "—",
    money: function (v, dp) {
      var n = K.num(v);
      if (n === null) return '<span class="unverified">—</span>';
      return "$" + n.toLocaleString("en-US", { minimumFractionDigits: dp === undefined ? 2 : dp,
                                                 maximumFractionDigits: dp === undefined ? 2 : dp });
    },
    px: function (v) {
      var n = K.num(v);
      return n === null ? '<span class="unverified">—</span>' : "$" + n.toFixed(4);
    },
    cents: function (v) {
      var n = K.num(v);
      return n === null ? '<span class="unverified">—</span>' : "$" + (n / 100).toFixed(2);
    },
    qty: function (v, dp) {
      var n = K.num(v);
      if (n === null) return '<span class="unverified">—</span>';
      return n.toLocaleString("en-US", { minimumFractionDigits: dp === undefined ? 2 : dp,
                                          maximumFractionDigits: dp === undefined ? 2 : dp });
    },
    int: function (v) {
      var n = K.num(v);
      return n === null ? '<span class="unverified">—</span>' : n.toLocaleString("en-US");
    },
    pct: function (v, dp) {
      var n = K.num(v);
      if (n === null) return '<span class="unverified">—</span>';
      return (n * 100).toFixed(dp === undefined ? 1 : dp) + "%";
    },
    dt: function (s) {
      if (!s) return '<span class="unverified">—</span>';
      var d = new Date(s);
      if (isNaN(d)) return esc(String(s));
      return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
    },
    ago: function (s) {
      if (!s) return "—";
      var d = new Date(s);
      if (isNaN(d)) return "—";
      var sec = Math.round((Date.now() - d.getTime()) / 1000);
      if (sec < 0) return "in " + fmt.shortDur(-sec);
      return fmt.shortDur(sec) + " ago";
    },
    shortDur: function (sec) {
      if (sec < 60) return sec + "s";
      if (sec < 3600) return (sec / 60).toFixed(1) + "m";
      if (sec < 86400) return (sec / 3600).toFixed(1) + "h";
      return (sec / 86400).toFixed(1) + "d";
    },
    money0: function (v) { return fmt.money(v, 0); },
    /** compact JSON for cells that legitimately hold an object (never truncated silently) */
    json: function (v, dp) {
      if (v === null || v === undefined || v === "") return '<span class="unverified">—</span>';
      var s = typeof v === "string" ? v : JSON.stringify(v);
      if (s.length > 160) s = s.slice(0, 160) + "…";
      return '<span class="mono small">' + esc(s) + "</span>";
    },
    /** a cell that must never guess: returns an explicit "not returned" marker */
    blank: function () { return '<span class="unverified">— not returned</span>'; }
  };

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  UI.esc = esc;

  /** A source cell: one short link that opens the exact API URL (or docs page) behind the row. */
  UI.src = function (url, label) {
    if (!url) return '<span class="unverified" title="no source recorded">unverified</span>';
    var text = label || String(url).replace(/^https?:\/\//, "").replace(/^external-api\.demo\.kalshi\.co\/trade-api\/v2/, "api");
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener" title="' + esc(url) + '">' + esc(text) + "</a>";
  };

  UI.tag = function (text, cls) {
    return '<span class="tag ' + (cls || "") + '">' + esc(text) + "</span>";
  };

  /* --------------------------------------------------------------- tables */
  /**
   * UI.table(el, {columns:[{k,label,cls,render}], rows, onRow, empty, id})
   * Returns the created <table> so a page can attach handlers.
   */
  UI.table = function (el, spec) {
    var host = typeof el === "string" ? document.querySelector(el) : el;
    if (!host) return null;
    var rows = spec.rows || [];
    var wrap = document.createElement("div");
    wrap.className = "tbl-wrap";
    if (!rows.length) {
      wrap.innerHTML = '<div class="empty">' + (spec.empty || "No rows — the API returned nothing for this filter.") + "</div>";
      host.innerHTML = "";
      host.appendChild(wrap);
      return null;
    }
    var head = spec.columns.map(function (c) {
      return '<th class="' + (c.cls || "") + '"' + (c.title ? ' title="' + esc(c.title) + '"' : "") + ">" + (c.label || c.k) + "</th>";
    }).join("");
    var body = rows.map(function (r, i) {
      var tds = spec.columns.map(function (c) {
        var v;
        if (c.render) v = c.render(r, i);
        else {
          v = c.k.split(".").reduce(function (o, kk) { return (o === null || o === undefined) ? undefined : o[kk]; }, r);
          if (v === undefined || v === null || v === "") v = '<span class="unverified" title="not returned by the API">—</span>';
          else v = esc(v);
        }
        return '<td class="' + (c.cls || "") + '">' + v + "</td>";
      }).join("");
      return '<tr data-i="' + i + '"' + (r.ticker ? ' data-ticker="' + esc(r.ticker) + '"' : "") + ">" + tds + "</tr>";
    }).join("");
    wrap.innerHTML = "<table" + (spec.id ? ' id="' + spec.id + '"' : "") + "><thead><tr>" + head +
      "</tr></thead><tbody>" + body + "</tbody></table>";
    host.innerHTML = "";
    host.appendChild(wrap);
    if (spec.onRow) {
      wrap.querySelectorAll("tbody tr").forEach(function (tr) {
        tr.addEventListener("click", function () {
          wrap.querySelectorAll("tbody tr.sel").forEach(function (x) { x.classList.remove("sel"); });
          tr.classList.add("sel");
          spec.onRow(rows[Number(tr.dataset.i)], tr);
        });
      });
    }
    return wrap.querySelector("table");
  };

  UI.kpi = function (label, value, detail) {
    return '<div class="kpi"><span class="kicker">' + esc(label) + '</span><span class="v">' + value +
      "</span>" + (detail ? '<span class="d">' + detail + "</span>" : "") + "</div>";
  };

  UI.topicsOf = function () { return UI.state.topics || []; };
  UI.topicLabel = function (id) {
    var t = (UI.state.topics || []).filter(function (x) { return x.id === id; })[0];
    return t ? t.label : id || "—";
  };

  /* ------------------------------------------------------------ boot glue */
  UI.boot = function (opts) {
    UI.mount(opts.page);
    return UI.load(opts).then(function (state) {
      UI.banner();
      return opts.onReady ? opts.onReady(state) : state;
    });
  };

  global.UI = UI;
})(window);
