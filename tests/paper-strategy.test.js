import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../assets/paper-strategy.js", import.meta.url), "utf8");

function makeStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key)
  };
}

function loadStrategies(storage = makeStorage()) {
  const context = { window: { localStorage: storage } };
  vm.runInNewContext(source, context, { filename: "assets/paper-strategy.js" });
  return { api: context.window.KalshiPaperStrategies, storage };
}

function alert(overrides = {}) {
  return Object.assign({
    id: "KXTEST|1000|0.400000|0.500000",
    ticker: "KXTEST-26DEC31-A",
    title: "Test event",
    topic: "crypto",
    delta: 0.10,
    yesAsk: 0.52,
    screenPass: true,
    observedAt: "2026-11-20T12:00:00.000Z",
    sourcePath: "/markets/KXTEST-26DEC31-A"
  }, overrides);
}

test("qualifying upward and downward alerts automatically enter separate paper strategies", () => {
  const { api } = loadStrategies();
  const added = api.processAlerts([
    alert(),
    alert({
      id: "KXDOWN|2000|0.600000|0.500000",
      ticker: "KXTEST-26DEC31-B",
      delta: -0.10,
      yesAsk: 0.60
    })
  ]);
  assert.equal(added.length, 2);
  assert.deepEqual(Array.from(added, (row) => row.strategyId), ["momentum-yes", "pullback-yes"]);
  assert.ok(added.every((row) => row.mode === "paper" && row.contracts === 1));
  assert.ok(added.every((row) => row.action === "buy" && row.side === "yes"));
});

test("simulated entries require the candidate screen and a valid YES ask", () => {
  const { api } = loadStrategies();
  const added = api.processAlerts([
    alert({ screenPass: false }),
    alert({ id: "missing-ask", yesAsk: null }),
    alert({ id: "bad-ask", yesAsk: 1.01 }),
    alert({ id: "bad-delta", delta: 0 })
  ]);
  assert.equal(added.length, 0);
  assert.equal(api.stats().trades, 0);
});

test("there is at most one open position per ticker and strategy", () => {
  const { api } = loadStrategies();
  assert.equal(api.processAlerts([alert()]).length, 1);
  assert.equal(api.processAlerts([alert({ id: "second-alert" })]).length, 0);
  assert.deepEqual(Array.from(api.openTickers()), ["KXTEST-26DEC31-A"]);
});

test("open positions use best YES bid mark and settle only on a final yes/no result", () => {
  const { api } = loadStrategies();
  api.processAlerts([alert()]); // entry at 52¢
  api.markToMarket([
    { ticker: "KXTEST-26DEC31-A", yb: 0.55, last: 0.56 }
  ], 2000);
  assert.ok(Math.abs(api.stats().unrealizedGrossPnl - 0.03) < 1e-9);

  assert.equal(api.settle("KXTEST-26DEC31-A", { status: "open", result: "yes" }, 3000), 0);
  assert.equal(api.settle("KXTEST-26DEC31-A", { status: "settled", result: "maybe" }, 3000), 0);
  assert.equal(api.settle("KXTEST-26DEC31-A", { status: "finalized", result: "yes" }, 4000), 1);
  const stats = api.stats();
  assert.equal(stats.open, 0);
  assert.equal(stats.settled, 1);
  assert.equal(stats.byStrategy[0].wins, 1);
  assert.ok(Math.abs(stats.realizedGrossPnl - 0.48) < 1e-9);
  assert.equal(api.list()[0].settlementSourcePath, "/markets/KXTEST-26DEC31-A");
});

test("no-result settlements produce gross loss and a settled trade can be retried later", () => {
  const { api } = loadStrategies();
  api.processAlerts([alert()]);
  assert.equal(api.settle("KXTEST-26DEC31-A", { status: "settled", result: "no" }, 2000), 1);
  assert.ok(Math.abs(api.stats().realizedGrossPnl + 0.52) < 1e-9);
  assert.equal(api.processAlerts([alert({ id: "second-cycle" })]).length, 1);
});

test("paper results persist in browser storage and can be cleared", () => {
  const storage = makeStorage();
  const { api } = loadStrategies(storage);
  api.processAlerts([alert()]);
  const reloaded = loadStrategies(storage).api;
  assert.equal(reloaded.list().length, 1);
  assert.equal(reloaded.list()[0].mode, "paper");
  reloaded.clear();
  assert.equal(reloaded.stats().trades, 0);
  assert.equal(storage.getItem("kd_auto_paper_strategies_v1"), null);
});
