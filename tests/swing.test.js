import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// app.js is a browser IIFE that only needs a `window` object at load time (it
// assigns window.KalshiDemo and touches window.crypto/devicePixelRatio only inside
// functions we do not call here). A minimal stub keeps this test dependency-free.
const windowStub = {};
globalThis.window = windowStub;
await import(`${pathToFileURL(path.join(repo, "assets/app.js")).href}?swing=${Date.now()}`);
const K = windowStub.KalshiDemo;

test("swing helpers are exported on the shared client", () => {
  assert.ok(K, "KalshiDemo client is loaded");
  for (const fn of ["swingDelta", "highRoiScore", "makeSwingAlert"]) {
    assert.equal(typeof K[fn], "function", `K.${fn} must be a function`);
  }
  assert.equal(K.SWING_THRESHOLD, 0.1);
});

test("swingDelta returns the signed move and rejects non-numeric inputs", () => {
  assert.equal(K.swingDelta(0.5, 0.62), 0.12);
  assert.equal(K.swingDelta(0.62, 0.4), -0.22);
  assert.equal(K.swingDelta(null, 0.5), null);
  assert.equal(K.swingDelta("x", 0.5), null);
  assert.equal(K.swingDelta(0.5, null), null);
});

test("highRoiScore prefers a big, liquid, tight-book swing over a quiet one", () => {
  const big = K.highRoiScore(
    { last: 0.6, yb: 0.58, ya: 0.62, vol: 5000, oi: 3000 }, 0.5);
  const quiet = K.highRoiScore(
    { last: 0.51, yb: 0.46, ya: 0.56, vol: 0, oi: 0 }, 0.5);
  assert.ok(big.score > quiet.score, "big swing must score higher");
  assert.equal(big.highRoi, true);
  assert.equal(quiet.highRoi, false);
  assert.equal(big.move, 0.1);
});

test("makeSwingAlert carries direction, tickers and threshold fields", () => {
  const up = K.makeSwingAlert(
    { ticker: "T-UP", event_ticker: "E-1", title: "Up", topic: "crypto",
      last: 0.62, yb: 0.6, ya: 0.64, vol: 5000, oi: 100 }, 0.5, 1700000000);
  assert.equal(up.delta, 0.12);
  assert.equal(up.direction, "up");
  assert.equal(up.ticker, "T-UP");
  assert.equal(up.event_ticker, "E-1");
  const down = K.makeSwingAlert(
    { ticker: "T-DOWN", last: 0.3, yb: 0.28, ya: 0.32, vol: 900, oi: 100 }, 0.45, 1700000000);
  assert.equal(down.delta, -0.15);
  assert.equal(down.direction, "down");
});

test("a swing of exactly $0.10 meets the default threshold", () => {
  const a = K.makeSwingAlert(
    { ticker: "T-EDGE", last: 0.6, yb: 0.58, ya: 0.62, vol: 500, oi: 500 }, 0.5, 1700000000);
  assert.ok(Math.abs(a.delta) >= 0.1);
  assert.equal(K.SWING_THRESHOLD, 0.1);
});

test("highRoiScore with no previous price yields no move and a low score", () => {
  const s = K.highRoiScore(
    { last: 0.5, yb: 0.48, ya: 0.52, vol: 0, oi: 0 }, null);
  assert.equal(s.delta, null);
  assert.equal(s.move, null);
  assert.equal(s.highRoi, false);
});
