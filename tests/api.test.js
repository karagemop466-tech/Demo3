import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_EVENT_PAGE_LIMIT,
  DEMO_API_BASE,
  fetchEvent,
  fetchEventsByStatus,
  fetchMarket,
  fetchMarketCandlesticks,
  fetchOrderbook,
  requestJSON,
} from "../demo-desk/src/api.js";

async function withFetch(mock, run) {
  const original = globalThis.fetch;
  globalThis.fetch = mock;
  try {
    await run();
  } finally {
    globalThis.fetch = original;
  }
}

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

test("event client requests only the demo host and reads all cursor pages", async () => {
  const calls = [];
  const progress = [];
  await withFetch(async (url, options) => {
    calls.push({ url: new URL(url), options });
    if (calls.length === 1) return jsonResponse({ events: [{ event_ticker: "E1" }], cursor: "cursor-1" });
    return jsonResponse({ events: [{ event_ticker: "E2" }], cursor: "" });
  }, async () => {
    const result = await fetchEventsByStatus("open", { maxPages: 4, onPage: (page) => progress.push(page) });
    assert.equal(result.complete, true);
    assert.equal(result.pages, 2);
    assert.deepEqual(result.events.map((event) => event.event_ticker), ["E1", "E2"]);
  });

  assert.equal(DEFAULT_EVENT_PAGE_LIMIT, 200);
  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.equal(call.url.origin, "https://external-api.demo.kalshi.co");
    assert.equal(call.url.pathname, "/trade-api/v2/events");
    assert.equal(call.url.searchParams.get("status"), "open");
    assert.equal(call.url.searchParams.get("limit"), "200");
    assert.equal(call.url.searchParams.get("with_nested_markets"), "true");
    assert.equal(call.options.credentials, "omit");
  }
  assert.equal(calls[1].url.searchParams.get("cursor"), "cursor-1");
  assert.deepEqual(progress.map((item) => item.pages), [1, 2]);
});

test("event cursor safety limit is explicit rather than silently presented as complete", async () => {
  let calls = 0;
  await withFetch(async () => {
    calls += 1;
    return jsonResponse({ events: [{ event_ticker: `E${calls}` }], cursor: "next" });
  }, async () => {
    const result = await fetchEventsByStatus("closed", { maxPages: 1 });
    assert.equal(result.pages, 1);
    assert.equal(result.complete, false);
    assert.equal(result.cursor, "next");
  });
  assert.equal(calls, 1);
});

test("repeated pagination cursors fail closed", async () => {
  let calls = 0;
  await withFetch(async () => {
    calls += 1;
    return jsonResponse({ events: [], cursor: calls === 1 ? "repeat" : "repeat" });
  }, async () => {
    await assert.rejects(fetchEventsByStatus("settled", { maxPages: 3 }), /repeated a pagination cursor/);
  });
  assert.equal(calls, 2);
});

test("API errors and network/CORS failures do not return substitute values", async () => {
  await withFetch(async () => { throw new TypeError("blocked"); }, async () => {
    await assert.rejects(requestJSON(`${DEMO_API_BASE}/events`), /network\/CORS access; no substitute data was loaded/);
  });
  await withFetch(async () => jsonResponse({ message: "rate limited" }, 429), async () => {
    await assert.rejects(requestJSON(`${DEMO_API_BASE}/events`), /rate limit/);
  });
  await withFetch(async () => jsonResponse({ unexpected: [] }), async () => {
    await assert.rejects(fetchEventsByStatus("open"), /did not contain an events array/);
  });
  await assert.rejects(fetchEventsByStatus("active"), /Unsupported event status filter/);
});

test("single-record helpers use the official demo endpoints and field envelopes", async () => {
  const calls = [];
  await withFetch(async (url) => {
    const parsed = new URL(url);
    calls.push(parsed);
    if (parsed.pathname === "/trade-api/v2/events/EV-1") return jsonResponse({ event: { event_ticker: "EV-1" } });
    if (parsed.pathname === "/trade-api/v2/markets/MKT-1") return jsonResponse({ market: { ticker: "MKT-1" } });
    if (parsed.pathname === "/trade-api/v2/markets/MKT-1/orderbook") return jsonResponse({ orderbook_fp: { yes_dollars: [["0.4", "2"]] } });
    if (parsed.pathname === "/trade-api/v2/series/SER-1/markets/MKT-1/candlesticks") return jsonResponse({ candlesticks: [{ end_period_ts: 1 }] });
    return jsonResponse({});
  }, async () => {
    assert.equal((await fetchEvent("EV-1")).event_ticker, "EV-1");
    assert.equal((await fetchMarket("MKT-1")).ticker, "MKT-1");
    assert.equal((await fetchOrderbook("MKT-1")).yes_dollars[0][0], "0.4");
    const candles = await fetchMarketCandlesticks("SER-1", "MKT-1", {
      startTs: 1,
      endTs: 2,
      periodInterval: 1,
    });
    assert.equal(candles.length, 1);
  });
  assert.equal(calls[0].searchParams.get("with_nested_markets"), "true");
  assert.deepEqual(calls.map((url) => url.hostname), calls.map(() => "external-api.demo.kalshi.co"));
});
