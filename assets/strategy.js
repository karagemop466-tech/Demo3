/* Strategy lab — cumulative net PnL chart for scripts/build_strategy_page.py.
 * Reads the same strategy/data/backtest.json that produced the page tables, so the
 * chart can never disagree with the numbers above it. No libraries, no network calls
 * beyond the one static JSON file in this repository.
 */
(function () {
  "use strict";

  var COLORS = ["#1f6feb", "#d29922", "#8250df", "#1a7f37", "#cf222e", "#0969da",
                "#bf3989", "#57606a"];
  var doc = null;

  function $(id) { return document.getElementById(id); }

  function fmtMoney(v) {
    var sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(v).toFixed(2);
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    return d.toISOString().slice(0, 16).replace("T", " ") + "Z";
  }

  function niceTicks(min, max, count) {
    if (min === max) { min -= 1; max += 1; }
    var span = max - min;
    var step = Math.pow(10, Math.floor(Math.log(span / count) / Math.LN10));
    var err = span / count / step;
    if (err >= 5) step *= 10; else if (err >= 2) step *= 5; else if (err >= 1) step *= 2;
    var ticks = [];
    for (var v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) {
      ticks.push(Math.round(v * 1e6) / 1e6);
    }
    return ticks;
  }

  function draw() {
    if (!doc) return;
    var dsKey = ($("eqDataset") || {}).value || "resolved";
    var fam = ($("eqFamily") || {}).value || "all";
    var ds = (doc.datasets || {})[dsKey];
    var svg = $("eqChart");
    var legend = $("eqLegend");
    var status = $("eqStatus");
    if (!ds || !svg) return;

    var series = (ds.strategies || []).filter(function (s) {
      return fam === "all" || s.family === fam;
    });
    var curves = (ds.equity_curves || {});

    var W = 900, H = 320, PADL = 64, PADR = 16, PADT = 12, PADB = 34;
    var xs = [], ys = [];
    series.forEach(function (s) {
      (curves[s.id] || []).forEach(function (p) { xs.push(p[0]); ys.push(p[1]); });
    });

    svg.innerHTML = "";
    if (!xs.length) {
      if (status) {
        status.textContent = "No simulated trades exist for this dataset/family, so there is " +
          "nothing to plot. An empty chart is shown instead of an invented line.";
      }
      if (legend) legend.textContent = "";
      return;
    }
    if (status) {
      status.textContent = xs.length + " plotted points across " + series.length +
        " strategies. Values are cumulative net PnL per 1-contract trade, after fees.";
    }

    var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
    var ymin = Math.min(0, Math.min.apply(null, ys)), ymax = Math.max(0, Math.max.apply(null, ys));
    if (ymin === ymax) { ymax += 1; }
    var pad = (ymax - ymin) * 0.06;
    ymin -= pad; ymax += pad;

    function sx(t) {
      return PADL + (xmax === xmin ? 0.5 : (t - xmin) / (xmax - xmin)) * (W - PADL - PADR);
    }
    function sy(v) {
      return PADT + (1 - (v - ymin) / (ymax - ymin)) * (H - PADT - PADB);
    }

    var ns = "http://www.w3.org/2000/svg";
    function el(name, attrs, text) {
      var e = document.createElementNS(ns, name);
      Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
      if (text !== undefined) e.textContent = text;
      svg.appendChild(e);
      return e;
    }

    // y grid + labels
    niceTicks(ymin, ymax, 5).forEach(function (v) {
      var y = sy(v);
      el("line", { x1: PADL, x2: W - PADR, y1: y, y2: y, stroke: "#e6e6e6", "stroke-width": 1 });
      el("text", { x: PADL - 8, y: y + 4, "text-anchor": "end", "font-size": 11, fill: "#57606a" },
        fmtMoney(v));
    });
    // zero line
    if (ymin < 0 && ymax > 0) {
      el("line", { x1: PADL, x2: W - PADR, y1: sy(0), y2: sy(0), stroke: "#8c959f",
                   "stroke-width": 1, "stroke-dasharray": "4 3" });
    }
    // x labels
    var xt = niceTicks(xmin, xmax, 4);
    xt.forEach(function (t) {
      el("text", { x: sx(t), y: H - 12, "text-anchor": "middle", "font-size": 11, fill: "#57606a" },
        fmtTime(t).slice(0, 10));
    });
    el("text", { x: W / 2, y: H - 1, "text-anchor": "middle", "font-size": 11, fill: "#57606a" },
      "x: exit time (UTC) · y: cumulative net PnL (USD, 1 contract, after fees)");

    var legendItems = [];
    series.forEach(function (s, i) {
      var pts = curves[s.id] || [];
      if (!pts.length) return;
      var colour = COLORS[i % COLORS.length];
      var d = pts.map(function (p, k) {
        return (k ? "L" : "M") + sx(p[0]).toFixed(1) + " " + sy(p[1]).toFixed(1);
      }).join(" ");
      var path = el("path", { d: d, fill: "none", stroke: colour, "stroke-width": 2,
                              "stroke-linejoin": "round" });
      var title = document.createElementNS(ns, "title");
      var last = pts[pts.length - 1];
      title.textContent = s.label + " — " + pts.length + " points, final " + fmtMoney(last[1]);
      path.appendChild(title);
      legendItems.push('<span style="color:' + colour + '">■</span> ' + s.label +
        ' <span class="muted">(' + pts.length + ' pts)</span>');
    });
    if (legend) legend.innerHTML = legendItems.join(" · ");
  }

  function boot() {
    var redraw = $("eqRedraw");
    if (redraw) redraw.addEventListener("click", draw);
    ["eqDataset", "eqFamily"].forEach(function (id) {
      var el = $(id);
      if (el) el.addEventListener("change", draw);
    });
    var url = "strategy/data/backtest.json";
    if (window.fetch) {
      fetch(url, { headers: { "Accept": "application/json" } })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (j) { doc = j; draw(); })
        .catch(function (e) {
          var status = $("eqStatus");
          if (status) {
            status.textContent = "Could not load " + url + " (" + e.message +
              "). The tables above are static and unaffected; only this chart is blank.";
          }
        });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
