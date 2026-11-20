// Tests for assets/alerts-core.js (live swing-alert logic). Run: node --test tests/alerts.test.js
import test from "node:test";
import assert from "node:assert/strict";
// assets/alerts-core.js is a classic browser script; it publishes window.KalshiAlerts
// (globalThis in Node) and is evaluated here as-is.
import "../assets/alerts-core.js";

const A = globalThis.KalshiAlerts;

test("toUnits uses the API's 4-decimal dollar precision", () => {
  assert.equal(A.toUnits("0.3500"), 3500);
  assert.equal(A.toUnits("0.0040"), 40);
  assert.equal(A.toUnits(""), null);
  assert.equal(A.toUnits(undefined), null);
  assert.equal(A.toUnits("abc"), null);
});

test("a $0.10 move is detected exactly at the threshold, in both directions", () => {
  const up = A.swingBetween(A.toUnits("0.30"), A.toUnits("0.40"));
  assert.ok(up, "exactly $0.10 up must alert");
  assert.equal(up.dir, "up");
  assert.equal(up.delta, 1000);
  const down = A.swingBetween(A.toUnits("0.55"), A.toUnits("0.45"));
  assert.ok(down, "exactly $0.10 down must alert");
  assert.equal(down.dir, "down");
  assert.equal(down.delta, -1000);
});

test("moves smaller than $0.10 do not alert (no float drift at the boundary)", () => {
  assert.equal(A.swingBetween(A.toUnits("0.30"), A.toUnits("0.3999")), null);
  assert.equal(A.swingBetween(A.toUnits("0.50"), A.toUnits("0.4001")), null);
  assert.equal(A.swingBetween(null, A.toUnits("0.40")), null);
});

test("ROI screen: tight two-sided quote with traded volume passes; reasons are listed otherwise", () => {
  const ok = A.roiScreen({ yes_bid: A.toUnits("0.30"), yes_ask: A.toUnits("0.31"), volume: 500 });
  assert.equal(ok.pass, true);
  const wide = A.roiScreen({ yes_bid: A.toUnits("0.30"), yes_ask: A.toUnits("0.35"), volume: 500 });
  assert.equal(wide.pass, false);
  assert.deepEqual(wide.reasons, ["spread above $0.02"]);
  const noVol = A.roiScreen({ yes_bid: A.toUnits("0.30"), yes_ask: A.toUnits("0.31"), volume: 0 });
  assert.deepEqual(noVol.reasons, ["no traded volume"]);
  const noQuote = A.roiScreen({ yes_bid: null, yes_ask: A.toUnits("0.31"), volume: 3 });
  assert.deepEqual(noQuote.reasons, ["no two-sided quote"]);
});

test("payoff is arithmetic (1 - ask) / ask, null outside (0, $1)", () => {
  assert.ok(Math.abs(A.payoffFraction(A.toUnits("0.35")) - (1 - 0.35) / 0.35) < 1e-12);
  assert.equal(A.payoffFraction(0), null);
  assert.equal(A.payoffFraction(A.UNIT), null);
  assert.equal(A.payoffFraction(null), null);
});

test("JSONL parsing skips malformed lines and counts them", () => {
  const { rows, bad } = A.parseJsonl('{"a":1}\nnot json\n\n{"b":2}\n');
  assert.equal(rows.length, 2);
  assert.equal(bad, 1);
});

test("snapshot swings compare consecutive collector rows per ticker, chronologically", () => {
  const row = (ticker, ts, last, ask = "0.3100", bid = "0.3000", vol = "10.00") => ({
    ticker, ts, topic: "crypto", last_price_dollars: last, yes_ask_dollars: ask,
    yes_bid_dollars: bid, volume_fp: vol,
  });
  const rows = [
    row("X-1", "2026-11-20T10:00:00+00:00", "0.3000"),
    row("X-1", "2026-11-20T10:10:00+00:00", "0.4500"), // +0.15 up
    row("X-1", "2026-11-20T10:20:00+00:00", "0.4400"), // -0.01, no alert
    row("X-2", "2026-11-20T10:00:00+00:00", "0.80"),
    row("X-2", "2026-11-20T10:10:00+00:00", "0.66", "0.67", "0.66", "0.00"), // -0.14 down, fails ROI
  ];
  const sw = A.snapshotSwings(rows, A.SWING_UNITS);
  assert.equal(sw.length, 2);
  assert.equal(sw[0].ticker, "X-1");
  assert.equal(sw[0].dir, "up");
  assert.equal(sw[0].prev_ts, "2026-11-20T10:00:00+00:00");
  assert.equal(sw[0].roi.pass, true);
  assert.equal(sw[1].ticker, "X-2");
  assert.equal(sw[1].dir, "down");
  assert.equal(sw[1].roi.pass, false);
});

test("live tracker: first sight is a baseline only; later moves alert once; resolution reported once", () => {
  const t = new A.LiveTracker();
  const m = (last, extra = {}) => ({
    ticker: "KX-A", title: "A", event_ticker: "KX", last_price_dollars: last,
    yes_bid_dollars: "0.3000", yes_ask_dollars: "0.3100", volume_fp: "100", ...extra,
  });
  assert.deepEqual(t.ingest(m("0.3000"), "t0"), []);
  const up = t.ingest(m("0.4100"), "t1");
  assert.equal(up.length, 1);
  assert.equal(up[0].kind, "swing");
  assert.equal(up[0].source, "live");
  assert.equal(up[0].dir, "up");
  assert.deepEqual(t.ingest(m("0.4200"), "t2"), []);
  const res = t.ingest(m("0.9900", { result: "yes", status: "finalized" }), "t3");
  const resolved = res.filter((e) => e.kind === "resolved");
  assert.equal(resolved.length, 1);
  assert.equal(resolved[0].result, "yes");
  assert.equal(t.ingest(m("0.9900", { result: "yes" }), "t4").filter((e) => e.kind === "resolved").length, 0);
});
