import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../assets/alerts.js", import.meta.url), "utf8");

function makeStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key)
  };
}

function loadAlerts(storage = makeStorage()) {
  const context = { window: { localStorage: storage } };
  vm.runInNewContext(source, context, { filename: "assets/alerts.js" });
  return { api: context.window.KalshiAlerts, storage };
}

function market(overrides = {}) {
  return Object.assign({
    ticker: "KXTEST-26DEC31-A",
    event_ticker: "KXTEST-26DEC31",
    rules_primary: "Resolves YES if the stated condition occurs.",
    title: "Test event",
    topic: "crypto",
    last: 0.50,
    yb: 0.48,
    ya: 0.52,
    vol: 12,
    oi: 20
  }, overrides);
}

test("root dashboard loads the alert modules before the dashboard and disclaims causal attribution", () => {
  const dashboard = readFileSync(new URL("../dashboard.html", import.meta.url), "utf8");
  const engine = readFileSync(new URL("../assets/dashboard.js", import.meta.url), "utf8");
  assert.ok(dashboard.indexOf("assets/alerts.js") < dashboard.indexOf("assets/dashboard.js"));
  assert.match(dashboard, /allAlerts/);
  assert.match(dashboard, /roiAlerts/);
  assert.ok(dashboard.includes("they are not evidence"));
  assert.ok(dashboard.includes("caused the price move"));
  assert.match(engine, /K\.apiGet\("\/events\/"/);
  assert.match(engine, /rulesPrimary/);
});

test("first observation seeds a baseline and does not emit an alert", () => {
  const { api } = loadAlerts();
  assert.equal(api.observe([market()], 1000).length, 0);
  assert.equal(api.observe([market({ yb: 0.49, ya: 0.53 })], 2000).length, 0);
});

test("alerts trigger at exactly ten cents in either direction", () => {
  const { api } = loadAlerts();
  api.observe([market({ yb: 0.38, ya: 0.42 })], 1000); // midpoint 0.40
  const up = api.observe([market({ yb: 0.48, ya: 0.52 })], 2000); // midpoint 0.50
  assert.equal(up.length, 1);
  assert.ok(Math.abs(up[0].delta - 0.10) < 1e-8);
  assert.equal(up[0].screenPass, true);
  assert.equal(up[0].sourcePath, "/markets/KXTEST-26DEC31-A");
  assert.equal(up[0].eventTicker, "KXTEST-26DEC31");
  assert.equal(up[0].rulesPrimary, "Resolves YES if the stated condition occurs.");

  const down = api.observe([market({ yb: 0.38, ya: 0.42 })], 3000);
  assert.equal(down.length, 1);
  assert.ok(Math.abs(down[0].delta + 0.10) < 1e-8);
});

test("moves smaller than ten cents do not alert", () => {
  const { api } = loadAlerts();
  api.observe([market({ yb: 0.40, ya: 0.44 })], 1000);
  assert.equal(api.observe([market({ yb: 0.49, ya: 0.53 })], 2000).length, 0);
});

test("candidate filter requires valid quotes, a spread no wider than five cents, and volume", () => {
  const { api } = loadAlerts();
  api.observe([market({ yb: 0.38, ya: 0.42 })], 1000);
  const tight = api.observe([market({ yb: 0.48, ya: 0.52 })], 2000)[0];
  assert.equal(tight.screenPass, true);

  api.observe([market({ ticker: "WIDE", yb: 0.38, ya: 0.42 })], 1000);
  const wide = api.observe([market({ ticker: "WIDE", yb: 0.45, ya: 0.55 })], 2000)[0];
  assert.equal(wide.screenPass, false);
  assert.match(wide.screenReason, /wider than 5¢/);

  api.observe([market({ ticker: "NO-VOLUME", yb: 0.38, ya: 0.42 })], 1000);
  const noVolume = api.observe([market({ ticker: "NO-VOLUME", yb: 0.48, ya: 0.52, vol: 0 })], 2000)[0];
  assert.equal(noVolume.screenPass, false);
  assert.match(noVolume.screenReason, /volume/);
});

test("switching price basis or losing a valid quote resets the baseline", () => {
  const { api } = loadAlerts();
  api.observe([market({ yb: 0.38, ya: 0.42 })], 1000);
  assert.equal(api.observe([market({ yb: null, ya: null, last: 0.80 })], 2000).length, 0);
  assert.equal(api.observe([market({ yb: null, ya: null, last: 0.85 })], 3000).length, 0);
  assert.equal(api.observe([market({ yb: null, ya: null, last: null })], 4000).length, 0);
  assert.equal(api.observe([market({ yb: null, ya: null, last: 0.20 })], 5000).length, 0);
});

test("event settlement-source context keeps only HTTPS URLs and preserves labels", () => {
  const { api } = loadAlerts();
  const context = api.normalizeEventContext({
    title: "Test event",
    settlement_sources: [
      { name: "Official source", url: "https://example.test/resolve" },
      { name: "Insecure source", url: "http://example.test/resolve" },
      { name: "No URL", url: "" },
      null
    ]
  });
  assert.equal(context.title, "Test event");
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].name, "Official source");
  assert.equal(context.sources[0].url, "https://example.test/resolve");
});

test("history is saved locally, bounded, and clearable", () => {
  const storage = makeStorage();
  const { api } = loadAlerts(storage);
  api.observe([market({ yb: 0.38, ya: 0.42 })], 1000);
  const entry = api.observe([market({ yb: 0.48, ya: 0.52 })], 2000)[0];
  api.append([entry]);
  assert.equal(api.history().length, 1);

  const reloaded = loadAlerts(storage).api;
  assert.equal(reloaded.history().length, 1);
  assert.equal(reloaded.history()[0].ticker, "KXTEST-26DEC31-A");
  assert.equal(reloaded.clearHistory().length, 0);
  assert.equal(storage.getItem("kd_swing_alerts_v1"), null);
});
