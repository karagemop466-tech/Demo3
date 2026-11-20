// Session 5125afd8 — end-to-end smoke: real dashboard.html + app.js + dashboard.js + alerts.js,
// with only the Kalshi HTTP responses mocked. Proves the scan hook feeds both alert feeds.
import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const TICKER = "KXAAAGASW-26NOV23-3.9400";
let price = 0.5;

function payload(url) {
  if (/\/series(\?|$)/.test(url)) {
    return { series: [{ ticker: "KXAAAGASW", title: "US gas price (AAA)", category: "Commodities",
      categories: ["Commodities"], tags: [], frequency: "daily" }] };
  }
  if (/\/markets(\?|$)/.test(url)) {
    return { cursor: "", markets: [{ ticker: TICKER, event_ticker: "KXAAAGASW-26NOV23",
      series_ticker: "KXAAAGASW", title: "Will average gas prices be above $3.9400?", status: "active",
      last_price_dollars: price.toFixed(4), yes_bid_dollars: (price - 0.01).toFixed(4),
      yes_ask_dollars: (price + 0.01).toFixed(4), volume_fp: "3421.27", open_interest_fp: "3421.27" }] };
  }
  return {};
}

async function waitFor(fn, label, ms = 8000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return; await new Promise((r) => setTimeout(r, 25)); }
  assert.fail("timed out: " + label);
}

test("live scan hook feeds the all-swings and high-ROI feeds on the real dashboard page", async () => {
  const vc = new VirtualConsole(); // swallow unrelated page-script noise (no network in sandbox)
  const dom = await JSDOM.fromFile(path.join(repo, "dashboard.html"), {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(window) {
      window.fetch = async (url) => { const body = payload(String(url));
        return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }; };
      window.HTMLCanvasElement.prototype.getContext = () => null;
      window.scrollTo = () => {};
    },
  });
  const d = dom.window.document;
  try {
  await waitFor(() => dom.window.KalshiAlerts && d.getElementById("alertFeedAll"), "alerts engine loaded");

  d.getElementById("discoverBtn").click();
  await waitFor(() => /Discovery complete/.test(d.getElementById("discoveryStatus").textContent), "discovery");

  d.getElementById("scanBtn").click(); // primes anchors at $0.50, no alert
  await waitFor(() => /open markets/.test(d.getElementById("scanStatus").textContent), "scan 1");
  assert.equal(d.querySelectorAll("#alertFeedAll li.alert").length, 0, "first scan raises no alert");

  price = 0.62; // +$0.12 move
  d.getElementById("scanBtn").click();
  await waitFor(() => d.querySelectorAll("#alertFeedAll li.alert").length === 1, "swing alert");
  const all = d.querySelector("#alertFeedAll li.alert");
  assert.match(all.textContent, /KXAAAGASW-26NOV23-3\.9400/);
  assert.match(all.className, /\bup\b/);
  assert.match(all.textContent, /\+\$0\.12/);
  assert.match(all.innerHTML, /href="https:\/\/external-api\.demo\.kalshi\.co\/trade-api\/v2\/markets\//);
  assert.equal(d.querySelectorAll("#alertFeedRoi li.alert").length, 1, "passes placeholder high-ROI rule");
  assert.match(d.getElementById("alertCountAll").textContent, /^1$/);
  } finally { dom.window.close(); }
});
