/* Tests for the live swing-alert system (session 996e3e28):
 *   1. pure engine: detectSwing threshold semantics (>= $0.10 default), model
 *      gates, market normalization — field names mirror the official /markets
 *      response as captured in data/latest/markets_open.json (per-row source_url);
 *   2. alerts.html integration: two scrolling chats (all events + model picks),
 *      per-message official source links, resolution sweep (yes/no), watch-list
 *      Track wiring to the orderbook ladder.
 * All API responses are mocks shaped like real demo-API payloads (sandbox
 * egress to Kalshi is blocked — see flagged F1; browser access verified live).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const alertsHTML = readFileSync(path.join(repo, "alerts.html"), "utf8");
let bootNumber = 0;

const BASE = "https://external-api.demo.kalshi.co/trade-api/v2";

/* Real timers, captured before the boot harness swaps the globals. */
const realSetTimeout = setTimeout;
const realClearTimeout = clearTimeout;
const sleep = (ms) => new Promise((r) => realSetTimeout(r, ms));

function jsonResponse(payload) {
  const body = JSON.stringify(payload);
  return { ok: true, status: 200, json: async () => payload, text: async () => body };
}

async function waitFor(predicate, label, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await sleep(5);
  }
  assert.fail(`Timed out waiting for ${label}`);
}

/* market rows shaped like the demo /markets response (field names verified
 * against data/latest/markets_open.json). */
function marketRow(overrides) {
  return Object.assign({
    ticker: "KXBTCD-26DEC31-T100K",
    event_ticker: "KXBTCD-26DEC31",
    series_ticker: "SER-BTC",
    title: "Will Bitcoin hit $100K by December 31?",
    status: "active",
    result: "",
    last_price_dollars: "0.3200",
    yes_bid_dollars: "0.3100",
    yes_ask_dollars: "0.3300",
    no_ask_dollars: "0.6800",
    yes_ask_size_fp: "5000",
    volume_24h_fp: "50000",
    volume_fp: "120000",
    open_interest_fp: "300000",
    close_time: "2026-12-31T15:00:00Z",
    rules_primary: "Resolves Yes per the official rules.",
  }, overrides);
}

function restoreGlobals(keys, oldDescriptors) {
  for (const key of keys) {
    const d = oldDescriptors.get(key);
    if (d) Object.defineProperty(globalThis, key, d);
    else delete globalThis[key];
  }
}

async function bootAlertsPage(fetchMock) {
  const dom = new JSDOM(alertsHTML, {
    url: "https://demo.example.test/Demo3/alerts.html",
    pretendToBeVisual: true,
  });
  const keys = ["window", "document", "fetch", "setInterval", "clearInterval",
    "setTimeout", "clearTimeout", "localStorage"];
  const old = new Map(keys.map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.fetch = fetchMock;
  globalThis.setInterval = () => ({ mocked: true });
  globalThis.clearInterval = () => {};
  /* the merged KD engine schedules setTimeout(pollOnce, 4000) at module scope.
   * Pass through short delays (apiGet sleeps <= 400ms; waitFor polls) but
   * swallow >= 1 s engine timers so none can fire after globals are restored. */
  globalThis.setTimeout = (fn, ms, ...rest) => {
    if (typeof ms === "number" && ms >= 1000) return { mocked: true };
    return realSetTimeout(fn, ms, ...rest);
  };
  globalThis.clearTimeout = (t) => { if (t && t.mocked) return; realClearTimeout?.(t); };
  globalThis.localStorage = dom.window.localStorage;
  const n = ++bootNumber;
  try {
    await import(`../assets/app.js?alerts=${n}`);
    await import(`../assets/alerts-page.js?alerts=${n}`);
  } catch (error) {
    dom.window.close();
    restoreGlobals(keys, old);
    throw error;
  }
  return {
    dom,
    win: dom.window,
    engine: dom.window.KalshiAlerts,
    cleanup() {
      dom.window.close();
      restoreGlobals(keys, old);
    },
  };
}

async function bootPage(html, scripts, fetchMock) {
  const dom = new JSDOM(html, {
    url: "https://demo.example.test/Demo3/page.html",
    pretendToBeVisual: true,
  });
  const keys = ["window", "document", "fetch", "setInterval", "clearInterval",
    "setTimeout", "clearTimeout", "localStorage"];
  const old = new Map(keys.map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.fetch = fetchMock;
  globalThis.setInterval = () => ({ mocked: true });
  globalThis.clearInterval = () => {};
  /* the merged KD engine schedules setTimeout(pollOnce, 4000) at module scope.
   * Pass through short delays (apiGet sleeps <= 400ms; waitFor polls) but
   * swallow >= 1 s engine timers so none can fire after globals are restored. */
  globalThis.setTimeout = (fn, ms, ...rest) => {
    if (typeof ms === "number" && ms >= 1000) return { mocked: true };
    return realSetTimeout(fn, ms, ...rest);
  };
  globalThis.clearTimeout = (t) => { if (t && t.mocked) return; realClearTimeout?.(t); };
  globalThis.localStorage = dom.window.localStorage;
  const n = ++bootNumber;
  try {
    for (const src of scripts) {
      await import(`../${src}?boot=${n}-${src.replace(/[^a-z]/g, "")}`);
    }
  } catch (error) {
    dom.window.close();
    restoreGlobals(keys, old);
    throw error;
  }
  return {
    dom,
    win: dom.window,
    cleanup() {
      dom.window.close();
      restoreGlobals(keys, old);
    },
  };
}

/* ------------------------------------------------------------------ engine */
test("detectSwing and model gates behave per the published spec", async () => {
  const fetchMock = async (url) => {
    const u = String(url);
    if (u.includes("/series?") || u.endsWith("/series")) {
      return jsonResponse({ series: [] });
    }
    if (u.includes("resolutions.json")) return jsonResponse({ resolutions: [] });
    return jsonResponse({});
  };
  const { engine, cleanup } = await bootAlertsPage(fetchMock);
  try {
    // first sighting: baseline only
    assert.equal(engine.detectSwing(null, { price: 0.5 }, 10), null);
    // below threshold
    assert.equal(engine.detectSwing({ price: 0.40 }, { price: 0.47 }, 10), null);
    // exactly 10 cents -> alert (>= semantics, brief: ">= $0.10")
    const up = engine.detectSwing({ price: 0.40 }, { price: 0.50 }, 10);
    assert.equal(up.dir, "up");
    assert.equal(up.deltaCents, 10);
    // down direction
    const down = engine.detectSwing({ price: 0.44 }, { price: 0.31 }, 10);
    assert.equal(down.dir, "down");
    assert.equal(down.deltaCents, 13);
    // normalization: missing fields stay null (never inferred)
    const m = engine.normalizeMarket(marketRow({ no_ask_size_fp: undefined }), "crypto");
    assert.equal(m.price, 0.32);
    assert.equal(m.yes_ask, 0.33);
    assert.equal(m.yes_ask_size, 5000);
    assert.equal(m.volume_24h, 50000);
    assert.equal(m.no_ask_size, null);
    assert.equal(m.topic, "crypto");

    // model gates
    const swing = { dir: "up", deltaCents: 13, from: 0.32, to: 0.45 };
    const pass = engine.modelLike(
      engine.normalizeMarket(marketRow({ last_price_dollars: "0.4500",
        yes_bid_dollars: "0.4400", yes_ask_dollars: "0.4500" }), "crypto"), swing);
    assert.equal(pass.liked, true);
    assert.ok(pass.roi > 1.2);
    assert.ok(pass.score > 4);

    const failLiquidity = engine.modelLike(
      engine.normalizeMarket(marketRow({ yes_ask_size_fp: "99" }), "crypto"), swing);
    assert.equal(failLiquidity.liked, false);
    assert.ok(failLiquidity.failed.includes("liquidity"));

    const failUpside = engine.modelLike(
      engine.normalizeMarket(marketRow({ yes_ask_dollars: "0.6000" }), "crypto"), swing);
    assert.equal(failUpside.liked, false);
    assert.ok(failUpside.failed.includes("upside"));

    const failSpread = engine.modelLike(
      engine.normalizeMarket(marketRow({ last_price_dollars: "0.4500",
        yes_bid_dollars: "0.2000", yes_ask_dollars: "0.4500" }), "crypto"), swing);
    assert.equal(failSpread.liked, false);
    assert.ok(failSpread.failed.includes("spread"));

    const failActivity = engine.modelLike(
      engine.normalizeMarket(marketRow({ volume_24h_fp: "500" }), "crypto"), swing);
    assert.equal(failActivity.liked, false);
    assert.ok(failActivity.failed.includes("activity"));

    const failUnknown = engine.modelLike(
      engine.normalizeMarket(marketRow({ yes_ask_dollars: "" }), "crypto"), swing);
    assert.equal(failUnknown.liked, false);
    assert.ok(failUnknown.failed.includes("entry-ask-unknown"));
  } finally {
    cleanup();
  }
});

/* ------------------------------------------------------------- integration */
test("alerts.html: two chats, per-row source links, resolution sweep, track wiring", async () => {
  const poll1 = [marketRow({}),
    marketRow({ ticker: "KXPGATOUR-26DEC05-MC", event_ticker: "KXPGATOUR-26DEC05",
      series_ticker: "SER-GOLF", title: "Will McIlroy top-5 at the Tour Championship?",
      last_price_dollars: "0.5000", yes_bid_dollars: "0.4900", yes_ask_dollars: "0.5100" })];
  const poll2 = [marketRow({ last_price_dollars: "0.4500", yes_bid_dollars: "0.4400",
      yes_ask_dollars: "0.4500" }),
    marketRow({ ticker: "KXPGATOUR-26DEC05-MC", event_ticker: "KXPGATOUR-26DEC05",
      series_ticker: "SER-GOLF", title: "Will McIlroy top-5 at the Tour Championship?",
      last_price_dollars: "0.4700", yes_bid_dollars: "0.4600", yes_ask_dollars: "0.4800" })];
  const settled = { markets: [marketRow({ status: "finalized", result: "yes",
      last_price_dollars: "1.0000", settlement_ts: "2026-11-20T12:20:29.609541Z" })] };
  const events = { events: [{ event_ticker: "KXBTCD-26DEC31", series_ticker: "SER-BTC",
      title: "Will Bitcoin hit $100K by December 31?",
      settlement_sources: [{ name: "Exchange settlement feed",
        url: "https://example-official.test/btc-settlement" }] }] };
  const orderbook = { orderbook_fp: {
    yes_dollars: [["0.44", "1200"], ["0.43", "3400"]],
    no_dollars: [["0.55", "800"], ["0.56", "2100"]],
  } };
  const requests = [];
  let inFlight = 0;
  const fetchMock = async (url) => {
    const u = String(url);
    requests.push(u);
    inFlight++;
    try {
      return await fetchBody(u);
    } finally {
      inFlight--;
    }
  };
  const fetchBody = async (u) => {
    if (u.includes("resolutions.json")) return jsonResponse({ resolutions: [] });
    if (u.endsWith("/series") || u.includes("/series?")) {
      return jsonResponse({ series: [
        { ticker: "SER-BTC", title: "Bitcoin price levels", category: "Financials",
          tags: ["Crypto"], categories: ["Financials"], frequency: "daily" },
        { ticker: "SER-GOLF", title: "PGA Tour golf", category: "Sports",
          tags: ["Golf"], categories: ["Sports"], frequency: "weekly" }] });
    }
    if (u.includes("/markets?") && u.includes("status=open")) {
      return jsonResponse({ markets: requests.filter((r) => r.includes("status=open")).length <= 1 ? poll1 : poll2 });
    }
    if (u.includes("/markets?") && u.includes("status=settled")) {
      return jsonResponse(settled);
    }
    if (u.includes("/events?")) return jsonResponse(events);
    if (u.includes("/orderbook")) return jsonResponse(orderbook);
    return jsonResponse({});
  };

  const { engine, win, cleanup } = await bootAlertsPage(fetchMock);
  const $ = (id) => win.document.getElementById(id);
  const norm = (rows, topic) => rows.map((r) => engine.normalizeMarket(r, topic));
  try {
    // 1. baseline poll -> no alerts, markets watched
    engine.ingest(norm(poll1, "crypto").concat(norm([poll1[1]], "golf")), 10);
    assert.equal($("chatAll").children.length, 0);
    assert.equal(Object.keys(engine.state.watched).length, 2);

    // 2. swing poll: BTC +13¢ (model liked), golf -3¢ (no alert)
    engine.ingest(norm(poll2, "crypto").concat(norm([poll2[1]], "golf")), 10);
    assert.equal($("chatAll").children.length, 1);
    assert.equal($("chatModel").children.length, 1);
    const msg = $("chatAll").firstElementChild.innerHTML;
    assert.match(msg, /13\.00¢/);                    // swing badge (>= 0.10 default)
    assert.match(msg, /45\.00¢/);                    // new price
    assert.match(msg, /%24/);                        // exact API URL (encoded $)
    assert.match(msg, /events\?series_ticker=SER-BTC/); // event API URL
    assert.match(msg, /news\.google\.com\/search/);  // labeled cause-investigation link
    assert.match(msg, /investigate cause/);
    assert.match(msg, /Model pick/);                 // model classification shown
    assert.match(msg, /unverified heuristic/);       // honesty label
    assert.match($("chatModel").firstElementChild.innerHTML, /potential ROI if right/);

    // 3. track wiring: watch list row -> chart + orderbook ladder
    const trackBtn = $("watchedTable").querySelector("button[data-ticker]");
    assert.ok(trackBtn, "watch list should render Track buttons");
    trackBtn.dispatchEvent(new win.Event("click", { bubbles: true }));
    await waitFor(() => $("obTable").innerHTML.includes("YES contracts"), "orderbook ladder");
    assert.match($("obTable").innerHTML, /markets\/KXBTCD-26DEC31-T100K\/orderbook/);
    assert.match($("obTable").innerHTML, /3,400/); // contracts at 0.43 level

    // 4. resolution sweep: settled row -> RESOLVED YES in both chats + table
    await engine.settleSweep();
    await waitFor(() => $("chatAll").innerHTML.includes("RESOLVED YES"), "resolution chat");
    assert.equal($("chatModel").innerHTML.includes("RESOLVED YES"), true,
      "model picks chat follows its tracked picks to resolution");
    assert.match($("resolutionsTable").innerHTML, /KXBTCD-26DEC31-T100K/);
    assert.match($("resolutionsTable").innerHTML, /market API/);
    assert.equal(engine.state.watched["KXBTCD-26DEC31-T100K"], undefined,
      "resolved market leaves the active watch");
    const stored = JSON.parse(win.localStorage.getItem("kd_resolutions"));
    assert.equal(stored.find((r) => r.ticker === "KXBTCD-26DEC31-T100K").result, "yes");
    // official settlement-source link attached from the event response
    await waitFor(() =>
      $("chatAll").innerHTML.includes("example-official.test/btc-settlement"),
      "settlement source link");
  } finally {
    cleanup();
  }
});

/* ------------------------------------------------- merged dashboard coexistence */
test("dashboard.html: merged PR #28 chat engine (assets/alerts.js) coexists with the page engine and renders swing rows with sources", async () => {
  const dashboardHTML = readFileSync(path.join(repo, "dashboard.html"), "utf8");
  const series = { series: [
    { ticker: "SER-BTC", title: "Bitcoin price levels", category: "Financials",
      tags: ["Crypto"], categories: ["Financials"], frequency: "daily" }] };
  const open = { markets: [marketRow({ last_price_dollars: "0.5000",
      yes_bid_dollars: "0.4900", yes_ask_dollars: "0.5100" })] };
  let dashInFlight = 0;
  const fetchMock = async (url) => {
    const u = String(url);
    dashInFlight++;
    try {
      return await dashBody(u);
    } finally {
      dashInFlight--;
    }
  };
  const dashBody = async (u) => {
    if (u.includes("resolutions.json") || u.includes("snapshot.json") ||
        u.includes("verified.json")) {
      return jsonResponse(u.includes("snapshot.json") ? { markets: [] } :
        u.includes("verified.json") ? { resolved: [] } : { resolutions: [] });
    }
    if (u.endsWith("/series") || u.includes("/series?")) return jsonResponse(series);
    if (u.includes("/markets?") && u.includes("status=open")) return jsonResponse(open);
    if (u.includes("/events?")) return jsonResponse({ events: [] });
    return jsonResponse({});
  };
  const { win, cleanup } = await bootPage(dashboardHTML,
    ["assets/app.js", "assets/trade.js", "assets/dashboard.js", "assets/alerts.js",
     "assets/site.js"], fetchMock);
  try {
    assert.ok(win.KD, "merged alert engine (window.KD) should be loaded");
    assert.ok(win.KalshiDemo, "shared client loaded");
    assert.ok(win.KalshiAlerts === undefined,
      "page engine must not load on the dashboard (no shared-script collision)");
    // feed the merged engine a >= $0.10 swing exactly like the dashboard samples do
    const $ = (id) => win.document.getElementById(id);
    win.KD.onSample(
      { ticker: "KXBTCD-26DEC31-T100K", title: "Will Bitcoin hit $100K by December 31?",
        topic: "crypto", series_ticker: "SER-BTC" },
      { t: Math.floor(Date.now() / 1000), price: 0.50 });
    win.KD.onSample(
      { ticker: "KXBTCD-26DEC31-T100K", title: "Will Bitcoin hit $100K by December 31?",
        topic: "crypto", series_ticker: "SER-BTC" },
      { t: Math.floor(Date.now() / 1000), price: 0.62 });
    await waitFor(() => $("alertsAll").innerHTML.includes("KXBTCD-26DEC31-T100K"),
      "merged chat renders the swing");
    assert.match($("alertsAll").innerHTML, /market API/);
    assert.match($("alertsAll").innerHTML, /62\.00¢/);
    assert.match($("alertCount").textContent, /1 alert/);
    // persistence key belongs to the merged engine only (page key untouched)
    assert.equal(win.localStorage.getItem("kd_alerts_page_v1"), null);
    // let the dashboard's async init (discover + scan chain) settle before teardown
    await waitFor(() => ($("scanStatus") || {}).textContent?.includes("Last scan"),
      "dashboard scan to settle");
    // sustained network quiescence: K.apiGet sleeps ~400ms BEFORE each fetch,
    // so "no in-flight fetch" must hold across a window longer than that
    // spacing (and any chain that just woke up) before globals are restored.
    let quietStreak = 0;
    for (let i = 0; i < 12; i++) {
      await sleep(500);
      quietStreak = dashInFlight === 0 ? quietStreak + 1 : 0;
      if (quietStreak >= 4) break;
    }
    assert.ok(quietStreak >= 4, "fetch activity never went quiet before teardown");
  } finally {
    cleanup();
  }
});
