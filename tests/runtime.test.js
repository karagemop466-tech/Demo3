import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dashboardHTML = readFileSync(path.join(repo, "demo-desk", "index.html"), "utf8");
let bootNumber = 0;

function jsonResponse(payload) {
  return { ok: true, status: 200, json: async () => payload };
}

async function waitFor(predicate, label) {
  const deadline = Date.now() + 2_000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.fail(`Timed out waiting for ${label}`);
}

async function bootDashboard(fetchMock) {
  const dom = new JSDOM(dashboardHTML, {
    url: "https://demo.example.test/Demo3/demo-desk/",
    pretendToBeVisual: true,
  });
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  const keys = ["window", "document", "CustomEvent", "fetch", "setInterval", "clearInterval"];
  const oldDescriptors = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));

  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.CustomEvent = dom.window.CustomEvent;
  globalThis.fetch = fetchMock;
  globalThis.setInterval = () => ({ mocked: true });
  globalThis.clearInterval = () => {};

  try {
    await import(`../demo-desk/src/main.js?runtime-smoke=${++bootNumber}`);
  } catch (error) {
    dom.window.close();
    restoreGlobals(keys, oldDescriptors);
    throw error;
  }

  return {
    dom,
    cleanup() {
      dom.window.close();
      restoreGlobals(keys, oldDescriptors);
    },
  };
}

function restoreGlobals(keys, descriptors) {
  for (const key of keys) {
    const descriptor = descriptors.get(key);
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
}

const event = {
  event_ticker: "EV-GOLF",
  series_ticker: "SER-GOLF",
  title: "PGA Championship winner",
  category: "Sports",
  markets: [{
    ticker: "MKT-GOLF-Y",
    event_ticker: "EV-GOLF",
    series_ticker: "SER-GOLF",
    title: "PGA Championship winner: YES",
    status: "active",
    volume_24h_fp: "19",
    open_interest_fp: "28",
    last_price_dollars: "0.62",
    yes_bid_dollars: "0.60",
    yes_ask_dollars: "0.64",
  }],
};

function successfulDemoFetch(calls) {
  return async (input, options) => {
    const url = new URL(input);
    calls.push({ url, options });
    if (url.hostname !== "external-api.demo.kalshi.co") throw new Error(`Unexpected non-demo host: ${url.hostname}`);
    if (url.pathname === "/trade-api/v2/events" && url.searchParams.get("status") === "open") {
      return jsonResponse({ events: [event], cursor: "" });
    }
    if (url.pathname === "/trade-api/v2/events/EV-GOLF") return jsonResponse({ event });
    if (url.pathname === "/trade-api/v2/markets/MKT-GOLF-Y") return jsonResponse({ market: event.markets[0] });
    if (url.pathname === "/trade-api/v2/markets/MKT-GOLF-Y/orderbook") {
      return jsonResponse({ orderbook_fp: { yes_dollars: [["0.60", "7"]], no_dollars: [["0.36", "3"]] } });
    }
    if (url.pathname === "/trade-api/v2/series/SER-GOLF/markets/MKT-GOLF-Y/candlesticks") return jsonResponse({ candlesticks: [] });
    throw new Error(`Unexpected demo endpoint: ${url.pathname}`);
  };
}

test("dashboard boots, renders official demo events, and inspects a market through read-only endpoints", async () => {
  const calls = [];
  const app = await bootDashboard(successfulDemoFetch(calls));
  try {
    const { document } = app.dom.window;
    await waitFor(() => document.querySelector("#market-table-container tbody tr"), "the live event row");
    const row = document.querySelector("#market-table-container tbody tr");
    assert.match(row.textContent, /PGA Championship winner/);
    assert.equal(row.querySelectorAll("a[href^='https://external-api.demo.kalshi.co/']").length, 1);
    assert.match(document.querySelector("#coverage-status").textContent, /all returned pages read/);
    assert.equal(document.querySelector("#global-feed-status").dataset.state, "success");

    document.querySelector("#market-table-container [data-select-event]").click();
    await waitFor(
      () => document.querySelector("#selected-market-summary").textContent.includes("$0.6200")
        && document.querySelector("#orderbook-container tbody tr"),
      "the selected-market quote and order-book rows",
    );
    assert.match(document.querySelector("#selected-market-summary").textContent, /Market API/);
    assert.match(document.querySelector("#orderbook-container").textContent, /\$0\.6000/);
    assert.ok(document.querySelector("#chart-container svg.price-chart"), "the chart should render actual market observations");
    assert.equal(document.querySelectorAll("#market-table-container tbody tr").length, 1);

    assert.ok(calls.some(({ url }) => url.pathname === "/trade-api/v2/events/EV-GOLF"));
    assert.ok(calls.some(({ url }) => url.pathname === "/trade-api/v2/markets/MKT-GOLF-Y/orderbook"));
    assert.ok(calls.some(({ url }) => url.pathname.endsWith("/candlesticks")));
    for (const { url, options } of calls) {
      assert.equal(url.hostname, "external-api.demo.kalshi.co");
      assert.equal(options.credentials, "omit");
      assert.equal(options.method, "GET");
    }
  } finally {
    app.cleanup();
  }
});

test("dashboard fails closed on a browser network/CORS error instead of showing a substitute row", async () => {
  const app = await bootDashboard(async () => { throw new TypeError("blocked by the browser"); });
  try {
    const { document } = app.dom.window;
    await waitFor(() => document.querySelector("#market-table-container [role='alert']"), "the API failure state");
    assert.match(document.querySelector("#market-table-container").textContent, /no substitute data was loaded/i);
    assert.equal(document.querySelectorAll("#market-table-container tbody tr").length, 0);
    assert.equal(document.querySelector("#stat-events").textContent, "—");
    assert.equal(document.querySelector("#global-feed-status").dataset.state, "error");
  } finally {
    app.cleanup();
  }
});
