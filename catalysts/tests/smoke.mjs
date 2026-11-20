/* Headless render test for catalysts/index.html (jsdom, no network).
 *
 * Verifies the shipped page actually renders the committed snapshot: the ledger rows,
 * their per-row official source links, the run-status chips, the feed-health and
 * endpoint tables, the topic/direction/link filters and the chart hook — and that no
 * script error occurs. `fetch` is stubbed against the files in this repository, so the
 * test is deterministic and runs with no egress (same command works in CI and locally).
 *
 * Run: node catalysts/tests/smoke.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const SITE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = path.resolve(SITE, "..");
const errors = [];
const checks = [];
function ok(cond, label) {
  checks.push({ label, pass: !!cond });
  if (!cond) console.error("FAIL:", label);
}

function absFor(url) {
  const clean = decodeURIComponent(String(url).split("#")[0].split("?")[0]);
  // relative paths are resolved from the page's own directory, exactly as a browser
  // would (the page fetches ../data/… from the repository root)
  return path.normalize(path.join(SITE, clean));
}

const ctxStub = new Proxy({}, {
  get(target, prop) {
    if (prop === "measureText") return () => ({ width: 12 });
    if (prop === "canvas") return {};
    if (["fillStyle", "strokeStyle", "font", "lineWidth"].includes(prop)) return "";
    if (prop in target) return target[prop];
    return () => undefined;
  },
  set() { return true; },
});

const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + (e.message || e)));
vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

const dom = await JSDOM.fromFile(path.join(SITE, "index.html"), {
  runScripts: "dangerously",
  resources: "usable",          // loads the real ./assets/catalysts.js from disk
  pretendToBeVisual: true,
  virtualConsole: vc,
  beforeParse(window) {
    window.fetch = async (input) => {
      const file = absFor(typeof input === "string" ? input : input.url);
      if (!fs.existsSync(file)) {
        return { ok: false, status: 404, async json() { throw new Error("404"); },
                 async text() { return ""; } };
      }
      const body = fs.readFileSync(file, "utf8");
      return {
        ok: true, status: 200,
        async json() { return JSON.parse(body); },
        async text() { return body; },
      };
    };
    window.HTMLCanvasElement.prototype.getContext = () => ctxStub;
    window.addEventListener("error", (e) => errors.push("window.error: " + e.message));
    window.addEventListener("unhandledrejection", (e) =>
      errors.push("unrejected: " + (e.reason && e.reason.message || e.reason)));
  },
});

const { window } = dom;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

await wait(400);                       // let the snapshot fetches resolve

const doc = window.document;
const snapshot = JSON.parse(fs.readFileSync(path.join(SITE, "data", "swings.json"), "utf8"));
const rows = [...doc.querySelectorAll("#ledger tbody tr")];
ok(rows.length === snapshot.swings.length,
   `ledger renders one row per published swing (${rows.length} of ${snapshot.swings.length})`);

// every row must carry its own official source link (per-row provenance rule)
rows.forEach((tr, i) => {
  const api = [...tr.querySelectorAll("a")].some((a) =>
    /external-api\.demo\.kalshi\.co|demo-api\.kalshi\.co/.test(a.getAttribute("href") || ""));
  ok(api, `row ${i + 1} links the demo API record it was computed from`);
});

const statusChips = doc.getElementById("statusChips").textContent;
ok(/Threshold/.test(statusChips) && /\$0\.10/.test(statusChips),
   "run status states the >= $0.10 threshold");
ok(/Run mode/.test(statusChips), "run status states the collection mode (live vs offline)");

const health = JSON.parse(fs.readFileSync(path.join(SITE, "data", "feed_health.json"), "utf8"));
const feedRows = [...doc.querySelectorAll("#feeds tbody tr")];
ok(feedRows.length === (health.feeds || []).length,
   `feed health table lists every probed feed (${feedRows.length})`);
ok(feedRows.every((tr) => /not usable|usable/.test(tr.textContent)),
   "every feed row states whether it may contribute links");

ok(doc.querySelectorAll("#endpoints tbody tr").length === 0,
   "endpoint table stays empty until a real probe exists (no invented statuses)");

// chart hook: a swing is auto-selected and its catalyst state is explained, never invented
const cats = doc.getElementById("chartCatalysts").textContent;
ok(/no candidate catalyst link|Candidate catalysts/.test(cats),
   "chart area explains the catalyst state for the selected swing");
ok(/chart data:/.test(doc.getElementById("chartSource").textContent),
   "chart states where its points came from (samples or ledger row only)");

// filters
const click = (el) => el.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
const golf = doc.querySelector('#topicFilter button[data-topic="golf"]');
click(golf);
await wait(60);
const golfRows = [...doc.querySelectorAll("#ledger tbody tr")];
ok(golfRows.length === 1 && /No swing matches this filter/.test(golfRows[0].textContent),
   "topic filter narrows the ledger and an empty topic says so plainly");
click(doc.querySelector('#topicFilter button[data-topic="all"]'));
await wait(60);
ok(doc.querySelectorAll("#ledger tbody tr").length === snapshot.swings.length,
   "filter back to All restores every row");

click(doc.querySelector('#linkFilter button[data-link="with"]'));
await wait(60);
const withRows = [...doc.querySelectorAll("#ledger tbody tr")];
const expectWith = snapshot.swings.filter((s) => (s.catalysts || []).length).length;
ok(expectWith ? withRows.length === expectWith
   : /No swing matches this filter/.test(withRows[0].textContent),
   "the 'with candidate link' filter only shows swings that have one");
click(doc.querySelector('#linkFilter button[data-link="all"]'));

// window selector must not break the chart
click(doc.querySelector('#windowPick button[data-window="86400"]'));
await wait(60);
ok(errors.length === 0, `no script errors during render (${errors.slice(0, 3).join(" | ") || "none"})`);

// live-watch wiring present but off by default (no surprise network calls)
ok(doc.getElementById("watchToggle").checked === false, "live polling is off until the user opts in");
ok(doc.getElementById("watchState").textContent.trim() === "idle", "watch state starts idle");

/* ---------- strategy table: numbers as published, verdicts gated by sample size ---------- */
const stratPath = path.join(SITE, "data", "strategies.json");
if (fs.existsSync(stratPath)) {
  const strat = JSON.parse(fs.readFileSync(stratPath, "utf8"));
  const srows = [...doc.querySelectorAll("#strategies tbody tr")];
  ok(srows.length === Math.max(1, (strat.results || []).length),
     `strategy table renders one row per category (${srows.length})`);
  (strat.results || []).forEach((r, i) => {
    const tr = srows[i];
    ok(tr && new RegExp(String(r.n)).test(tr.textContent), `strategy row ${i + 1} states its trade count`);
    if (r.n < (strat.min_n_for_a_claim || 0)) {
      ok(/not evaluable/.test(tr.textContent),
         `strategy row ${i + 1} refuses a verdict below the ${strat.min_n_for_a_claim}-trade floor`);
    }
    (r.markets || []).slice(0, 1).forEach((m) => {
      ok(tr.innerHTML.includes(m.market_api_url),
         `strategy row ${i + 1} links each simulated trade to its market API record`);
    });
  });
  ok(/gross of fees/i.test(doc.getElementById("strategyNote").textContent),
     "the fee/spread caveat is printed next to the table, not hidden in the data file");
} else {
  ok(/No strategy snapshot committed yet/.test(doc.querySelector("#strategies tbody").textContent),
     "strategy table states it has no snapshot rather than inventing one");
}

/* ---------- browser-side alert rule: poll once against a stubbed demo API ---------- */
// The seeded swing's last published price; +15 cents must fire, +9 cents must not.
const seeded = snapshot.swings[0];
const lastUnits = Math.round(Number(seeded.to.last_price_dollars) * 10000);
const priceIn = (unitsDelta) => ((lastUnits + unitsDelta) / 10000).toFixed(4);

const answers = {
  live: { markets: [{
    ticker: seeded.ticker, event_ticker: seeded.event_ticker, series_ticker: "KXDEMOFUTHOURLY",
    title: seeded.title, status: "active", result: "",
    last_price_dollars: priceIn(1500),            // +$0.15 -> alert
    yes_bid_dollars: "0.7000", yes_ask_dollars: "0.8000",
    volume_fp: "8220.00", open_interest_fp: "30.00",
  }] },
  below: { markets: [{
    ticker: seeded.ticker, event_ticker: seeded.event_ticker, title: seeded.title,
    status: "active", result: "",
    last_price_dollars: priceIn(900),              // +$0.09 -> no alert
    yes_bid_dollars: "0.6400", yes_ask_dollars: "0.6600",
  }] },
  settled: { markets: [{
    ticker: seeded.ticker, event_ticker: seeded.event_ticker, title: seeded.title,
    status: "finalized", result: "no", last_price_dollars: "0.0000",
    settlement_ts: "2026-11-20T12:01:19Z", settlement_value_dollars: "0.0000",
  }] },
};
let mode = "live";
window.fetch = async (input) => {
  const url = typeof input === "string" ? input : input.url;
  if (/\/markets\?tickers=/.test(url)) {
    const body = JSON.stringify(answers[mode]);
    return { ok: true, status: 200, async json() { return JSON.parse(body); },
             async text() { return body; } };
  }
  const clean = decodeURIComponent(url.split("#")[0].split("?")[0]);
  const file = path.normalize(path.join(SITE, clean));
  if (!fs.existsSync(file)) {
    return { ok: false, status: 404, async json() { throw new Error("404"); },
             async text() { return ""; } };
  }
  const body = fs.readFileSync(file, "utf8");
  return { ok: true, status: 200, async json() { return JSON.parse(body); },
           async text() { return body; } };
};

click(doc.getElementById("pollNow"));
await wait(120);
const alertText = doc.getElementById("watchAlerts").textContent;
ok(/0\.15/.test(alertText) && /▲/.test(alertText),
   "a $0.15 in-browser move fires an UP alert at the same >= $0.10 rule");
ok(/external-api\.demo\.kalshi\.co/.test(doc.getElementById("watchAlerts").innerHTML),
   "the alert links the exact market API record it came from");
ok(/1 markets/.test(doc.getElementById("watchState").textContent),
   "watch state reports what the poll returned");
ok(/NO|open/.test(doc.querySelector("#ledger tbody tr").textContent),
   "ledger still reports the resolution column after a poll");

mode = "below";
doc.getElementById("watchAlerts").innerHTML = "";
click(doc.getElementById("pollNow"));
await wait(120);
ok(doc.getElementById("watchAlerts").textContent.trim() === "",
   "a $0.09 move does NOT alert (threshold is exact, not rounded)");

mode = "settled";
doc.getElementById("watchAlerts").innerHTML = "";
click(doc.getElementById("pollNow"));
await wait(120);
const settledText = doc.getElementById("watchAlerts").textContent;
ok(/resolved NO/i.test(settledText) && /tracking stopped/i.test(settledText),
   "a finalized market is reported with its yes/no result and polling-tracking stops");

ok(errors.length === 0,
   `no script errors during live watch either (${errors.slice(0, 3).join(" | ") || "none"})`);

const failed = checks.filter((c) => !c.pass);
console.log(`smoke: ${checks.length - failed.length}/${checks.length} checks passed`);
if (failed.length) {
  failed.forEach((f) => console.error("  -", f.label));
  process.exit(1);
}
dom.window.close();
