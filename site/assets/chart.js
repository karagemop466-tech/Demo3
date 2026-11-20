/* chart.js — dependency-free canvas charts for the dashboard.
 *
 * Deliberately hand-rolled: the site must work from GitHub Pages with no CDN, and a broken
 * <script> tag is exactly the kind of "broken site" this project must not merge.
 *
 * Chart.render(series) where series = [{points:[{x:epochMs,y:number,hi,lo,open,close}],type,label,color}]
 *   type 'line'  -> y from a numeric field
 *   type 'step'  -> held value between points (used for bid/ask)
 *   type 'candle'-> expects open/high/low/close per point
 *   type 'bar'   -> volume histogram pinned to the bottom 22% of the plot
 */
(function (global) {
  "use strict";

  var PAD = { l: 62, r: 14, t: 12, b: 30 };

  function Chart(canvas, opts) {
    this.c = typeof canvas === "string" ? document.querySelector(canvas) : canvas;
    this.o = Object.assign({ yMin: 0, yMax: 1, yFmt: function (v) { return "$" + v.toFixed(2); },
                             xFmt: null, title: "", height: 290, onHover: null, yFromData: false }, opts || {});
    this.hover = null;
    var self = this;
    this.c.addEventListener("mousemove", function (e) {
      var r = self.c.getBoundingClientRect();
      self.hover = { px: e.clientX - r.left, py: e.clientY - r.top, w: r.width, h: r.height };
      self.draw();
      if (self.o.onHover) self.o.onHover(self.pick(self.hover), self);
    });
    this.c.addEventListener("mouseleave", function () { self.hover = null; self.draw(); if (self.o.onHover) self.o.onHover(null, self); });
    global.addEventListener("resize", function () { self.draw(); });
  }

  Chart.prototype.setData = function (series, meta) {
    this.series = (series || []).filter(function (s) { return s && s.points && s.points.length; });
    this.meta = meta || {};
    this.draw();
    return this;
  };

  Chart.prototype.bounds = function () {
    var xs = [], ys = [];
    var ymin = Infinity, ymax = -Infinity, xmin = Infinity, xmax = -Infinity;
    this.series.forEach(function (s) {
      s.points.forEach(function (p) {
        if (p.x < xmin) xmin = p.x;
        if (p.x > xmax) xmax = p.x;
        [p.y, p.open, p.close, p.hi, p.lo].forEach(function (v) {
          if (typeof v !== "number" || !isFinite(v)) return;
          if (v < ymin) ymin = v;
          if (v > ymax) ymax = v;
        });
      });
    });
    if (!isFinite(xmin)) { xmin = 0; xmax = 1; }
    if (xmin === xmax) { xmax = xmin + 1000; }
    if (!isFinite(ymin)) { ymin = this.o.yMin; ymax = this.o.yMax; }
    if (!this.o.yFromData) { ymin = this.o.yMin; ymax = this.o.yMax; }
    else {
      var pad = Math.max((ymax - ymin) * 0.12, 0.01);
      ymin = Math.max(0, ymin - pad); ymax = Math.min(1, ymax + pad);
      if (ymax - ymin < 0.04) { var m = (ymax + ymin) / 2; ymin = Math.max(0, m - 0.02); ymax = Math.min(1, m + 0.02); }
    }
    return { xmin: xmin, xmax: xmax, ymin: ymin, ymax: ymax };
  };

  Chart.prototype.geom = function () {
    var w = this.c.clientWidth, h = this.o.height;
    return { w: w, h: h, x0: PAD.l, x1: w - PAD.r, y0: PAD.t, y1: h - PAD.b };
  };

  Chart.prototype.xOf = function (x, b, g) { return g.x0 + (x - b.xmin) / (b.xmax - b.xmin) * (g.x1 - g.x0); };
  Chart.prototype.yOf = function (y, b, g) { return g.y1 - (y - b.ymin) / (b.ymax - b.ymin) * (g.y1 - g.y0); };

  Chart.prototype.pick = function (hover) {
    if (!hover || !this.series.length) return null;
    var b = this.bounds(), g = this.geom();
    var t = b.xmin + (hover.px - g.x0) / (g.x1 - g.x0) * (b.xmax - b.xmin);
    var best = null;
    this.series.forEach(function (s) {
      if (s.type === "bar") return;
      var lo = 0, hi = s.points.length - 1;
      while (hi - lo > 1) {
        var mid = (lo + hi) >> 1;
        if (s.points[mid].x < t) lo = mid; else hi = mid;
      }
      var cand = Math.abs(s.points[lo].x - t) < Math.abs(s.points[hi].x - t) ? s.points[lo] : s.points[hi];
      if (!best || Math.abs(cand.x - t) < Math.abs(best.p.x - t)) best = { s: s, p: cand };
    });
    return best ? { x: best.p.x, series: best.s, point: best.p } : null;
  };

  Chart.prototype.draw = function () {
    var c = this.c;
    if (!c) return;
    var dpr = global.devicePixelRatio || 1;
    var g = this.geom();
    c.width = Math.max(320, g.w) * dpr;
    c.height = this.o.height * dpr;
    var ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, g.w, this.o.height);
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, g.w, this.o.height);

    if (!this.series || !this.series.length) {
      ctx.fillStyle = "#7b8894";
      ctx.font = "13px system-ui";
      ctx.fillText(this.o.empty || "no data for this filter", g.x0 + 8, (g.y0 + g.y1) / 2);
      return;
    }
    var b = this.bounds();

    // grid + y ticks
    ctx.strokeStyle = "#eef1f4";
    ctx.fillStyle = "#7b8894";
    ctx.font = "11px ui-monospace,Menlo,monospace";
    ctx.lineWidth = 1;
    var ticks = 5;
    for (var i = 0; i <= ticks; i++) {
      var yv = b.ymin + (b.ymax - b.ymin) * (i / ticks);
      var y = Math.round(this.yOf(yv, b, g)) + 0.5;
      ctx.beginPath(); ctx.moveTo(g.x0, y); ctx.lineTo(g.x1, y); ctx.stroke();
      ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText(this.o.yFmt(yv), g.x0 - 8, y);
    }

    // x ticks
    var span = (b.xmax - b.xmin) / 1000;
    var n = 6;
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (var j = 0; j <= n; j++) {
      var xv = b.xmin + (b.xmax - b.xmin) * (j / n);
      var x = Math.round(this.xOf(xv, b, g)) + 0.5;
      ctx.strokeStyle = "#f2f5f8";
      ctx.beginPath(); ctx.moveTo(x, g.y0); ctx.lineTo(x, g.y1); ctx.stroke();
      ctx.fillStyle = "#7b8894";
      ctx.fillText(this.o.xFmt ? this.o.xFmt(xv, span) : fmtTime(xv, span), x, g.y1 + 7);
    }
    ctx.strokeStyle = "#e2e6eb";
    ctx.beginPath(); ctx.moveTo(g.x0, g.y1 + 0.5); ctx.lineTo(g.x1, g.y1 + 0.5); ctx.stroke();

    // series
    var self = this;
    this.series.forEach(function (s) {
      if (s.type === "candle") return drawCandles(ctx, s, b, g, self);
      if (s.type === "bar") return drawBars(ctx, s, b, g, self);
      drawLine(ctx, s, b, g, self);
    });

    // hover crosshair
    if (this.hover && this.hover.px > g.x0 && this.hover.px < g.x1) {
      ctx.strokeStyle = "#93a4b6";
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(Math.round(this.hover.px) + 0.5, g.y0); ctx.lineTo(Math.round(this.hover.px) + 0.5, g.y1); ctx.stroke();
      ctx.setLineDash([]);
      var pk = this.pick(this.hover);
      if (pk) {
        ctx.fillStyle = pk.s.color || "#0b62d6";
        ctx.beginPath(); ctx.arc(this.xOf(pk.p.x, b, g), this.yOf(pk.p.y, b, g), 3.2, 0, Math.PI * 2); ctx.fill();
      }
    }

    // legend
    if (this.series.length > 1 || this.o.showLegend) {
      var lx = g.x0 + 4, ly = g.y0 + 2;
      ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.font = "11.5px system-ui";
      this.series.forEach(function (s) {
        if (!s.label) return;
        ctx.fillStyle = s.color || "#0b62d6";
        ctx.fillRect(lx, ly + 3, 9, 9);
        ctx.fillStyle = "#495967";
        ctx.fillText(s.label, lx + 13, ly);
        lx += 22 + ctx.measureText(s.label).width;
      });
    }
  };

  function drawLine(ctx, s, b, g, ch) {
    ctx.lineWidth = s.width || 1.6;
    ctx.strokeStyle = s.color || "#0b62d6";
    if (s.fill) {
      ctx.beginPath();
      ctx.moveTo(ch.xOf(s.points[0].x, b, g), g.y1);
      s.points.forEach(function (p) { ctx.lineTo(ch.xOf(p.x, b, g), ch.yOf(p.y, b, g)); });
      ctx.lineTo(ch.xOf(s.points[s.points.length - 1].x, b, g), g.y1);
      ctx.closePath();
      ctx.fillStyle = s.fill;
      ctx.fill();
    }
    ctx.beginPath();
    s.points.forEach(function (p, i) {
      var x = ch.xOf(p.x, b, g), y = ch.yOf(p.y, b, g);
      if (i === 0) ctx.moveTo(x, y);
      else if (s.type === "step") { ctx.lineTo(x, ch.yOf(s.points[i - 1].y, b, g)); ctx.lineTo(x, y); }
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    if (s.dots && s.points.length < 160) {
      ctx.fillStyle = s.color || "#0b62d6";
      s.points.forEach(function (p) {
        ctx.beginPath(); ctx.arc(ch.xOf(p.x, b, g), ch.yOf(p.y, b, g), 1.9, 0, Math.PI * 2); ctx.fill();
      });
    }
  }

  function drawCandles(ctx, s, b, g, ch) {
    var n = s.points.length;
    var w = Math.max(1.5, Math.min(11, (g.x1 - g.x0) / Math.max(n, 1) * 0.62));
    s.points.forEach(function (p) {
      var x = ch.xOf(p.x, b, g);
      var up = (p.close === null || p.close === undefined) ? true : p.close >= (p.open === null || p.open === undefined ? p.close : p.open);
      var col = p.y === null || p.y === undefined ? "#c3ccd6" : (up ? "#0f7a3d" : "#a01c1c");
      if (typeof p.hi === "number" && typeof p.lo === "number") {
        ctx.strokeStyle = col; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, ch.yOf(p.hi, b, g)); ctx.lineTo(x, ch.yOf(p.lo, b, g)); ctx.stroke();
      }
      var yo = ch.yOf(p.open === null || p.open === undefined ? p.close : p.open, b, g);
      var yc = ch.yOf(p.close === null || p.close === undefined ? p.close : p.close, b, g);
      var top = Math.min(yo, yc), h = Math.max(1.2, Math.abs(yc - yo));
      ctx.fillStyle = col;
      ctx.fillRect(x - w / 2, top, w, h);
    });
  }

  function drawBars(ctx, s, b, g, ch) {
    var max = 0;
    s.points.forEach(function (p) { if (p.y > max) max = p.y; });
    if (!max) return;
    var bandTop = g.y0 + (g.y1 - g.y0) * 0.78;
    var w = Math.max(1, (g.x1 - g.x0) / Math.max(s.points.length, 1) * 0.6);
    ctx.fillStyle = s.color || "#c8d6e8";
    s.points.forEach(function (p) {
      var x = ch.xOf(p.x, b, g);
      var h = (p.y / max) * (g.y1 - bandTop);
      ctx.fillRect(x - w / 2, g.y1 - h, w, h);
    });
  }

  function fmtTime(ms, spanSec) {
    var d = new Date(ms);
    function p(n) { return (n < 10 ? "0" : "") + n; }
    if (spanSec <= 180) return p(d.getUTCHours()) + ":" + p(d.getUTCMinutes()) + ":" + p(d.getUTCSeconds());
    if (spanSec <= 3 * 3600) return p(d.getUTCHours()) + ":" + p(d.getUTCMinutes());
    if (spanSec <= 2 * 86400) return p(d.getUTCMonth() + 1) + "/" + p(d.getUTCDate()) + " " + p(d.getUTCHours()) + "h";
    return d.getUTCFullYear() + "-" + p(d.getUTCMonth() + 1) + "-" + p(d.getUTCDate());
  }

  /* --------------------------------------------------- liquidity ladder */
  /**
   * Renders "contracts available at a given price" from GET /markets/{t}/orderbook.
   * Bids only by design; the opposite side's implied ask is derived and labelled.
   * https://docs.kalshi.com/getting_started/orderbook_responses.md
   */
  function ladder(el, book, opts) {
    var host = typeof el === "string" ? document.querySelector(el) : el;
    if (!host) return;
    var yes = ((book || {}).orderbook_fp || {}).yes_dollars || [];
    var no = ((book || {}).orderbook_fp || {}).no_dollars || [];
    opts = opts || {};
    if (!yes.length && !no.length) {
      host.innerHTML = '<div class="empty">Book is empty. Note: the API also returns an empty book for an ' +
        'unknown ticker, so confirm the market with <a href="' + (opts.marketUrl || "#") + '">GET /markets/{ticker}</a>.</div>';
      return;
    }
    var maxQty = 0;
    yes.concat(no).forEach(function (l) { maxQty = Math.max(maxQty, K.num(l[1]) || 0); });
    function row(level, side) {
      var price = K.num(level[0]), qty = K.num(level[1]);
      var dollars = (price || 0) * (qty || 0);
      var w = maxQty ? Math.max(1.5, (qty || 0) / maxQty * 100) : 0;
      return '<div class="lvl ' + side + '"><span class="px">' + (price === null ? "—" : "$" + price.toFixed(4)) +
        '</span><span class="bar"><span style="--w:' + w.toFixed(1) + '%"></span></span>' +
        '<span class="qty">' + (qty === null ? "—" : qty.toLocaleString("en-US", { maximumFractionDigits: 2 })) +
        " <span class='sub'>ct</span></span></div>";
    }
    var bestNo = no.length ? K.num(no[no.length - 1][0]) : null;
    var bestYes = yes.length ? K.num(yes[yes.length - 1][0]) : null;
    var mid = '<div class="lvl mid">YES ask (implied) ' + (bestNo === null ? "—" : "$" + (1 - bestNo).toFixed(4)) +
      " · YES bid " + (bestYes === null ? "—" : "$" + bestYes.toFixed(4)) +
      " · spread " + (bestYes === null || bestNo === null ? "—" : "$" + (1 - bestNo - bestYes).toFixed(4)) + "</div>";
    host.innerHTML = '<div class="ladder">' +
      yes.slice().reverse().map(function (l) { return row(l, "yes"); }).join("") +
      mid +
      no.slice().reverse().map(function (l) { return row(l, "no"); }).join("") +
      "</div>";
  }

  global.Chart = Chart;
  global.Ladder = { render: ladder };
})(window);
