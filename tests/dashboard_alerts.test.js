// Session 5125afd8 — end-to-end smoke: the real dashboard.html + app.js + dashboard.js + trade.js +
// alerts.js + site.js run in jsdom; only the Kalshi HTTP responses are mocked. Proves the scan
// samples reach the alert chats (dashboard.js -> KD.onMarkets / KD.onSample -> alerts.js -> DOM).
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

async function waitFor(fn, label, ms = 12000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return; await new Promise((r) => setTimeout(r, 25)); }
  assert.fail("timed out: " + label);
}

test("live scans feed the all-events and high-ROI chats on the real dashboard page", async () => {
  const dom = await JSDOM.fromFile(path.join(repo, "dashboard.html"), {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    virtualConsole: new VirtualConsole(),
    beforeParse(window) {
      window.fetch = async (url) => {
        const body = payload(String(url));
        return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
      };
      window.HTMLCanvasElement.prototype.getContext = () => null;
      window.scrollTo = () => {};
    },
  });
  try {
    const d = dom.window.document;
    await waitFor(() => dom.window.KD && d.getElementById("alertsAll"), "alerts engine loaded");
    d.getElementById("discoverBtn").click();
    await waitFor(() => /Discovery complete/.test(d.getElementById("discoveryStatus").textContent), "discovery");

    d.getElementById("scanBtn").click(); // seeds the anchor at $0.50
    await waitFor(() => /open markets/.test(d.getElementById("scanStatus").textContent), "scan 1");
    assert.equal(dom.window.KD.allRows().length, 0);

    // dashboard.js records a sample at most every 5 s; wait past that window before the second scan.
    await new Promise((r) => setTimeout(r, 5200));
    price = 0.62;
    d.getElementById("scanBtn").click();
    await waitFor(() => dom.window.KD.allRows().length === 1, "swing alert");

    const row = d.querySelector("#alertsAll tr.alert");
    assert.ok(row, "an alert row is rendered in the all-events chat");
    assert.match(row.className, /\bup\b/);
    assert.match(row.textContent, /KXAAAGASW-26NOV23-3\.9400/);
    assert.match(row.innerHTML, /href="https:\/\/external-api\.demo\.kalshi\.co\/trade-api\/v2\/markets\//);
    assert.equal(dom.window.KD.roiRows().length, 1, "passes the placeholder high-ROI rule");
    // The badge wording follows the published screen: "high-ROI screen" when the
    // documented roi-model screen admits the row, else "high-ROI signal (heuristic)".
    assert.match(d.getElementById("alertsROI").textContent, /high-ROI (screen|signal)/);
  } finally {
    dom.window.close();
  }
});
