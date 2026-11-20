/* Headless smoke test for the Live Alert Desk pages (jsdom, no network).
 * Loads each page, injects its scripts, blocks remote fetch (so the pages must
 * fall back to the committed snapshots) and asserts the key panels render from
 * live/data. Run: node live/tests/smoke.mjs
 */
import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "live");
const pages = ["index.html", "dashboard.html", "graph.html", "gas.html", "elections.html",
  "culture.html", "crypto.html", "golf.html", "tracking.html", "strategies.html",
  "portfolio.html", "suggestions.html", "methodology.html", "flagged.html", "sources.html"];

let fails = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { fails++; console.log("  FAIL", msg); } }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

for (const page of pages) {
  const html = fs.readFileSync(path.join(ROOT, page), "utf8");
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.message || e)));
  const dom = new JSDOM(html, {
    url: "https://karagemop466-tech.github.io/Demo3/live/" + page,
    runScripts: "dangerously", virtualConsole: vc, pretendToBeVisual: true,
    beforeParse(win) {
      // serve repo-root-relative paths for pages that reach outside live/
      const REPO = path.resolve(ROOT, "..");
      win.fetch = async (url) => {
        const clean = String(url).split("?")[0];
        if (/^https?:/.test(clean)) throw new Error("offline in test");
        const p = path.join(REPO, "live", clean);
        if (!fs.existsSync(p)) return { ok: false, status: 404, json: async () => ({}) };
        const body = fs.readFileSync(p, "utf8");
        return { ok: true, status: 200, json: async () => JSON.parse(body), text: async () => body };
      };
      win.HTMLCanvasElement.prototype.getContext = function () {
        return new Proxy({}, { get: () => (() => ({ addColorStop() {} })) });
      };
      win.requestAnimationFrame = (fn) => setTimeout(fn, 0);
      win.addEventListener("unhandledrejection", (e) => errors.push("unhandled: " + (e.reason && e.reason.message)));
    }
  });
  const doc = dom.window.document;
  const scripts = [...doc.querySelectorAll("script[src]")].map((s) => s.getAttribute("src"));
  for (const src of scripts) {
    const code = fs.readFileSync(path.join(ROOT, src), "utf8");
    try { dom.window.eval(code); } catch (e) { ok(false, `${page}: script ${src} threw ${e.message}`); }
  }
  doc.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  await sleep(400);
  ok(errors.length === 0, `${page}: jsdom errors: ${errors.join(" | ")}`);
  if (page === "index.html") {
    ok(doc.getElementById("statGrid").children.length >= 5, "index: stat cards rendered");
    ok(doc.getElementById("liveStatus").textContent !== "checking the demo API…",
       "index: live status resolved to snapshot fallback");
  }
  if (page === "dashboard.html") {
    const msgs = doc.querySelectorAll("#chatAllbody .msg").length;
    const roi = doc.querySelectorAll("#chatRoibody .msg").length;
    ok(msgs > 20, `dashboard: all-alerts stream populated (${msgs})`);
    ok(roi > 0, `dashboard: high-ROI stream populated (${roi})`);
    ok(doc.querySelectorAll("#topicTables section").length === 5, "dashboard: five topic sections");
    ok(/YES|NO/.test(doc.getElementById("resolutionBody").textContent), "dashboard: resolutions rendered");
    ok(doc.getElementById("obTicker").options.length > 3, "dashboard: ticker dropdown filled");
  }
  if (page === "graph.html") {
    ok(doc.getElementById("windowSeg").children.length === 9, "graph: nine time windows");
  }
  if (page === "portfolio.html") {
    const ready = doc.querySelectorAll("canvas[data-ready]").length;
    ok(ready >= 3, `portfolio: ${ready} equity curves drawn`);
  }
  dom.window.close();
}
console.log(`\n${checks} checks, ${fails} failures`);
process.exit(fails ? 1 : 0);
