/**
 * Behavioural check of the live swing-alerting dashboard (alerts.html + assets/alerts.js)
 * inside jsdom, against a mocked Kalshi demo API.
 *
 * It asserts the brief's rules rather than the markup:
 *   - a >= $0.10 move in either direction alerts; $0.09 does not;
 *   - the high-ROI feed only receives alerts that pass the published screen;
 *   - every alert row links the two observation URLs;
 *   - a missing price never becomes a zero or a fake move;
 *   - the movers roll-up and liquidity table are driven by real reported values.
 *
 * Run: node --test tests/alerts.test.js
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { JSDOM, VirtualConsole } from "jsdom";

const ROOT = path.resolve(import.meta.dirname, "..");
const HTML = fs.readFileSync(path.join(ROOT, "alerts.html"), "utf8");
const SCRIPT = fs.readFileSync(path.join(ROOT, "assets/alerts.js"), "utf8");
const TICKER = "KXBTCY-27JAN0100-T20000.00";

function market(price, extra = {}) {
  return {
    ticker: TICKER,
    event_ticker: "KXBTCY-27JAN0100",
    series_ticker: "KXBTCY",
    title: "BTC price on Jan 1, 2027?",
    yes_sub_title: "19,999.99 or below",
    status: "active",
    last_price_dollars: price === null ? null : price.toFixed(4),
    previous_price_dollars: price === null ? null : price.toFixed(4),
    yes_bid_dollars: price === null ? null : (price - 0.01).toFixed(4),
    yes_ask_dollars: price === null ? null : (price + 0.01).toFixed(4),
    volume_fp: "1000.00",
    volume_24h_fp: "500.00",
    open_interest_fp: "2000.00",
    close_time: "2027-01-01T05:00:00Z",
    result: "",
    ...extra
  };
}

function makeFetch(prices) {
  const calls = [];
  const fetchFn = async (url) => {
    const u = new URL(url);
    calls.push(u.toString());
    const body = (obj) => ({
      ok: true, status: 200,
      text: async () => JSON.stringify(obj),
      json: async () => obj
    });
    if (u.pathname.endsWith("/events")) {
      if (u.searchParams.get("series_ticker") !== "KXBTCY") return body({ events: [] });
      return body({
        events: [{
          event_ticker: "KXBTCY-27JAN0100",
          series_ticker: "KXBTCY",
          title: "BTC price on Jan 1, 2027?",
          category: "Crypto",
          tags: ["Crypto"],
          settlement_sources: [
            { name: "CF Benchmarks", url: "https://www.cfbenchmarks.com/" }
          ],
          markets: [market(prices.btc)]
        }]
      });
    }
    if (u.pathname.endsWith("/markets")) {
      if (u.searchParams.get("status") === "settled") {
        return body({ markets: [
          market(0, { status: "settled", result: "yes",
            settlement_value_dollars: "1.0000",
            settlement_ts: "2026-11-20T10:00:00Z" }),
          market(0, { status: "settled", result: "",
            settlement_value_dollars: "" })
        ] });
      }
      const list = (u.searchParams.get("tickers") || "").split(",").filter(Boolean);
      return body({ markets: list.map(() => market(prices.btc)) });
    }
    if (u.pathname.endsWith("/orderbook")) {
      return body({ orderbook_fp: {
        yes_dollars: [["0.3900", "120.00"], ["0.3800", "60.00"]],
        no_dollars: [["0.5900", "80.00"]]
      } });
    }
    return body({});
  };
  fetchFn.calls = calls;
  return fetchFn;
}

async function boot(prices) {
  const vc = new VirtualConsole();
  const errors = [];
  vc.on("jsdomError", (e) => errors.push(e.message));
  vc.on("error", (e) => errors.push(String(e)));
  const dom = new JSDOM(HTML, {
    url: "https://karagemop466-tech.github.io/Demo3/alerts.html",
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole: vc
  });
  const { window } = dom;
  window.fetch = makeFetch(prices);
  window.HTMLCanvasElement.prototype.getContext = function () {
    return new Proxy({}, {
      get: (_t, k) => (k === "canvas" ? this : () => {}),
      set: () => true
    });
  };
  window.eval(SCRIPT);
  window.KalshiAlerts.stop();
  window.KalshiAlerts.setMinGap(0);
  await window.KalshiAlerts.discover();
  await window.KalshiAlerts.pollPrices();
  return { window, dom, errors };
}

function forcePrev(window, price) {
  const st = window.KalshiAlerts.state;
  const arr = st.samples[TICKER];
  if (!arr.length) arr.push({ t: new Date().toISOString(), price, url: "https://prev" });
  arr[arr.length - 1].price = price;
}

test("discovery keeps only the five topics", async () => {
  const { window, errors } = await boot({ btc: 0.40 });
  assert.deepEqual(errors, []);
  const st = window.KalshiAlerts.state;
  assert.equal(Object.keys(st.contracts).length, 1);
  assert.equal(st.contracts[TICKER].topic, "crypto");
  assert.equal(window.KalshiAlerts.topicFor("KXSOLE-26", [], "", "solar") ,
    null, "solar energy must stay out of scope");
  assert.equal(window.KalshiAlerts.topicFor("KXUSOPEN-26", ["Golf"], "Sports", "").topic,
    "golf", "the API's own Golf tag classifies KXUSOPEN");
});

test("threshold: +$0.10 alerts, +$0.09 does not, -$0.10 alerts", async () => {
  const prices = { btc: 0.40 };
  const { window } = await boot(prices);
  const st = window.KalshiAlerts.state;
  forcePrev(window, 0.40);
  prices.btc = 0.49;
  await window.KalshiAlerts.pollPrices();
  assert.equal(st.alerts.length, 0, "$0.09 must not alert");

  forcePrev(window, 0.40);
  prices.btc = 0.50;
  await window.KalshiAlerts.pollPrices();
  assert.equal(st.alerts.length, 1, "exactly $0.10 must alert");
  const up = st.alerts[0];
  assert.equal(up.direction, "up");
  assert.ok(Math.abs(up.delta - 0.10) < 1e-9);
  assert.match(up.prev_url, /\/markets\?tickers=/);
  assert.match(up.url, /\/markets\?tickers=/);
  assert.deepEqual(up.sources, [{ name: "CF Benchmarks", url: "https://www.cfbenchmarks.com/" }]);

  forcePrev(window, 0.50);
  prices.btc = 0.40;
  await window.KalshiPoll || null;
  await window.KalshiAlerts.pollPrices();
  assert.equal(st.alerts.length, 2, "-$0.10 must alert");
  assert.equal(st.alerts[1].direction, "down");
});

test("high-ROI feed only receives screened alerts", async () => {
  const prices = { btc: 0.60 };
  const { window } = await boot(prices);
  const st = window.KalshiAlerts.state;
  forcePrev(window, 0.60);
  prices.btc = 0.70; // $0.10 move -> fails the $0.20 cushion
  await window.KalshiAlerts.pollPrices();
  assert.equal(st.alerts.filter((a) => a.screen.passes).length, 0);

  forcePrev(window, 0.50);
  prices.btc = 0.75; // $0.25 move -> buy NO at 0.25, ROI 3.0
  await window.KalshiAlerts.pollPrices();
  const passing = st.alerts.filter((a) => a.screen.passes);
  assert.equal(passing.length, 1);
  assert.equal(passing[0].screen.side, "no");
  assert.ok(passing[0].screen.roi > 2.9);
  assert.match(window.document.getElementById("bodyRoi").textContent, /HIGH ROI/);
  // the all-events feed still contains everything
  assert.match(window.document.getElementById("bodyAll").textContent, /\$0\.10/);
});

test("movers roll-up reflects the reported move", async () => {
  const prices = { btc: 0.50 };
  const { window } = await boot(prices);
  forcePrev(window, 0.50);
  const st = window.KalshiAlerts.state;
  // make the baseline older than the window so it counts as the "from" sample
  st.samples[TICKER][0].t = new Date(Date.now() - 60000).toISOString();
  prices.btc = 0.62;
  await window.KalshiAlerts.pollPrices();
  const movers = window.KalshiAlerts.moversNow();
  assert.equal(movers.length, 1);
  assert.ok(Math.abs(movers[0].delta - 0.12) < 1e-9);
  assert.match(window.document.getElementById("moversTable").textContent, /BTC price/);
});

test("a missing price never becomes a zero or a fake move", async () => {
  const prices = { btc: 0.50 };
  const { window } = await boot(prices);
  const st = window.KalshiAlerts.state;
  const before = st.alerts.length;
  window.fetch = async () => ({
    ok: true, status: 200,
    json: async () => ({ markets: [{ ticker: TICKER, last_price_dollars: null,
      status: "active" }] }),
    text: async () => ""
  });
  await window.KalshiAlerts.pollPrices();
  assert.equal(st.alerts.length, before, "missing price must not alert");
  assert.equal(st.contracts[TICKER].price, 0.50, "last known price preserved, not zeroed");
});

test("unverified fields are flagged, not filled in", async () => {
  const prices = { btc: 0.50 };
  const { window } = await boot(prices);
  const st = window.KalshiAlerts.state;
  forcePrev(window, 0.60);
  prices.btc = 0.45; // down $0.15 -> movers row
  // The API omits volume_24h_fp for this poll: the row must say unverified, not 0.
  window.fetch = async (url) => {
    const m = market(0.45);
    delete m.volume_24h_fp;
    return { ok: true, status: 200, text: async () => "", json: async () => ({ markets: [m] }) };
  };
  await window.KalshiAlerts.pollPrices();
  const html = window.document.getElementById("moversTable").textContent;
  assert.match(html, /volume_24h unverified/);
  assert.ok(!/\u00a50\b/.test(html), "never renders a zero for a missing volume");
});
