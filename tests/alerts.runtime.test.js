// Session 6d201d19: runtime test of alerts.html in jsdom (real page + scripts, mocked network).
// Session 13603ac5: extended for the yes/no resolution feed, the official cause/event links and
// the exchange previous_price_dollars detection path.
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

test("alerts.html: snapshot seeds chats + resolutions + cause links; live polls raise swings; settled markets post yes/no", async () => {
  const snapshot = JSON.parse(readFileSync(path.join(repo, "data/latest/alerts.json"), "utf8"));
  // four real watchlist tickers stand in for A/B/C/D so the page actually requests them
  const [TA, TB, TC, TD] = snapshot.watchlist.map((w) => w.ticker);
  // baseline quotes (used by the automatic first poll): KX-A 0.20, KX-B 0.50, KX-C 0.10, KX-D 0.40
  let live = (tickers) => tickers.map((t) => ({ ticker: t, title: "Live test market",
    last_price_dollars: t === TA ? "0.2000" : t === TB ? "0.5000" : t === TC ? "0.1000" :
      t === TD ? "0.4000" : "0.0100",
    previous_price_dollars: t === TA ? "0.2000" : t === TB ? "0.5000" : t === TC ? "0.1000" :
      t === TD ? "0.4000" : "0.0100",
    volume_fp: "5.00" }));
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
        if (u.startsWith("https://external-api.demo.kalshi.co/trade-api/v2/events/")) {
          return ok({ event: { event_ticker: u.split("/").pop(),
            title: "Live test event",
            settlement_sources: [{ name: "Live Test Source", url: "https://example.org/live" }] } });
        }
        if (u.startsWith("https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=")) {
          apiCalls.push(u);
          const tickers = decodeURIComponent(u.split("tickers=")[1].split("&")[0]).split(",");
          return ok({ markets: live(tickers), cursor: "" });
        }
        throw new Error("unexpected fetch " + u);
      };
    },
  });
  const w = dom.window, d = w.document;
  const $ = (id) => d.getElementById(id);
  const msgs = (id) => d.querySelectorAll("#" + id + " .msg").length;
  const seeded = snapshot.counts.alerts + (snapshot.resolutions || []).length;

  // 1. snapshot seeding (swings + resolution messages)
  await waitFor(() => msgs("chatAll") === seeded, "snapshot alerts and resolutions in All chat");
  assert.equal(msgs("chatRoi"), snapshot.counts.high_roi + (snapshot.resolutions || []).length);
  const rows = d.querySelectorAll("#snapRows tr");
  assert.equal(rows.length, snapshot.alerts.length);
  assert.ok(rows[0].children.length === 11, "snapshot row has 11 cells incl. cause link and resolution");
  for (const tr of rows) {
    assert.ok(tr.querySelector('a[href^="https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers="]'), "row has official source link");
  }
  // official cause / event links come from the event settlement_sources
  const causeLinks = d.querySelectorAll("#snapRows a[href^='https://']").length;
  assert.ok(causeLinks >= snapshot.alerts.length, "every snapshot row links its official event / settlement source");
  // resolution messages are in the chats and say how the event resolved
  const allText = $("chatAll").textContent;
  assert.ok(/RESOLVED/.test(allText), "resolution message posted");
  assert.ok(/\b(yes|no)\b/.test(allText), "resolution states yes or no");
  assert.ok(/synthetic exchange-test/.test(allText), "synthetic series labelled");
  // the resolution table lists the official outcomes per topic
  const resRows = d.querySelectorAll("#resRows tr");
  assert.equal(resRows.length, (snapshot.recent_resolutions || []).length);
  for (const tr of resRows) {
    assert.ok(tr.querySelector('a[href^="https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers="]'), "resolution row has official source link");
  }

  // 2. first live poll = baseline only (no new messages)
  await waitFor(() => apiCalls.length >= 1, "first live poll");
  await waitFor(() => /LIVE/.test($("alertStatus").textContent), "live status after baseline");
  const baselineAll = msgs("chatAll");
  assert.equal(baselineAll, seeded, "baseline poll emits no swing");

  // 3. second poll: KX-A 0.20 -> 0.35 (+0.15, YES at 0.35 passes ROI);
  //    KX-B 0.50 -> 0.40 (-0.10, NO at 0.60 fails ROI); KX-C 0.10 -> 0.15 (+0.05: no alert);
  //    KX-D settles: status finalized, result yes -> RESOLVED message
  live = (tickers) => tickers.map((t) => {
    if (t === TA) return { ticker: t, title: "Live test market", last_price_dollars: "0.3500", previous_price_dollars: "0.2000", volume_fp: "5.00" };
    if (t === TB) return { ticker: t, title: "Live test market", last_price_dollars: "0.4000", previous_price_dollars: "0.5000", volume_fp: "5.00" };
    if (t === TC) return { ticker: t, title: "Live test market", last_price_dollars: "0.1500", previous_price_dollars: "0.1000", volume_fp: "5.00" };
    if (t === TD) return { ticker: t, title: "Live test market", last_price_dollars: "0.4000", previous_price_dollars: "0.4000", volume_fp: "5.00",
      status: "finalized", result: "yes", settlement_ts: "2026-11-20T20:00:00.000000Z", settlement_value_dollars: "1.0000" };
    return { ticker: t, title: "Live test market", last_price_dollars: "0.0100", previous_price_dollars: "0.0100", volume_fp: "5.00" };
  });
  w.__timer();
  await waitFor(() => msgs("chatAll") === baselineAll + 3, "two live swings + one resolution");
  // ROI chat holds: the seeded resolution, the seeded high-ROI swings, KX-A (passes) and
  // the KX-D resolution message (resolutions are posted to both chats).
  assert.equal(msgs("chatRoi"), snapshot.counts.high_roi + (snapshot.resolutions || []).length + 2,
    "only KX-A passes the placeholder ROI screen; resolutions post to both chats");
  const text = $("chatAll").textContent;
  assert.ok(/\+\$0\.1500/.test(text), "KX-A delta shown");
  assert.ok(/-\$0\.1000/.test(text), "KX-B delta shown");
  assert.ok(!text.includes(TC), "sub-threshold move not alerted");
  assert.ok(/High-ROI screen \(placeholder\): passes - would buy YES at \$0\.3500/.test($("chatRoi").textContent));
  assert.ok(/RESOLVED/.test(text) && /yes/.test(text), "settled market posted a yes resolution");
  assert.equal($("countAll").textContent, String(baselineAll + 3));

  // 4. exchange previous_price_dollars path: the first read of a market already alerts
  //    (last 0.20 with previous 0.05 = +0.15 that the browser baseline cannot see)
  const live2 = (tickers) => tickers.map((t) => {
    if (t === TA) return { ticker: t, title: "Live test market", last_price_dollars: "0.2000", previous_price_dollars: "0.0500", volume_fp: "0.00" };
    if (t === TB) return { ticker: t, title: "Live test market", last_price_dollars: "0.4000", previous_price_dollars: "0.4000", volume_fp: "5.00" };
    if (t === TC) return { ticker: t, title: "Live test market", last_price_dollars: "0.1500", previous_price_dollars: "0.1000", volume_fp: "5.00" };
    if (t === TD) return { ticker: t, title: "Live test market", last_price_dollars: "0.4000", previous_price_dollars: "0.4000", volume_fp: "5.00" };
    return { ticker: t, title: "Live test market", last_price_dollars: "0.0100", previous_price_dollars: "0.0100", volume_fp: "5.00" };
  });
  live = live2;
  const before = msgs("chatAll");
  w.__timer();
  await waitFor(() => msgs("chatAll") === before + 1, "exchange previous-price swing on first read");
  assert.ok(/\+\$0\.1500/.test($("chatAll").textContent), "exchange-path delta shown");

  // 5. topic filter hides non-matching messages
  $("topicSel").value = "golf";
  $("topicSel").dispatchEvent(new w.Event("change"));
  assert.equal(d.querySelectorAll("#chatAll .msg:not([hidden])").length, 0, "golf filter hides elections/crypto swings");
  $("topicSel").value = "all";
  $("topicSel").dispatchEvent(new w.Event("change"));
  assert.ok(d.querySelectorAll("#chatAll .msg:not([hidden])").length > 0, "all topics shows messages");

  // 6. a failing API read is reported honestly and does not emit alerts
  const beforeFail = msgs("chatAll");
  w.fetch = async () => { throw new Error("CORS blocked"); };
  w.__timer();
  await waitFor(() => /could not read the demo API/.test($("alertStatus").textContent), "failure banner");
  assert.equal(msgs("chatAll"), beforeFail);
  dom.window.close();
});
