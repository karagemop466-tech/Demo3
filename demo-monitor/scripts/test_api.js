"use strict";

// This is a synthetic API-client test fixture. Values below are test-only and are
// never loaded by the production site or presented as Kalshi market data.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const requests = [];
let failingCategory = "";
const fixtureSeries = {
  series: [{
    ticker: "FIXTURE-GAS",
    title: "Fixture monthly gas price series",
    category: "Economics",
    categories: ["Economics", "Commodities"],
    tags: ["Oil & Gas"]
  }],
  cursor: ""
};
const fixtureEvents = {
  events: [{
    event_ticker: "FIXTURE-GAS-EVENT",
    series_ticker: "FIXTURE-GAS",
    title: "Fixture gas-price event",
    category: "Economics",
    markets: [{
      ticker: "FIXTURE-GAS-MARKET",
      event_ticker: "FIXTURE-GAS-EVENT",
      status: "active",
      yes_bid_dollars: "0.4100",
      yes_bid_size_fp: "3.00",
      yes_ask_dollars: "0.4400",
      yes_ask_size_fp: "2.00",
      volume_24h_fp: "5.00",
      open_interest_fp: "8.00"
    }]
  }],
  cursor: ""
};

async function fakeFetch(input) {
  const url = new URL(String(input));
  requests.push(url);
  let body;
  if (url.pathname.endsWith("/series")) {
    const category = url.searchParams.get("category");
    if (category === failingCategory) throw new Error("synthetic category failure");
    body = category === "Economics" || category === "Commodities" ? fixtureSeries : { series: [], cursor: "" };
  } else if (url.pathname.endsWith("/events")) {
    body = url.searchParams.get("series_ticker") === "FIXTURE-GAS" ? fixtureEvents : { events: [], cursor: "" };
  } else {
    throw new Error(`Unexpected synthetic-client request: ${url.pathname}`);
  }
  return { ok: true, status: 200, json: async () => body };
}

async function main() {
  const sandbox = {
    URL,
    AbortController,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    fetch: fakeFetch,
    console
  };
  sandbox.window = sandbox;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assets/api.js"), "utf8"), sandbox, { filename: "assets/api.js" });
  const api = sandbox.KalshiAPI;
  assert.ok(api, "API module should expose KalshiAPI");
  assert.equal(api.API_ROOTS[0], "https://external-api.demo.kalshi.co/trade-api/v2");
  assert.equal(api.API_ROOTS.some(root => root.includes("kalshi.com/trade-api/v2")), false, "client must not include the production REST host");

  failingCategory = "Economics";
  const partial = await api.loadTopic("gas", "open", true);
  assert.equal(partial.queried, true);
  assert.equal(partial.complete, false, "a failed category request must invalidate complete coverage");
  assert.equal(partial.errors.length, 1);
  assert.equal(partial.events.length, 1, "successful category/event rows remain available in a partial response");

  failingCategory = "";
  const result = await api.loadTopic("gas", "open", true);
  assert.equal(result.queried, true);
  assert.equal(result.complete, true);
  assert.equal(result.errors.length, 0);
  assert.equal(result.series.length, 1);
  assert.equal(result.events.length, 1);
  assert.equal(result.events[0].event_ticker, "FIXTURE-GAS-EVENT");
  assert.equal(result.events[0]._topicLabel, "Gas prices");
  assert.ok(requests.length >= 3, "fixture should exercise category metadata and event data requests");
  const allowedHosts = api.API_ROOTS.map(root => new URL(root).hostname);
  assert.ok(requests.every(url => allowedHosts.includes(url.hostname)), "all requests should use one of the documented demo REST hosts");
  assert.ok(requests.some(url => url.searchParams.get("with_nested_markets") === "true"));
  assert.ok(requests.some(url => url.searchParams.get("status") === "open"));

  const marketUrl = api.directUrl("/markets/FIXTURE-GAS-MARKET");
  assert.equal(new URL(marketUrl).hostname, "external-api.demo.kalshi.co");
  console.log("PASS: synthetic API-client fixture verifies demo-host selection, category matching, nested open-event requests, source URLs, and partial-coverage handling.");
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
