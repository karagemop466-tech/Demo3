/* Regression pins from session 2a0ddd99 (integration pass) — the parts of the
 * live-alert change requests that the canonical implementation (7b47094a, PR #60)
 * did not yet cover:
 *   1. CR-6D-4 / I-15: demo-exchange synthetic test series (KXDEMO*, KXQUICKSETTLE)
 *      are badged "demo test market" on swing and resolution rows, and the page
 *      discloses that they can appear in the chat.
 *   2. A3 pin: the automation checkbox is initialized from the persisted state.
 *      (Fixed on main via the PR #48 merge; this test keeps it fixed.)
 * Runs assets/alerts.js inside jsdom with a mocked fetch (no network needed).
 *
 * Sources:
 *   https://docs.kalshi.com/api-reference/market/get-markets  (result, settlement fields)
 *   https://docs.kalshi.com/getting_started/market_settlement  (winner pays $1.00)
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function boot({ markets = null } = {}) {
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
      return { ok: true, json: async () => ({ event: { title: "T", settlement_sources: [] } }) };
    }
    return { ok: true, json: async () => ({ markets: markets || [] }) };
  };
  w.setInterval = () => 0;
  w.setTimeout = () => 0;
  w.eval(readFileSync(path.join(ROOT, "assets/alerts.js"), "utf8"));
  w.KD.__urls = urls;
  return w;
}

test("synthetic demo-exchange swing rows are badged 'demo test market' (CR-6D-4 / I-15)", () => {
  const w = boot();
  w.KD.onSample(
    { ticker: "KXDEMOFUTHOURLY-26NOV20H12-UP", title: "Demo hourly up", topic: "crypto",
      event_ticker: "KXDEMOFUTHOURLY-26NOV20H12" },
    { price: 0.50, t: 1 }
  );
  w.KD.onSample(
    { ticker: "KXDEMOFUTHOURLY-26NOV20H12-UP", title: "Demo hourly up", topic: "crypto",
      event_ticker: "KXDEMOFUTHOURLY-26NOV20H12" },
    { price: 0.65, t: 2 }
  );
  assert.equal(w.KD.allRows().length, 1);
  assert.match(w.document.getElementById("alertsAll").innerHTML, /demo test market/);
});

test("non-synthetic rows carry no demo-test-market badge", () => {
  const w = boot();
  w.KD.onSample(
    { ticker: "KXAAAGASM-26NOV30-4.70", title: "Regular gas market", topic: "gas" },
    { price: 0.50, t: 1 }
  );
  w.KD.onSample(
    { ticker: "KXAAAGASM-26NOV30-4.70", title: "Regular gas market", topic: "gas" },
    { price: 0.65, t: 2 }
  );
  assert.doesNotMatch(w.document.getElementById("alertsAll").innerHTML, /demo test market/);
});

test("synthetic resolution rows (KXQUICKSETTLE) are badged and logged once per ticker", () => {
  const w = boot();
  // The canonical implementation renders a resolution in the chat only for a
  // market that produced a swing alert — create that alert first.
  const m = { ticker: "KXQUICKSETTLE-20NOV26H1400-2", title: "1+1 = 2", topic: "other",
    event_ticker: "KXQUICKSETTLE-20NOV26H1400" };
  w.KD.onSample(m, { price: 0.50, t: 1 });
  w.KD.onSample(m, { price: 0.62, t: 2 });
  const first = w.KD.noteResolution({
    ticker: "KXQUICKSETTLE-20NOV26H1400-2", title: "1+1 = 2", result: "yes",
    status: "settled", settlement_value_dollars: "1.0000",
    event_ticker: "KXQUICKSETTLE-20NOV26H1400", series: "KXQUICKSETTLE",
  });
  const dup = w.KD.noteResolution({
    ticker: "KXQUICKSETTLE-20NOV26H1400-2", title: "1+1 = 2", result: "yes",
  });
  assert.equal(first, true);
  assert.equal(dup, false, "a resolution is recorded once per ticker");
  const html = w.document.getElementById("alertsAll").innerHTML;
  assert.match(html, /RESOLVED YES/);
  assert.match(html, /demo test market/);
});

test("the page discloses that synthetic test markets can appear in the chat", () => {
  const html = readFileSync(path.join(ROOT, "dashboard.html"), "utf8");
  assert.match(html, /Synthetic markets/);
  assert.match(html, /KXQUICKSETTLE/);
  assert.match(html, /demo test market/);
  assert.match(html, /I-15/);
});

test("automation checkbox is initialized from persisted state (A3 pin)", () => {
  const dash = readFileSync(path.join(ROOT, "assets", "dashboard.js"), "utf8");
  assert.match(dash, /auto\.checked = !!st\.enabled/);
  assert.match(dash, /var st = T\.automationStatus \? T\.automationStatus\(\) : \{\}/);
});
