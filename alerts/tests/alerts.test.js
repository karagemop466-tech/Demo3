// Offline tests for the live price-swing alert engine (no network; mock fetch).
// Run: node --test alerts/tests/   (the browser files are loaded into a VM sandbox)
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const assetsDir = path.join(here, "..", "assets");

function load() {
  const sandbox = { window: {}, console };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const f of ["model.js", "alerts.js"]) {
    vm.runInContext(fs.readFileSync(path.join(assetsDir, f), "utf8"), sandbox, { filename: f });
  }
  return sandbox.window;
}
const W = load();
const E = W.AlertsEngine;

// Market object shape copied from the live demo record fetched 2026-11-20
// (https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-GPLA).
function market(over = {}) {
  return Object.assign({
    ticker: "KXPRESNOMD-28-GPLA", event_ticker: "KXPRESNOMD-28",
    title: "Will Graham Platner be the nominee for the Presidency for the Democratic party?",
    status: "active", result: "",
    last_price_dollars: "0.9900", yes_bid_dollars: "0.0000", yes_ask_dollars: "1.0000",
    open_interest_fp: "44108150.17", volume_fp: "465856531.27"
  }, over);
}
function ok(body) { return { ok: true, status: 200, json: async () => body }; }
function fail(status) { return { ok: false, status, json: async () => ({}) }; }

test("dollar strings convert to exact integer cents", () => {
  assert.equal(E.cents("0.5600"), 56);
  assert.equal(E.cents("0.1000"), 10);
  assert.equal(E.cents("0.0900"), 9);
  assert.equal(E.cents(null), null);
  assert.equal(E.cents(""), null);
});

test("moves below $0.10 never alert; exactly $0.10 does, both directions", () => {
  assert.equal(E.classifyMove(50, 59, 10), null);
  assert.equal(JSON.stringify(E.classifyMove(50, 60, 10)), JSON.stringify({ direction: "up", delta_cents: 10 }));
  assert.equal(JSON.stringify(E.classifyMove(60, 50, 10)), JSON.stringify({ direction: "down", delta_cents: -10 }));
  assert.equal(JSON.stringify(E.classifyMove(99, 89, 10)), JSON.stringify({ direction: "down", delta_cents: -10 }));
  assert.equal(E.classifyMove(null, 50, 10), null, "first sample is a baseline only");
  assert.equal(E.classifyMove(50, null, 10), null, "missing price is never inferred");
});

test("parseMarket reads the official fields used by the page", () => {
  const p = E.parseMarket(market());
  assert.equal(p.lastC, 99);
  assert.equal(p.bidC, 0);
  assert.equal(p.askC, 100);
  assert.equal(p.spreadC, 100);
  assert.equal(p.result, null);
  assert.equal(E.parseMarket(market({ result: "no" })).result, "no");
});

test("watchlist: top open markets per topic, finalized excluded, bounded size", () => {
  const snap = { topics: {
    elections: [{ event_ticker: "E1", title: "Ev1", markets: [
      { ticker: "A", open_interest: 10, status: "active", title: "a" },
      { ticker: "B", open_interest: 99, status: "finalized", title: "b" },
      { ticker: "C", open_interest: 50, status: "active", title: "c" } ] }],
    golf: [] } };
  const w = E.buildWatchlist(snap);
  assert.equal(JSON.stringify(w.map((x) => x.ticker)), JSON.stringify(["C", "A"]));
  assert.equal(w[0].topic, "elections");
  assert.equal(w[0].topic_label, "Elections");
});

test("the committed snapshot builds a bounded watchlist with ticker and topic on every row", () => {
  const snap = JSON.parse(fs.readFileSync(path.join(here, "..", "..", "data", "events.json"), "utf8"));
  const w = E.buildWatchlist(snap);
  assert.ok(w.length > 0 && w.length <= E.PER_TOPIC * E.TOPICS.length);
  for (const row of w) {
    assert.ok(row.ticker && row.topic && row.topic_label);
    assert.equal(E.marketURL(row.ticker).startsWith("https://external-api.demo.kalshi.co/trade-api/v2/markets/"), true);
  }
});

test("engine: baseline, then a $0.12 move alerts; ROI screen decides which feed gets it", async () => {
  const calls = [];
  let price = "0.4000", spread = [ "0.3900", "0.4100" ];
  const fetchImpl = async (url) => {
    calls.push(url);
    const m = market({ last_price_dollars: price, yes_bid_dollars: spread[0], yes_ask_dollars: spread[1],
      open_interest_fp: "5000" });
    return ok({ markets: [m], cursor: "" });
  };
  const eng = E.createEngine({ fetch: fetchImpl, screen: W.AlertModel.screen,
    now: () => new Date("2026-11-20T12:00:00Z") });
  eng.setWatchlist([{ ticker: "KXPRESNOMD-28-GPLA", event_ticker: "KXPRESNOMD-28", event_title: "Ev",
    title: "t", topic: "elections", topic_label: "Elections", oi: 1 }]);

  let r = await eng.poll();
  assert.equal(r.errors, 0);
  assert.equal(eng.state.alerts.length, 0, "baseline only");
  assert.ok(calls[0].startsWith("https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=1000&tickers=KXPRESNOMD-28-GPLA"));

  price = "0.5200";                       // +$0.12
  r = await eng.poll();
  assert.equal(eng.state.alerts.length, 1);
  const a = eng.state.alerts[0];
  assert.equal(a.direction, "up");
  assert.equal(a.delta_cents, 12);
  assert.equal(a.from_cents, 40);
  assert.equal(a.to_cents, 52);
  assert.equal(a.source_url, E.marketURL("KXPRESNOMD-28-GPLA"));
  assert.equal(a.screen.pass, true, "tight spread, mid price, open interest 5000 pass the stand-in screen");
  assert.equal(eng.state.feedROI.length, 1);

  price = "0.5000";                       // -$0.02, no alert
  await eng.poll();
  assert.equal(eng.state.alerts.length, 1);
});

test("engine: a wide spread alert appears in All events but not in the ROI feed", async () => {
  let price = "0.2000";
  const fetchImpl = async () => ok({ markets: [market({ last_price_dollars: price,
    yes_bid_dollars: "0.1000", yes_ask_dollars: "0.3000", open_interest_fp: "5000" })] });
  const eng = E.createEngine({ fetch: fetchImpl, screen: W.AlertModel.screen });
  eng.setWatchlist([{ ticker: "KXPRESNOMD-28-GPLA", event_ticker: "E", event_title: "", title: "t",
    topic: "elections", topic_label: "Elections", oi: 1 }]);
  await eng.poll();
  price = "0.3100";
  await eng.poll();
  assert.equal(eng.state.feedAll.filter((x) => x.kind === "alert").length, 1);
  assert.equal(eng.state.feedROI.length, 0);
  assert.equal(eng.state.alerts[0].screen.pass, false);
});

test("engine: a yes/no result is recorded as a resolution and tracking stops", async () => {
  let m = market({ last_price_dollars: "0.9000" });
  const eng = E.createEngine({ fetch: async () => ok({ markets: [m] }), screen: W.AlertModel.screen });
  eng.setWatchlist([{ ticker: "KXPRESNOMD-28-GPLA", event_ticker: "E", event_title: "", title: "t",
    topic: "elections", topic_label: "Elections", oi: 1 }]);
  await eng.poll();
  m = market({ last_price_dollars: "1.0000", result: "yes", status: "finalized" });
  await eng.poll();
  assert.equal(eng.state.resolved.length, 1);
  assert.equal(eng.state.resolved[0].result, "yes");
  assert.equal(Object.keys(eng.state.watch).length, 0);
});

test("batch request fails -> single-ticker fallback; absent ticker is reported, not re-requested", async () => {
  const urls = [];
  const fetchImpl = async (url) => {
    urls.push(url);
    if (url.includes("tickers=")) throw new Error("network down");
    return ok({ market: market({ ticker: "T1" }) });
  };
  const eng = E.createEngine({ fetch: fetchImpl, screen: W.AlertModel.screen });
  eng.setWatchlist([{ ticker: "T1", event_ticker: "", event_title: "", title: "", topic: "gas", topic_label: "Gas prices", oi: 1 }]);
  const r = await eng.poll();
  assert.equal(urls.filter((u) => u.includes("tickers=")).length, 1);
  assert.equal(urls.filter((u) => u.endsWith("/markets/T1")).length, 1);
  assert.equal(r.found, 1);
  assert.equal(r.errors, 1, "the failed batch is recorded");

  const urls2 = [];
  const eng2 = E.createEngine({ fetch: async (u) => { urls2.push(u); return ok({ markets: [] }); } });
  eng2.setWatchlist([{ ticker: "ABSENT", event_ticker: "", event_title: "", title: "", topic: "crypto", topic_label: "Crypto", oi: 1 }]);
  const r2 = await eng2.poll();
  assert.equal(urls2.length, 1, "no single-ticker re-request after a successful batch");
  assert.equal(r2.found, 0);
  assert.match(eng2.state.lastErrors[0].error, /not returned/);
});

test("HTTP 429 is reported so the page backs off", async () => {
  const eng = E.createEngine({ fetch: async () => fail(429) });
  eng.setWatchlist([{ ticker: "T1", event_ticker: "", event_title: "", title: "", topic: "golf", topic_label: "Golf", oi: 1 }]);
  const r = await eng.poll();
  assert.equal(r.rateLimited, true);
});

test("ROI stand-in screen: each check is explicit; no return estimate is produced", () => {
  const base = { delta_cents: 12, spread_cents: 2, to_cents: 50, open_interest: 5000 };
  assert.equal(W.AlertModel.screen(base).pass, true);
  assert.equal(W.AlertModel.screen({ ...base, spread_cents: 4 }).pass, false);
  assert.equal(W.AlertModel.screen({ ...base, to_cents: 90 }).pass, false);
  assert.equal(W.AlertModel.screen({ ...base, open_interest: 999 }).pass, false);
  assert.equal(W.AlertModel.screen({ ...base, spread_cents: null }).pass, false, "unknown spread fails");
  assert.equal(W.AlertModel.grossPayoutRatio(50), 1);
  assert.equal(W.AlertModel.grossPayoutRatio(null), null);
});
