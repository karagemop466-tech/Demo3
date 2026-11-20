import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const tradeSource = readFileSync(new URL("../assets/trade.js", import.meta.url), "utf8");
const dashboardSource = readFileSync(new URL("../assets/dashboard.js", import.meta.url), "utf8");

async function boot(savedAutomation) {
  const dom = new JSDOM(
    `<!doctype html><html><body>
      <input type="checkbox" id="autoTrade" disabled>
    </body></html>`,
    { url: "https://kalshi-demo-test.example/", runScripts: "outside-only" }
  );
  const { window } = dom;
  if (savedAutomation !== undefined) {
    window.localStorage.setItem("kd_automation_v1", JSON.stringify(savedAutomation));
  }

  const domReady = window.document.readyState === "loading"
    ? new Promise((resolve) => window.document.addEventListener("DOMContentLoaded", resolve, { once: true }))
    : Promise.resolve();

  window.eval(tradeSource);
  window.eval(dashboardSource);
  await domReady;
  return dom;
}

test("paper automation is off by default and the dashboard toggle persists changes", async () => {
  const dom = await boot();
  try {
    const { window } = dom;
    const control = window.document.getElementById("autoTrade");

    assert.equal(control.disabled, false, "dashboard startup should enable the toggle");
    assert.equal(control.checked, false, "a new browser starts with automation off");
    assert.equal(window.KalshiTrade.automationStatus().enabled, false);

    control.checked = true;
    control.dispatchEvent(new window.Event("change", { bubbles: true }));
    assert.equal(control.checked, true);
    assert.equal(window.KalshiTrade.automationStatus().enabled, true);
    assert.equal(JSON.parse(window.localStorage.getItem("kd_automation_v1")).enabled, true);

    control.checked = false;
    control.dispatchEvent(new window.Event("change", { bubbles: true }));
    assert.equal(window.KalshiTrade.automationStatus().enabled, false);
    assert.equal(JSON.parse(window.localStorage.getItem("kd_automation_v1")).enabled, false);
  } finally {
    dom.window.close();
  }
});

test("persisted enabled automation is visibly checked after dashboard reload", async () => {
  const dom = await boot({ enabled: true, rule: "momentum", maxPerDay: 20, fired: 2, day: "2026-11-20" });
  try {
    const control = dom.window.document.getElementById("autoTrade");
    assert.equal(control.disabled, false);
    assert.equal(control.checked, true, "a saved active strategy must not look disabled after reload");
    assert.equal(dom.window.KalshiTrade.automationStatus().enabled, true);
  } finally {
    dom.window.close();
  }
});
