/* Live alert chat: >= $0.10 swing threshold, yes/no resolution tracking, and the
 * published high-ROI screen hook. Runs assets/alerts.js inside jsdom with a mocked
 * fetch, so no network is needed (the sandbox cannot reach the demo API).
 *
 * Verified against:
 *   https://docs.kalshi.com/api-reference/market/get-markets   (result, limit, tickers)
 *   https://docs.kalshi.com/getting_started/market_settlement   (winner pays $1.00)
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function boot({ model = null, markets = null, event = null } = {}) {
  const dom = new JSDOM(
    `<!doctype html><html><body>
      <span id="alertCount"></span><span id="resPollStatus"></span>
      <button id="tabAll" data-chat="all"></button><button id="tabROI" data-chat="roi"></button>
      <div id="chatAll"></div><div id="chatROI"></div>
      <div id="alertsAll"></div><div id="alertsROI"></div>
      <input id="alertsEnabled" type="checkbox" checked><button id="clearAlertsBtn"></button>
    </body></html>`,
    { url: "https://example.invalid/Demo3/dashboard.html", runScripts: "outside-only" }
  );
  const w = dom.window;
  const store = {};
  w.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  };
  const urls = [];
  w.fetch = async (url) => {
    urls.push(String(url));
    if (String(url).includes("/events/")) {
      return { ok: true, json: async () => ({ event: event || { title: "T", settlement_sources: [] } }) };
    }
    return { ok: true, json: async () => ({ markets: markets || [] }) };
  };
  // Keep the IIFE from leaving timers behind that would hold the test process open.
  w.setInterval = () => 0;
  w.setTimeout = () => 0;
  w.eval(readFileSync(path.join(ROOT, "assets/alerts.js"), "utf8"));
  if (model) {
    w.KD.roiScore = (a) => model(a);
  }
  w.KD.__urls = urls;
  return w;
}

const market = (over = {}) => ({
  ticker: "KXTESTGAS-26NOV30-4.70",
  title: "Gas price question?",
  topic: "gas",
  series_ticker: "KXTESTGAS",
  event_ticker: "KXTESTGAS-26NOV30",
  rules_primary: "Resolves on the published index.",
  ...over,
});

test("a move of exactly $0.10 alerts; $0.0999 does not (brief threshold is >=)", () => {
  const w = boot();
  w.KD.onSample(market(), { price: 0.45, t: Math.floor(Date.now() / 1000) });
  w.KD.onSample(market(), { price: 0.5499, t: Math.floor(Date.now() / 1000) });
  assert.equal(w.KD.allRows().length, 0, "9.99c must not fire");
  w.KD.onSample(market(), { price: 0.6499, t: Math.floor(Date.now() / 1000) });
  assert.equal(w.KD.allRows().length, 1, "10c fires");
  assert.equal(w.KD.allRows()[0].dir, "up");
  // the cents case that IEEE-754 loses: 0.55 - 0.45 === 0.09999999999999998
  w.KD.clear();
  w.KD.onSample(market({ ticker: "KXOTHER-1" }), { price: 0.45, t: 3 });
  w.KD.onSample(market({ ticker: "KXOTHER-1" }), { price: 0.55, t: 4 });
  assert.equal(w.KD.allRows().length, 1, "an exact 45c -> 55c swing must fire");
});

test("down-swings alert in the other direction and label the price move", () => {
  const w = boot();
  const m = market();
  w.KD.onSample(m, { price: 0.72, t: 1 });
  w.KD.onSample(m, { price: 0.61, t: 2 });
  const rows = w.KD.allRows();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].dir, "down");
  assert.match(w.document.getElementById("alertsAll").innerHTML, /alert down/);
});

test("resolution is tracked to yes/no and shown in the chat with the $1.00 / $0.00 payoff", () => {
  const w = boot();
  const m = market();
  w.KD.onSample(m, { price: 0.40, t: 1 });
  w.KD.onSample(m, { price: 0.60, t: 2 });
  const before = w.document.getElementById("alertsAll").innerHTML;
  assert.doesNotMatch(before, /RESOLVED/, "no outcome while result is empty");

  const added = w.KD.noteResolution({
    ticker: m.ticker, title: m.title, topic: m.topic, series: m.series_ticker,
    result: "yes", status: "finalized", settlement_value_dollars: "1.0000",
    settlement_ts: "2026-11-30T00:00:00Z", event_ticker: m.event_ticker,
    source: "live poll (GET /markets?tickers=…)",
  });
  assert.equal(added, true);
  const html = w.document.getElementById("alertsAll").innerHTML;
  assert.match(html, /RESOLVED YES/);
  assert.match(html, /settled at \$1\.00/);
  assert.match(html, /2026-11-30T00:00:00Z/);
  // the swing row itself now carries the outcome badge
  assert.match(html, /resolved YES/);
  // a duplicate record for the same ticker is not re-posted
  assert.equal(w.KD.noteResolution({ ticker: m.ticker, result: "yes" }), false);
  assert.equal(w.KD.allFeed().filter((i) => i.kind === "resolution").length, 1);
});

test("an unresolved market (empty result) never produces a resolution row", () => {
  const w = boot({ markets: [{ ticker: "KXTESTGAS-26NOV30-4.70", result: "", status: "active" }] });
  const m = market();
  w.KD.onSample(m, { price: 0.40, t: 1 });
  w.KD.onSample(m, { price: 0.55, t: 2 });
  w.KD.noteResolution({ ticker: m.ticker, result: "" });
  w.KD.noteResolution({ ticker: m.ticker, result: "maybe" });
  assert.equal(w.KD.allFeed().filter((i) => i.kind === "resolution").length, 0);
});

test("row links use the documented Get Market route (no undocumented /series/{s}/markets/{t})", () => {
  const w = boot();
  const m = market();
  w.KD.onSample(m, { price: 0.40, t: 1 });
  w.KD.onSample(m, { price: 0.60, t: 2 });
  const api = w.KD.allRows()[0].api;
  assert.equal(api, "https://external-api.demo.kalshi.co/trade-api/v2/markets/" + m.ticker);
  assert.doesNotMatch(api, /\/series\//);
});

test("the resolution watcher batches market tickers with an explicit limit", async () => {
  const w = boot({
    markets: [{
      ticker: "KXTESTGAS-26NOV30-4.70", title: "Gas price question?", event_ticker: "KXTESTGAS-26NOV30",
      result: "no", status: "finalized", settlement_value_dollars: "0.0000",
      settlement_ts: "2026-11-30T00:05:00Z",
    }],
  });
  const m = market();
  w.KD.onSample(m, { price: 0.40, t: 1 });
  w.KD.onSample(m, { price: 0.66, t: 2 });
  const found = await w.KD.pollResolutions();
  assert.equal(found, 1, "one resolution absorbed from the batched call");
  const poll = w.KD.__urls.find((u) => u.includes("/markets?tickers="));
  assert.ok(poll, "a batched GET /markets?tickers= call was made");
  assert.match(poll, /limit=100/, "Get Markets limit is set explicitly (docs default 100)");
  const html = w.document.getElementById("alertsAll").innerHTML;
  assert.match(html, /RESOLVED NO/);
  assert.match(html, /settled at \$0\.0000/);
});

test("the high-ROI chat uses the published screen when it is loaded, and says so", () => {
  const w = boot({ model: () => ({ signal: true, basis: "screen roi-screen-v1: test", stats: { n: 1 } }) });
  const m = market();
  w.KD.onSample(m, { price: 0.40, t: 1 });
  w.KD.onSample(m, { price: 0.60, t: 2 });
  assert.equal(w.KD.roiRows().length, 1);
  const html = w.document.getElementById("alertsROI").innerHTML;
  assert.match(html, /roi-screen-v1/);
});

test("without the model file the row is labelled as the heuristic, not as a model score", () => {
  const w = boot();
  const m = market();
  w.KD.onSample(m, { price: 0.40, t: 1 });
  w.KD.onSample(m, { price: 0.60, t: 2 });
  const basis = w.KD.allRows()[0].roiBasis || "";
  assert.match(basis, /model file not loaded|heuristic/, "the row must say which rule admitted it");
});

test("a resolution of a screened market also appears in the high-ROI chat, not the other chat only", () => {
  const w = boot({ model: () => ({ signal: true, basis: "screen roi-screen-v1: test" }) });
  const m = market({ ticker: "KXTESTGAS-26NOV30-4.90" });
  w.KD.onSample(m, { price: 0.40, t: 1 });
  w.KD.onSample(m, { price: 0.60, t: 2 });
  w.KD.noteResolution({ ticker: m.ticker, result: "no", settlement_value_dollars: "0.0000" });
  assert.match(w.document.getElementById("alertsROI").innerHTML, /RESOLVED NO/);
});

test("titles and tickers are escaped before they reach the chat DOM", () => {
  const w = boot();
  const evil = market({ ticker: "KX<EVIL>", title: "<img src=x onerror=alert(1)>" });
  w.KD.onSample(evil, { price: 0.10, t: 1 });
  w.KD.onSample(evil, { price: 0.90, t: 2 });
  const html = w.document.getElementById("alertsAll").innerHTML;
  assert.doesNotMatch(html, /<img src=x/, "raw markup must not be injected");
  assert.match(html, /&lt;img/, "escaped instead");
});
