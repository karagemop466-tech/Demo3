import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const alertsScript = readFileSync(new URL("../assets/alerts.js", import.meta.url), "utf8");

function bootAlerts() {
  const dom = new JSDOM(`<!doctype html><body>
    <button id="tabAll" data-chat="all" class="active" aria-pressed="true">All events</button>
    <button id="tabROI" data-chat="roi" aria-pressed="false">High ROI model</button>
    <input id="alertsEnabled" type="checkbox" checked>
    <button id="clearAlertsBtn">Clear</button><span id="alertCount"></span>
    <div id="chatAll"><div id="alertsAll"></div></div>
    <div id="chatROI" style="display:none"><div id="alertsROI"></div></div>
  </body>`, {
    url: "https://demo.example.test/Demo3/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  dom.window.setInterval = () => 1;
  dom.window.clearInterval = () => {};
  dom.window.eval(alertsScript);
  return dom;
}

const sampleMarket = { ticker: "KXTEST-26", series_ticker: "KXTEST", title: "Test event",
  topic: "crypto", last: 0.4 };

test("first quote is a baseline; inclusive ten-cent moves alert in both directions", () => {
  const dom = bootAlerts();
  try {
    const market = { ...sampleMarket };
    const { KD } = dom.window;
    KD.onMarkets([market]);
    KD.onSample(market, { price: 0.4, t: 100 });
    assert.equal(KD.allRows().length, 0, "the initial quote should not be an alert");

    KD.onSample(market, { price: 0.5, t: 110 });
    assert.equal(KD.allRows().length, 1, "a +$0.10 change must qualify, despite float representation");
    assert.ok(KD.allRows()[0].change >= 0.1 - Number.EPSILON);

    KD.onSample(market, { price: 0.4, t: 120 });
    assert.equal(KD.allRows().length, 2, "a -$0.10 change must qualify");
    assert.ok(KD.allRows()[0].change <= -0.1 + Number.EPSILON);
  } finally {
    dom.window.close();
  }
});

test("high-ROI tab is an explicitly labeled heuristic and alert rows link to official market data", () => {
  const dom = bootAlerts();
  try {
    const market = { ...sampleMarket };
    const { KD, document } = dom.window;
    KD.onMarkets([market]);
    KD.onSample(market, { price: 0.5, t: 100 });
    assert.equal(KD.allRows().length, 1);
    assert.equal(KD.roiRows().length, 1);
    const source = document.querySelector("#alertsAll a");
    assert.equal(source.href,
      "https://external-api.demo.kalshi.co/trade-api/v2/series/KXTEST/markets/KXTEST-26");
    assert.match(document.querySelector("#alertsROI").textContent, /high-ROI signal \(heuristic\)/);
    document.querySelector("#tabROI").click();
    assert.equal(document.querySelector("#chatROI").style.display, "");
    assert.equal(document.querySelector("#chatAll").style.display, "none");
    assert.match(document.querySelector("#alertCount").textContent, /1 alert/);
  } finally {
    dom.window.close();
  }
});

test("alert renderer escapes market text and clear removes persisted alerts", () => {
  const dom = bootAlerts();
  try {
    const market = { ...sampleMarket, title: "<script>unsafe</script>" };
    const { KD, document, localStorage } = dom.window;
    KD.onMarkets([market]);
    KD.onSample(market, { price: 0.5, t: 100 });
    assert.equal(document.querySelector("#alertsAll script"), null);
    assert.match(document.querySelector("#alertsAll").textContent, /<script>unsafe/);
    assert.ok(localStorage.getItem("kd_alerts_v1"));
    document.querySelector("#clearAlertsBtn").click();
    assert.equal(KD.allRows().length, 0);
    assert.equal(localStorage.getItem("kd_alerts_v1"), null);
  } finally {
    dom.window.close();
  }
});
