import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { JSDOM } from "jsdom";

const source = readFileSync(new URL("../assets/alerts.js", import.meta.url), "utf8");
const sandbox = { module: { exports: {} }, Number, Date };
vm.runInNewContext(source, sandbox, { filename: "assets/alerts.js" });
const alerts = sandbox.module.exports;
const market = (overrides = {}) => ({
  ticker: "KXTEST-26",
  title: "Example event",
  topic: "crypto",
  status: "open",
  last: 0.5,
  yb: 0.48,
  ya: 0.52,
  vol: 10,
  ...overrides,
});

test("no alert without a previous open quote or a full ten-cent swing", () => {
  assert.equal(alerts.compare(null, market({ last: 0.8 })), null);
  assert.equal(alerts.compare(market(), market({ last: 0.599999 })), null);
  assert.equal(alerts.compare(market(), market({ last: 0.400001 })), null);
  assert.ok(alerts.compare(market({ last: 0.4 }), market({ last: 0.5 })));
});

test("alerts trigger inclusively at a ten-cent swing in either direction", () => {
  const up = alerts.compare(market({ last: 0.4 }), market({ last: 0.5 }));
  const down = alerts.compare(market({ last: 0.6 }), market({ last: 0.5 }));
  assert.ok(up && up.delta >= 0.1 - Number.EPSILON);
  assert.ok(down && down.delta <= -0.1 + Number.EPSILON);
});

test("Model Watch requires every stated screen condition and excludes non-open markets", () => {
  assert.equal(alerts.compare(market({ last: 0.4 }), market({ last: 0.5 })).modelWatch, true);
  assert.equal(alerts.compare(market({ last: 0.4 }), market({ last: 0.5, ya: 0.7 })).modelWatch, false);
  assert.equal(alerts.compare(market({ last: 0.4 }), market({ last: 0.5, vol: 0 })).modelWatch, false);
  assert.equal(alerts.compare(market({ last: 0.4 }), market({ last: 0.99 })).modelWatch, false);
  assert.equal(alerts.compare(market(), market({ status: "settled", last: 0.8 })), null);
});

test("live dashboard renders price swings in the all-events and heuristic feeds", async () => {
  const html = readFileSync(new URL("../dashboard.html", import.meta.url), "utf8")
    .replace(/<script[^>]*><\/script>/g, "");
  const dom = new JSDOM(html, { url: "https://demo.example.test/Demo3/", pretendToBeVisual: true, runScripts: "outside-only" });
  const { window } = dom;
  let last = "0.40";
  window.setInterval = () => 1;
  window.clearInterval = () => {};
  window.fetch = async (input) => {
    const url = new URL(input);
    let payload;
    if (url.pathname.endsWith("/series")) {
      payload = { series: [{ ticker: "KXBTC", title: "Bitcoin price", category: "Crypto" }], cursor: "" };
    } else if (url.pathname.endsWith("/markets")) {
      payload = { markets: [{ ticker: "KXBTC-26", series_ticker: "KXBTC", title: "Bitcoin above threshold",
        status: "open", last_price_dollars: last, yes_bid_dollars: "0.36", yes_ask_dollars: "0.44",
        volume_fp: "100", open_interest_fp: "20" }], cursor: "" };
    } else {
      throw new Error(`Unexpected request: ${url.href}`);
    }
    return { ok: true, status: 200, text: async () => JSON.stringify(payload) };
  };

  try {
    window.eval(readFileSync(new URL("../assets/app.js", import.meta.url), "utf8"));
    window.eval(readFileSync(new URL("../assets/alerts.js", import.meta.url), "utf8"));
    window.eval(readFileSync(new URL("../assets/dashboard.js", import.meta.url), "utf8"));
    const wait = async (predicate, label) => {
      const deadline = Date.now() + 5_000;
      while (Date.now() < deadline) {
        if (predicate()) return;
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      assert.fail(`Timed out waiting for ${label}`);
    };
    await wait(() => window.document.querySelector("#scanStatus").textContent.includes("open markets"), "initial quote baseline");
    assert.equal(window.document.querySelector("#allAlertCount").textContent, "0");

    last = "0.51";
    window.document.querySelector("#scanBtn").click();
    await wait(() => window.document.querySelector("#allAlertCount").textContent === "1", "the threshold-crossing alert");
    assert.equal(window.document.querySelector("#modelAlertCount").textContent, "1");
    assert.match(window.document.querySelector("#allAlerts").textContent, /\+11\.00¢/);
    assert.match(window.document.querySelector("#modelAlerts").textContent, /Catalyst: not verified/);
    assert.equal(window.document.querySelectorAll("#allAlerts a[href^='https://external-api.demo.kalshi.co/']").length, 1);
  } finally {
    window.close();
  }
});
