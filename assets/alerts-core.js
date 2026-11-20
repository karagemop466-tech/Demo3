/* Swing-alert core (session 6d201d19). Pure functions shared by alerts.html and tests/alerts.test.js.
 * Mirrors scripts/price_alerts.py exactly:
 *  - SWING: consecutive observations of the same market whose last price differs by >= 0.10
 *    (compared in integer ten-thousandths to avoid floating-point drift).
 *  - HIGH-ROI SCREEN (PLACEHOLDER, not the user's model): the side made cheaper by the move;
 *    gross payout multiple (1 - p) / p on the bought price p must be >= 1.00, volume > 0,
 *    and the market must not be a synthetic exchange-test series.
 * Plain script (no module syntax) so it loads in the browser and under node:vm.
 */
var AlertsCore = (function () {
  var THRESHOLD_TICKS = 1000;           // 0.10 in ten-thousandths
  var SYNTHETIC_PREFIXES = ["KXDEMO", "KXQUICKSETTLE"];

  function toTicks(dollarStr) {
    // API dollar strings look like "0.3500". Parse to integer ten-thousandths; null if absent.
    if (dollarStr === null || dollarStr === undefined || dollarStr === "") return null;
    var s = String(dollarStr).trim();
    if (!/^-?\d+(\.\d+)?$/.test(s)) return null;
    var neg = s.charAt(0) === "-";
    if (neg) s = s.slice(1);
    var parts = s.split(".");
    var frac = (parts[1] || "").slice(0, 4);
    while (frac.length < 4) frac += "0";
    var v = parseInt(parts[0], 10) * 10000 + parseInt(frac, 10);
    return neg ? -v : v;
  }

  function fmtDollars(ticks) {
    if (ticks === null || ticks === undefined) return "";
    var sign = ticks < 0 ? "-" : "";
    var a = Math.abs(ticks);
    var whole = Math.floor(a / 10000);
    var frac = String(a % 10000);
    while (frac.length < 4) frac = "0" + frac;
    return sign + "$" + whole + "." + frac;
  }

  function fmtSigned(ticks) {
    return (ticks > 0 ? "+" : ticks < 0 ? "-" : "") + fmtDollars(Math.abs(ticks));
  }

  function isSynthetic(ticker) {
    var t = String(ticker || "").toUpperCase();
    for (var i = 0; i < SYNTHETIC_PREFIXES.length; i++) {
      if (t.indexOf(SYNTHETIC_PREFIXES[i]) === 0) return true;
    }
    return false;
  }

  // prevTicks / ticks: integers from toTicks. Returns null or {deltaTicks, direction}.
  function detectSwing(prevTicks, ticks) {
    if (prevTicks === null || prevTicks === undefined || ticks === null || ticks === undefined) return null;
    var d = ticks - prevTicks;
    if (Math.abs(d) < THRESHOLD_TICKS) return null;
    return { deltaTicks: d, direction: d > 0 ? "up" : "down" };
  }

  // Placeholder high-ROI screen. Returns {passes, side, boughtTicks, multiple}.
  function roiScreen(ticks, volumeFp, ticker, direction) {
    var out = { passes: false, side: "", boughtTicks: null, multiple: null };
    if (ticks === null || ticks === undefined || ticks <= 0 || ticks >= 10000) return out;
    var bought;
    if (direction === "up") { out.side = "YES"; bought = ticks; }
    else { out.side = "NO"; bought = 10000 - ticks; }
    out.boughtTicks = bought;
    out.multiple = (10000 - bought) / bought;   // gross payout multiple, e.g. 0.8182
    var vol = parseFloat(volumeFp);
    out.passes = out.multiple >= 1.0 && isFinite(vol) && vol > 0 && !isSynthetic(ticker);
    return out;
  }

  return {
    THRESHOLD_TICKS: THRESHOLD_TICKS,
    toTicks: toTicks,
    fmtDollars: fmtDollars,
    fmtSigned: fmtSigned,
    isSynthetic: isSynthetic,
    detectSwing: detectSwing,
    roiScreen: roiScreen
  };
})();
