/*
 * End-to-end smoke test of the alert console (session 5ab18dc3, tasks A1/A3).
 *
 * Loads alerts.html in jsdom with a mocked fetch: relative paths resolve to the real
 * committed files in the repo, and https://external-api.demo.kalshi.co/... returns
 * deterministic fixtures shaped like the live demo API (field names per
 * https://docs.kalshi.com/api-reference/market/get-markets.md, .../get-multiple-market-orderbooks.md,
 * .../get-market-candlesticks.md and https://external-api.demo.kalshi.co/trade-api/v2/series/KXWTIMAX).
 * No network is touched. Run: node --test tests/alert_console.test.js
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const API = "https://external-api.demo.kalshi.co/trade-api/v2";

// one market that walks from 40c to 51c across two polls: a +$0.11 swing off the window low
const MARKETS = {
  "KXSMOKE-1-A": { price: 0.4000, bid: 0.3900, ask: 0.4200, bidSize: "900.00", askSize: "700.00" },
  "KXSMOKE-1-B": { price: 0.5000, bid: 0.4900, ask: 0.5100, bidSize: "1200.00", askSize: "1500.00" },
};
let pollCount = 0;

function marketObject(ticker) {
  const m = MARKETS[ticker];
  return {
    ticker, event_ticker: ticker.split("-").slice(0, 2).join("-"), series_ticker: "KXSMOKE",
    title: `Smoke market ${ticker}`, yes_sub_title: ticker, status: "active",
    last_price_dollars: m.price.toFixed(4), previous_price_dollars: "0.4000",
    yes_bid_dollars: m.bid.toFixed(4), yes_ask_dollars: m.ask.toFixed(4),
    yes_bid_size_fp: m.bidSize, yes_ask_size_fp: m.askSize,
    no_bid_dollars: (1 - m.ask).toFixed(4), no_ask_dollars: (1 - m.bid).toFixed(4),
    volume_fp: "120000.00", volume_24h_fp: "40000.00", open_interest_fp: "250000.00",
    notional_value_dollars: "1.0000", close_time: "2026-11-21T06:00:00Z",
    latest_expiration_time: "2026-11-21T06:00:00Z",
    rules_primary: "If the smoke test passes, this market resolves to Yes.",
    result: "", settlement_ts: "", settlement_value_dollars: "",
  };
}

function respond(url) {
  const u = new URL(url, "http://localhost/");
  if (u.origin === "http://localhost") {
    const file = path.join(ROOT, decodeURIComponent(u.pathname));
    if (fs.existsSync(file)) return { ok: true, json: JSON.parse(fs.readFileSync(file, "utf8")) };
    return { ok: false, status: 404 };
  }
  if (!url.startsWith(API)) return { ok: false, status: 400 };
  if (url.includes("/markets?tickers=")) {
    const tickers = (url.split("tickers=")[1].split("&")[0] || "").split(",");
    const first = pollCount === 0;
    return { ok: true, json: { markets: tickers.filter(t => MARKETS[t]).map(t => {
      const base = marketObject(t);
      if (!first) return base;                        // poll 1: seed level
      return base;                                    // poll 2+: same file, price from MARKETS
    }) } };
  }
  if (url.includes("/markets/orderbooks")) {
    return { ok: true, json: { orderbooks: [{ ticker: "KXSMOKE-1-A", orderbook_fp: {
      yes_dollars: [["0.3800", "400.00"], ["0.3900", "900.00"]],
      no_dollars: [["0.5800", "300.00"]] } }] } };
  }
  if (url.includes("/markets/trades")) {
    return { ok: true, json: { trades: [
      // required fields per https://docs.kalshi.com/api-reference/market/get-trades.md
      { trade_id: "t1", ticker: "KXSMOKE-1-A", count_fp: "250.00", yes_price_dollars: "0.5100",
        no_price_dollars: "0.4900", taker_outcome_side: "yes", taker_book_side: "offer",
        created_time: "2026-11-20T19:40:00Z", is_block_trade: false },
      { trade_id: "t2", ticker: "KXSMOKE-1-A", count_fp: "80.00", yes_price_dollars: "0.4000",
        no_price_dollars: "0.6000", taker_outcome_side: "no", taker_book_side: "bid",
        created_time: "2026-11-20T19:39:00Z", is_block_trade: true },
      // a row missing documented required fields -> blank cells + unverified flag, no guessing
      { trade_id: "t3", ticker: "KXSMOKE-1-A", created_time: "2026-11-20T19:38:00Z" },
    ], cursor: "" } };
  }
  if (url.includes("/series/KXSMOKE")) {
    return { ok: true, json: { series: { ticker: "KXSMOKE", title: "Smoke series",
      category: "Test", tags: ["smoke"], fee_type: "quadratic", fee_multiplier: 1,
      settlement_sources: [{ name: "Smoke Feed", url: "https://example.invalid/feed" }],
      contract_terms_url: "https://example.invalid/terms.pdf" } } };
  }
  if (url.includes("candlesticks")) {
    // 3 hours of 1-minute candles flat at the seed price, then the jump only via live polls
    const candlesticks = [];
    for (let i = 0; i < 60; i++) {
      candlesticks.push({ end_period_ts: 1763000000 + i * 60,
        price: { close_dollars: "0.4000", open_dollars: "0.4000", low_dollars: "0.4000", high_dollars: "0.4000" },
        yes_bid: { close_dollars: "0.3900" }, yes_ask: { close_dollars: "0.4200" },
        volume_fp: "5.00", open_interest_fp: "500.00" });
    }
    return { ok: true, json: { ticker: "KXSMOKE-1-A", candlesticks } };
  }
  return { ok: false, status: 404 };
}

async function loadPage() {
  // jsdom will not fetch local files from disk here, so the two page scripts are inlined.
  // "</script" inside a script body (e.g. in a comment or a template string) must be escaped
  // or it terminates the inline element early.
  const inline = (f) => fs.readFileSync(path.join(ROOT, f), "utf8").replace(/<\/script/g, "<\\/script");
  const html = fs.readFileSync(path.join(ROOT, "alerts.html"), "utf8")
    .replace('<script src="assets/swing-core.js"></script><script src="assets/alerts.js"></script>',
      `<script>${inline("assets/swing-core.js")}</script><script>${inline("assets/alerts.js")}</script>`);
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", e => {
    const s = String(e);
    if (/Could not load|not implemented/i.test(s)) return;
    errors.push(s.split("\n").slice(0, 6).join("\n"));
  });
  vc.on("error", (...a) => errors.push(a.join(" ")));
  const dom = new JSDOM(html, {
    url: "http://localhost/alerts.html", runScripts: "dangerously", virtualConsole: vc,
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = async (url) => {
        const r = respond(String(url));
        return { ok: r.ok, status: r.status || 200, json: async () => r.json };
      };
      window.HTMLCanvasElement.prototype.getContext = () => ({
        canvas: { width: 800, height: 400 }, clearRect() {}, fillRect() {}, beginPath() {},
        moveTo() {}, lineTo() {}, stroke() {}, fill() {}, closePath() {}, fillText() {},
        save() {}, restore() {}, arc() {}, setTransform() {},
      });
      window.Notification = { permission: "denied", requestPermission: async () => "denied" };
    },
  });
  const page = { dom, window: dom.window, errors };
  await new Promise(r => setTimeout(r, 700));   // let the async boot settle
  return page;
}

const doc = {};
test("console boots on the committed snapshot and renders the universe", { skip: !fs.existsSync(path.join(ROOT, "data/swings/strategies.json")) }, async () => {
  const p = await loadPage();
  Object.assign(doc, p);
  const d = p.window.document;
  assert.deepEqual(p.errors, [], "page script errors");
  assert.ok(d.getElementById("universeTables").querySelectorAll("table tr").length > 0,
    "universe table should render rows from the snapshot");
  // every row must carry its own API source link (the repo's per-row rule)
  const rows = [...d.querySelectorAll("#universeTables tbody tr")];
  assert.ok(rows.length >= 5);
  for (const r of rows) {
    assert.match(r.innerHTML, /class="src"/, "row without a source link: " + r.textContent.slice(0, 80));
  }
  assert.match(d.getElementById("universeStatus").textContent, /markets across .* topics \| source/);
  assert.match(d.getElementById("modelStatus").textContent, /model: (live|offline) calibration|unreachable/);
  assert.match(d.getElementById("ciStatus").textContent, /CI scan|no CI scan/);
  assert.match(d.getElementById("catalystStatus").textContent, /series metadata|unavailable/);
  // backtest table renders one row per strategy with the source link
  const stratRows = [...d.querySelectorAll("#backtestTable tbody tr")];
  assert.ok(stratRows.length >= 4, "expected a row per measured strategy");
  assert.match(stratRows[0].innerHTML, /strategies\.json/);
});

test("polling two price levels produces one >= $0.10 alert in both feeds", async () => {
  const { window } = doc;
  const d = window.document;
  // feed the engine two levels 11 cents apart through the same code path the timer uses
  const api = window.__alerts;
  assert.ok(api, "the console exposes test hooks");
  const state = api.state;
  const t = "KXSMOKE-1-A";
  const st = api.track(marketObject(t), "crypto");
  api.ingest(marketObject(t));                                   // 0.40 seed
  const jumped = marketObject(t);
  jumped.last_price_dollars = "0.5100";
  api.ingest(jumped);                                            // +$0.11 -> alert
  assert.equal(st.alerts, 1, "one alert expected for a single leg");
  // series metadata is fetched asynchronously; the feed redraws when it lands
  await new Promise(r => setTimeout(r, 400));
  const alert = state.alerts[state.alerts.length - 1];
  assert.equal(alert.direction, "up");
  assert.equal(alert.windowMinutes, 10, "tracker must honour the 10-minute window");
  assert.equal(alert.deltaDollars, 0.11);
  const all = d.querySelectorAll("#feedAll li").length;
  const roi = d.querySelectorAll("#feedRoi li").length;
  assert.ok(all >= 1, "all-events chat should show the alert");
  assert.ok(roi >= 1, "the ROI chat should show the alert or its dimmed near-miss");
  const lastMsg = d.querySelector("#feedAll li:last-child");
  assert.match(lastMsg.textContent, /Smoke market/);
  assert.match(lastMsg.textContent, /Crypto/, "topic badge");
  assert.match(lastMsg.textContent, /book \$0\.3900\/\$0\.4200/, "book prices are dollars, not bits");
  assert.match(lastMsg.innerHTML, /class="src"/, "alert must link its API source");
  assert.match(lastMsg.innerHTML, /candidate news search/, "alerts carry the labelled candidate-news link");
  assert.match(lastMsg.textContent, /settles on Smoke Feed|series metadata/, "official settlement source");
  // no second alert while the run continues (re-arm band), and none below the threshold
  const small = marketObject(t); small.last_price_dollars = "0.5200";
  api.ingest(small);
  assert.equal(st.alerts, 1, "a further $0.01 must not fire a second alert");
});

test("selecting a market draws the chart, the depth ladder and the catalyst block", async () => {
  const { window } = doc;
  const d = window.document;
  await api_select("KXSMOKE-1-A");
  async function api_select(x) { return doc.window.__alerts.select(x); }
  assert.equal(d.getElementById("detail").hidden, false);
  assert.match(d.getElementById("detailTitle").textContent, /KXSMOKE-1-A/);
  assert.match(d.getElementById("chartNote").textContent, /window .* points|candles/);
  assert.match(d.getElementById("depthNote").textContent, /markets\/orderbooks/);
  // YES ladder is sorted best-bid-first, with a running cumulative column and the
  // mirrored NO ask (1 - p) per https://docs.kalshi.com/getting_started/orderbook_responses.md
  const ladder = [...d.querySelectorAll("#depthTable tbody tr")];
  assert.equal(ladder.length, 2, "two YES levels in the fixture book");
  assert.deepEqual([...ladder[0].querySelectorAll("td")].map(x => x.textContent),
    ["$0.3900", "900", "900", "$0.6100"]);
  assert.deepEqual([...ladder[1].querySelectorAll("td")].map(x => x.textContent),
    ["$0.3800", "400", "1,300", "$0.6200"]);
  assert.match(d.getElementById("catalysts").textContent, /Smoke Feed/);
  assert.match(d.getElementById("catalysts").textContent, /If the smoke test passes/);
  // trades table: documented schema, and an unverified flag on the incomplete row
  const fills = [...d.querySelectorAll("#tradesTable tbody tr")];
  assert.equal(fills.length, 3, "three fixture prints");
  assert.deepEqual([...fills[0].querySelectorAll("td")].map(x => x.textContent),
    ["2026-11-20T19:40:00", "$0.5100", "$0.4900", "250", "yes / offer", "no", "trades"]);
  assert.match(fills[2].innerHTML, /pill unverified/, "missing required fields must be flagged, not filled in");
  assert.match(fills[0].innerHTML, /markets\/trades\?ticker=KXSMOKE-1-A&(?:amp;)?limit=100/,
    "the row's link must be the exact request that produced it");
  assert.match(d.getElementById("catalysts").innerHTML, /class="src"/, "catalyst rows need source links");
});

test("resolution of a tracked market is reported once, with its source", async () => {
  const { window } = doc;
  const d = window.document;
  const api = doc.window.__alerts;
  api.track(marketObject("KXSMOKE-1-B"), "crypto");
  const settled = marketObject("KXSMOKE-1-B");
  settled.status = "settled"; settled.result = "yes";
  settled.settlement_ts = "2026-11-20T12:00:00Z"; settled.settlement_value_dollars = "1.0000";
  api.ingest(settled);
  const rows = [...d.querySelectorAll("#resolutionTable tbody tr")];
  assert.ok(rows.length >= 1, "resolution row expected");
  assert.match(rows[0].textContent, /KXSMOKE-1-B/);
  assert.match(rows[0].textContent, /YES/);
  assert.match(rows[0].innerHTML, /markets\?tickers=KXSMOKE-1-B/);
  const before = d.querySelectorAll("#feedAll li").length;
  api.ingest(settled);
  assert.equal(d.querySelectorAll("#feedAll li").length, before, "a resolution must not repeat every poll");
});
