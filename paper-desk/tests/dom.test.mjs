/**
 * DOM smoke test for the paper-desk live panel (jsdom, mocked fetch — no network).
 *
 * Guards the behaviour the brief asks for on this subsite:
 *  - the live panel reads the official demo `GET /markets?tickers=` shape and renders one
 *    row per market, each carrying its own API source link;
 *  - a YES-bid change of >= $0.10 since the last desk cycle is surfaced;
 *  - a failed fetch says "could not reach" and renders NO invented values.
 *
 * Run: node --test paper-desk/tests/   (skips cleanly when jsdom is not installed)
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const site = path.join(repo, "paper-desk");
const htmlPath = path.join(site, "positions.html");
const jsPath = path.join(site, "assets", "paper.js");
const API = "https://external-api.demo.kalshi.co/trade-api/v2";

let JSDOM;
try {
  ({ JSDOM } = await import("jsdom"));
} catch {
  console.log("jsdom not installed - paper-desk DOM test skipped");
}

function marketPayload() {
  return {
    cursor: "",
    markets: [
      {
        ticker: "KXTEST-1-A", event_ticker: "KXTEST-1", status: "active", result: "",
        title: "Test market A", yes_sub_title: "Test A",
        last_price_dollars: "0.2100", yes_bid_dollars: "0.2000", yes_ask_dollars: "0.2200",
        yes_bid_size_fp: "1200.00", yes_ask_size_fp: "900.50",
        no_bid_dollars: "0.7800", no_ask_dollars: "0.8000",
        volume_24h_fp: "500.00", updated_time: "2026-11-20T12:00:00Z",
      },
      {
        ticker: "KXTEST-1-B", event_ticker: "KXTEST-1", status: "active", result: "",
        title: "Test market B", yes_sub_title: "Test B",
        last_price_dollars: "0.5000", yes_bid_dollars: "0.5050", yes_ask_dollars: "0.5100",
        yes_bid_size_fp: "10.00", yes_ask_size_fp: "10.00",
        no_bid_dollars: "0.4900", no_ask_dollars: "0.4950",
        volume_24h_fp: "5.00", updated_time: "2026-11-20T12:00:00Z",
      },
    ],
  };
}

async function boot(fetchImpl) {
  const html = readFileSync(htmlPath, "utf8")
    .replace(/<script src="assets\/paper\.js"><\/script>/, "");
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true,
    url: "https://karagemop466-tech.github.io/Demo3/paper-desk/positions.html" });
  const { window } = dom;
  window.fetch = fetchImpl;
  // the built page's inline globals, overridden for the assertions below
  window.PAPER_API_ROOT = API;
  window.PAPER_TICKERS = ["KXTEST-1-A", "KXTEST-1-B"];
  window.PAPER_MARKS = {
    "KXTEST-1-A": { mark: 0.05, entry: 0.06, side: "yes", count: 40, topic: "crypto",
                    strategy: "swing_fade" },
  };
  window.eval(readFileSync(jsPath, "utf8"));
  window.document.dispatchEvent(new window.Event("DOMContentLoaded"));
  await new Promise((r) => setTimeout(r, 30));
  return window;
}

const ok = (payload) => async (url) => ({
  ok: true, status: 200, json: async () => payload,
  text: async () => JSON.stringify(payload),
});

test("live panel renders one sourced row per market and flags a >= $0.10 move", {
  skip: !JSDOM || !existsSync(htmlPath) ? "jsdom or the built page is missing" : false,
}, async () => {
  const calls = [];
  const window = await boot((url) => {
    calls.push(String(url));
    return Promise.resolve({ ok: true, status: 200, json: async () => marketPayload() });
  });
  const rows = window.document.querySelectorAll("#liveTable tbody tr");
  assert.equal(rows.length, 2, "both demo markets should render");
  assert.match(calls[0], /\/markets\?tickers=/, "must call the documented batch endpoint");
  for (const row of rows) {
    const href = row.querySelector("a[href]") ? row.querySelector("a[href]").getAttribute("href") : "";
    assert.match(href, /^https:\/\/external-api\.demo\.kalshi\.co\/trade-api\/v2\/markets\?tickers=/,
      "each row links the exact API request that produced it");
  }
  // KXTEST-1-A: desk mark 0.05 vs live bid 0.20 -> +0.15 must be surfaced
  const html0 = rows[0].innerHTML;
  assert.match(html0, /\$0\.10 move since the last desk cycle/, "swing badge expected");
  assert.match(html0, /class="pos"/, "direction must be shown as positive");
  assert.match(html0, /\+0\.1500/, "delta value expected");
  // sizes and prices are shown verbatim from the API, never rounded away
  assert.match(html0, /1200\.00 ct/);
  assert.match(rows[1].innerHTML, /\$0\.5050/);
});

test("a blocked request leaves the panel honest, never fabricated", {
  skip: !JSDOM || !existsSync(htmlPath) ? "jsdom or the built page is missing" : false,
}, async () => {
  const window = await boot(() => Promise.reject(new Error("CORS blocked")));
  const box = window.document.getElementById("liveTable").innerHTML;
  assert.match(box, /Could not reach the demo API from this browser/);
  assert.doesNotMatch(box, /\$0\.\d\d\d\d/, "no prices may be invented on failure");
  assert.match(window.document.getElementById("liveStatus").textContent, /blocked or offline/);
});
