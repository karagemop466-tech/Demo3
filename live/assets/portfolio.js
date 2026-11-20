/* Simulated portfolio page: draws one equity curve per strategy book from the
 * closed trades in live/data/portfolio.json. No data is invented here. */
(function () {
  "use strict";
  var D = window.Desk;
  document.addEventListener("DOMContentLoaded", function () {
    D.get("data/portfolio.json").then(function (j) {
      var byId = {};
      (j.books || []).forEach(function (b) { byId[b.id] = b; });
      Array.prototype.forEach.call(document.querySelectorAll("canvas[data-equity]"), function (c) {
        var b = byId[c.getAttribute("data-equity")];
        if (!b) return;
        c.setAttribute("data-ready", "1");
        function draw() { D.equityChart(c, b.equity_curve, b.bankroll); }
        draw();
        window.addEventListener("resize", draw);
      });
    }).catch(function (e) {
      console.warn("portfolio curves unavailable", e);
    });
  });
})();
