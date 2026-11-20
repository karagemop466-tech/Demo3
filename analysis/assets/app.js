/* Kalshi dashboard — shared client code (no external libraries).
 * Data lives in data/live/*.json (refreshed by scripts/refresh_kalshi.py) and
 * data/findings.json (hand-verified findings). Every table row shows its source link.
 */
(function () {
  "use strict";

  var NAV = [
    { href: "index.html", label: "Overview" },
    { href: "pages/markets.html", label: "All open markets" },
    { href: "pages/gas.html", label: "Gas prices" },
    { href: "pages/elections.html", label: "Elections" },
    { href: "pages/culture.html", label: "Culture" },
    { href: "pages/crypto.html", label: "Crypto" },
    { href: "pages/golf.html", label: "Golf" },
    { href: "pages/resolutions.html", label: "Resolutions" },
    { href: "pages/price-history.html", label: "Price history" },
    { href: "pages/liquidity.html", label: "Liquidity" },
    { href: "pages/portfolio.html", label: "Demo portfolio" },
    { href: "pages/strategies.html", label: "Strategies" },
    { href: "pages/suggestions.html", label: "Suggestions" },
    { href: "pages/questions.html", label: "Questions" },
    { href: "pages/repo-review.html", label: "Repo review" },
    { href: "pages/flagged.html", label: "Flagged for Review" },
    { href: "pages/sources.html", label: "Sources" }
  ];

  var inPages = /\/pages\//.test(window.location.pathname);
  var PREFIX = inPages ? "../" : "";
  var cache = {};

  /* ---------- helpers ---------- */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") node.className = attrs[k];
        else if (k === "text") node.textContent = attrs[k];
        else if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }
  function link(href, text, cls) {
    return el("a", { href: href, target: "_blank", rel: "noopener", class: cls || "", text: text });
  }
  function load(path) {
    if (!cache[path]) {
      cache[path] = fetch(PREFIX + path, { cache: "no-store" }).then(function (r) {
        if (!r.ok) throw new Error(path + " → HTTP " + r.status);
        return r.json();
      });
    }
    return cache[path];
  }
  function price(p) {
    if (p === null || p === undefined || p === "") return "—";
    var s = Number(p).toFixed(4);
    return "$" + s.replace(/(\.\d\d.*?)0+$/, "$1");
  }
  function num(n, digits) {
    if (n === null || n === undefined || n === "") return "—";
    return Number(n).toLocaleString("en-US", { maximumFractionDigits: digits === undefined ? 2 : digits });
  }
  function usd(n) {
    if (n === null || n === undefined || n === "") return "—";
    return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }
  function badge(text, kind) {
    return el("span", { class: "badge " + (kind || ""), text: text });
  }
  function statusKind(s) {
    var v = (s || "").toLowerCase();
    if (v.indexOf("irregular") === 0 || v.indexOf("blocked") === 0 || v.indexOf("unanswered") === 0) return "bad";
    if (v.indexOf("partial") === 0 || v.indexOf("note") === 0 || v.indexOf("pending") === 0 || v.indexOf("unverified") === 0) return "warn";
    if (v.indexOf("ok") === 0 || v.indexOf("answered") === 0 || v.indexOf("verified") === 0) return "ok";
    return "";
  }
  function srcLinks(ids, sourcesById) {
    var wrap = el("span", { class: "srcs" });
    (ids || []).forEach(function (id) {
      var s = sourcesById[id];
      if (!s) { wrap.appendChild(el("span", { class: "badge bad", text: id + " missing" })); return; }
      wrap.appendChild(el("a", { href: s.url, target: "_blank", rel: "noopener", title: s.label, class: "srcid", text: id }));
    });
    return wrap;
  }
  function sourceIndex(findings) {
    var map = {};
    (findings.sources.rows || []).forEach(function (s) { map[s.id] = s; });
    return map;
  }

  /* ---------- sortable, filterable table ---------- */
  // cols: [{key, label, render(row)->node|string, value(row)->sortable, cls}]
  function table(container, cols, rows, opts) {
    opts = opts || {};
    var state = { key: opts.defaultSort || null, dir: opts.defaultDir || -1 };
    var search = el("input", { type: "search", placeholder: opts.searchPlaceholder || "Filter rows…", class: "filter" });
    var count = el("span", { class: "muted" });
    var thead = el("thead");
    var tbody = el("tbody");
    var tbl = el("table", { class: "data" }, [thead, tbody]);
    container.innerHTML = "";
    container.appendChild(el("div", { class: "toolbar" }, [search, count]));
    container.appendChild(el("div", { class: "table-wrap" }, [tbl]));

    function draw() {
      var q = search.value.trim().toLowerCase();
      var list = rows.filter(function (r) {
        if (!q) return true;
        return cols.some(function (c) {
          var v = c.value ? c.value(r) : (c.render ? "" : r[c.key]);
          return String(v === null || v === undefined ? "" : v).toLowerCase().indexOf(q) !== -1;
        });
      });
      if (state.key) {
        var col = cols.filter(function (c) { return c.key === state.key; })[0];
        if (col) {
          var get = col.value || function (r) { return r[col.key]; };
          list = list.slice().sort(function (a, b) {
            var x = get(a), y = get(b);
            if (x === null || x === undefined || x === "") return 1;
            if (y === null || y === undefined || y === "") return -1;
            if (typeof x === "number" && typeof y === "number") return (x - y) * state.dir;
            return String(x).localeCompare(String(y)) * state.dir;
          });
        }
      }
      thead.innerHTML = "";
      var tr = el("tr");
      cols.forEach(function (c) {
        var arrow = state.key === c.key ? (state.dir === 1 ? " ▲" : " ▼") : "";
        var th = el("th", { class: c.cls || "" }, [c.label + arrow]);
        if (c.sortable !== false) {
          th.className += " sortable";
          th.addEventListener("click", function () {
            if (state.key === c.key) state.dir = -state.dir; else { state.key = c.key; state.dir = -1; }
            draw();
          });
        }
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      tbody.innerHTML = "";
      list.forEach(function (r) {
        var row = el("tr");
        cols.forEach(function (c) {
          var content = c.render ? c.render(r) : (r[c.key] === null || r[c.key] === undefined ? "—" : String(r[c.key]));
          var td = el("td", { class: c.cls || "" }, [content]);
          row.appendChild(td);
        });
        tbody.appendChild(row);
      });
      if (!list.length) tbody.appendChild(el("tr", null, [el("td", { colspan: String(cols.length), class: "muted", text: opts.empty || "No rows." })]));
      count.textContent = list.length + " of " + rows.length + " rows";
    }
    search.addEventListener("input", draw);
    draw();
    return { redraw: draw };
  }

  /* ---------- SVG line chart ---------- */
  function lineChart(container, points, opts) {
    container.innerHTML = "";
    var W = 920, H = 340, padL = 62, padR = 18, padT = 16, padB = 46;
    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "chart");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", opts.label || "Price chart");
    container.appendChild(svg);
    if (!points.length) {
      var t = document.createElementNS(svgNS, "text");
      t.setAttribute("x", W / 2); t.setAttribute("y", H / 2); t.setAttribute("text-anchor", "middle");
      t.setAttribute("class", "axis-label"); t.textContent = "No data for this selection yet.";
      svg.appendChild(t);
      return;
    }
    var xs = points.map(function (p) { return p.t; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    if (x1 === x0) x1 = x0 + 1;
    var yMax = Math.max(0.05, Math.min(1, Math.max.apply(null, points.map(function (p) { return p.y; })) * 1.15));
    function sx(t) { return padL + (t - x0) / (x1 - x0) * (W - padL - padR); }
    function sy(y) { return padT + (1 - y / yMax) * (H - padT - padB); }
    function add(name, attrs, text) {
      var n = document.createElementNS(svgNS, name);
      Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
      if (text !== undefined) n.textContent = text;
      svg.appendChild(n);
      return n;
    }
    // grid + y labels
    for (var i = 0; i <= 4; i++) {
      var yv = yMax * i / 4, yy = sy(yv);
      add("line", { x1: padL, x2: W - padR, y1: yy, y2: yy, class: "grid" });
      add("text", { x: padL - 8, y: yy + 4, "text-anchor": "end", class: "axis-label" }, "$" + yv.toFixed(3));
    }
    // x labels (5 ticks)
    for (var j = 0; j <= 4; j++) {
      var tv = x0 + (x1 - x0) * j / 4, xx = sx(tv);
      add("line", { x1: xx, x2: xx, y1: padT, y2: H - padB, class: "grid" });
      var d = new Date(tv * 1000);
      add("text", { x: xx, y: H - padB + 18, "text-anchor": "middle", class: "axis-label" }, d.toISOString().slice(5, 16).replace("T", " "));
    }
    add("text", { x: W / 2, y: H - 6, "text-anchor": "middle", class: "axis-title" }, opts.xTitle || "Time (UTC)");
    add("text", { x: 14, y: H / 2, "text-anchor": "middle", transform: "rotate(-90 14 " + H / 2 + ")", class: "axis-title" }, opts.yTitle || "Price (USD per contract)");
    // line
    var d2 = points.map(function (p, k) { return (k ? "L" : "M") + sx(p.t).toFixed(1) + " " + sy(p.y).toFixed(1); }).join(" ");
    add("path", { d: d2, class: "series", fill: "none" });
    points.forEach(function (p) {
      var c = add("circle", { cx: sx(p.t), cy: sy(p.y), r: 3.2, class: "dot" });
      var tip = document.createElementNS(svgNS, "title");
      tip.textContent = new Date(p.t * 1000).toISOString().replace(".000", "") + "  " + price(p.y);
      c.appendChild(tip);
    });
  }

  /* ---------- page renderers ---------- */
  var R = {};

  R.index = function (content) {
    Promise.all([load("data/live/markets.json"), load("data/live/resolutions.json"), load("data/findings.json")]).then(function (v) {
      var markets = v[0], res = v[1], f = v[2];
      var open = 0; markets.topics.forEach(function (t) { open += t.open_markets_fetched || 0; });
      var tiles = el("div", { class: "tiles" }, [
        tile("Open market rows in snapshot", num(open, 0), "pages/markets.html"),
        tile("Resolved outcomes captured", num(res.items.length, 0), "pages/resolutions.html"),
        tile("Flagged for review", num(f.flagged.rows.length, 0), "pages/flagged.html"),
        tile("Suggestions awaiting your choice", num(f.suggestions.rows.filter(function (r) { return r.decision === "Pending"; }).length, 0), "pages/suggestions.html"),
        tile("Portfolio and trading", "Blocked", "pages/portfolio.html", "bad")
      ]);
      content.appendChild(tiles);
      content.appendChild(el("p", { class: "muted" }, ["Market data snapshot: " + markets.generated_at + ". Source of record: Kalshi public API, " + markets.api_base + "."]));
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };
  function tile(label, value, href, kind) {
    return el("a", { class: "tile " + (kind || ""), href: (inPages ? "../" : "") + href }, [
      el("div", { class: "tile-value", text: value }),
      el("div", { class: "tile-label", text: label })
    ]);
  }

  R.markets = function (content) {
    var onlyTopic = document.body.getAttribute("data-topic") || "";
    load("data/live/markets.json").then(function (data) {
      content.appendChild(el("p", { class: "muted" }, ["Ranking: " + data.ranking + ". Snapshot: " + data.generated_at + "."]));
      content.appendChild(el("p", { class: "notice" }, [data.coverage_note]));
      var topics = onlyTopic ? data.topics.filter(function (t) { return t.id === onlyTopic; }) : data.topics;
      var cards = el("div", { class: "cards" });
      topics.forEach(function (t) {
        cards.appendChild(el("div", { class: "card" }, [
          el("h3", { text: t.label }),
          el("div", { class: "big", text: num(t.open_markets_fetched, 0) + " rows in snapshot" }),
          el("div", { class: "muted small", text: "Series: " + t.series.join(", ") }),
          el("div", { class: "small", text: "Settlement source: " + t.settlement_source })
        ]));
      });
      content.appendChild(cards);
      var all = [];
      topics.forEach(function (t) { t.top_markets.forEach(function (m) { all.push(m); }); });
      var tabs = el("div", { class: "tabs" });
      var current = "all";
      var holder = el("div");
      function show() {
        Array.prototype.forEach.call(tabs.children, function (b) { b.className = b.dataset.id === current ? "tab active" : "tab"; });
        var rows = current === "all" ? all : all.filter(function (m) { return m.topic === current; });
        holder.innerHTML = "";
        table(holder, [
          { key: "topic", label: "Topic", render: function (r) { return topicLabel(data, r.topic); } },
          { key: "title", label: "Market", render: function (r) { return el("span", null, [el("strong", { text: r.title }), el("div", { class: "muted small", text: r.ticker })]); }, value: function (r) { return r.title + " " + r.outcome; } },
          { key: "outcome", label: "Outcome" },
          { key: "last_price", label: "Last", render: function (r) { return price(r.last_price); }, cls: "num" },
          { key: "yes_bid", label: "YES bid", render: function (r) { return price(r.yes_bid); }, cls: "num" },
          { key: "yes_ask", label: "YES ask", render: function (r) { return price(r.yes_ask); }, cls: "num" },
          { key: "yes_bid_size", label: "Bid size (contracts)", render: function (r) { return num(r.yes_bid_size, 2); }, cls: "num" },
          { key: "yes_ask_size", label: "Ask size (contracts)", render: function (r) { return num(r.yes_ask_size, 2); }, cls: "num" },
          { key: "volume_contracts", label: "Volume (volume_fp, unit not confirmed)", render: function (r) { return num(r.volume_contracts, 2); }, cls: "num" },
          { key: "volume_24h_contracts", label: "24h volume", render: function (r) { return num(r.volume_24h_contracts, 2); }, cls: "num" },
          { key: "open_interest_contracts", label: "Open interest", render: function (r) { return num(r.open_interest_contracts, 2); }, cls: "num" },
          { key: "close_time", label: "Closes (UTC)", render: function (r) { return r.close_time || "—"; } },
          { key: "updated_time", label: "Last updated (API)", render: function (r) { return r.updated_time || "—"; } },
          { key: "source", label: "Source", sortable: false, render: function (r) { return link(r.source_url, "API ↗", "srcid"); } }
        ], rows, { defaultSort: "volume_contracts", defaultDir: -1, searchPlaceholder: "Filter by market, outcome or ticker…", empty: "No open markets captured for this topic." });
      }
      if (!onlyTopic) {
        var tabNames = [["all", "All topics"]].concat(topics.map(function (t) { return [t.id, t.label]; }));
        tabNames.forEach(function (tn) {
          var b = el("button", { class: "tab", "data-id": tn[0], text: tn[1] });
          b.addEventListener("click", function () { current = tn[0]; show(); });
          tabs.appendChild(b);
        });
        content.appendChild(tabs);
      } else {
        current = onlyTopic;
      }
      content.appendChild(holder);
      show();
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };
  function topicLabel(data, id) {
    var t = data.topics.filter(function (x) { return x.id === id; })[0];
    return t ? t.label : id;
  }

  R.resolutions = function (content) {
    load("data/live/resolutions.json").then(function (data) {
      var items = data.items.slice();
      var yes = items.filter(function (r) { return r.result === "yes"; }).length;
      var no = items.filter(function (r) { return r.result === "no"; }).length;
      content.appendChild(el("p", { class: "notice", text: data.coverage_note }));
      content.appendChild(el("div", { class: "tiles" }, [
        tileStatic("Resolved: No", num(no, 0)), tileStatic("Resolved: Yes", num(yes, 0)), tileStatic("Total captured", num(items.length, 0))
      ]));
      var holder = el("div");
      content.appendChild(holder);
      table(holder, [
        { key: "result", label: "Result", render: function (r) { return badge((r.result || "").toUpperCase(), r.result === "yes" ? "ok" : "bad"); } },
        { key: "topic", label: "Topic", render: function (r) { return r.topic; } },
        { key: "title", label: "Market", render: function (r) { return el("span", null, [el("strong", { text: r.title }), el("div", { class: "muted small", text: r.ticker })]); }, value: function (r) { return r.title; } },
        { key: "outcome", label: "Outcome" },
        { key: "settlement_ts", label: "Settled (UTC)", render: function (r) { return r.settlement_ts || "—"; } },
        { key: "expiration_value", label: "Expiration value (as published by Kalshi)", render: function (r) { return r.expiration_value || "—"; } },
        { key: "last_price", label: "Last price", render: function (r) { return price(r.last_price); }, cls: "num" },
        { key: "volume_contracts", label: "Contracts traded", render: function (r) { return num(r.volume_contracts, 2); }, cls: "num" },
        { key: "source", label: "Source", sortable: false, render: function (r) { return link(r.source_url, "API ↗", "srcid"); } }
      ], items, { defaultSort: "settlement_ts", defaultDir: -1, searchPlaceholder: "Filter resolved markets…", empty: "No resolved markets captured yet." });
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };
  function tileStatic(label, value) {
    return el("div", { class: "tile" }, [el("div", { class: "tile-value", text: value }), el("div", { class: "tile-label", text: label })]);
  }

  R["price-history"] = function (content) {
    load("data/live/candles.json").then(function (data) {
      var keys = Object.keys(data.series || {});
      content.appendChild(el("p", { class: "notice", text: "Chart axes: x = time (UTC), y = candle close price in USD per contract (0 to 1). Kalshi REST candlesticks support 1-minute, 1-hour and 1-day periods (docs). The refresh job stores 1-hour and 1-day candles. Second-level charts need the WebSocket feed (not built; see Suggestions S-04)." }));
      if (!keys.length) { content.appendChild(el("p", { class: "muted", text: "No price history stored yet." })); return; }
      var sel = el("select", { class: "select" });
      keys.forEach(function (k) { sel.appendChild(el("option", { value: k, text: data.series[k].title + " (" + k + ")" })); });
      var period = el("select", { class: "select" }, [
        el("option", { value: "1440", text: "1-day candles" }),
        el("option", { value: "60", text: "1-hour candles" })
      ]);
      var controls = el("div", { class: "controls" }, [el("label", null, ["Market ", sel]), el("label", null, ["Candle size ", period])]);
      var chartBox = el("div", { class: "chart-box" });
      var tableBox = el("div");
      content.appendChild(controls);
      content.appendChild(chartBox);
      content.appendChild(el("p", { class: "muted small", id: "ph-src" }));
      content.appendChild(tableBox);
      function draw() {
        var s = data.series[sel.value];
        var block = s && s[period.value];
        var candles = block ? block.candles : [];
        var pts = candles.filter(function (c) { return c.price_close !== null && c.price_close !== undefined; })
          .map(function (c) { return { t: c.end_period_ts, y: c.price_close, raw: c }; });
        lineChart(chartBox, pts, { label: "Price history for " + sel.value });
        var srcEl = document.getElementById("ph-src");
        srcEl.innerHTML = "";
        srcEl.appendChild(document.createTextNode("Source: "));
        if (block) srcEl.appendChild(link(block.source_url, "Kalshi API candlesticks ↗", "srcid"));
        else srcEl.appendChild(document.createTextNode("not yet fetched for this candle size."));
        tableBox.innerHTML = "";
        table(tableBox, [
          { key: "end_period_utc", label: "Period end (UTC)", render: function (r) { return r.end_period_utc || "—"; } },
          { key: "price_open", label: "Open", render: function (r) { return price(r.price_open); }, cls: "num" },
          { key: "price_high", label: "High", render: function (r) { return price(r.price_high); }, cls: "num" },
          { key: "price_low", label: "Low", render: function (r) { return price(r.price_low); }, cls: "num" },
          { key: "price_close", label: "Close", render: function (r) { return price(r.price_close); }, cls: "num" },
          { key: "volume_contracts", label: "Contracts", render: function (r) { return num(r.volume_contracts, 2); }, cls: "num" },
          { key: "open_interest_contracts", label: "Open interest", render: function (r) { return num(r.open_interest_contracts, 2); }, cls: "num" },
          { key: "source", label: "Source", sortable: false, render: function () { return block ? link(block.source_url, "API ↗", "srcid") : "—"; } }
        ], candles.slice().reverse(), { defaultSort: "end_period_utc", defaultDir: -1, searchPlaceholder: "Filter candles…", empty: "No candles for this selection." });
      }
      sel.addEventListener("change", draw);
      period.addEventListener("change", draw);
      draw();
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };

  R.liquidity = function (content) {
    load("data/live/orderbooks.json").then(function (data) {
      var keys = Object.keys(data.books || {}).filter(function (k) { return data.books[k]; });
      content.appendChild(el("p", { class: "notice", text: data.method }));
      if (!keys.length) { content.appendChild(el("p", { class: "muted", text: "No order books stored yet." })); return; }
      var sel = el("select", { class: "select" });
      keys.forEach(function (k) { sel.appendChild(el("option", { value: k, text: data.books[k].title + " (" + k + ")" })); });
      content.appendChild(el("div", { class: "controls" }, [el("label", null, ["Market ", sel])]));
      var box = el("div");
      content.appendChild(box);
      function draw() {
        var b = data.books[sel.value];
        box.innerHTML = "";
        box.appendChild(el("p", { class: "small" }, ["Source: ", link(b.source_url, "Kalshi API orderbook ↗", "srcid"), " · fetched " + b.fetched_at]));
        var yesCum = 0, noCum = 0;
        var yesRows = b.yes_bids.map(function (r) { yesCum += r.contracts; return { price: r.price, contracts: r.contracts, cum: yesCum }; });
        var askRows = b.no_bids.map(function (r) { noCum += r.contracts; return { price: r.price, implied: Math.round((1 - r.price) * 10000) / 10000, contracts: r.contracts, cum: noCum }; });
        var maxY = Math.max.apply(null, [1].concat(yesRows.map(function (r) { return r.contracts; })));
        var maxA = Math.max.apply(null, [1].concat(askRows.map(function (r) { return r.contracts; })));
        box.appendChild(el("h3", { text: "Buy YES orders (YES bids): contracts resting at each price" }));
        var yesBox = el("div");
        box.appendChild(yesBox);
        table(yesBox, [
          { key: "price", label: "YES bid price", render: function (r) { return price(r.price); }, cls: "num" },
          { key: "contracts", label: "Contracts", render: function (r) { return num(r.contracts, 2); }, cls: "num" },
          { key: "cum", label: "Cumulative", render: function (r) { return num(r.cum, 2); }, cls: "num" },
          { key: "bar", label: "Depth", sortable: false, render: function (r) { return bar(r.contracts / maxY); } },
          { key: "source", label: "Source", sortable: false, render: function () { return link(b.source_url, "API ↗", "srcid"); } }
        ], yesRows, { defaultSort: "price", defaultDir: -1, searchPlaceholder: "Filter levels…", empty: "No YES bids resting." });
        box.appendChild(el("h3", { text: "Sell YES orders (implied YES asks, from NO bids): contracts available to buy YES" }));
        box.appendChild(el("p", { class: "muted small", text: "Each NO bid at price P is the same as a YES ask at 1 − P (Kalshi docs). 'Implied YES ask' is that conversion; it is not a separate quote." }));
        var askBox = el("div");
        box.appendChild(askBox);
        table(askBox, [
          { key: "implied", label: "Implied YES ask", render: function (r) { return price(r.implied); }, cls: "num" },
          { key: "price", label: "NO bid price", render: function (r) { return price(r.price); }, cls: "num" },
          { key: "contracts", label: "Contracts", render: function (r) { return num(r.contracts, 2); }, cls: "num" },
          { key: "cum", label: "Cumulative", render: function (r) { return num(r.cum, 2); }, cls: "num" },
          { key: "bar", label: "Depth", sortable: false, render: function (r) { return bar(r.contracts / maxA); } },
          { key: "source", label: "Source", sortable: false, render: function () { return link(b.source_url, "API ↗", "srcid"); } }
        ], askRows, { defaultSort: "implied", defaultDir: 1, searchPlaceholder: "Filter levels…", empty: "No NO bids resting." });
        if (b.depth_note) box.appendChild(el("p", { class: "muted small", text: b.depth_note }));
      }
      sel.addEventListener("change", draw);
      draw();
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };
  function bar(frac) {
    var w = Math.max(0, Math.min(1, frac || 0)) * 100;
    return el("div", { class: "bar" }, [el("div", { class: "bar-fill", style: "width:" + w.toFixed(1) + "%" })]);
  }

  R.portfolio = function (content) {
    load("data/findings.json").then(function (f) {
      var sources = sourceIndex(f);
      content.appendChild(el("div", { class: "banner bad" }, [
        el("strong", { text: "Status: " + f.portfolio.status + ". " }), f.portfolio.reason
      ]));
      content.appendChild(el("p", null, [
        "To unblock: provide a Kalshi demo API key pair through a GitHub Actions secret (see Suggestions S-09). Nothing has been estimated; blank cells mean UNVERIFIED."
      ]));
      var holder = el("div");
      content.appendChild(holder);
      table(holder, [
        { key: "metric", label: "Metric" },
        { key: "value", label: "Value", render: function (r) { return r.value === "" ? el("span", { class: "muted", text: "— (UNVERIFIED)" }) : r.value; } },
        { key: "status", label: "Status", render: function (r) { return badge(r.status, statusKind(r.status)); } },
        { key: "src", label: "Sources", sortable: false, render: function (r) { return srcLinks(r.src, sources); } }
      ], f.portfolio.rows, { searchPlaceholder: "Filter metrics…" });
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };

  R.strategies = function (content) {
    load("data/findings.json").then(function (f) {
      var sources = sourceIndex(f);
      content.appendChild(el("p", { class: "notice", text: f.strategies.intro }));
      var holder = el("div");
      content.appendChild(holder);
      table(holder, [
        { key: "field", label: "Trade field" },
        { key: "definition", label: "Definition (Kalshi)" },
        { key: "value", label: "Value", render: function (r) { return r.value === "" ? el("span", { class: "muted", text: "— (no trades)" }) : r.value; } },
        { key: "src", label: "Sources", sortable: false, render: function (r) { return srcLinks(r.src, sources); } }
      ], f.strategies.rows, { searchPlaceholder: "Filter fields…" });
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };

  R.suggestions = function (content) {
    load("data/findings.json").then(function (f) {
      var sources = sourceIndex(f);
      var saved = {};
      try { saved = JSON.parse(window.localStorage.getItem("kalshi-suggestion-choices") || "{}"); } catch (e) { saved = {}; }
      content.appendChild(el("p", { class: "notice", text: f.suggestions.intro }));
      var holder = el("div");
      content.appendChild(holder);
      var out = el("textarea", { class: "copybox", rows: "4", readonly: "readonly", "aria-label": "Your choices, copyable" });
      function refreshOut() {
        var lines = f.suggestions.rows.map(function (r) { return r.id + ": " + (saved[r.id] || "Pending"); });
        out.value = "My suggestion choices:\n" + lines.join("\n");
      }
      var rowsForTable = f.suggestions.rows.map(function (r) { return r; });
      table(holder, [
        { key: "id", label: "ID" },
        { key: "suggestion", label: "Suggestion" },
        { key: "benefit", label: "Why it helps" },
        { key: "information_needed", label: "Information needed" },
        { key: "effort", label: "Effort" },
        { key: "choice", label: "Your choice (saved in this browser)", sortable: false, render: function (r) {
          var s = el("select", { class: "select small-select", "aria-label": "Choice for " + r.id });
          ["Pending", "Approve", "Defer", "Reject"].forEach(function (o) {
            var opt = el("option", { value: o, text: o }); if ((saved[r.id] || "Pending") === o) opt.selected = true; s.appendChild(opt);
          });
          s.addEventListener("change", function () { saved[r.id] = s.value; window.localStorage.setItem("kalshi-suggestion-choices", JSON.stringify(saved)); refreshOut(); });
          return s;
        } },
        { key: "src", label: "Sources", sortable: false, render: function (r) { return srcLinks(r.src, sources); } }
      ], rowsForTable, { searchPlaceholder: "Filter suggestions…" });
      content.appendChild(el("h3", { text: "Send your choices" }));
      content.appendChild(el("p", { class: "muted small", text: "Copy the text below and reply in chat with the IDs you approve. Nothing is implemented until you approve it." }));
      content.appendChild(out);
      refreshOut();
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };

  R.questions = function (content) {
    load("data/findings.json").then(function (f) {
      var sources = sourceIndex(f);
      content.appendChild(el("p", { class: "notice", text: f.questions.intro }));
      var counts = { Answered: 0, Partial: 0, Unanswered: 0 };
      f.questions.rows.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
      content.appendChild(el("div", { class: "tiles" }, [
        tileStatic("Answered", num(counts.Answered, 0)), tileStatic("Partial", num(counts.Partial, 0)), tileStatic("Unanswered", num(counts.Unanswered, 0))
      ]));
      var holder = el("div");
      content.appendChild(holder);
      table(holder, [
        { key: "id", label: "ID" },
        { key: "question", label: "Question" },
        { key: "status", label: "Status", render: function (r) { return badge(r.status, statusKind(r.status)); } },
        { key: "answer", label: "Information and answer" },
        { key: "missing", label: "Missing" },
        { key: "how", label: "How to find it" },
        { key: "src", label: "Sources", sortable: false, render: function (r) { return srcLinks(r.src, sources); } }
      ], f.questions.rows, { searchPlaceholder: "Filter questions…" });
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };

  R["repo-review"] = function (content) {
    load("data/findings.json").then(function (f) {
      var sources = sourceIndex(f);
      content.appendChild(el("p", { class: "notice", text: f.repo_review.intro }));
      var holder = el("div");
      content.appendChild(holder);
      table(holder, [
        { key: "id", label: "ID" },
        { key: "item", label: "Item" },
        { key: "finding", label: "Finding" },
        { key: "status", label: "Status", render: function (r) { return badge(r.status, statusKind(r.status)); } },
        { key: "src", label: "Sources", sortable: false, render: function (r) { return srcLinks(r.src, sources); } }
      ], f.repo_review.rows, { searchPlaceholder: "Filter repo checks…" });
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };

  R.flagged = function (content) {
    load("data/findings.json").then(function (f) {
      var sources = sourceIndex(f);
      content.appendChild(el("div", { class: "banner warn" }, [el("strong", { text: "Flagged for Review. " }), f.flagged.intro]));
      var holder = el("div");
      content.appendChild(holder);
      table(holder, [
        { key: "id", label: "ID" },
        { key: "type", label: "Type" },
        { key: "item", label: "Item" },
        { key: "detail", label: "Detail" },
        { key: "action", label: "Reviewer action" },
        { key: "src", label: "Sources", sortable: false, render: function (r) { return srcLinks(r.src, sources); } }
      ], f.flagged.rows, { searchPlaceholder: "Filter flagged items…" });
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };

  R.sources = function (content) {
    load("data/findings.json").then(function (f) {
      content.appendChild(el("p", { class: "notice", text: "Status 'opened' = the page or API response was read in this session. 'listed only' = the URL is named by an official index but its content was not opened. 'search result only' = third-party, used only to flag a disagreement." }));
      var holder = el("div");
      content.appendChild(holder);
      table(holder, [
        { key: "id", label: "ID" },
        { key: "label", label: "Source", render: function (r) { return link(r.url, r.label, "srcid"); } },
        { key: "status", label: "Read status", render: function (r) { return badge(r.status, r.status === "opened" ? "ok" : (r.status === "listed only" ? "warn" : "bad")); } },
        { key: "supports", label: "What it supports" },
        { key: "url", label: "URL", render: function (r) { return el("code", { class: "small", text: r.url }); } }
      ], f.sources.rows, { searchPlaceholder: "Filter sources…" });
    }).catch(function (e) { content.appendChild(el("p", { class: "error", text: "Could not load data: " + e.message })); });
  };

  /* ---------- boot ---------- */
  function nav() {
    var host = document.getElementById("site-nav");
    if (!host) return;
    var here = window.location.pathname.split("/").pop() || "index.html";
    var ul = el("ul", { class: "nav-list" });
    NAV.forEach(function (item) {
      var file = item.href.split("/").pop();
      var a = el("a", { href: PREFIX + item.href, text: item.label, class: file === here ? "active" : "" });
      ul.appendChild(el("li", null, [a]));
    });
    host.appendChild(el("div", { class: "brand" }, [el("a", { href: PREFIX + "index.html", text: "Kalshi market dashboard" }), el("span", { class: "muted small", text: "Demo3 · data via Kalshi public API" })]));
    host.appendChild(ul);
  }

  document.addEventListener("DOMContentLoaded", function () {
    nav();
    var page = document.body.getAttribute("data-page") || "index";
    var content = document.getElementById("content");
    if (content && R[page]) R[page](content);
  });

  // exposed for the static checker
  window.KALSHI_NAV = NAV;
})();
