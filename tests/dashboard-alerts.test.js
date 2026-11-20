import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dashboardHTML = readFileSync(path.join(repo, "dashboard.html"), "utf8");

function jsonResponse(payload) {
  const text = JSON.stringify(payload);
  return { ok: true, status: 200, text: async () => text, json: async () => payload };
}

async function waitFor(predicate, label) {
  const deadline = Date.now() + 3_000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.fail(`Timed out waiting for ${label}`);
}

// Market price changes from $0.50 (first scan) to $0.62 (alert poll): a $0.12 swing.
const listMarket = {
  ticker: "MKT-1", event_ticker: "EV-1", series_ticker: "S1",
  title: "Election winner YES", status: "active", result: "",
  last_price_dollars: "0.50", yes_bid_dollars: "0.48", yes_ask_dollars: "0.52",
  volume_fp: "5000", open_interest_fp: "3000",
};
const detailMarket = {
  ...listMarket, last_price_dollars: "0.62",
  yes_bid_dollars: "0.60", yes_ask_dollars: "0.64",
};

function fetchMock() {
  return async (input) => {
    const url = new URL(input);
    if (url.hostname !== "external-api.demo.kalshi.co") {
      // seeded-resolution archives: empty, so the seeded table stays empty
      return jsonResponse({ resolved: [], markets: [] });
    }
    if (url.pathname === "/trade-api/v2/series") {
      return jsonResponse({ series: [{
        ticker: "S1", title: "Election winner", category: "Elections",
        tags: [], categories: [], frequency: "", volume_fp: "100",
      }] });
    }
    if (url.pathname === "/trade-api/v2/markets" &&
        url.searchParams.get("series_ticker") === "S1") {
      return jsonResponse({ markets: [listMarket], cursor: "" });
    }
    if (url.pathname === "/trade-api/v2/markets/MKT-1") {
      return jsonResponse({ market: detailMarket });
    }
    if (url.pathname === "/trade-api/v2/markets/MKT-1/orderbook") {
      return jsonResponse({ orderbook_fp: {
        yes_dollars: [["0.60", "7"]], no_dollars: [["0.40", "3"]],
      } });
    }
    if (url.pathname === "/trade-api/v2/markets/trades") {
      return jsonResponse({ trades: [] });
    }
    if (url.pathname.endsWith("/candlesticks")) {
      return jsonResponse({ candlesticks: [] });
    }
    throw new Error(`Unexpected demo endpoint: ${url.pathname}`);
  };
}

test("dashboard streams a >=$0.10 swing into both scrolling alert chats", async () => {
  const dom = new JSDOM(dashboardHTML, {
    url: "https://demo.example.test/Demo3/",
    pretendToBeVisual: true,
  });
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};

  const keys = ["window", "document", "fetch", "setInterval", "clearInterval",
    "localStorage", "CustomEvent"];
  const old = new Map(keys.map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  const intervals = [];
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.fetch = fetchMock();
  globalThis.localStorage = dom.window.localStorage;
  globalThis.CustomEvent = dom.window.CustomEvent;
  globalThis.setInterval = (fn) => { intervals.push(fn); return { mocked: true }; };
  globalThis.clearInterval = () => {};

  try {
    await import(`../assets/app.js?dash=${Date.now()}`);
    await import(`../assets/dashboard.js?dash=${Date.now()}`);

    const { document } = dom.window;
    // wait for discovery + first scan to populate the ranking
    await waitFor(() => document.querySelector("#rankingTable tbody tr"), "ranking row");
    assert.match(document.querySelector("#rankingTable").textContent, /MKT-1/);

    // the alert poll is the 4th interval registered by startTimers
    assert.ok(intervals.length >= 4, "alert poll interval registered");
    await intervals[3](); // pollTopForAlerts: fetches detail price 0.62, emits alert

    await waitFor(() => document.querySelector("#allChat .msg .mtitle"),
      "an alert message in the all-events chat");
    const allText = document.querySelector("#allChat").textContent;
    assert.match(allText, /MKT-1/);
    assert.match(allText, /Election winner YES/);
    assert.match(allText, /\+12\.00¢/, "delta label should show the +$0.12 move");

    // high-ROI heuristic: liquid, tight-book swing -> model-picks chat as well
    const pickText = document.querySelector("#pickChat").textContent;
    assert.match(pickText, /MKT-1/);
    assert.match(pickText, /model score/);

    // every alert message carries an official market source link
    const srcLinks = document.querySelectorAll("#allChat a[href^='https://external-api.demo.kalshi.co/']");
    assert.ok(srcLinks.length >= 1, "alert must link the official market API record");
  } finally {
    for (const [k, d] of old) {
      if (d) Object.defineProperty(globalThis, k, d);
      else delete globalThis[k];
    }
    dom.window.close();
  }
});
