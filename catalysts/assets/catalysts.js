/* Kalshi Demo Tracker — swing & catalyst ledger.
 *
 * Renders the committed snapshot written by catalysts/scan.py, then optionally
 * re-polls the same markets live from the official demo API in this browser:
 *   GET https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=…
 * (public market data needs no key — https://docs.kalshi.com/getting_started/quick_start_market_data.md)
 *
 * Rules mirror the Python layer exactly so the page and the data agree:
 *   - swing: |last - previous| >= $0.10 in either direction, integer 1/100-cent units
 *   - a market stops being polled once the API reports it settled with a result
 *   - nothing is inferred: absent values render as an em dash with a flag
 *
 * No framework, no build step, no external requests other than the demo API.
 */
(function () {
  "use strict";

  var API = "https://external-api.demo.kalshi.co/trade-api/v2";
  var ALT_API = "https://demo-api.kalshi.co/trade-api/v2";
  var SWING_UNITS = 1000;            // $0.10 in 1/10000-dollar units
  var TICKERS_PER_REQUEST = 30;

  var state = {
    doc: null, status: null, health: null, endpoints: null,
    tape: {},                       // ticker -> [{ts, price(units), origin}]
    orderbooks: null,
    swings: [],
    topic: "all", dir: "all", link: "all",   // set by the segmented filters
    window: 1800,
    selected: null,
    live: {},                       // ticker -> latest live fields
    samples: {},                    // ticker -> in-browser samples
    watchTimer: null,
    candles: null
  };

  // ------------------------------------------------------------------ helpers
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function units(dollars) {
    if (dollars === null || dollars === undefined || dollars === "") return null;
    var n = Number(dollars);
    if (!isFinite(n)) return null;
    return Math.round(n * 10000);
  }
  function money(u) {
    if (u === null || u === undefined) return "\u2014";
    var text = (u / 10000).toFixed(4);
    while (text.length > text.indexOf(".") + 3 && text.slice(-1) === "0") text = text.slice(0, -1);
    return "$" + text;                       // 2 decimals minimum: $0.10, $0.6500-style extra kept
  }
  function cents(u) { return u === null || u === undefined ? "\u2014" : (u / 100).toFixed(2) + "\u00a2"; }
  function fmtTime(iso, spanSeconds) {
    var d = new Date(iso);
    if (isNaN(d)) return "\u2014";
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    var hms = p(d.getUTCHours()) + ":" + p(d.getUTCMinutes()) + ":" + p(d.getUTCSeconds());
    var hm = p(d.getUTCHours()) + ":" + p(d.getUTCMinutes());
    if (!spanSeconds) return hms;
    if (spanSeconds <= 600) return hms;
    if (spanSeconds <= 4 * 3600) return hm;
    var mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return mon[d.getUTCMonth()] + " " + d.getUTCDate() + " " + hm + "Z";
  }
  function flag(text, title) {
    return "<span class=\"flag\" title=\"" + esc(title || text) + "\">" + esc(text) + "</span>";
  }
  function srcLink(url, label) {
    if (!url) return flag("\u2014", "no source URL in the data — unverified");
    return "<a class=\"src\" href=\"" + esc(url) + "\" target=\"_blank\" rel=\"noopener\">" +
      esc(label || "source") + "</a>";
  }

  function banner(msg, kind) {
    var el = $("banner");
    if (!el) return;
    el.hidden = false;
    el.className = "banner " + (kind || "info");
    el.innerHTML = msg;
  }

  async function getJSON(url) {
    var r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(url + " -> HTTP " + r.status);
    return r.json();
  }
  async function getText(url) {
    var r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(url + " -> HTTP " + r.status);
    return r.text();
  }

  // ------------------------------------------------------------------- load
  async function loadSnapshot() {
    var jobs = await Promise.allSettled([
      getJSON("data/swings.json"),
      getJSON("data/status.json"),
      getJSON("data/feed_health.json"),
      getJSON("data/endpoints.json"),
      getText("../data/history/prices.jsonl"),
      getText("data/tape.jsonl"),
      getJSON("../data/latest/orderbooks.json"),
      getJSON("data/strategies.json")
    ]);
    state.doc = jobs[0].status === "fulfilled" ? jobs[0].value : null;
    state.status = jobs[1].status === "fulfilled" ? jobs[1].value : null;
    state.health = jobs[2].status === "fulfilled" ? jobs[2].value : null;
    state.endpoints = jobs[3].status === "fulfilled" ? jobs[3].value : null;
    if (jobs[4].status === "fulfilled") readTape(jobs[4].value, "data/history/prices.jsonl");
    if (jobs[5].status === "fulfilled") readTape(jobs[5].value, "catalysts/data/tape.jsonl");
    if (jobs[6].status === "fulfilled") state.orderbooks = jobs[6].value;
    state.strategies = jobs[7].status === "fulfilled" ? jobs[7].value : null;
    if (!state.doc) {
      banner("<strong>Snapshot unavailable.</strong> <span class='mono'>catalysts/data/swings.json</span> " +
             "could not be read, so the ledger is empty. Nothing is substituted from memory.", "err");
      return;
    }
    if (jobs[0].status === "rejected") {
      banner("<strong>Snapshot could not be parsed.</strong> Nothing is substituted.", "err");
    }
    state.swings = (state.doc.swings || []).slice();
    renderAll();
  }

  function readTape(text, origin) {
    (text || "").split("\n").forEach(function (line) {
      line = line.trim();
      if (!line) return;
      var rec;
      try { rec = JSON.parse(line); } catch (e) { return; }
      var u = units(rec.last_price_dollars);
      if (!rec.ticker || u === null || !rec.ts) return;
      var arr = state.tape[rec.ticker] = state.tape[rec.ticker] || [];
      if (arr.some(function (p) { return p.ts === rec.ts; })) return;
      arr.push({ ts: rec.ts, price: u, origin: origin,
                 bid: units(rec.yes_bid_dollars), ask: units(rec.yes_ask_dollars) });
    });
    Object.keys(state.tape).forEach(function (k) {
      state.tape[k].sort(function (a, b) { return a.ts < b.ts ? -1 : 1; });
    });
  }

  // --------------------------------------------------------------- rendering
  function renderAll() {
    renderStatus();
    renderLedger();
    renderStrategies();
    renderFeeds();
    renderEndpoints();
    if (!state.selected) selectFirstVisible();
    drawChart();
  }

  function renderStatus() {
    var d = state.doc || {}, st = state.status || {};
    var win = d.window_minutes || {};
    var chips = [
      ["Threshold", "≥ $0.10 per contract, either direction"],
      ["Swings published", String((d.swings || []).length)],
      ["With candidate link", String((d.swings || []).filter(function (s) {
        return (s.catalysts || []).length;
      }).length)],
      ["Run mode", st.mode || d.mode || "\u2014"],
      ["API root", shortHost(d.api_root || API)],
      ["Requests", st.requests !== undefined ? String(st.requests) : "\u2014"],
      ["Errors", st.request_errors !== undefined ? String(st.request_errors) : "\u2014"],
      ["Feed probe", st.feeds_ok !== undefined ? st.feeds_ok + " / " + st.feeds_total : "not run"],
      ["Link window", (win.pre !== undefined ? "-" + win.pre + " min / +" + win.post + " min" : "\u2014")],
      ["Snapshot", st.finished_at || d.generated_at || "\u2014"]
    ];
    $("statusChips").innerHTML = chips.map(function (c) {
      return "<span class=\"chip\"><b>" + esc(c[0]) + "</b> " + esc(c[1]) + "</span>";
    }).join("");
    var notes = [];
    if (d.disclaimer) notes.push(esc(d.disclaimer));
    if (d.link_root_note) notes.push("<em>" + esc(d.link_root_note) + "</em>");
    if ((st.mode || "").indexOf("offline") === 0) {
      notes.push("This snapshot was produced without network access (the build sandbox cannot " +
                 "reach the demo API), so live prices and feed matches are pending the next " +
                 "scheduled run. Blank cells stay blank.");
    }
    $("statusNote").innerHTML = notes.join(" ");
    $("thresholdLabel").textContent = "≥ $" + (d.threshold_dollars || "0.10");
  }
  function shortHost(u) {
    try { return new URL(u).host; } catch (e) { return String(u || "\u2014"); }
  }

  function visibleSwings() {
    return (state.swings || []).filter(function (s) {
      if (state.topic !== "all" && (s.topic || "other") !== state.topic) return false;
      if (state.dir !== "all" && s.direction !== state.dir) return false;
      var has = (s.catalysts || []).length > 0;
      if (state.link === "with" && !has) return false;
      if (state.link === "without" && has) return false;
      return true;
    });
  }

  function renderLedger() {
    var rows = visibleSwings();
    $("rowCount").textContent = rows.length + " of " + (state.swings || []).length + " swings";
    var body = $("ledger").tBodies[0];
    if (!rows.length) {
      body.innerHTML = "<tr><td colspan=\"8\" class=\"muted\">No swing matches this filter in the " +
        "committed snapshot. The demo exchange is thin: an empty ledger is a real result, not a gap " +
        "to fill.</td></tr>";
      return;
    }
    body.innerHTML = rows.map(function (s, i) {
      var live = state.live[s.ticker];
      var move = units(s.abs_delta_dollars);
      var arrow = s.direction === "up" ? "\u25b2" : "\u25bc";
      var links = (s.catalysts || []).map(function (c) {
        return "<li><a href=\"" + esc(c.link) + "\" target=\"_blank\" rel=\"noopener\">" +
          esc(c.title || "(untitled item)") + "</a> <span class=\"small muted\">" +
          esc(fmtTime(c.published_ts)) + " \u00b7 " + esc(c.feed_name || "\u2014") +
          (c.matched_keywords && c.matched_keywords.length
            ? " \u00b7 keywords: " + esc(c.matched_keywords.join(", ")) : "") +
          (typeof c.lead_seconds === "number"
            ? " \u00b7 " + (c.lead_seconds >= 0 ? "before swing " + Math.round(c.lead_seconds / 60) + " min"
                                               : "after swing " + Math.round(-c.lead_seconds / 60) + " min")
            : "") + "</span></li>";
      }).join("");
      var matchNote = s.catalyst_match && s.catalyst_match.match_status &&
                      s.catalyst_match.match_status !== "matched"
        ? flag(s.catalyst_match.match_status,
               "no qualifying feed item — nothing is inferred. Reason code from the scan.")
        : "";
      var res = s.resolution_label
        ? "<span class=\"res " + (s.resolution_label === "YES" ? "yes" : "no") + "\">" +
          esc(s.resolution_label) + "</span>" +
          (s.settlement_ts ? "<div class=\"small muted\">" + esc(s.settlement_ts) + "</div>" : "") +
          (s.settlement_value_dollars ? "<div class=\"small muted\">payout " +
            esc(s.settlement_value_dollars) + "$/contract</div>" : "")
        : flag("open", "no result reported by the API yet — tracking continues");
      var series = s.series || {};
      var official = (series.settlement_sources || []).map(function (x) {
        return "<a href=\"" + esc(x.url) + "\" target=\"_blank\" rel=\"noopener\">" +
          esc(x.name || "source") + "</a>";
      }).join(", ");
      return "<tr data-i=\"" + i + "\">" +
        "<td><span class=\"tag " + esc(s.topic || "other") + "\">" + esc(s.topic || "other") + "</span></td>" +
        "<td><button class=\"linkish\" data-sel=\"" + esc(s.id) + "\">" +
          esc(s.title || s.ticker) + "</button>" +
          "<div class=\"small muted mono\">" + esc(s.ticker) + "</div>" +
          "<div class=\"small muted\">" + esc(s.record_source || "\u2014") + "</div></td>" +
        "<td class=\"" + (s.direction === "up" ? "up" : "down") + "\"><strong>" + arrow + " " +
          money(move) + "</strong><div class=\"small muted\">" +
          (typeof s.sample_gap_seconds === "number" ? "over " + fmtGap(s.sample_gap_seconds)
           : flag("\u2014", "no sample gap recorded")) + "</div></td>" +
        "<td class=\"small mono\">" + money(units(s.from && s.from.last_price_dollars)) + " \u2192 " +
          money(units(s.to && s.to.last_price_dollars)) +
          "<div class=\"muted\">" + esc(fmtTime(s.from && s.from.ts, s.sample_gap_seconds)) +
          " \u2192 " + esc(fmtTime(s.to && s.to.ts, s.sample_gap_seconds)) + "</div></td>" +
        "<td>" + res + "</td>" +
        "<td class=\"mono\">" + (live ? money(units(live.price)) +
            (live.ts ? "<div class=\"small muted\">" + esc(fmtTime(live.ts)) + "</div>" : "")
          : flag("\u2014", "not polled in this browser yet — tick the live watch box")) + "</td>" +
        "<td>" + (links ? "<ul class=\"cats\">" + links + "</ul>" : "") + matchNote +
          (s.catalyst_match && s.catalyst_match.note ? "<div class=\"small muted\">" +
            esc(s.catalyst_match.note) + "</div>" : "") + "</td>" +
        "<td class=\"small\">" +
          srcLink(s.links && s.links.market_api_url, "market") + " " +
          srcLink(s.links && s.links.event_api_url, "event") + " " +
          srcLink(series.source_url, "series") +
          (official ? "<div class=\"small muted\">official sources: " + official + "</div>" : "") +
          (s.links && s.links.kalshi_market_page
            ? "<div class=\"small\">" + srcLink(s.links.kalshi_market_page, "demo desk page") + "</div>" : "") +
        "</td></tr>";
    }).join("");
    Array.prototype.forEach.call(body.querySelectorAll("[data-sel]"), function (btn) {
      btn.addEventListener("click", function () {
        selectById(btn.getAttribute("data-sel"));
      });
    });
  }

  function fmtGap(sec) {
    if (sec < 120) return sec + " s";
    if (sec < 7200) return (sec / 60).toFixed(1) + " min";
    return (sec / 3600).toFixed(1) + " h";
  }

  function renderStrategies() {
    var d = state.strategies;
    if (!d) return;
    var min = d.min_n_for_a_claim || 0;
    $("strategyMin").textContent = "evaluation floor: n \u2265 " + min;
    var rules = {};
    (d.strategies || []).forEach(function (x) { rules[x.id] = x; });
    var rows = d.results || [];
    if (!rows.length) {
      $("strategies").tBodies[0].innerHTML =
        "<tr><td colspan=\"8\" class=\"muted\">Nothing scoreable yet: " +
        esc(JSON.stringify(d.skipped_observations || {})) +
        " observation(s) were skipped because the source record lacked the field the exit needs. " +
        "Nothing is derived or estimated to fill the gap.</td></tr>";
      $("strategyNote").textContent = d.skipped_note || "";
      return;
    }
    $("strategies").tBodies[0].innerHTML = rows.map(function (r) {
      var rule = rules[r.strategy] || {};
      var verdict = r.evaluable
        ? "<span class=\"res yes\">\u2265 " + min + " trades \u00b7 computed</span>"
        : flag("not evaluable (n=" + r.n + " < " + min + ")",
               "sample floor from the scan; no expectancy claim is made below it");
      var audit = (r.markets || []).map(function (m) {
        return srcLink(m.market_api_url, m.ticker + " " + (m.pnl_dollars || "") + "$");
      }).join(" ") || flag("\u2014", "no market links recorded for this category");
      return "<tr><td><strong>" + esc(rule.name || r.strategy) + "</strong>" +
        "<div class=\"small muted\">entry: " + esc(rule.entry_rule || "\u2014") + "</div>" +
        "<div class=\"small muted\">exit: " + esc(rule.exit_rule || "\u2014") + "</div></td>" +
        "<td><span class=\"tag " + esc((r.category || "").split("/")[0]) + "\">" +
          esc(r.category) + "</span></td>" +
        "<td class=\"mono\">" + esc(r.n) + "</td>" +
        "<td class=\"mono\">" + esc(r.wins) + " / " + esc(r.losses) + " / " + esc(r.pushes) + "</td>" +
        "<td class=\"mono\">" + esc(r.mean_pnl_dollars_per_contract) + "</td>" +
        "<td class=\"mono\">" + esc(r.net_pnl_dollars_per_contract) + "</td>" +
        "<td>" + verdict + "</td><td class=\"small\">" + audit + "</td></tr>";
    }).join("");
    var notes = [d.disclaimer || ""];
    if (d.skipped_observations) {
      notes.push("skipped observations: " + JSON.stringify(d.skipped_observations) +
                 " \u2014 " + (d.skipped_note || ""));
    }
    $("strategyNote").textContent = notes.filter(Boolean).join(" ");
  }

  function renderFeeds() {
    var h = state.health && state.health.feeds;
    if (!h) return;
    $("feeds").tBodies[0].innerHTML = h.map(function (f) {
      var ok = f.ok && f.items_parsed > 0;
      return "<tr><td>" + esc(f.name || "\u2014") + "</td>" +
        "<td class=\"small\">" + (f.topics && f.topics.length
          ? f.topics.map(function (t) { return "<span class=\"tag " + esc(t) + "\">" + esc(t) + "</span>"; }).join(" ")
          : flag("\u2014", "feed declares no topic list")) + "</td>" +
        "<td>" + (typeof f.items_parsed === "number" ? esc(f.items_parsed) : flag("\u2014", "unparsed")) + "</td>" +
        "<td>" + (ok ? "<span class=\"res yes\">usable</span>"
                      : "<span class=\"res no\">not usable</span>") +
          (f.error ? "<div class=\"small muted\">" + esc(String(f.error)).slice(0, 160) + "</div>" : "") + "</td>" +
        "<td class=\"small mono\">" + esc(f.checked_at || "\u2014") + "</td>" +
        "<td>" + srcLink(f.url, "probe") + "</td></tr>";
    }).join("");
  }

  function renderEndpoints() {
    var list = state.endpoints && state.endpoints.endpoints;
    if (!list) return;
    $("endpoints").tBodies[0].innerHTML = list.map(function (e) {
      var extra = [];
      if (typeof e.item_count === "number") extra.push("items: " + e.item_count);
      if (e.filter_honoured === false) extra.push("<span class=\"flag\">filter ignored by this deployment</span>");
      if (e.filter_honoured === true) extra.push("filter honoured");
      return "<tr><td class=\"small mono\">" + esc(e.method + " " + e.url.replace(/^https?:\/\/[^/]+/, "")) + "</td>" +
        "<td class=\"small\">" + esc(e.purpose) + (extra.length ? "<div class=\"muted\">" + extra.join(" \u00b7 ") + "</div>" : "") + "</td>" +
        "<td>" + (e.http_status ? esc(e.http_status) : flag("\u2014", "not probed in this run")) + "</td>" +
        "<td>" + srcLink(e.doc, "docs") + "</td>" +
        "<td>" + srcLink(e.url, "url") + "</td></tr>";
    }).join("");
  }

  // ------------------------------------------------------------------- chart
  function selectFirstVisible() {
    var rows = visibleSwings();
    state.selected = rows.length ? rows[0].id : null;
  }
  function selectById(id) {
    state.selected = id;
    state.candles = null;
    renderLedger();
    drawChart();
    $("chartCard").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function selectedSwing() {
    var list = state.swings || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === state.selected) return list[i];
    return null;
  }

  function seriesPoints(ticker) {
    var out = [];
    (state.tape[ticker] || []).forEach(function (p) {
      out.push({ ts: p.ts, price: p.price, kind: p.origin });
    });
    (state.samples[ticker] || []).forEach(function (p) { out.push(p); });
    (state.candles && state.candles.ticker === ticker ? state.candles.points : []).forEach(function (p) {
      if (!out.some(function (x) { return x.ts === p.ts; })) out.push(p);
    });
    out.sort(function (a, b) { return a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0; });
    return out;
  }

  function drawChart() {
    var cv = $("priceChart");
    var s = selectedSwing();
    var ctx = cv && cv.getContext ? cv.getContext("2d") : null;
    if (!ctx) {
      // No 2D canvas (very old browser, or a headless render test): the ledger and the
      // catalyst links below still carry every value, so nothing is hidden.
      $("chartState").textContent = "canvas unavailable in this browser — the ledger below " +
        "carries the same values";
      if (s) { renderCatalystBox(s); renderBook(s.ticker); }
      return;
    }
    var dpr = window.devicePixelRatio || 1;
    var w = cv.clientWidth || 900, h = cv.height || 280;
    cv.width = w * dpr; cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    if (!s) {
      ctx.fillStyle = "#8a8f98";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText("No market selected.", 12, 24);
      $("chartTitle").textContent = "No market selected.";
      $("chartCatalysts").innerHTML = "";
      $("bookBox").innerHTML = "Select a market to see contracts available at each price.";
      return;
    }
    var pts = seriesPoints(s.ticker);
    var nowMs = Date.now();
    var anchor = s.to && s.to.ts ? new Date(s.to.ts).getTime() : nowMs;
    var fromMs = anchor - state.window * 1000;
    var winPts = pts.filter(function (p) {
      var t = new Date(p.ts).getTime();
      return t >= fromMs && t <= nowMs;
    });
    $("chartTitle").innerHTML = "<strong>" + esc(s.title || s.ticker) + "</strong> " +
      "<span class='mono small muted'>" + esc(s.ticker) + "</span>";
    $("chartSource").innerHTML = "chart data: " +
      (winPts.length ? winPts.length + " samples (price tape" +
        (state.candles && state.candles.ticker === s.ticker ? " + candles" : "") + ")"
        : "no samples inside this window — showing the ledger point only");

    var marks = (state.swings || []).filter(function (x) { return x.ticker === s.ticker; });
    if (!winPts.length) {
      winPts = [{ ts: s.from.ts, price: units(s.from.last_price_dollars) },
                { ts: s.to.ts, price: units(s.to.last_price_dollars) }].filter(function (p) {
        return p.price !== null;
      });
      marks = [s];
    }
    if (!winPts.length) {
      ctx.fillStyle = "#8a8f98";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText("No price samples available for this market.", 12, 24);
      renderCatalystBox(s);
      renderBook(s.ticker);
      return;
    }

    var xs = winPts.map(function (p) { return new Date(p.ts).getTime(); });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    if (maxX - minX < 1000) maxX = minX + 1000;
    var ys = winPts.map(function (p) { return p.price; });
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    if (maxY === minY) { maxY += 10000; minY = Math.max(0, minY - 10000); }
    var padY = (maxY - minY) * 0.15;
    minY = Math.max(0, minY - padY); maxY = Math.min(1000000, maxY + padY);

    var pad = { l: 52, r: 12, t: 12, b: 26 };
    var X = function (t) { return pad.l + (t - minX) / (maxX - minX) * (w - pad.l - pad.r); };
    var Y = function (v) { return h - pad.b - (v - minY) / (maxY - minY) * (h - pad.t - pad.b); };

    // grid + y labels (cents)
    ctx.strokeStyle = "#e8eaee"; ctx.fillStyle = "#6b7280";
    ctx.font = "11px system-ui, sans-serif"; ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      var val = minY + (maxY - minY) * g / 4;
      var yy = Y(val);
      ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(w - pad.r, yy); ctx.stroke();
      ctx.fillText(cents(Math.round(val)), 6, yy + 3);
    }
    // x labels
    var ticks = 5, span = (maxX - minX) / 1000;
    for (var t2 = 0; t2 <= ticks; t2++) {
      var tx = minX + (maxX - minX) * t2 / ticks;
      ctx.fillText(fmtTime(new Date(tx).toISOString(), span), X(tx) - 18, h - 8);
    }
    // price line
    ctx.strokeStyle = "#1f6feb"; ctx.lineWidth = 1.8; ctx.beginPath();
    winPts.forEach(function (p, i) {
      var x = X(new Date(p.ts).getTime()), y = Y(p.price);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    // points
    ctx.fillStyle = "#1f6feb";
    winPts.forEach(function (p) {
      ctx.beginPath();
      ctx.arc(X(new Date(p.ts).getTime()), Y(p.price), 2.2, 0, Math.PI * 2);
      ctx.fill();
    });
    // swing markers
    state._markers = [];
    marks.forEach(function (m) {
      var t = new Date(m.to && m.to.ts).getTime();
      if (!(t >= minX - 1 && t <= maxX + 1)) return;
      var x = X(t), y = Y(units(m.to && m.to.last_price_dollars));
      if (y === null || !isFinite(y)) return;
      ctx.beginPath();
      ctx.moveTo(x, y - (m.direction === "up" ? 12 : 4));
      ctx.lineTo(x - 6, y - (m.direction === "up" ? 22 : 14));
      ctx.lineTo(x + 6, y - (m.direction === "up" ? 22 : 14));
      ctx.closePath();
      ctx.fillStyle = m.direction === "up" ? "#0a7d33" : "#c0392b";
      ctx.fill();
      state._markers.push({ x: x, y: y, id: m.id });
    });
    renderCatalystBox(s);
    renderBook(s.ticker);
  }

  function renderCatalystBox(s) {
    var box = $("chartCatalysts");
    var cats = s.catalysts || [];
    if (!cats.length) {
      var why = (s.catalyst_match && s.catalyst_match.match_status) || "unknown";
      box.innerHTML = "<p class=\"small\">" + flag("no candidate catalyst link",
        "reason code: " + why) + " <span class='muted'>reason code <span class='mono'>" +
        esc(why) + "</span> — " + esc((s.catalyst_match && s.catalyst_match.note) ||
        "the scan found no feed item published inside this swing window that shares keywords " +
        "with the market; nothing is inferred.") + "</span></p>";
      return;
    }
    box.innerHTML = "<h3>Candidate catalysts for this swing</h3><ul class=\"cats big\">" +
      cats.map(function (c) {
        return "<li><a href=\"" + esc(c.link) + "\" target=\"_blank\" rel=\"noopener\">" +
          esc(c.title || c.link) + "</a><div class=\"small muted\">published " +
          esc(c.published_ts || "\u2014") + " \u00b7 feed " + esc(c.feed_name || "\u2014") +
          " \u00b7 " + (c.lead_seconds >= 0 ? c.lead_seconds + " s before the sample"
                                            : (-c.lead_seconds) + " s after") +
          " \u00b7 keywords " + esc((c.matched_keywords || []).join(", ") || "\u2014") + "</div>" +
          "<div class=\"small muted\">feed record: " + srcLink(c.feed_url, "feed URL") + "</div></li>";
      }).join("") + "</ul>";
  }

  function renderBook(ticker) {
    var box = $("bookBox");
    var live = state.live[ticker];
    var book = state.orderbooks && state.orderbooks.orderbooks &&
               state.orderbooks.orderbooks[ticker];
    var rows = [];
    if (book) {
      ["yes_dollars", "no_dollars"].forEach(function (side) {
        (book[side] || []).forEach(function (lvl) {
          rows.push({ side: side === "yes_dollars" ? "YES" : "NO",
                      price: lvl[0], size: lvl[1] });
        });
      });
    }
    var head = "<p class=\"small\">" +
      (book ? "Orderbook ladder from the committed snapshot (" +
              srcLink(book.source_url || state.orderbooks.doc, "orderbook API") + ")."
            : flag("no orderbook in the snapshot for this market",
                   "the collector stores ladders for its top markets only; nothing is simulated")) +
      (live ? " Live best: YES bid " + money(units(live.yes_bid_dollars)) +
              " / ask " + money(units(live.yes_ask_dollars)) + " (poll " + esc(live.ts) + ")"
            : " Live best: " + flag("\u2014", "not polled in this browser yet")) + "</p>";
    if (!rows.length) { box.innerHTML = head; return; }
    rows.sort(function (a, b) { return Number(b.size) - Number(a.size); });
    box.innerHTML = head + "<div class=\"tablewrap\"><table class=\"book\"><thead><tr>" +
      "<th>Side</th><th>Price</th><th>Contracts available</th></tr></thead><tbody>" +
      rows.slice(0, 12).map(function (r) {
        return "<tr><td>" + r.side + "</td><td class=\"mono\">$" + esc(r.price) +
          "</td><td class=\"mono\">" + esc(r.size) + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  // ------------------------------------------------------------- live watch
  async function pollOnce(manual) {
    var tickers = [];
    (state.swings || []).forEach(function (s) {
      if (tickers.indexOf(s.ticker) === -1) tickers.push(s.ticker);
    });
    if (!tickers.length) {
      $("watchState").textContent = "nothing to poll";
      return;
    }
    $("watchState").textContent = "polling…";
    var url = API + "/markets?tickers=" + tickers.slice(0, TICKERS_PER_REQUEST).join(",");
    var data;
    try {
      data = await (await fetch(url, { cache: "no-store" })).json();
    } catch (e) {
      try {
        url = ALT_API + "/markets?tickers=" + tickers.slice(0, TICKERS_PER_REQUEST).join(",");
        data = await (await fetch(url, { cache: "no-store" })).json();
      } catch (e2) {
        $("watchState").textContent = "blocked/failed";
        $("watchLog").textContent = "The browser could not reach the demo API (" +
          e2.message + "). Snapshot values remain untouched.";
        return;
      }
    }
    var markets = (data && data.markets) || [];
    var byTicker = {};
    markets.forEach(function (m) { byTicker[m.ticker] = m; });
    var fired = 0, resolved = 0;
    var nowIso = new Date().toISOString();
    markets.forEach(function (m) {
      var u = units(m.last_price_dollars);
      var prev = lastKnownPrice(m.ticker);
      state.live[m.ticker] = { price: m.last_price_dollars, ts: nowIso,
                               yes_bid_dollars: m.yes_bid_dollars,
                               yes_ask_dollars: m.yes_ask_dollars, status: m.status };
      if (u !== null) {
        var arr = state.samples[m.ticker] = state.samples[m.ticker] || [];
        if (!arr.length || arr[arr.length - 1].ts !== nowIso) {
          arr.push({ ts: nowIso, price: u, kind: "browser" });
        }
      }
      var settled = m.status === "finalized" || m.status === "settled" ||
                    (m.result === "yes" || m.result === "no");
      if (settled) {
        resolved++;
        pushNotice(m.ticker, "resolved " + (m.result ? m.result.toUpperCase() : "settled") +
          " \u00b7 payout " + (m.settlement_value_dollars || "\u2014") + "$ \u00b7 tracking stopped",
          url);
        markResolved(m);
      }
      if (prev !== null && u !== null && Math.abs(u - prev) >= SWING_UNITS) {
        fired++;
        pushAlert({ ticker: m.ticker, from: prev, to: u, ts: state.live[m.ticker].ts,
                    title: m.title || m.ticker, url: url, settled: settled });
      }
    });
    if (markets.length < tickers.length) {
      tickers.slice(0, TICKERS_PER_REQUEST).forEach(function (tk) {
        if (!byTicker[tk]) pushNotice(tk, "not returned by the open-market query \u00b7 " +
          "may have settled (check the event link in its ledger row)", url);
      });
    }
    $("watchState").textContent = markets.length + " markets \u00b7 " + fired + " swing(s) \u00b7 " +
      resolved + " resolved";
    $("watchLog").textContent = (manual ? "manual poll" : "auto poll") + " at " +
      new Date().toISOString().slice(11, 19) + "Z \u00b7 " +
      "<a class='mono' href=\"" + esc(url) + "\" target=\"_blank\" rel=\"noopener\">request URL</a>";
    renderLedger();
    drawChart();
  }

  function lastKnownPrice(ticker) {
    var arr = (state.tape[ticker] || []).concat(state.samples[ticker] || []);
    if (!arr.length) {
      for (var i = 0; i < (state.swings || []).length; i++) {
        var s = state.swings[i];
        if (s.ticker === ticker) return units(s.to && s.to.last_price_dollars);
      }
      return null;
    }
    return arr[arr.length - 1].price;
  }

  function markResolved(m) {
    (state.swings || []).forEach(function (s) {
      if (s.ticker !== m.ticker) return;
      s.resolved = true;
      s.tracking = "stopped_resolved";
      s.result = m.result || s.result;
      s.resolution_label = m.result === "yes" ? "YES" : m.result === "no" ? "NO" : s.resolution_label;
      s.settlement_ts = m.settlement_ts || s.settlement_ts;
      s.settlement_value_dollars = m.settlement_value_dollars || s.settlement_value_dollars;
    });
  }

  function pushAlert(a) {
    var box = $("watchAlerts");
    var up = a.to > a.from;
    var div = document.createElement("div");
    div.className = "alert " + (up ? "up" : "down");
    div.innerHTML = "<span class=\"when\">" + esc(a.ts.slice(11, 19)) + "Z</span> " +
      "<strong>" + (up ? "\u25b2" : "\u25bc") + " " + money(Math.abs(a.to - a.from)) + "</strong> " +
      "<a href=\"" + esc(API + "/markets/" + a.ticker) + "\" target=\"_blank\" rel=\"noopener\">" +
      esc(a.title) + "</a> <span class=\"mono small\">" + money(a.from) + " \u2192 " + money(a.to) +
      "</span>";
    box.insertBefore(div, box.firstChild);
    while (box.children.length > 60) box.removeChild(box.lastChild);
  }
  function pushNotice(ticker, text, url) {
    var box = $("watchAlerts");
    var div = document.createElement("div");
    div.className = "alert notice";
    div.innerHTML = "<span class=\"when\">" + new Date().toISOString().slice(11, 19) + "Z</span> " +
      "<span class=\"mono\">" + esc(ticker) + "</span> " + esc(text) + " " +
      srcLink(url, "request");
    box.insertBefore(div, box.firstChild);
    while (box.children.length > 60) box.removeChild(box.lastChild);
  }

  function setWatch(on) {
    if (state.watchTimer) { clearInterval(state.watchTimer); state.watchTimer = null; }
    if (!on) { $("watchState").textContent = "off"; return; }
    var every = Math.max(10, Number(($("pollEvery").value) || 30));
    state.watchTimer = setInterval(function () { pollOnce(false); }, every * 1000);
    $("watchState").textContent = "every " + every + " s";
    pollOnce(false);
  }

  async function loadCandles() {
    var s = selectedSwing();
    if (!s) return;
    var series = (s.series && s.series.series_ticker) || s.series_ticker;
    if (!series) {
      $("chartState").textContent = "no series ticker in the record — candle request skipped";
      return;
    }
    var end = Math.floor(Date.now() / 1000);
    var start = end - Math.max(state.window, 3600);
    var interval = state.window <= 4 * 3600 ? 1 : 60;
    var url = API + "/series/" + encodeURIComponent(series) + "/markets/" +
      encodeURIComponent(s.ticker) + "/candlesticks?start_ts=" + start + "&end_ts=" + end +
      "&period_interval=" + interval;
    $("chartState").textContent = "loading candles…";
    try {
      var data = await (await fetch(url, { cache: "no-store" })).json();
      var list = (data && (data.candlesticks || data.candles)) || [];
      var pts = list.map(function (c) {
        var t = c.timestamp || c.ts || c.updated_at;
        var close = c.close_dollars !== undefined ? c.close_dollars : (c.close / 100);
        return { ts: t ? new Date(t * (typeof t === "number" ? 1000 : 1)).toISOString()
                       : new Date(Date.now()).toISOString(),
                 price: units(close), kind: "candle " + interval + "m" };
      }).filter(function (p) { return p.price !== null && p.ts; });
      state.candles = { ticker: s.ticker, points: pts, url: url, interval: interval };
      $("chartState").innerHTML = pts.length + " candle(s) \u00b7 " +
        "<a href=\"" + esc(url) + "\" target=\"_blank\" rel=\"noopener\">request</a>";
      drawChart();
    } catch (e) {
      $("chartState").textContent = "candle request failed in this browser (" + e.message +
        "); the price tape is still shown";
    }
  }

  // ---------------------------------------------------------------- wiring
  function wireSeg(id, key, attr, after) {
    var el = $(id);
    if (!el) return;
    el.addEventListener("click", function (ev) {
      var btn = ev.target.closest("button");
      if (!btn) return;
      Array.prototype.forEach.call(el.querySelectorAll("button"), function (b) {
        b.classList.toggle("on", b === btn);
      });
      state[key] = btn.getAttribute(attr);
      if (after) after();
    });
  }

  function init() {
    wireSeg("topicFilter", "topic", "data-topic", function () {
      selectFirstVisible(); renderLedger(); drawChart();
    });
    wireSeg("dirFilter", "dir", "data-dir", function () {
      selectFirstVisible(); renderLedger(); drawChart();
    });
    wireSeg("linkFilter", "link", "data-link", function () {
      selectFirstVisible(); renderLedger(); drawChart();
    });
    wireSeg("windowPick", "window", "data-window", function () {
      state.window = Number(state.window) || 1800;
      state.candles = null;
      $("chartState").textContent = "";
      drawChart();
    });
    $("pollNow").addEventListener("click", function () { pollOnce(true); });
    $("watchToggle").addEventListener("change", function (e) { setWatch(e.target.checked); });
    $("pollEvery").addEventListener("change", function () {
      if ($("watchToggle").checked) setWatch(true);
    });
    $("candlesBtn").addEventListener("click", loadCandles);
    $("priceChart").addEventListener("click", function (ev) {
      var r = ev.target.getBoundingClientRect();
      var x = ev.clientX - r.left, y = ev.clientY - r.top, best = null, bd = 1e9;
      (state._markers || []).forEach(function (m) {
        var d = (m.x - x) * (m.x - x) + (m.y - y) * (m.y - y);
        if (d < bd) { bd = d; best = m; }
      });
      if (best && bd < 400) selectById(best.id);
    });
    loadSnapshot();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
