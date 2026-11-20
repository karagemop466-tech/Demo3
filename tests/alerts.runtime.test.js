// Session 6d201d19: runtime test of alerts.html in jsdom (real page + scripts, mocked network).
// Snapshot file comes from disk; the demo API is mocked. Polls are driven manually via a captured timer.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { JSDOM } from "jsdom";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pageUrl = pathToFileURL(path.join(repo, "alerts.html")).href;

function ok(payload) { return { ok: true, status: 200, json: async () => payload }; }

async function waitFor(pred, label) {
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) { if (pred()) return; await new Promise((r) => setTimeout(r, 10)); }
  assert.fail("timed out: " + label);
}

test("alerts.html: snapshot seeds chats; live polls raise >= $0.10 swings; ROI chat gets only passing swings", async () => {
  const snapshot = JSON.parse(readFileSync(path.join(repo, "data/latest/alerts.json"), "utf8"));
  // three real watchlist tickers stand in for A/B/C so the page actually requests them
  const [TA, TB, TC] = snapshot.watchlist.map((w) => w.ticker);
  // baseline quotes (used by the automatic first poll): KX-A 0.20, KX-B 0.50, KX-C 0.10, others 0.01
  let live = (tickers) => tickers.map((t) => ({ ticker: t, title: "Live test market",
    last_price_dollars: t === TA ? "0.2000" : t === TB ? "0.5000" : t === TC ? "0.1000" : "0.0100", volume_fp: "5.00" }));
  const apiCalls = [];
  const dom = new JSDOM(readFileSync(path.join(repo, "alerts.html"), "utf8"), {
    url: pageUrl,
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(window) {
      window.__timer = null;
      window.setInterval = (fn) => { window.__timer = fn; return 1; };
      window.clearInterval = () => {};
      window.fetch = async (url) => {
        const u = String(url);
        if (u.includes("data/latest/alerts.json")) return ok(snapshot);
        if (u.startsWith("https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=")) {
          apiCalls.push(u);
          const tickers = decodeURIComponent(u.split("tickers=")[1]).split(",");
          return ok({ markets: live(tickers), cursor: "" });
        }
        throw new Error("unexpected fetch " + u);
      };
    },
  });
  const w = dom.window, d = w.document;
  const $ = (id) => d.getElementById(id);
  const msgs = (id) => d.querySelectorAll("#" + id + " .msg").length;

  // 1. snapshot seeding
  await waitFor(() => msgs("chatAll") === snapshot.counts.alerts, "snapshot alerts in All chat");
  assert.equal(msgs("chatRoi"), snapshot.counts.high_roi);
  const rows = d.querySelectorAll("#snapRows tr");
  assert.equal(rows.length, snapshot.alerts.length);
  for (const tr of rows) {
    assert.ok(tr.querySelector('a[href^="https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers="]'), "row has official source link");
    assert.ok(/unverified/.test(tr.textContent), "cause link flagged unverified");
  }
  assert.ok(/title unverified/.test($("chatAll").textContent), "missing title shown as unverified");
  assert.ok(/synthetic exchange-test/.test($("chatAll").textContent), "synthetic series labelled");

  // 2. first live poll = baseline only (no new messages)
  await waitFor(() => apiCalls.length >= 1, "first live poll");
  await waitFor(() => /LIVE/.test($("alertStatus").textContent), "live status after baseline");
  const baselineAll = msgs("chatAll");
  assert.equal(baselineAll, snapshot.counts.alerts, "baseline poll emits no swing");

  // 3. second poll: KX-A 0.20 -> 0.35 (+0.15, YES at 0.35 passes ROI); KX-B 0.50 -> 0.40 (-0.10, NO at 0.60 fails ROI)
  //    plus KX-C 0.10 -> 0.15 (+0.05, below threshold: no alert)
  live = (tickers) => tickers.map((t) => ({ ticker: t, title: "Live test market",
    last_price_dollars: t === TA ? "0.3500" : t === TB ? "0.4000" : t === TC ? "0.1500" : "0.0100", volume_fp: "5.00" }));
  w.__timer();
  await waitFor(() => msgs("chatAll") === baselineAll + 2, "two live swings");
  assert.equal(msgs("chatRoi"), snapshot.counts.high_roi + 1, "only KX-A passes the placeholder ROI screen");
  const allText = $("chatAll").textContent;
  assert.ok(/\+\$0\.1500/.test(allText), "KX-A delta shown");
  assert.ok(/-\$0\.1000/.test(allText), "KX-B delta shown");
  assert.ok(!allText.includes(TC), "sub-threshold move not alerted");
  assert.ok(/High-ROI screen \(placeholder\): passes - would buy YES at \$0\.3500/.test($("chatRoi").textContent));
  assert.equal($("countAll").textContent, String(baselineAll + 2));

  // 4. topic filter hides non-matching messages
  $("topicSel").value = "golf";
  $("topicSel").dispatchEvent(new w.Event("change"));
  assert.equal(d.querySelectorAll("#chatAll .msg:not([hidden])").length, 0, "golf filter hides elections/crypto swings");
  $("topicSel").value = "all";
  $("topicSel").dispatchEvent(new w.Event("change"));
  assert.ok(d.querySelectorAll("#chatAll .msg:not([hidden])").length > 0, "all topics shows messages");

  // 5. a failing API read is reported honestly and does not emit alerts
  const before = msgs("chatAll");
  w.fetch = async () => { throw new Error("CORS blocked"); };
  w.__timer();
  await waitFor(() => /could not read the demo API/.test($("alertStatus").textContent), "failure banner");
  assert.equal(msgs("chatAll"), before);
  dom.window.close();
});
