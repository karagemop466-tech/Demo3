// Session 5125afd8 — tests for the swing-alert chat engine (assets/alerts.js, session 6ebc1cb7).
// Exercises the public KD API directly; no network.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const alertsJS = readFileSync(path.join(repo, "assets", "alerts.js"), "utf8");
const dashboardHTML = readFileSync(path.join(repo, "dashboard.html"), "utf8");

const doms = [];
// Close every DOM even when an assertion fails: the engine's setInterval would keep Node alive.
after(() => { doms.forEach((d) => d.window.close()); });
function load() {
  const dom = new JSDOM(dashboardHTML, { url: "https://demo.example.test/Demo3/", runScripts: "outside-only", pretendToBeVisual: true });
  doms.push(dom);
  dom.window.eval(alertsJS);
  return { dom, KD: dom.window.KD };
}
const TICKER = "KXAAAGASW-26NOV23-3.9400";
const mk = (last, extra = {}) => ({
  ticker: TICKER, title: "Will average gas prices be above $3.9400?", topic: "gas",
  series_ticker: "KXAAAGASW", last, vol: 3421.27, oi: 3421.27, ...extra,
});
// Seed the anchor price from a scan row, then feed one live sample.
function step(KD, from, to, extra) {
  KD.onMarkets([mk(from, extra)]);
  KD.onSample(mk(to, extra), { price: to, t: 1 });
}

test("an exact $0.10 move alerts (float-safe): 0.50 -> 0.60", () => {
  const { KD, dom } = load();
  step(KD, 0.5, 0.6);
  const rows = KD.allRows();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].dir, "up");
  assert.equal(rows[0].change, 0.1);
});

test("exact $0.10 downward move alerts too: 0.70 -> 0.60 (0.6-0.7 is not exact in doubles)", () => {
  const { KD, dom } = load();
  step(KD, 0.7, 0.6);
  assert.equal(KD.allRows().length, 1);
  assert.equal(KD.allRows()[0].dir, "down");
});

test("a $0.09 move does not alert", () => {
  const { KD, dom } = load();
  step(KD, 0.5, 0.59);
  assert.equal(KD.allRows().length, 0);
});

test("every alert links the official Get Market record, even when series_ticker is set", () => {
  const { KD, dom } = load();
  step(KD, 0.5, 0.62);
  assert.equal(KD.allRows()[0].api,
    "https://external-api.demo.kalshi.co/trade-api/v2/markets/" + TICKER);
});

test("placeholder high-ROI rule filters: liquid mid-band swing passes; zero volume or extreme price fails", () => {
  const { KD, dom } = load();
  step(KD, 0.5, 0.62);                                 // liquid, mid-band
  step(KD, 0.5, 0.62, { vol: 0, oi: 0, ticker: "NOLIQ" });
  step(KD, 0.90, 1.00, { ticker: "EXTREME" });         // pinned at 100c
  const roi = Array.from(KD.roiRows(), (r) => r.ticker); // local realm for deepStrictEqual
  assert.deepEqual(roi, [TICKER]);
  assert.equal(KD.allRows().length, 3, "the all-events feed keeps every swing");
});

test("the ROI chat is a strict subset of the all-events chat (it filters something)", () => {
  const { KD, dom } = load();
  step(KD, 0.5, 0.62);
  step(KD, 0.2, 0.31, { ticker: "B", vol: 0 });
  assert.ok(KD.roiRows().length < KD.allRows().length);
});

test("alerts render into the two chat tables on the dashboard", () => {
  const { KD, dom } = load();
  step(KD, 0.5, 0.62);
  const d = dom.window.document;
  assert.match(d.getElementById("alertsAll").textContent, /KXAAAGASW-26NOV23-3\.9400/);
  assert.match(d.getElementById("alertsROI").textContent, /high-ROI signal/);
});

// --- ported from session 09824fd8's suite (integration a7ce6f14) ---
test("first quote is a baseline; the same price again produces no alert", () => {
  const { KD } = load();
  KD.onMarkets([mk(0.5)]);
  KD.onSample(mk(0.5), { price: 0.5, t: 1 });
  assert.equal(KD.allRows().length, 0, "an unchanged price is a baseline, not a swing");
  KD.onSample(mk(0.62), { price: 0.62, t: 2 });
  assert.equal(KD.allRows().length, 1, "the next different quote alerts");
});

test("alert renderer escapes market text; clear removes persisted alerts", () => {
  const { KD, dom } = load();
  const evil = mk(0.5, { title: "<script>unsafe</script>" });
  KD.onMarkets([evil]);
  KD.onSample(evil, { price: 0.62, t: 1 });
  const d = dom.window.document;
  assert.equal(d.querySelector("#alertsAll script"), null, "title text must not execute");
  assert.match(d.querySelector("#alertsAll").textContent, /<script>unsafe/);
  assert.ok(dom.window.localStorage.getItem("kd_alerts_v1"), "alerts persist across reloads");
  d.querySelector("#clearAlertsBtn").click();
  assert.equal(KD.allRows().length, 0);
  assert.equal(dom.window.localStorage.getItem("kd_alerts_v1"), null);
});

test("chat tabs switch between the all-events and high-ROI panels", () => {
  const { KD, dom } = load();
  step(KD, 0.5, 0.62);
  const d = dom.window.document;
  d.getElementById("tabROI").click();
  assert.equal(d.getElementById("chatROI").style.display, "");
  assert.equal(d.getElementById("chatAll").style.display, "none");
  d.getElementById("tabAll").click();
  assert.equal(d.getElementById("chatAll").style.display, "");
  assert.match(d.getElementById("alertCount").textContent, /1 alert/);
});

// --- resolution (yes/no) messages, ported from session 13603ac5's feature set (integration a7ce6f14) ---
// Settled records verified live 2026-11-20: GET /markets?series_ticker=KXAAAGASW&status=settled
// returns status "finalized" with result "yes"/"no", settlement_ts, settlement_value_dollars.
const settledRow = (extra = {}) => ({
  ticker: "KXAAAGASW-26NOV16-4.2000", title: "Will average gas prices be above $4.2000?",
  topic: "gas", series_ticker: "KXAAAGASW", event_ticker: "KXAAAGASW-26NOV16",
  status: "finalized", result: "no",
  settlement_ts: "2026-11-16T14:32:51.060078Z", settlement_value: "0.0000",
  ...extra,
});

test("a settled market posts a RESOLVED no message exactly once", () => {
  const { KD, dom } = load();
  KD.onSettled([settledRow()]);
  KD.onSettled([settledRow()]);           // second scan must not duplicate
  const rows = KD.allRows().filter((r) => r.kind === "resolution");
  assert.equal(rows.length, 1, "resolution announced once (deduped by ticker)");
  assert.equal(rows[0].result, "no");
  const text = dom.window.document.getElementById("alertsAll").textContent;
  assert.match(text, /RESOLVED/);
  assert.match(text, /NO/);
  assert.equal(KD.roiRows().length, 0, "resolutions are events, not ROI signals");
});

test("an open market with an empty result does not post a resolution", () => {
  const { KD } = load();
  KD.onSettled([settledRow({ status: "active", result: "" })]);
  KD.onSettled([settledRow({ status: "active", result: "yes" })]); // not finalized yet
  assert.equal(KD.allRows().length, 0);
});

test("a yes resolution renders with its official market API link", () => {
  const { KD, dom } = load();
  KD.onSettled([settledRow({ ticker: "KXDEMO-YES", result: "yes" })]);
  const d = dom.window.document;
  const text = d.getElementById("alertsAll").textContent;
  assert.match(text, /RESOLVED/);
  assert.match(text, /YES/);
  const link = d.querySelector("#alertsAll a.src");
  assert.match(link.getAttribute("href"), /\/markets\/KXDEMO-YES$/);
});
