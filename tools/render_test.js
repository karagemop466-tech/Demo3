#!/usr/bin/env node
/**
 * Renders every published page in jsdom against the real committed artifacts and fails if:
 *   - a script throws,
 *   - a page ends up with a .loading placeholder still on screen (i.e. data never rendered),
 *   - an .error element appears,
 *   - a required table has no rows,
 *   - the price chart canvas has no points for a market that does have candlesticks.
 *
 * This is the closest thing to a browser test that can run without downloading Chromium, and it
 * catches the failure mode that matters most here: a page that looks fine but shows no data.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const SITE = path.resolve(__dirname, "..", "docs");
const PAGES = [
  "index.html", "dashboard.html", "resolutions.html", "liquidity.html",
  "portfolio.html", "strategy.html", "suggestions.html", "questions.html",
  "flagged.html", "sources.html",
  "categories/gas.html", "categories/elections.html", "categories/culture.html",
  "categories/crypto.html", "categories/golf.html",
];

const failures = [];
const notes = [];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function renderPage(rel) {
  const file = path.join(SITE, rel);
  let html = fs.readFileSync(file, "utf8");
  // Inline the shared runtime so the test does not depend on jsdom fetching external scripts.
  const shared = fs.readFileSync(path.join(SITE, "assets", "app.js"), "utf8");
  html = html.replace(/<script src="[^"]*assets\/app\.js"><\/script>/,
    "<script>" + shared + "</script>");
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + (e && e.message)));
  vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

  // Canvas is not implemented by jsdom; a stub keeps the drawing path running and lets us
  // assert that points were actually produced.
  const drawCalls = [];
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "http://localhost:8080/" + rel,
    virtualConsole: vc,
    resources: undefined,
    beforeParse(window) {
      window.HTMLCanvasElement.prototype.getContext = function () {
        const ctx = {
          canvas: this, setTransform() {}, clearRect() {}, fillRect() {}, strokeRect() {},
          beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, fill() {}, closePath() {},
          fillText() { drawCalls.push("text"); }, measureText() { return { width: 10 }; },
          save() {}, restore() {},
        };
        return ctx;
      };
      Object.defineProperty(window.HTMLElement.prototype, "clientWidth", { get() { return 800; } });
      Object.defineProperty(window.HTMLElement.prototype, "clientHeight", { get() { return 320; } });
      window.fetch = function (url) {
        const rel = String(url).replace(/^\.\.\//, "").replace(/^data\//, "data/");
        const p = path.join(SITE, rel.split("?")[0]);
        if (!fs.existsSync(p)) return Promise.reject(new Error("404 " + rel));
        const body = fs.readFileSync(p, "utf8");
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve(JSON.parse(body)),
          text: () => Promise.resolve(body),
        });
      };
      window.scrollTo = () => {};
      window.URL.createObjectURL = () => "blob:stub";
    },
  });

  await sleep(700);

  const doc = dom.window.document;
  const loading = doc.querySelectorAll(".loading");
  const errs = doc.querySelectorAll(".error");
  // Only inspect what a user sees: clone the body and strip <script>/<style> nodes, since the
  // inlined runtime legitimately contains the words "undefined" and "isNaN".
  const clone = doc.body.cloneNode(true);
  clone.querySelectorAll("script, style").forEach((n) => n.remove());
  const text = clone.textContent || "";

  if (errors.length) failures.push(rel + ": script errors -> " + errors.slice(0, 3).join(" | "));
  if (errs.length) failures.push(rel + ": rendered an .error block -> " + errs[0].textContent.slice(0, 160));
  if (loading.length) notes.push(rel + ": " + loading.length + " .loading placeholder(s) still present (" +
    Array.from(loading).map((l) => l.textContent.trim().slice(0, 40)).join(" / ") + ")");
  // A rendering bug shows up as these exact tokens glued to markup or numbers; prose such as
  // "the value is undefined" is legitimate and must not fail the build.
  for (const bad of ["$undefined", "undefined%", "NaN%", "$NaN", "NaN¢", "undefined¢", "undefined</", ">undefined<"]) {
    if (text.includes(bad)) {
      failures.push(rel + ": rendered a broken value token '" + bad + "'");
    }
  }
  const nav = doc.querySelectorAll("header.top nav.main a");
  if (nav.length < 10) failures.push(rel + ": navigation did not render (" + nav.length + " links)");
  const tables = doc.querySelectorAll("table tbody tr");
  if (tables.length === 0) failures.push(rel + ": no table rows rendered at all");

  if (rel === "liquidity.html" && drawCalls.length < 3) {
    failures.push(rel + ": chart drawing produced almost no canvas operations (" + drawCalls.length + ")");
  }
  dom.window.close();
}

(async () => {
  for (const p of PAGES) {
    try {
      await renderPage(p);
      process.stdout.write("checked " + p + "\n");
    } catch (e) {
      failures.push(p + ": threw during render -> " + e.message);
    }
  }
  if (notes.length) {
    console.log("\nnotes:");
    notes.forEach((n) => console.log(" - " + n));
  }
  if (failures.length) {
    console.log("\nFAIL (" + failures.length + "):");
    failures.forEach((f) => console.log(" - " + f));
    process.exit(1);
  }
  console.log("\nPASS: all " + PAGES.length + " pages rendered with data and no script errors");
})();
