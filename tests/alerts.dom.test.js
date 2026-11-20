// DOM test for alerts.html + assets/alerts.js using jsdom and a mocked API (no network).
// Run: node --test tests/alerts.dom.test.js   (requires `npm ci` for jsdom)
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "alerts.html"), "utf8");
const core = fs.readFileSync(path.join(root, "assets/alerts-core.js"), "utf8");
const app = fs.readFileSync(path.join(root, "assets/alerts.js"), "utf8");

const resp = (body, ok = true) => ({
  ok, status: ok ? 200 : 500,
  json: async () => body,
  text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
});

const HISTORY = [
  { ticker: "M1", topic: "crypto", ts: "2026-11-20T11:00:00+00:00", last_price_dollars: "0.3000",
    yes_bid_dollars: "0.2990", yes_ask_dollars: "0.3010", volume_fp: "5.00" },
  { ticker: "M1", topic: "crypto", ts: "2026-11-20T11:10:00+00:00", last_price_dollars: "0.4500",
    yes_bid_dollars: "0.4490", yes_ask_dollars: "0.4510", volume_fp: "6.00" },
  { ticker: "M1", topic: "crypto", ts: "2026-11-20T11:20:00+00:00", last_price_dollars: "0.4300",
    yes_bid_dollars: "0.4290", yes_ask_dollars: "0.4310", volume_fp: "6.00" },
  { ticker: "M1", topic: "crypto", ts: "2026-11-20T11:30:00+00:00", last_price_dollars: "0.4600",
    yes_bid_dollars: "0.4590", yes_ask_dollars: "0.4610", volume_fp: "6.00" },
];

function makeHandlers(polls, opts = {}) {
  let n = 0;
  return (url) => {
    if (url.endsWith("data/latest/top_events.json")) {
      return resp({
        retrieved_at: "2026-11-20T12:00:00+00:00",
        by_topic: {
          crypto: [{ title: "BTC <i>event</i>", event_ticker: "E1",
            top_markets: [{ ticker: "M1", title: "Market <b>one</b>" }] }],
        },
      });
    }
    if (url.endsWith("data/history/prices.jsonl")) {
      return resp(HISTORY.map((r) => JSON.stringify(r)).join("\n"));
    }
    if (url.includes("tickers=M1")) {
      if (opts.fail) return Promise.reject(new TypeError("Failed to fetch"));
      const s = polls[Math.min(n, polls.length - 1)];
      n++;
      return resp({
        markets: [{
          ticker: "M1", title: "Market <b>one</b>", event_ticker: "E1",
          last_price_dollars: s.last, yes_bid_dollars: s.bid, yes_ask_dollars: s.ask,
          volume_fp: "100.00", status: s.status || "active", result: s.result || "",
        }],
        cursor: "",
      });
    }
    return resp({}, false);
  };
}

async function boot(handlers) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true,
    url: "https://karagemop466-tech.github.io/Demo3/alerts.html",
  });
  const w = dom.window;
  let tick = null;
  w.setInterval = (fn) => { tick = fn; return 1; };
  w.clearInterval = () => {};
  w.fetch = (url) => Promise.resolve().then(() => handlers(String(url)));
  w.eval(core);
  w.eval(app);
  const flush = async () => { for (let i = 0; i < 25; i++) await new Promise((r) => setTimeout(r, 5)); };
  await flush();
  return {
    w, doc: w.document,
    poll: async () => { assert.ok(tick, "poll timer was scheduled"); tick(); await flush(); },
    flush,
  };
}

const UP_AND_DOWN = [
  { last: "0.4600", bid: "0.4500", ask: "0.4600" },  // baseline, no alert
  { last: "0.6000", bid: "0.5900", ask: "0.6000" },  // +0.14 up
  { last: "0.5000", bid: "0.4900", ask: "0.5000", result: "no", status: "finalized" }, // -0.10 down + resolved NO
];

test("alerts page: snapshot backfill, live swings, exact $0.10 threshold, resolution yes/no", async () => {
  const { doc, poll } = await boot(makeHandlers(UP_AND_DOWN));
  const all = () => doc.querySelectorAll("#chatAll .msg");
  const roi = () => doc.querySelectorAll("#chatRoi .msg");

  // Initial: snapshot backfill has one +$0.15 move (0.30 -> 0.45) and one -$0.02 move (no alert).
  // The first live poll is only a baseline.
  assert.equal(all().length, 1, "one snapshot swing expected");
  assert.match(all()[0].className, /\bup\b/);
  assert.match(all()[0].textContent, /snapshot \(collector\)/);
  assert.equal(doc.getElementById("countAll").textContent, "1");

  await poll(); // 0.46 -> 0.60 (+0.14)
  assert.equal(all().length, 2);
  assert.match(all()[1].textContent, /live poll/);
  assert.match(all()[1].textContent, /\+\$0\.1400/);

  await poll(); // 0.60 -> 0.50 (-0.10 exactly) and result "no"
  assert.equal(all().length, 4, "down swing and resolution should both appear");
  const down = [...all()].find((m) => /\bdown\b/.test(m.className) && /live poll/.test(m.textContent));
  assert.ok(down, "live down swing present");
  assert.match(down.textContent, /−\$0\.1000/);
  const res = doc.querySelector("#chatAll .msg.resolved");
  assert.ok(res, "resolution message present");
  assert.match(res.textContent, /RESOLVED: NO/);

  // High-ROI chat: spreads are <= $0.02 and volume > 0 in every fixture, so all swings pass.
  assert.equal(roi().length, 4);
  assert.equal(doc.getElementById("countRoi").textContent, "4");
});

test("alerts page: text from the API is escaped, every API link points at the official demo host", async () => {
  const { doc, poll } = await boot(makeHandlers(UP_AND_DOWN));
  await poll();
  const chat = doc.getElementById("chatAll");
  assert.equal(chat.querySelectorAll("b, i").length, 0, "API text must not become markup");
  assert.match(chat.textContent, /Market <b>one<\/b>/);
  const links = [...chat.querySelectorAll("a.src")];
  assert.ok(links.length >= 2);
  for (const a of links) {
    assert.ok(a.href.startsWith("https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=M1"),
      `unexpected link ${a.href}`);
  }
  assert.match(chat.textContent, /cause link: unverified/);
});

test("alerts page: topic filter hides other topics and the status line reports polling", async () => {
  const { doc, w, poll } = await boot(makeHandlers(UP_AND_DOWN));
  await poll();
  await poll(); // second observation creates the down swing and resolution
  const sel = doc.getElementById("topicSel");
  sel.value = "gas";
  sel.dispatchEvent(new w.Event("change"));
  assert.equal(doc.querySelectorAll("#chatAll .msg").length, 0);
  assert.match(doc.getElementById("chatAll").textContent, /No messages yet for this filter/);
  sel.value = "crypto";
  sel.dispatchEvent(new w.Event("change"));
  assert.ok(doc.querySelectorAll("#chatAll .msg").length >= 3);
  assert.match(doc.getElementById("statusLine").textContent, /LIVE · tracking 1 markets/);
});

test("alerts page: a blocked browser request shows a banner and keeps the snapshot backfill", async () => {
  const { doc } = await boot(makeHandlers(UP_AND_DOWN, { fail: true }));
  const banner = doc.getElementById("banner");
  assert.notEqual(banner.style.display, "none");
  assert.match(banner.textContent, /could not load live data from the demo API/);
  assert.equal(doc.querySelectorAll("#chatAll .msg").length, 1, "snapshot swing still shown");
});
