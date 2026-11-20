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

test("ROI screen rejects prices outside (0,1) and missing prices", () => {
  assert.equal(C.roiScreen(0, "5", "X", "up").passes, false);
  assert.equal(C.roiScreen(10000, "5", "X", "down").passes, false);
  assert.equal(C.roiScreen(null, "5", "X", "up").passes, false);
});
