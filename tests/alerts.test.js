import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f) => readFileSync(path.join(repo, f), "utf8");

/* Load the real root engines (app.js -> KalshiDemo, alerts.js -> KD,
 * trade.js -> KalshiTrade) into a jsdom window and exercise the pure logic.
 * The alert engine fetches the event record (GET /events/{event_ticker}) for
 * official settlement-source context, so fetch is mocked. */
function boot(fetchMock) {
  const html = `<!doctype html><html><body>
    <div id="alertsAll"></div><div id="alertsROI"></div>
    <div id="chatAll"></div><div id="chatROI"></div>
    <button id="tabAll" data-chat="all"></button>
    <button id="tabROI" data-chat="roi"></button>
    <input id="alertsEnabled" type="checkbox" checked>
    <button id="clearAlertsBtn"></button><span id="alertCount"></span>
  </body></html>`;
  const dom = new JSDOM(html, {
    url: "https://demo.example.test/Demo3/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const w = dom.window;
  w.setInterval = () => ({ mocked: true });
  w.clearInterval = () => {};
  w.fetch = fetchMock || (async () => { throw new Error("no fetch mock"); });
  w.eval(read("assets/app.js"));
  w.eval(read("assets/alerts.js"));
  w.eval(read("assets/trade.js"));
  return { dom, w };
}

const NOW = Math.floor(Date.now() / 1000);
function market(over) {
  return Object.assign({
    ticker: "MKT1", title: "Test market", topic: "golf",
    series_ticker: "SER1", event_ticker: "EV1", rules_primary: "If X then YES.",
    oi: 1000000, last: 0.5,
  }, over || {});
}

function eventFetchMock() {
  return async (url) => {
    const u = new URL(url);
    if (u.pathname.endsWith("/events/EV1")) {
      return {
        ok: true, status: 200,
        json: async () => ({
          event: {
            title: "Test event",
            settlement_sources: [
              { name: "ESPN", url: "https://www.espn.com/" },
              { name: "Bad", url: "javascript:alert(1)" },
            ],
          },
        }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
}

test("alert engine flags a >= $0.10 swing (float-safe) and records event + rules", async () => {
  const { dom, w } = boot(eventFetchMock());
  try {
    const m = market();
    w.KD.onSample(m, { t: NOW, price: 0.5 });
    w.KD.onSample(m, { t: NOW + 5, price: 0.65 }); // +$0.15 swing
    // An exact $0.10 move (0.60 - 0.50) must fire despite float rounding.
    w.KD.onSample(market({ ticker: "M2", oi: 0 }), { t: NOW, price: 0.5 });
    w.KD.onSample(market({ ticker: "M2", oi: 0 }), { t: NOW + 5, price: 0.60 });
    const all = w.KD.allRows();
    assert.equal(all.length, 2);
    assert.equal(all[0].ticker, "M2");          // newest first
    assert.equal(all[0].dir, "up");
    assert.equal(all[1].ticker, "MKT1");
    assert.equal(all[1].event, "EV1");
    assert.equal(all[1].rules, "If X then YES.");
    // Event context is fetched async and only https sources are kept.
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(w.KD.events["EV1"].status, "ok");
    assert.deepEqual(w.KD.events["EV1"].sources, [{ name: "ESPN", url: "https://www.espn.com/" }]);
    // Rendered chat shows the event API link and the official source, not javascript:.
    w.KD.renderAlerts();
    const html = w.document.getElementById("alertsAll").innerHTML;
    assert.match(html, /event API/);
    assert.match(html, /ESPN/);
    assert.doesNotMatch(html, /javascript:/);
  } finally { dom.window.close(); }
});

test("ROI model is a documented, bounded score and only signals strong moves", async () => {
  const { dom, w } = boot(eventFetchMock());
  try {
    const m = market({ ticker: "M1", oi: 1000000 });
    w.KD.onSample(m, { t: NOW, price: 0.5 });
    w.KD.onSample(m, { t: NOW + 5, price: 0.65 }); // 15¢ swing on 0.50 + 1M OI
    const a = w.KD.allRows()[0];
    assert.equal(a.roiSignal, true);
    assert.ok(a.roi.score >= 0 && a.roi.score <= 1);
    // swing 15¢ -> swingNorm 0.3; pct 30% -> pctNorm 0.6; liq 1M -> 1.0
    assert.ok(Math.abs(a.roi.score - (0.4 * 0.3 + 0.3 * 0.6 + 0.3 * 1)) < 1e-9);
    // A swing that fires but is small/thin must not signal.
    const m2 = market({ ticker: "M2", oi: 0 });
    w.KD.onSample(m2, { t: NOW, price: 0.5 });
    w.KD.onSample(m2, { t: NOW + 5, price: 0.60 }); // exactly +$0.10, zero OI
    assert.equal(w.KD.allRows()[0].ticker, "M2");
    assert.equal(w.KD.allRows()[0].roiSignal, false);
    assert.equal(w.KD.roiRows().length, 1);
    // Let the async event fetch settle before the window closes.
    await new Promise((r) => setTimeout(r, 0));
  } finally { dom.window.close(); }
});

test("automated paper trades follow the selected strategy and categorize by strategy", () => {
  const { dom, w } = boot(eventFetchMock());
  try {
    w.KalshiTrade.setAutomation(true);
    const alert = { ticker: "MKT1", dir: "up", change: 0.15, newPrice: 0.65 };
    w.KalshiTrade.setStrategy("momentum");
    w.KalshiTrade.onSwingAlert(alert);
    w.KalshiTrade.setStrategy("mean_reversion");
    w.KalshiTrade.onSwingAlert(alert);
    const fills = w.KalshiTrade.fills.filter((f) => f.automated);
    assert.equal(fills.length, 2);
    assert.equal(fills[0].action, "buy");       // momentum trades with the move
    assert.equal(fills[0].strategy, "momentum");
    assert.equal(fills[1].action, "sell");      // mean reversion fades the move
    assert.equal(fills[1].strategy, "mean_reversion");
    // Breakout ignores small swings.
    w.KalshiTrade.setStrategy("breakout");
    w.KalshiTrade.onSwingAlert({ ticker: "MKT1", dir: "up", change: 0.12, newPrice: 0.62 });
    assert.equal(w.KalshiTrade.fills.filter((f) => f.automated).length, 2);
    const cats = w.KalshiTrade.categories();
    assert.ok(cats.some((c) => /momentum/.test(c.key)));
    assert.ok(cats.some((c) => /mean_reversion/.test(c.key)));
  } finally { dom.window.close(); }
});
