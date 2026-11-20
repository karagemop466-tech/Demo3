import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

/* Runtime test for the integrated swing-alert engine (assets/alerts.js).
 * Contract under test: window.KD sinks from assets/dashboard.js (onSample/
 * onMarkets), the 10 s batch poll via KalshiDemo.apiGet, two chat panels,
 * trade-automation hook, chart annotations, resolution notices.
 * Market-row shapes mirror the official Get Markets response
 * (https://docs.kalshi.com/api-reference/market/get-markets.md):
 * dollar-string prices, volume_fp, status/result enums, tickers batch filter. */
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const alertsSrc = readFileSync(path.join(repo, "assets", "alerts.js"), "utf8");

const PAGE = `<!DOCTYPE html><html><body>
<span id="alertStatus"></span>
<label><input type="checkbox" id="alertsEnabled" checked></label>
<button id="autoTrade" disabled></button>
<button id="clearAlertsBtn"></button><button id="exportAlertsBtn"></button>
<span id="alertCount"></span>
<button id="tabAll" data-chat="all"></button><button id="tabROI" data-chat="roi"></button>
<button id="tabSplit" data-chat="split"></button>
<div id="chatAll" class="chat-wrap"><div id="alertsAll"></div></div>
<div id="chatROI" class="chat-wrap"><div id="alertsROI"></div></div>
<span id="alertCountAll"></span><span id="alertCountRoi"></span><span id="noticeCountAll"></span>
<div id="chartAnnotations"></div>
</body></html>`;

function apiRows(tick) {
  // tick 1: baseline; tick 2: >= $0.10 moves; tick 3: T1 resolves YES
  const t1 = {
    ticker: "KXTEST-1-A", event_ticker: "KXTEST-1",
    status: "active", result: "", volume_fp: "5",
    last_price_dollars: "0.41", yes_bid_dollars: "0.40", yes_ask_dollars: "0.42"
  };
  const t2 = {
    ticker: "KXTEST-2-B", event_ticker: "KXTEST-2",
    status: "active", result: "", volume_fp: "0",
    last_price_dollars: "0.41", yes_bid_dollars: "0.40", yes_ask_dollars: "0.42"
  };
  if (tick === 2) {
    return [
      Object.assign({}, t1, { last_price_dollars: "0.53",
        yes_bid_dollars: "0.52", yes_ask_dollars: "0.54" }),
      Object.assign({}, t2, { last_price_dollars: "0.61",
        yes_bid_dollars: "0.60", yes_ask_dollars: "0.64" })
    ];
  }
  if (tick >= 3) {
    return [
      Object.assign({}, t1, { last_price_dollars: "0.53", yes_bid_dollars: "0.52",
        yes_ask_dollars: "0.54", status: "finalized", result: "yes" }),
      Object.assign({}, t2, { last_price_dollars: "0.61", yes_bid_dollars: "0.60",
        yes_ask_dollars: "0.64" })
    ];
  }
  return [t1, t2];
}

function boot() {
  const dom = new JSDOM(PAGE, { url: "https://demo.example.test/Demo3/dashboard.html",
    pretendToBeVisual: true });
  const w = dom.window;
  let nowMs = 1700000000000;
  const RealDate = Date;
  class FakeDate extends RealDate {
    constructor(...args) { if (!args.length) super(nowMs); else super(...args); }
    static now() { return nowMs; }
  }
  let tickFn = null;

  let calls = 1; // boot-time poll short-circuits before the first scan (no fetch),
                 // so the first real fetch happens on the first manual tick
  const drawn = { n: 0 };
  const tradeHits = [];
  const esc = (s) => String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  w.KalshiDemo = {
    BASE: "https://external-api.demo.kalshi.co/trade-api/v2",
    esc,
    cents: (x) => (x === null || x === undefined || isNaN(Number(x)))
      ? "—" : (Number(x) * 100).toFixed(2) + "¢",
    apiGet: async () => { calls += 1; return { markets: apiRows(Math.min(calls, 3)) }; }
  };
  w.KalshiDash = { state: { markets: [] }, drawChart: () => { drawn.n += 1; } };
  w.KalshiTrade = { onSwingAlert: (a) => tradeHits.push(a) };

  const keys = ["window", "document", "localStorage", "setInterval", "clearInterval", "Date"];
  const saved = new Map(keys.map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  globalThis.window = w;
  globalThis.document = w.document;
  globalThis.localStorage = w.localStorage;
  globalThis.Date = FakeDate;
  globalThis.setInterval = (fn) => { tickFn = fn; return 1; };
  globalThis.clearInterval = () => {};
  // eslint-disable-next-line no-eval
  eval(alertsSrc);

  const restore = () => {
    for (const [k, d] of saved) {
      if (d) Object.defineProperty(globalThis, k, d);
      else delete globalThis[k];
    }
  };
  const drain = async (n) => {
    for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r));
  };
  // dashboard.js-equivalent scan feed: KD.onMarkets with marketRow-shaped rows
  const scanFeed = (tick) => {
    const rows = apiRows(tick).map((r) => ({
      ticker: r.ticker, title: r.ticker === "KXTEST-1-A" ? "Test A?" : "Test B?",
      topic: r.ticker === "KXTEST-1-A" ? "crypto" : "elections",
      event_ticker: r.event_ticker, series_ticker: "KXTEST",
      last: Number(r.last_price_dollars), yb: Number(r.yes_bid_dollars),
      ya: Number(r.yes_ask_dollars), vol: Number(r.volume_fp),
      volDollars: Number(r.last_price_dollars) * 10,
      status: r.status, result: r.result
    }));
    w.KD.onMarkets(rows);
    return rows;
  };
  return { w, tick: async () => { await tickFn(); }, advance: (s) => { nowMs += s * 1000; },
    drain, drawn, restore, scanFeed, tradeHits };
}

test("integrated engine: scans + poll alert both chats, ROI screen filters, annotations + links + notices", async () => {
  const env = boot();
  try {
    const { w, advance, drain } = env;
    await drain(6);
    env.scanFeed(1); // baseline prices from the scan
    advance(30);
    await env.tick(); // poll tick 2: >= $0.10 moves on both books
    await drain(10);

    const all = w.document.getElementById("alertsAll");
    const roi = w.document.getElementById("alertsROI");
    assert.match(all.innerHTML, /KXTEST-1-A/, "T1 swing in All chat");
    assert.match(all.innerHTML, /KXTEST-2-B/, "T2 swing in All chat");
    // mid 41c -> 53c
    assert.match(all.innerHTML, /41\.00¢ → 53\.00¢|0\.41/, "price move rendered");
    assert.match(roi.innerHTML, /KXTEST-1-A/, "T1 (all rules pass) in ROI chat");
    assert.doesNotMatch(roi.innerHTML, /KXTEST-2-B/,
      "T2 (no trades: HR-3 fails) absent from ROI chat");
    assert.match(all.innerHTML, /HR-3/, "HR rule chips shown");
    assert.match(all.innerHTML, /✗/, "failed rule marked on T2 row");
    assert.equal(w.document.getElementById("alertCountAll").textContent, "2");
    assert.equal(w.document.getElementById("alertCountRoi").textContent, "1");

    // per-alert links: exact API row (Get Market), event rows query, generated news search
    assert.match(all.innerHTML, /\/trade-api\/v2\/markets\/KXTEST-1-A/, "market API row link");
    assert.ok(!all.innerHTML.includes("/series/KXTEST/markets/"),
      "no bogus /series/…/markets/ market-row link (integration fix)");
    assert.match(all.innerHTML, /markets\?event_ticker=KXTEST-1/, "event rows link");
    assert.match(all.innerHTML, /news\.google\.com\/search\?q=/, "generated news search link");
    assert.match(all.innerHTML, /unv/, "news link labelled unverified");

    // trade automation hook keeps firing (contract from PR #28)
    assert.equal(env.tradeHits.length, 2);
    assert.equal(env.tradeHits[0].dir, "up");

    // chart annotations + per-market jump list
    const ann = w.KalshiAlerts.annotationsFor("KXTEST-1-A");
    assert.equal(ann.length, 1);
    assert.equal(ann[0].dir, "up");
    assert.ok(Math.abs(ann[0].price - 0.53) < 1e-9);
    w.KalshiAlerts.onSelected("KXTEST-1-A");
    assert.match(w.document.getElementById("chartAnnotations").innerHTML, /12\.00¢/,
      "jump listed for the selected market");
    assert.match(w.document.getElementById("chartAnnotations").innerHTML, /NOT an assertion/,
      "causation disclaimer rendered");
    assert.ok(env.drawn.n >= 1, "chart redraw requested on new alert");

    // persistence under the same localStorage key as the merged engine
    assert.equal(JSON.parse(w.localStorage.getItem("kd_alerts_v1")).length, 2);

    // resolution notice on transition to finalized/yes
    advance(30);
    await env.tick();
    await drain(10);
    assert.match(all.innerHTML, /RESOLVED YES/, "resolution notice posted");
    assert.match(all.innerHTML, /settlement doc/, "settlement doc linked");
    assert.equal(w.document.getElementById("noticeCountAll").textContent, "1");
  } finally { env.restore(); }
});

test("below-threshold moves do not alert; cooldown bucket suppresses repeat same-direction swings", async () => {
  const env = boot();
  try {
    const { w, advance, drain } = env;
    await drain(6);
    env.scanFeed(1);
    // small move: 41c -> 43c — nothing
    w.KalshiDemo.apiGet = async () => ({ markets: [
      { ticker: "KXTEST-1-A", event_ticker: "KXTEST-1", status: "active", result: "",
        volume_fp: "5", last_price_dollars: "0.43", yes_bid_dollars: "0.42",
        yes_ask_dollars: "0.44" },
      { ticker: "KXTEST-2-B", event_ticker: "KXTEST-2", status: "active", result: "",
        volume_fp: "0", last_price_dollars: "0.43", yes_bid_dollars: "0.42",
        yes_ask_dollars: "0.44" }
    ] });
    advance(30);
    await env.tick();
    await drain(8);
    assert.equal(w.document.getElementById("alertCountAll").textContent, "0");

    // >= $0.10 jump once, then repeated identical jumps inside the same bucket
    const big = { markets: [
      { ticker: "KXTEST-1-A", event_ticker: "KXTEST-1", status: "active", result: "",
        volume_fp: "5", last_price_dollars: "0.60", yes_bid_dollars: "0.59",
        yes_ask_dollars: "0.61" },
      { ticker: "KXTEST-2-B", event_ticker: "KXTEST-2", status: "active", result: "",
        volume_fp: "5", last_price_dollars: "0.60", yes_bid_dollars: "0.59",
        yes_ask_dollars: "0.61" }
    ] };
    w.KalshiDemo.apiGet = async () => big;
    advance(30);
    await env.tick();
    await drain(8);
    const after1 = w.document.getElementById("alertCountAll").textContent;
    assert.equal(after1, "2");
    advance(30);
    await env.tick();
    await drain(8);
    assert.equal(w.document.getElementById("alertCountAll").textContent, "2",
      "repeat inside the 5-minute bucket is suppressed");
  } finally { env.restore(); }
});

test("dashboard wiring: alert card is generator-owned with the union ids and scripts order", () => {
  const html = readFileSync(path.join(repo, "dashboard.html"), "utf8");
  for (const id of ["alertsEnabled", "autoTrade", "clearAlertsBtn", "exportAlertsBtn",
    "alertCount", "alertStatus", "tabAll", "tabROI", "tabSplit", "chatAll", "chatROI",
    "alertsAll", "alertsROI", "alertCountAll", "alertCountRoi", "noticeCountAll",
    "chartAnnotations"]) {
    assert.ok(html.includes(`id="${id}"`), `dashboard.html contains #${id}`);
  }
  const order = ["assets/app.js", "assets/dashboard.js", "assets/alerts.js"];
  const at = order.map((s) => html.indexOf(`<script src="${s}"></script>`));
  assert.ok(at.every((x) => x >= 0) && at[0] < at[1] && at[1] < at[2],
    "alerts.js loads after app.js and dashboard.js");
  assert.ok(html.includes("≥ $0.10"), "threshold disclosed on the page");
  assert.ok(html.includes("not validated alpha"), "ROI screen labelled heuristic");
  // the card must live in the generator, not only in the page (I-f428c4bd-01)
  const gen = readFileSync(path.join(repo, "scripts", "build_root_site.py"), "utf8");
  assert.ok(gen.includes('id="alertsAll"') && gen.includes("assets/alerts.js"),
    "build_root_site.py owns the alert card and the script tag");
});
