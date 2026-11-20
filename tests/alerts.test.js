import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

/* Runtime test for assets/alerts.js (live swing-alert engine, session f428c4bd).
 * Market-row shapes mirror the official Get Markets response
 * (https://docs.kalshi.com/api-reference/market/get-markets.md):
 * dollar-string prices, volume_fp, status/result enums, tickers batch filter.
 * Same harness pattern as tests/runtime.test.js (globals swapped, timers mocked). */
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const alertsSrc = readFileSync(path.join(repo, "assets", "alerts.js"), "utf8");

const PAGE = `<!DOCTYPE html><html><body>
<span id="alertStatus"></span>
<button id="pauseAlertsBtn"></button><button id="exportAlertsBtn"></button>
<button id="clearAlertsBtn"></button>
<span id="alertCountAll"></span><span id="alertCountRoi"></span>
<div id="chatAll"></div><div id="chatRoi"></div><div id="chartAnnotations"></div>
</body></html>`;

function rowsFor(tick) {
  // tick 1: baseline prices; tick 2: >= $0.10 swings on both markets;
  // tick 3: T1 resolves YES (T1 price unchanged so no new swing; T2 reverts to
  // the no-alert book).
  const t1 = {
    ticker: "KXTEST-1-A", event_ticker: "KXTEST-1", title: "Test A?",
    status: "active", result: "", volume_fp: "5",
    last_price_dollars: "0.41", yes_bid_dollars: "0.40", yes_ask_dollars: "0.42"
  };
  const t2 = {
    ticker: "KXTEST-2-B", event_ticker: "KXTEST-2", title: "Test B?",
    status: "active", result: "", volume_fp: "0",
    last_price_dollars: "0.41", yes_bid_dollars: "0.40", yes_ask_dollars: "0.42"
  };
  if (tick === 1) return [t1, t2];
  if (tick === 2) {
    return [
      Object.assign({}, t1, { last_price_dollars: "0.53",
        yes_bid_dollars: "0.52", yes_ask_dollars: "0.54" }),
      Object.assign({}, t2, { last_price_dollars: "0.61",
        yes_bid_dollars: "0.60", yes_ask_dollars: "0.64" })
    ];
  }
  return [
    Object.assign({}, t1, { last_price_dollars: "0.53", yes_bid_dollars: "0.52",
      yes_ask_dollars: "0.54", status: "finalized", result: "yes" }),
    Object.assign({}, t2, { last_price_dollars: "0.61", yes_bid_dollars: "0.60",
      yes_ask_dollars: "0.64" })
  ];
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

  let calls = 0;
  const drawn = { n: 0 };
  const BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  const esc = (s) => String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  w.KalshiDemo = {
    BASE,
    esc,
    cents: (x) => (x === null || x === undefined || isNaN(Number(x)))
      ? "—" : (Number(x) * 100).toFixed(2) + "¢",
    apiGet: async () => { calls += 1; return { markets: rowsFor(Math.min(calls, 3)) }; }
  };
  w.KalshiDash = {
    state: { markets: [
      { ticker: "KXTEST-1-A", volDollars: 100, _topic: "crypto", title: "Test A?",
        topic: "crypto", event_ticker: "KXTEST-1", status: "active", result: "" },
      { ticker: "KXTEST-2-B", volDollars: 50, _topic: "elections", title: "Test B?",
        topic: "elections", event_ticker: "KXTEST-2", status: "active", result: "" }
    ] },
    drawChart: () => { drawn.n += 1; }
  };

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
  return { w, tick: async () => { await tickFn(); }, advance: (s) => { nowMs += s * 1000; },
    drain, drawn, restore,
    setRows: (rows) => { w.KalshiDemo.apiGet = async () => ({ markets: rows }); } };
}

test("swings >= $0.10 alert both chats, ROI screen filters, chart + jump list annotated, resolution logged", async () => {
  const env = boot();
  try {
    const { w, advance, drain } = env;
    await drain(6); // initial poll records the baseline sample
    assert.match(w.document.getElementById("alertStatus").textContent, /last poll/);

    advance(30);
    await env.tick();
    await drain(8);

    const all = w.document.getElementById("chatAll");
    const roi = w.document.getElementById("chatRoi");
    assert.match(all.innerHTML, /\+12\.00¢/, "T1 swing +12.00c in All feed");
    assert.match(all.innerHTML, /\+21\.00¢/, "T2 swing +21.00c (mid 41->62) in All feed");
    assert.match(all.innerHTML, /not a high-ROI pick/, "T2 marked not-a-pick");
    assert.match(all.innerHTML, /crypto/, "topic tag shown");
    assert.match(roi.innerHTML, /high-ROI pick/, "T1 in ROI chat");
    assert.doesNotMatch(roi.innerHTML, /Test B\?/, "T2 absent from ROI chat");
    assert.match(roi.innerHTML, /HR-3 ✓/, "passed rules displayed");
    assert.equal(w.document.getElementById("alertCountAll").textContent, "2");
    assert.equal(w.document.getElementById("alertCountRoi").textContent, "1");

    // per-row source discipline: exact API row + event link + generated, labelled-unverified news link
    assert.match(all.innerHTML, /external-api\.demo\.kalshi\.co\/trade-api\/v2\/markets\/KXTEST-1-A/,
      "API row link");
    assert.match(all.innerHTML, /markets\?event_ticker=KXTEST-1/, "event rows link");
    assert.match(all.innerHTML, /news\.google\.com\/search\?q=Test/, "generated news search link");
    assert.match(all.innerHTML, /class="unv"/, "news link labelled unverified");

    // chart annotation API + per-market jump list
    const ann = w.KalshiAlerts.annotationsFor("KXTEST-1-A");
    assert.equal(ann.length, 1);
    assert.equal(ann[0].dir, "up");
    assert.ok(Math.abs(ann[0].price - 0.53) < 1e-9);
    w.KalshiAlerts.onSelected("KXTEST-1-A");
    assert.match(w.document.getElementById("chartAnnotations").innerHTML, /▲ 12\.00¢/,
      "jump row listed for the selected market");
    assert.match(w.document.getElementById("chartAnnotations").innerHTML, /NOT an assertion/,
      "causation disclaimer rendered");

    // persistence (browser-only) + redraw hook fired
    assert.equal(JSON.parse(w.localStorage.getItem("kd_alerts_v1")).length, 2);
    assert.ok(env.drawn.n >= 1, "chart redraw requested on new alert");

    // resolution notice: T1 transitions to finalized/yes
    advance(30);
    await env.tick();
    await drain(8);
    assert.match(all.innerHTML, /RESOLVED YES/, "resolution notice posted");
    assert.match(all.innerHTML, /Market Settlement/, "settlement doc linked");
  } finally { env.restore(); }
});

test("below-threshold moves produce no alerts; cooldown buckets dedupe repeat same-direction swings", async () => {
  const env = boot();
  try {
    const { w, advance, drain } = env;
    await drain(6);
    // $0.02 move (below $0.10) — no alert
    env.setRows([
      { ticker: "KXTEST-1-A", event_ticker: "KXTEST-1", title: "Test A?",
        status: "active", result: "", volume_fp: "5",
        last_price_dollars: "0.43", yes_bid_dollars: "0.42", yes_ask_dollars: "0.44" },
      { ticker: "KXTEST-2-B", event_ticker: "KXTEST-2", title: "Test B?",
        status: "active", result: "", volume_fp: "0",
        last_price_dollars: "0.43", yes_bid_dollars: "0.42", yes_ask_dollars: "0.44" }
    ]);
    advance(30);
    await env.tick();
    await drain(8);
    assert.equal(w.document.getElementById("alertCountAll").textContent, "0");

    // >= $0.10 jump: both markets alert; a repeat inside the same 5-min bucket does not
    env.setRows([
      { ticker: "KXTEST-1-A", event_ticker: "KXTEST-1", title: "Test A?",
        status: "active", result: "", volume_fp: "5",
        last_price_dollars: "0.60", yes_bid_dollars: "0.59", yes_ask_dollars: "0.61" },
      { ticker: "KXTEST-2-B", event_ticker: "KXTEST-2", title: "Test B?",
        status: "active", result: "", volume_fp: "0",
        last_price_dollars: "0.60", yes_bid_dollars: "0.59", yes_ask_dollars: "0.61" }
    ]);
    advance(30);
    await env.tick();
    await drain(8);
    assert.equal(w.document.getElementById("alertCountAll").textContent, "2");
    advance(30);
    await env.tick();
    await drain(8);
    assert.equal(w.document.getElementById("alertCountAll").textContent, "2",
      "same-direction repeat within the 5-minute cooldown bucket is suppressed");
  } finally { env.restore(); }
});

test("dashboard page wires the alert engine: ids present and script loaded after dashboard.js", () => {
  const html = readFileSync(path.join(repo, "dashboard.html"), "utf8");
  for (const id of ["chatAll", "chatRoi", "alertStatus", "alertCountAll",
    "alertCountRoi", "chartAnnotations", "pauseAlertsBtn", "exportAlertsBtn",
    "clearAlertsBtn"]) {
    assert.ok(html.includes(`id="${id}"`), `dashboard.html contains #${id}`);
  }
  const order = ["assets/app.js", "assets/dashboard.js", "assets/alerts.js"];
  const at = order.map((s) => html.indexOf(`<script src="${s}"></script>`));
  assert.ok(at.every((x) => x >= 0) && at[0] < at[1] && at[1] < at[2],
    "alerts.js loads after app.js and dashboard.js");
  assert.ok(html.includes("≥ $0.10"), "threshold disclosed on the page");
  assert.ok(html.includes("not validated alpha"), "ROI screen labelled heuristic");
});
