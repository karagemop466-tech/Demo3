import test from "node:test";
import assert from "node:assert/strict";
import {
  FLAGS,
  QUESTIONS,
  SOURCES,
  STRATEGY_FIELDS,
  SUGGESTIONS,
  TOPICS,
} from "../demo-desk/src/content.js";
import {
  aggregateEvent,
  isInResolutionQueue,
  resolutionDetails,
  sortEventAggregates,
  sumMarketField,
} from "../demo-desk/src/metrics.js";
import { matchingTopics, topicMatchesEvent } from "../demo-desk/src/topics.js";
import {
  localPriceSamples,
  mergePriceSeries,
  recordPriceSample,
} from "../demo-desk/src/chart.js";
import {
  renderEventTable,
  renderFlags,
  renderOrderbook,
  renderQuestions,
  renderResolutionTable,
  renderSelectedMarket,
  renderSettlementSources,
  renderSources,
  renderStrategyFields,
  renderSuggestions,
  setSuggestionDecision,
} from "../demo-desk/src/renderers.js";
import { escapeHTML, finiteNumber, formatNumber, safeHttpsUrl } from "../demo-desk/src/utils.js";

function container() {
  return { innerHTML: "" };
}

function bodyRows(markup) {
  const body = markup.match(/<tbody>([\s\S]*?)<\/tbody>/i)?.[1] ?? "";
  return [...body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map((match) => match[1]);
}

function assertEachRowHasOfficialLink(markup) {
  const rows = bodyRows(markup);
  assert.ok(rows.length > 0, "expected at least one body row");
  for (const [index, row] of rows.entries()) {
    assert.match(row, /<a\b[^>]*href="https:\/\//i, `row ${index + 1} must contain an HTTPS source link`);
  }
  return rows;
}

test("source register is HTTPS-only and every documented evidence ID resolves", () => {
  const sourceIds = new Set(SOURCES.map((item) => item.id));
  assert.equal(sourceIds.size, SOURCES.length, "source IDs must be unique");
  for (const source of SOURCES) {
    const url = new URL(source.url);
    assert.equal(url.protocol, "https:", `${source.id} must use HTTPS`);
    assert.ok(["docs.kalshi.com", "help.kalshi.com", "external-api.demo.kalshi.co"].includes(url.hostname), `${source.id} must use an official Kalshi host`);
  }
  for (const item of [...QUESTIONS, ...FLAGS, ...STRATEGY_FIELDS, ...SUGGESTIONS]) {
    assert.ok(item.sourceIds.length > 0, `${item.id ?? item.name} needs at least one source`);
    for (const id of item.sourceIds) assert.ok(sourceIds.has(id), `${item.id ?? item.name} references missing ${id}`);
  }
});

test("topic matching uses the documented local rules and avoids substring accidents", () => {
  assert.ok(topicMatchesEvent({ title: "Weekly US gas prices", markets: [] }, "gas"));
  assert.ok(topicMatchesEvent({ title: "General election results", markets: [] }, "elections"));
  assert.ok(topicMatchesEvent({ title: "Grammy awards", markets: [] }, "culture"));
  assert.ok(topicMatchesEvent({ title: "Bitcoin above 90,000", markets: [] }, "crypto"));
  assert.ok(topicMatchesEvent({ title: "PGA Championship winner", markets: [] }, "golf"));
  assert.ok(topicMatchesEvent({ category: "Elections", title: "Unknown", markets: [] }, "elections"));
  assert.equal(topicMatchesEvent({ title: "gaslighting in a film", markets: [] }, "gas"), false);
  assert.deepEqual(matchingTopics({ title: "Golf and PGA Championship", markets: [] }), ["golf"]);
  assert.deepEqual(Object.keys(TOPICS), ["gas", "elections", "culture", "crypto", "golf"]);
});

test("missing child-market values do not become partial or invented event totals", () => {
  const markets = [
    { status: "active", volume_24h_fp: "8.25", open_interest_fp: "10" },
    { status: "active", volume_24h_fp: null, open_interest_fp: "2.5" },
  ];
  assert.equal(sumMarketField(markets, "volume_24h_fp"), null);
  assert.equal(sumMarketField(markets, "open_interest_fp"), 12.5);
  const event = aggregateEvent({ event_ticker: "E1", markets });
  assert.equal(event.marketCount, 2);
  assert.equal(event.volume24hContracts, null);
  assert.equal(event.openInterestContracts, 12.5);
  assert.equal(formatNumber(null), "—");
  assert.equal(finiteNumber("not-a-number"), null);
});

test("event sort puts missing metrics last and keeps active-market aggregation", () => {
  const events = [
    { event: { title: "B" }, volume24hContracts: null, openInterestContracts: 12 },
    { event: { title: "A" }, volume24hContracts: 4, openInterestContracts: 9 },
    { event: { title: "C" }, volume24hContracts: 7, openInterestContracts: 4 },
  ];
  assert.deepEqual(sortEventAggregates(events, "volume").map((row) => row.event.title), ["C", "A", "B"]);
  assert.deepEqual(sortEventAggregates(events, "openInterest").map((row) => row.event.title), ["B", "A", "C"]);
});

test("only finalized binary markets are called YES/NO resolved", () => {
  const cases = [
    [{ status: "finalized", result: "yes" }, true, "resolved"],
    [{ status: "finalized", result: "no" }, true, "resolved"],
    [{ status: "determined", result: "yes" }, false, "determined"],
    [{ status: "disputed", result: "no" }, false, "disputed"],
    [{ status: "finalized", result: "scalar" }, false, "scalar"],
    [{ status: "closed", result: "" }, false, "closed"],
  ];
  for (const [market, expectedBinary, expectedKey] of cases) {
    const detail = resolutionDetails(market);
    assert.equal(detail.isYesNoResolved, expectedBinary);
    assert.equal(detail.key, expectedKey);
  }
  assert.equal(isInResolutionQueue({ status: "determined" }), true);
  assert.equal(isInResolutionQueue({ status: "active" }), false);
});

test("event table links every visible row and flags unverified totals", () => {
  const target = container();
  const events = [
    {
      event_ticker: "EVENT/ONE",
      title: "<Election> event",
      category: "Politics",
      markets: [
        { ticker: "MKT-1", title: "First market", status: "active", volume_24h_fp: "5", open_interest_fp: "3" },
        { ticker: "MKT-2", title: "Second market", status: "active", volume_24h_fp: null, open_interest_fp: "2" },
      ],
    },
    { title: "No official ticker", markets: [{ status: "active", volume_24h_fp: 20 }] },
  ];
  const counts = renderEventTable(target, events);
  assert.deepEqual(counts, { visibleEvents: 1, visibleMarkets: 2 });
  const rows = assertEachRowHasOfficialLink(target.innerHTML);
  assert.equal(rows.length, 1);
  assert.match(rows[0], /EVENT%2FONE/);
  assert.match(rows[0], /&lt;Election&gt; event/);
  assert.doesNotMatch(rows[0], /<Election>/);
  assert.match(rows[0], /Unverified/);
});

test("order-book rows are source-linked and distinguish dollar prices from legacy cents", () => {
  const dollarTarget = container();
  renderOrderbook(dollarTarget, {
    yes_dollars: [["0.42", "12.5"]],
    no_dollars: [["0.58", "4"]],
  }, "MKT-ABC");
  const dollarRows = assertEachRowHasOfficialLink(dollarTarget.innerHTML);
  assert.equal(dollarRows.length, 2);
  assert.match(dollarTarget.innerHTML, /\$0\.4200/);
  assert.match(dollarTarget.innerHTML, /\$0\.5800/);

  const legacyTarget = container();
  renderOrderbook(legacyTarget, { yes: [[42, 3]] }, "MKT-LEGACY");
  assert.match(legacyTarget.innerHTML, /\$0\.4200/);
  assertEachRowHasOfficialLink(legacyTarget.innerHTML);

  const errorTarget = container();
  renderOrderbook(errorTarget, null, "MKT-FAIL", "HTTP 429");
  assert.match(errorTarget.innerHTML, /HTTP 429/);
  assert.match(errorTarget.innerHTML, /No fallback depth is shown/);
});

test("resolution table keeps pending outcomes distinct and links every contract row", () => {
  const target = container();
  const events = [{
    event_ticker: "EV-SETTLE",
    title: "A test event",
    markets: [
      { ticker: "F-YES", status: "finalized", result: "yes", close_time: "2026-11-20T12:00:00Z", title: "Resolved YES" },
      { ticker: "D-YES", status: "determined", result: "yes", title: "Determined YES" },
      { ticker: "F-SCALAR", status: "finalized", result: "scalar", title: "Scalar result" },
      { ticker: "DISPUTED", status: "disputed", result: "no", title: "Disputed NO" },
      { ticker: "CLOSED", status: "closed", result: "", title: "Closed pending" },
    ],
  }];
  const result = renderResolutionTable(target, events);
  assert.equal(result.rows, 5);
  const rows = assertEachRowHasOfficialLink(target.innerHTML);
  assert.equal(rows.length, 5);
  assert.match(target.innerHTML, /Finalized · YES/);
  assert.match(target.innerHTML, /YES · NOT FINAL/);
  assert.match(target.innerHTML, /SCALAR · NOT FINAL/);
  assert.match(target.innerHTML, /Unverified/);
  assert.match(target.innerHTML, /Only finalized markets with YES\/NO results/);
});

test("static register/question/flag/strategy tables have official row links", () => {
  for (const render of [renderSources, renderQuestions, renderFlags, renderStrategyFields]) {
    const target = container();
    render(target);
    assertEachRowHasOfficialLink(target.innerHTML);
  }
  const suggestionTarget = container();
  renderSuggestions(suggestionTarget);
  assert.equal((suggestionTarget.innerHTML.match(/class="suggestion-card"/g) ?? []).length, SUGGESTIONS.length);
  assert.match(suggestionTarget.innerHTML, /data-review-decision="preferred"/);
});

test("settlement-source rows link the Kalshi record and mark an untrusted URL unverified", () => {
  const target = container();
  renderSettlementSources(target, {
    event_ticker: "EV-SOURCES",
    markets: [{ ticker: "MKT-SOURCES" }],
    settlement_sources: [{ name: "Listed source", url: "javascript:alert(1)" }],
  });
  const rows = assertEachRowHasOfficialLink(target.innerHTML);
  assert.equal(rows.length, 1);
  assert.match(rows[0], /Unverified URL/);
  assert.doesNotMatch(rows[0], /javascript:/);
});

test("selected-market renderer escapes untrusted rule text and flags absent quote values", () => {
  const target = container();
  renderSelectedMarket(target, { event_ticker: "EV-1", markets: [] }, {
    ticker: "MKT-1",
    status: "active",
    title: "<Test contract>",
    rules_primary: "<script>alert(1)</script>",
  });
  assert.match(target.innerHTML, /&lt;Test contract&gt;/);
  assert.doesNotMatch(target.innerHTML, /<script>/);
  assert.match(target.innerHTML, /Unverified/);
  assert.match(target.innerHTML, /Market API/);
});

test("price history merges official candles and real browser-local observations by timestamp", () => {
  const now = 1_800_000_000_000;
  const candles = [
    { end_period_ts: (now - 60_000) / 1000, price: { close_dollars: "0.40" } },
    { end_period_ts: (now - 30_000) / 1000, price: { close_dollars: "0.45" } },
  ];
  const samples = [
    { timestamp: now - 30_000, price: 0.46, origin: "REST observation" },
    { timestamp: now, price: 0.48, origin: "REST observation" },
  ];
  const points = mergePriceSeries(candles, samples, 120_000, now);
  assert.deepEqual(points.map((point) => point.price), [0.4, 0.46, 0.48]);
  assert.equal(points[1].origin, "REST observation");
  assert.equal(mergePriceSeries(candles, samples, 1_000, now).length, 1);

  const ticker = `TEST-${now}`;
  recordPriceSample(ticker, "0.51", now);
  assert.deepEqual(localPriceSamples(ticker, 10_000, now).map((sample) => sample.price), [0.51]);
  recordPriceSample(ticker, "invalid", now + 1);
  assert.equal(localPriceSamples(ticker, 10_000, now).length, 1);
});

test("small utility helpers reject unsafe URLs and escape markup", () => {
  assert.equal(escapeHTML(`<a "x">`), "&lt;a &quot;x&quot;&gt;");
  assert.equal(safeHttpsUrl("javascript:alert(1)"), null);
  assert.equal(safeHttpsUrl("https://example.com/ok"), "https://example.com/ok");
});

test("review decisions persist only as local browser preferences", () => {
  const oldDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  const values = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    },
  });
  try {
    setSuggestionDecision("P1", "preferred");
    const target = container();
    renderSuggestions(target);
    assert.match(target.innerHTML, /Preferred for review/);
    assert.ok(values.has("kalshi-demo-suggestion-review-v1"));
  } finally {
    if (oldDescriptor) Object.defineProperty(globalThis, "localStorage", oldDescriptor);
    else delete globalThis.localStorage;
  }
});
