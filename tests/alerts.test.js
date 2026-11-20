// Session 6d201d19: swing-alert core tests (assets/alerts-core.js). Run: node --test tests/
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const ctx = {};
vm.runInNewContext(fs.readFileSync(new URL("../assets/alerts-core.js", import.meta.url), "utf8"), ctx);
const C = ctx.AlertsCore;

test("toTicks parses API dollar strings exactly", () => {
  assert.equal(C.toTicks("0.3500"), 3500);
  assert.equal(C.toTicks("1.0000"), 10000);
  assert.equal(C.toTicks("0.0100"), 100);
  assert.equal(C.toTicks(""), null);
  assert.equal(C.toTicks(undefined), null);
  assert.equal(C.toTicks("abc"), null);
});

test("fmtDollars and fmtSigned render four decimals", () => {
  assert.equal(C.fmtDollars(3500), "$0.3500");
  assert.equal(C.fmtDollars(10000), "$1.0000");
  assert.equal(C.fmtSigned(1000), "+$0.1000");
  assert.equal(C.fmtSigned(-2000), "-$0.2000");
});

test("swing threshold: exactly 0.10 counts, 0.0999 does not, both directions", () => {
  const up = C.detectSwing(3500, 4500);
  assert.equal(up.deltaTicks, 1000); assert.equal(up.direction, "up");
  const dn = C.detectSwing(5500, 4500);
  assert.equal(dn.deltaTicks, -1000); assert.equal(dn.direction, "down");
  assert.equal(C.detectSwing(3500, 4499), null);
  assert.equal(C.detectSwing(3500, 3501), null);
  assert.equal(C.detectSwing(null, 4500), null);
  assert.equal(C.detectSwing(3500, null), null);
});

test("no float drift: 0.55 -> 0.65 is exactly one tick of 0.10", () => {
  const d = C.detectSwing(C.toTicks("0.5500"), C.toTicks("0.6500"));
  assert.equal(d.deltaTicks, 1000);
});

test("placeholder ROI screen: multiple = (1-p)/p on the bought side", () => {
  // up move to 0.55 buys YES at 0.55 -> multiple 0.45/0.55 = 0.8182 (fails the >= 1.00 bar)
  const up = C.roiScreen(5500, "100", "KXPRESNOMD-28-AOC", "up");
  assert.equal(up.side, "YES");
  assert.equal(up.boughtTicks, 5500);
  assert.ok(Math.abs(up.multiple - 0.45 / 0.55) < 1e-12);
  assert.equal(up.passes, false);
  // up move to 0.20 buys YES at 0.20 -> multiple 4.0 and volume > 0 -> passes
  assert.equal(C.roiScreen(2000, "5", "KXPRESNOMD-28-AOC", "up").passes, true);
  // down move to 0.30 buys NO at 0.70 -> multiple 0.4286 -> fails
  const dn = C.roiScreen(3000, "5", "KXPRESNOMD-28-AOC", "down");
  assert.equal(dn.side, "NO");
  assert.equal(dn.boughtTicks, 7000);
  assert.equal(dn.passes, false);
  // down move to 0.20 buys NO at 0.80 -> fails; down move to 0.90 buys NO at 0.10 -> passes
  assert.equal(C.roiScreen(9000, "5", "KXPRESNOMD-28-AOC", "down").passes, true);
});

test("ROI screen never passes with zero volume or on synthetic exchange-test series", () => {
  assert.equal(C.roiScreen(2000, "0", "KXPRESNOMD-28-AOC", "up").passes, false);
  assert.equal(C.roiScreen(2000, "5", "KXDEMOFUTHOURLY-26NOV20H12-UP", "up").passes, false);
  assert.equal(C.roiScreen(2000, "5", "KXQUICKSETTLE-1", "up").passes, false);
  assert.equal(C.isSynthetic("KXDEMOFUTHOURLY-X"), true);
  assert.equal(C.isSynthetic("KXBTC-26"), false);
});

test("detectSwingFromPrevious uses the exchange's own previous_price_dollars", () => {
  // last 0.2000 with previous 0.0500 -> +0.15 move that the browser baseline cannot see
  const sw = C.detectSwingFromPrevious(C.toTicks("0.2000"), C.toTicks("0.0500"));
  assert.equal(sw.deltaTicks, 1500);
  assert.equal(sw.direction, "up");
  assert.equal(C.detectSwingFromPrevious(C.toTicks("0.2000"), C.toTicks("0.2000")), null);
  assert.equal(C.detectSwingFromPrevious(null, C.toTicks("0.2000")), null);
});

test("resolutionOf reads the official result only on a settled market", () => {
  // verified live on the demo API: status "finalized" + result "no"/"yes"
  const yes = C.resolutionOf({ status: "finalized", result: "yes", settlement_ts: "2026-11-20T12:00:00Z",
    settlement_value_dollars: "1.0000" });
  assert.equal(yes.resolved, true);
  assert.equal(yes.result, "yes");
  assert.equal(yes.settlementValue, "1.0000");
  const no = C.resolutionOf({ status: "finalized", result: "no" });
  assert.equal(no.resolved, true);
  assert.equal(no.result, "no");
  // open market: empty result means "not resolved" - never inferred
  const open = C.resolutionOf({ status: "active", result: "" });
  assert.equal(open.resolved, false);
  assert.equal(open.result, "");
  // a result on a market that is not finalized is not treated as resolved
  assert.equal(C.resolutionOf({ status: "active", result: "yes" }).resolved, false);
  assert.equal(C.resolutionOf(null).resolved, false);
});

test("settlementSourceLinks keeps only http(s) official sources", () => {
  const links = C.settlementSourceLinks([
    { name: "Democratic Party", url: "https://democrats.org/" },
    { name: "bad", url: "javascript:alert(1)" },
    { name: "", url: "https://www.cfbenchmarks.com/" },
    null,
  ]);
  assert.equal(links.length, 2);
  assert.equal(links[0].url, "https://democrats.org/");
  assert.equal(links[1].name, "https://www.cfbenchmarks.com/");
  assert.equal(C.settlementSourceLinks(undefined).length, 0);
  assert.equal(C.settlementSourceLinks([]).length, 0);
});

test("ROI screen rejects prices outside (0,1) and missing prices", () => {
  assert.equal(C.roiScreen(0, "5", "X", "up").passes, false);
  assert.equal(C.roiScreen(10000, "5", "X", "down").passes, false);
  assert.equal(C.roiScreen(null, "5", "X", "up").passes, false);
});
