/*
 * Unit tests for the alert console's shared logic (session 5ab18dc3, task A1/A2).
 * Run: node --test tests/swing_core.test.js   (also run by .github/workflows/swing-scan.yml)
 *
 * The reference vectors below are hand-computed against the rule stated in
 * alerts/SPEC.md and are asserted identically from the Python side in
 * scripts/tests/test_scan_swings.py — the live poller and the CI backtest cannot drift.
 *
 * Real-response fixtures come from the official demo API (captured 2026-11-20):
 *   https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=2&status=open
 *   https://docs.kalshi.com/api-reference/market/get-markets.md
 *   https://kalshi.com/docs/kalshi-fee-schedule.pdf
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

// assets/swing-core.js is a classic browser script (window global), so it is evaluated in a
// vm context here rather than imported — the file under test stays build-step free.
const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(here, "..", "assets", "swing-core.js"), "utf8");
const ctx = vm.createContext({ console });
vm.runInContext(src, ctx, { filename: "assets/swing-core.js" });
const C = ctx.KalshiSwingCore;

const VECTORS = [5000, 5200, 5400, 5600, 5800, 6000, 6100, 7300, 7400, 6500,
                7600, 8700, 6400, 6300, 7200, 6000, 5100, 4000];
const series = () => VECTORS.map((price, i) => ({ ts: i * 600, price }));

test("bit conversion is exact for API dollar strings", () => {
  assert.equal(C.toBits("0.0040"), 40);
  assert.equal(C.toBits("0.1000"), 1000);
  assert.equal(C.toBits("1.0000"), 10000);
  assert.equal(C.toBits(""), null);
  assert.equal(C.toBits(null), null);
  assert.equal(C.toDollars(1234), 0.1234);
  // the threshold must be an exact integer number of bits, never a float compare
  assert.equal(C.THRESHOLD_BITS, 1000);
});

test("detectSwings matches the documented rule and re-arm band", () => {
  const hits = C.detectSwings(series(), { windowMinutes: 60 });
  // JSON round-trip: the arrays are built inside the vm realm, so a realm-crossing
  // deepStrictEqual would fail on prototypes while the values are identical.
  assert.deepEqual(JSON.parse(JSON.stringify(hits.map(h => [h.ts / 600, h.direction, h.from, h.to, h.deltaDollars]))), [
    // +$0.10 off the window low at sample 5, then the run stays silent (one message per
    // leg) until price gives back $0.05 of the anchor at 16; -$0.47 off the window high at 17.
    [5, "up", 0.5, 0.6, 0.1],
    [17, "down", 0.87, 0.4, 0.47],
  ]);
});

test("a $0.0999 move does not alert; exactly $0.1000 does (>= per the brief)", () => {
  const justUnder = [{ ts: 0, price: 5000 }, { ts: 600, price: 5999 }];
  assert.equal(C.detectSwings(justUnder, { windowMinutes: 60 }).length, 0);
  const exact = [{ ts: 0, price: 5000 }, { ts: 600, price: 6000 }];
  const hits = C.detectSwings(exact, { windowMinutes: 60 });
  assert.equal(hits.length, 1);
  assert.equal(hits[0].deltaDollars, 0.1);
});

test("live tracker mirrors the historical detector on the same samples", () => {
  const t = C.createTracker(60);
  const fired = [];
  VECTORS.forEach((price, i) => {
    const a = C.observe(t, "KXTEST-1-A", {
      ts: i * 600 * 1000, price, bid: price - 100, ask: price + 100,
    });
    if (a) fired.push([a.ts / 600000, a.direction, a.deltaDollars]);
  });
  assert.deepEqual(fired, [[5, "up", 0.1], [17, "down", 0.47]]);
});

test("quoteOf reads the documented market fields and mirrors the book", () => {
  // trimmed real demo record (see header URL); sizes are fixed-point strings
  const market = {
    ticker: "KXPRESNOMD-28-BOBA", event_ticker: "KXPRESNOMD-28",
    series_ticker: "KXPRESNOMD", status: "active",
    last_price_dollars: "0.0040", previous_price_dollars: "0.0030",
    yes_bid_dollars: "0.0020", yes_ask_dollars: "0.0040",
    yes_bid_size_fp: "166666.66", yes_ask_size_fp: "39176.81",
    no_bid_dollars: "0.9960", no_ask_dollars: "0.9980",
    volume_fp: "537223235.37", volume_24h_fp: "62163.57",
    open_interest_fp: "140195139.02", notional_value_dollars: "1.0000",
    close_time: "2028-11-07T15:00:00Z", result: "",
  };
  const q = C.quoteOf(market);
  assert.equal(q.price, 40);
  assert.equal(q.bid, 20);
  assert.equal(q.ask, 40);
  assert.equal(q.mid, 30);
  assert.equal(q.spread, 20);
  assert.equal(q.bidSize, 166666.66);
  assert.equal(q.reference, 30);
  // estimate = volume x notional, labelled an estimate everywhere it is shown
  assert.equal(C.estDollarVolume(market), Math.round(537223235.37 * 1 * 100) / 100);
});

test("fee model reproduces Kalshi's published General Trading Fees Table", () => {
  // https://kalshi.com/docs/kalshi-fee-schedule.pdf — "Fee for 100 contracts" column
  const table = [["0.0100", 0.07], ["0.0500", 0.34], ["0.1000", 0.63], ["0.1500", 0.90],
                 ["0.2000", 1.12], ["0.2500", 1.32], ["0.3000", 1.47], ["0.3500", 1.60],
                 ["0.4000", 1.68], ["0.4500", 1.74], ["0.5000", 1.75], ["0.5500", 1.74],
                 ["0.6000", 1.68], ["0.6500", 1.60], ["0.7000", 1.47], ["0.7500", 1.32],
                 ["0.8000", 1.12], ["0.8500", 0.90], ["0.9000", 0.63], ["0.9500", 0.34],
                 ["0.9900", 0.07]];
  for (const [price, fee] of table) {
    const bits = C.toBits(price);
    const cost = C.buyCostDollars(bits, 100);
    const eff = Math.round((cost - 100 * (bits / C.BIT)) * 100) / 100;
    assert.equal(eff, fee, `taker fee at ${price} for 100 contracts`);
    const proceeds = C.sellProceedsDollars(bits, 100);
    const sellFee = Math.round((100 * (bits / C.BIT) - proceeds) * 100) / 100;
    assert.equal(sellFee, fee, `taker fee on the sell leg at ${price}`);
  }
});

test("roiScore: calibrated bucket + tradable book can pass; a locked book cannot", () => {
  const model = {
    alert_rule: { threshold_dollars: 0.1 },
    roi_model: {
      pass_threshold_score: 0.6,
      weights: { calibrated_edge: 0.35, relative_move: 0.2, executability: 0.2,
                 liquidity_depth: 0.15, time_to_resolution: 0.1 },
      buckets: {
        "crypto|20-50c|10-20c|2-24h": {
          n_swings: 40, n_markets: 12, evidence: "sufficient", reversion_rate: 0.7,
          reversion_rate_shrunk: 0.68, reversion_rate_within_horizon_minutes: 60,
          fade_mean_net_dollars: 0.021, fade_hit_rate: 0.6, fade_n_quotable: 30,
          // the CI scan publishes the best measured exit per bucket; the gate uses it
          best_strategy: "fade60", best_mean_net_dollars: 0.021,
          strategies: {
            fade15: { n_quotable: 28, mean_net_dollars: 0.008, hit_rate: 0.54, mean_gross_dollars: 0.03 },
            fade60: { n_quotable: 30, mean_net_dollars: 0.021, hit_rate: 0.6, mean_gross_dollars: 0.044 },
            momo60: { n_quotable: 30, mean_net_dollars: -0.013, hit_rate: 0.4, mean_gross_dollars: 0.01 },
          },
        },
        // a bucket where swings happen but no measured exit earns its cost back
        "golf|20-50c|10-20c|2-24h": {
          n_swings: 22, n_markets: 9, evidence: "sufficient", reversion_rate: 0.9,
          reversion_rate_shrunk: 0.88, best_strategy: "fade60", best_mean_net_dollars: -0.04,
          strategies: { fade60: { n_quotable: 20, mean_net_dollars: -0.04, hit_rate: 0.2 } },
        },
      },
      excluded_series_prefixes: ["KXDEMOFUTHOURLY", "KXQUICKSETTLE", "KXMVE"],
    },
  };
  const now = Date.parse("2026-11-20T12:00:00Z");
  const market = {
    ticker: "KXBTC-26DEC31-T100000", series_ticker: "KXBTC", __topic: "crypto",
    last_price_dollars: "0.4000", yes_bid_dollars: "0.3900", yes_ask_dollars: "0.4100",
    yes_bid_size_fp: "800.00", yes_ask_size_fp: "650.00",
    latest_expiration_time: "2026-11-21T06:00:00Z",
  };
  const alert = { direction: "up", from: 0.3, to: 0.4, deltaDollars: 0.1,
                  fromBits: 3000, deltaBits: 1000 };
  const good = C.roiScore(market, alert, model, now);
  assert.equal(good.bucket, "crypto|20-50c|10-20c|2-24h");
  assert.equal(good.pass, true, "score " + good.score + " reasons " + good.reasons.join(";"));
  assert.ok(good.score >= 0.6);
  assert.ok(good.components.calibrated_edge > 0.5 && good.components.calibrated_edge <= 1);

  const locked = Object.assign({}, market, { yes_bid_dollars: "0.0000", yes_ask_dollars: "0.0000",
                                              yes_bid_size_fp: "0.00", yes_ask_size_fp: "0.00" });
  const bad = C.roiScore(locked, alert, model, now);
  assert.equal(bad.pass, false);
  assert.equal(bad.components.executability, 0);
  assert.ok(bad.reasons.length >= 1);

  // negative post-fee expectancy in the bucket => never a pick, however big the move
  const golf = Object.assign({}, market, { __topic: "golf", series_ticker: "KXGOLFMAJOR" });
  const noEdge = C.roiScore(golf, alert, model, now);
  assert.equal(noEdge.pass, false, "a bucket whose best strategy loses money cannot be a pick");
  assert.ok(noEdge.reasons.join(" ").indexOf("positive expectancy") >= 0);

  const demoSynthetic = Object.assign({}, market, { series_ticker: "KXDEMOFUTHOURLY" });
  const flagged = C.roiScore(demoSynthetic, alert, model, now);
  assert.equal(flagged.pass, false, "demo synthetic exchange-test series must be excluded");

  const unproven = Object.assign({}, market, { latest_expiration_time: "2027-06-01T06:00:00Z" });
  const noBucket = C.roiScore(unproven, alert, model, now);
  assert.equal(noBucket.evidence, "none");
  assert.equal(noBucket.pass, false, "no calibrated bucket -> not shown as high-ROI");
});

test("bucketKey follows the same string shape the CI calibration table uses", () => {
  // pinned against scan_swings.bucket_key output for a real swing row:
  // "elections|0-5c|>40c|>14d"  (see data/swings/swings.json)
  assert.equal(C.bucketKey("elections", C.toBits("0.0030"), 8200, 17227.6),
               "elections|0-5c|>40c|>14d");
  assert.equal(C.bucketKey("golf", null, 1200, null), "golf|unclassified|10-20c|unclassified");
});

test("classify maps series tickers to the five tracked topics only", () => {
  assert.equal(C.classify({ series_ticker: "KXPRESNOMD" }), "elections");
  assert.equal(C.classify({ series_ticker: "KXGASPRICE" }), "gas");
  assert.equal(C.classify({ series_ticker: "KXBTCMAX150" }), "crypto");
  assert.equal(C.classify({ series_ticker: "KXPGATOUR" }), "golf");
  assert.equal(C.classify({ series_ticker: "KXTIMEPOY" }), "culture");
  assert.equal(C.classify({ series_ticker: "KXNBA" }), null);
  assert.equal(C.classify({ title: "What will the average US gas price be on Nov 30?" }), "gas");
});

test("windowCandlesFor keeps a 60-minute window comparable across intervals", () => {
  assert.equal(C.windowCandlesFor(60, 1), 60);
  assert.equal(C.windowCandlesFor(60, 60), 1);
  assert.equal(C.windowCandlesFor(10, 60), 1);   // never zero: fall back to the prior candle
});

test("candleSeries reads only documented candlestick fields and drops unusable rows", () => {
  const candles = [
    { end_period_ts: 100, price: { close_dollars: "0.3000" }, yes_bid: { close_dollars: "0.2900" },
      yes_ask: { close_dollars: "0.3100" } },
    { end_period_ts: 50, price: { close_dollars: "0.2000" } },
    { end_period_ts: 150, price: {} },
  ];
  const rows = C.candleSeries(candles);
  assert.deepEqual(rows.map(r => r.price), [2000, 3000]);   // sorted, null close dropped
  assert.deepEqual(rows.map(r => r.ts), [50, 100]);
});
