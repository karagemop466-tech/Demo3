// Session 5125afd8 — swing-alert engine tests (assets/alerts.js).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const alertsJS = readFileSync(path.join(repo, "assets", "alerts.js"), "utf8");
const dashboardHTML = readFileSync(path.join(repo, "dashboard.html"), "utf8");

function loadAlerts(html = "<html><body></body></html>") {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  w.KalshiDemo = {
    esc: (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    srcLink: (p, label) => `<a class='src' href='https://external-api.demo.kalshi.co/trade-api/v2${p}'>${label}</a>`,
  };
  w.eval(alertsJS);
  return { w, A: w.KalshiAlerts, dom };
}

// Wait for DOMContentLoaded so alerts.js has attached its pause-button listener (as in a browser).
async function ready(dom) {
  if (dom.window.document.readyState !== "loading") return;
  await new Promise((resolve) => dom.window.document.addEventListener("DOMContentLoaded", resolve));
}

const mk = (ticker, last, extra = {}) => ({
  ticker, title: `T ${ticker}`, topic: "crypto", event_ticker: "E-" + ticker,
  series_ticker: "S", last, yb: last - 0.01, ya: last + 0.01, vol: 100, oi: 50, ...extra,
});

test("ROI-if-right is gross payout arithmetic on the $1 settlement rule", () => {
  const { A } = loadAlerts();
  const r = A.core.roiIfRight(0.25);
  assert.equal(Number(r.yes.toFixed(6)), 3);             // (1-0.25)/0.25
  assert.equal(Number(r.no.toFixed(6)), Number((1 / 3).toFixed(6))); // 0.25/0.75
  assert.equal(A.core.roiIfRight(0), null);
  assert.equal(A.core.roiIfRight(1), null);
});

test("first observation only sets anchors; no alert", () => {
  const { A } = loadAlerts();
  const r = A.core.evaluate({}, [mk("A", 0.5)], 0.10, 1);
  assert.equal(r.alerts.length, 0);
  assert.equal(r.anchors.A, 0.5);
});

test("moves of exactly $0.10 alert in both directions; $0.09 does not", () => {
  const { A } = loadAlerts();
  const up = A.core.evaluate({ A: 0.5 }, [mk("A", 0.6)], 0.10, 2);
  assert.equal(up.alerts.length, 1);
  assert.equal(up.alerts[0].direction, "up");
  assert.equal(up.alerts[0].delta, 0.1);
  const down = A.core.evaluate({ A: 0.5 }, [mk("A", 0.4)], 0.10, 2);
  assert.equal(down.alerts[0].direction, "down");
  assert.equal(down.alerts[0].delta, -0.1);
  const small = A.core.evaluate({ A: 0.5 }, [mk("A", 0.59)], 0.10, 2);
  assert.equal(small.alerts.length, 0);
  assert.equal(small.anchors.A, 0.5, "anchor unchanged when no alert fires");
});

test("slow drift that adds up to $0.10 alerts once; anchor resets on alert", () => {
  const { A } = loadAlerts();
  let anchors = { A: 0.5 };
  const seen = [];
  for (const p of [0.53, 0.56, 0.59, 0.62]) {
    const r = A.core.evaluate(anchors, [mk("A", p)], 0.10, 3);
    seen.push(r.alerts.length);
    anchors = r.anchors;
  }
  assert.deepEqual(seen, [0, 0, 0, 1]);
  assert.equal(anchors.A, 0.62);
  const after = A.core.evaluate(anchors, [mk("A", 0.66)], 0.10, 4);
  assert.equal(after.alerts.length, 0, "a $0.04 move after re-anchoring does not alert");
});

test("markets that leave the scan are pruned; null prices are ignored", () => {
  const { A } = loadAlerts();
  const r = A.core.evaluate({ A: 0.5, GONE: 0.3 }, [mk("A", 0.5), mk("B", null)], 0.10, 5);
  assert.equal(Object.prototype.hasOwnProperty.call(r.anchors, "GONE"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(r.anchors, "B"), false);
});

test("placeholder high-ROI rule: price band, volume and open interest are required", () => {
  const { A } = loadAlerts();
  const rule = A.config.roiRule;
  const base = { delta: 0.12, to: 0.5, vol: 10, oi: 5 };
  assert.equal(A.core.passesRoi(base, rule), true);
  assert.equal(A.core.passesRoi({ ...base, to: 0.97 }, rule), false);
  assert.equal(A.core.passesRoi({ ...base, vol: 0 }, rule), false);
  assert.equal(A.core.passesRoi({ ...base, oi: 0 }, rule), false);
  assert.equal(A.core.passesRoi({ ...base, delta: -0.12 }, rule), true);
});

test("feeds render newest-first in the dashboard DOM; pause holds new alerts", async () => {
  const { w, A, dom } = loadAlerts(dashboardHTML);
  await ready(dom);
  const d = w.document;
  const allEl = d.getElementById("alertFeedAll");
  const roiEl = d.getElementById("alertFeedRoi");
  assert.ok(allEl && roiEl, "dashboard.html must contain both feed containers");
  A.onScan([mk("A", 0.5), mk("B", 0.2, { vol: 0 })]); // primes anchors
  A.onScan([mk("A", 0.62), mk("B", 0.32, { vol: 0 })]); // A: +0.12 (ROI-eligible); B: +0.12 (no volume)
  assert.equal(allEl.querySelectorAll("li.alert").length, 2);
  assert.equal(roiEl.querySelectorAll("li.alert").length, 1);
  assert.match(allEl.textContent, /Cause: not reported by the API/);
  const btn = d.getElementById("alertPauseBtn");
  btn.click();
  A.onScan([mk("A", 0.40)]);
  assert.equal(allEl.querySelectorAll("li.alert").length, 2, "paused feed does not change");
  assert.match(d.getElementById("alertPending").textContent, /held while paused/);
  btn.click();
  assert.equal(allEl.querySelectorAll("li.alert").length, 3, "resume flushes held alerts");
});
