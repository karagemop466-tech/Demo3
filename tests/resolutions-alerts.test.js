/* Tests for the alert chat's swing detection and yes/no resolution messages.
 *
 * Exercises assets/alerts.js in a stubbed browser environment:
 *   - >= $0.10 swing detection in either direction (docs: get-markets prices)
 *   - RESOLVED · YES/NO messages via KD.onResolution (docs: market_settlement)
 *   - dedupe of resolution messages, unknown results ignored
 *   - high-ROI chat receives resolutions only for model-screened tickers
 *
 * Sources:
 *   https://docs.kalshi.com/api-reference/market/get-markets
 *   https://docs.kalshi.com/getting_started/market_settlement
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function fakeEl(id) {
  return {
    id,
    innerHTML: "",
    textContent: "",
    style: {},
    className: "",
    checked: true,
    disabled: false,
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute() {},
    getAttribute(name) { return name === "data-chat" ? "all" : null; },
    addEventListener() {},
  };
}

function loadAlerts() {
  const els = {};
  for (const id of ["alertsAll", "alertsROI", "tabAll", "tabROI", "chatAll", "chatROI",
    "alertsEnabled", "clearAlertsBtn", "alertCount"]) els[id] = fakeEl(id);
  const store = new Map();
  const sandbox = {
    console,
    Date,
    Math,
    JSON,
    Number,
    String,
    Object,
    Array,
    isNaN,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval() {},
    fetch: () => Promise.resolve({ ok: false, status: 500, json: async () => ({}) }),
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    document: {
      readyState: "complete",
      getElementById: (id) => els[id] || null,
      querySelector: () => els.tabAll,
      querySelectorAll: () => [],
      addEventListener() {},
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(path.join(repo, "assets", "alerts.js"), "utf8"), sandbox);
  return { KD: sandbox.window.KD, store };
}

test("swing detection fires at exactly $0.10 in either direction", () => {
  const { KD } = loadAlerts();
  const m = { ticker: "T1", title: "Test market", topic: "crypto", series_ticker: "S1" };
  KD.onMarkets([Object.assign({ last: 0.5 }, m)]);
  KD.onSample(m, { t: 1, price: 0.5 });
  KD.onSample(m, { t: 2, price: 0.6 }); // +$0.10 exactly -> alert (float-safe)
  assert.equal(KD.allRows().length, 1);
  assert.equal(KD.allRows()[0].change, 0.1);
  assert.equal(KD.allRows()[0].dir, "up");
  KD.onSample(m, { t: 3, price: 0.45 }); // -$0.15 -> alert
  assert.equal(KD.allRows().length, 2);
  assert.equal(KD.allRows()[0].dir, "down");
  assert.equal(KD.allRows()[0].change, -0.15);
  KD.onSample(m, { t: 4, price: 0.47 }); // +$0.02 -> no alert
  assert.equal(KD.allRows().length, 2);
});

test("resolution messages post RESOLVED yes/no rows and dedupe", () => {
  const { KD } = loadAlerts();
  KD.onResolution({ ticker: "T2", title: "Resolves yes", topic: "golf",
    result: "yes", status: "settled", ts: 100 });
  KD.onResolution({ ticker: "T3", title: "Resolves no", topic: "elections",
    result: "no", status: "settled", ts: 101 });
  assert.equal(KD.allRows().length, 2);
  const rows = KD.allRows();
  assert.equal(rows[0].kind, "resolution");
  assert.equal(rows[0].result, "no");
  assert.equal(rows[1].result, "yes");
  // duplicate + unknown results are ignored
  KD.onResolution({ ticker: "T2", result: "yes" });
  KD.onResolution({ ticker: "T4", result: "maybe" });
  KD.onResolution({ ticker: "T5" });
  assert.equal(KD.allRows().length, 2);
  // rows are marked as resolutions for the chat renderer
  assert.ok(KD.allRows().every((a) => a.kind === "resolution"));
});

test("model chat receives resolutions only for high-ROI screened tickers", () => {
  const { KD } = loadAlerts();
  const m = { ticker: "T6", title: "ROI market", topic: "gas", series_ticker: "S6", oi: 0 };
  KD.onSample(m, { t: 1, price: 0.2 });
  KD.onSample(m, { t: 2, price: 0.75 }); // +$0.55 swing + 275% -> model score 0.7 >= 0.5
  assert.equal(KD.allRows().length, 1);
  assert.equal(KD.roiRows().length, 1);
  KD.onResolution({ ticker: "T6", result: "yes", topic: "gas" });
  assert.equal(KD.roiRows().length, 2); // swing + resolution
  KD.onResolution({ ticker: "T7", result: "no", topic: "crypto" });
  assert.equal(KD.roiRows().length, 2); // T7 never screened -> All chat only
  assert.equal(KD.allRows().length, 3);
});
