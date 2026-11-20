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
  const dom = new JSDOM(dashboardHTML, { runScripts: "outside-only", pretendToBeVisual: true });
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
