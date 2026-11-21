/* Real-browser end-to-end check of the published site (session 3528551d, task K3).
 *
 * Why this exists: every earlier check of these pages was either jsdom with a mocked
 * API or a fetch of the HTML with no JavaScript executed. Neither can show whether a
 * real browser, on the real GitHub Pages origin, actually gets live data from the
 * Kalshi demo API (CORS, rate limits, response shapes, rendering).
 *
 * What it does: starts headless Chromium (Playwright), opens every HTML page of the
 * site, lets the page's own scripts talk to the live demo API, and records only what
 * the browser observed: console errors, uncaught exceptions, failed / blocked
 * requests, HTTP statuses of the demo-API calls, how many table rows and painted
 * charts exist after the page settled, and same-origin links that do not resolve.
 * Nothing is asserted that the browser did not observe; an empty table is reported as
 * empty, never explained away.
 *
 * Modes (E2E_MODE):
 *   local     the checked-out tree is served to the browser *as*
 *             https://karagemop466-tech.github.io/Demo3/ (request interception), so the
 *             branch is tested before merge with the genuine Origin header that the
 *             demo API sees from the deployed site.
 *   deployed  nothing is intercepted: the browser loads what GitHub Pages serves now.
 *
 * Official endpoints only: https://external-api.demo.kalshi.co/trade-api/v2 and
 * https://demo-api.kalshi.co/trade-api/v2
 * (https://docs.kalshi.com/getting_started/demo_env).
 *
 * Run (needs network egress to the demo API — GitHub Actions has it, the build
 * sandbox does not):  cd e2e && npm ci && npx playwright install chromium && node run.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { FLOWS } from "./flows.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");
const SITE_ORIGIN = "https://karagemop466-tech.github.io";
const SITE_PREFIX = "/Demo3/";
const SITE_BASE = SITE_ORIGIN + SITE_PREFIX;

const MODE = (process.env.E2E_MODE || "local").trim();
const OUT = path.resolve(process.env.E2E_OUT || path.join(HERE, "report", MODE));
const SHOT_DIR = path.join(OUT, "shots");
const CONCURRENCY = Math.max(1, Number(process.env.E2E_CONCURRENCY || 3));
const STATIC_SETTLE_MS = Number(process.env.E2E_STATIC_MS || 6000);
const LIVE_SETTLE_MS = Number(process.env.E2E_LIVE_MS || 25000);
/* One live page at a time by default: a page is one visitor. Opening several polling pages
 * at once from one runner IP would add rate-limit pressure that a real visitor never causes
 * and would make any HTTP 429 in the report the harness's fault rather than the site's. */
const LIVE_CONCURRENCY = Math.max(1, Number(process.env.E2E_LIVE_CONCURRENCY || 1));
const PAGE_FILTER = (process.env.E2E_PAGES || "all").trim();
const SHOT_FILTER = (process.env.E2E_SHOTS || "key").trim();

const KALSHI_HOSTS = new Set([
  "external-api.demo.kalshi.co", "demo-api.kalshi.co",
  "external-api-ws.demo.kalshi.co",
  // production hosts are listed so that a page still calling production is *reported*
  "api.elections.kalshi.com", "external-api.kalshi.com", "api.kalshi.com",
  "trading-api.kalshi.com",
]);
const DEMO_HOSTS = new Set(["external-api.demo.kalshi.co", "demo-api.kalshi.co",
  "external-api-ws.demo.kalshi.co"]);

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".jsonl": "application/octet-stream",
  ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".ico": "image/x-icon", ".csv": "text/csv; charset=utf-8",
  ".py": "text/plain; charset=utf-8", ".yml": "text/plain; charset=utf-8",
};

/* Pages whose scripts poll the live API need a longer settle time than static tables. */
const LIVE_PAGES = new Set([
  "index.html", "dashboard.html", "alerts.html", "portfolio.html", "trades.html",
  "gas-prices.html", "elections.html", "culture.html", "crypto.html", "golf.html",
  "live/index.html", "live/dashboard.html", "live/graph.html", "live/tracking.html",
  "live/gas.html", "live/elections.html", "live/culture.html", "live/crypto.html",
  "live/golf.html", "live/portfolio.html", "live/strategies.html",
  "catalysts/index.html", "demo-desk/index.html", "demo-desk/pages/events.html",
  "demo-desk/pages/gas-prices.html", "demo-desk/pages/elections.html",
  "demo-desk/pages/culture.html", "demo-desk/pages/crypto.html",
  "demo-desk/pages/golf.html", "demo-desk/pages/resolution.html",
  "docs/index.html", "docs/dashboard.html", "docs/resolved.html",
  "docs/categories/gas.html", "docs/categories/elections.html",
  "docs/categories/culture.html", "docs/categories/crypto.html",
  "docs/categories/golf.html", "docs/tracker/dashboard.html",
  "docs/tracker/index.html", "analysis/index.html",
  "analysis/pages/price-history.html", "analysis/pages/liquidity.html",
]);
/* Screenshots are committed, so only the pages a trader actually works in get one. */
const KEY_SHOTS = new Set([
  "index.html", "dashboard.html", "alerts.html", "data-tracking.html", "trades.html",
  "golf.html", "live/index.html", "catalysts/index.html", "paper-desk/index.html",
  "flagged.html",
]);

function listPages() {
  const out = [];
  const skipDirs = new Set([".git", "node_modules", ".github", "e2e"]);
  (function walk(dir) {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      if (ent.isDirectory()) {
        if (!skipDirs.has(ent.name)) walk(path.join(dir, ent.name));
      } else if (ent.name.endsWith(".html")) {
        out.push(path.relative(REPO, path.join(dir, ent.name)).split(path.sep).join("/"));
      }
    }
  })(REPO);
  // page fragments that are fetched by another page are not pages of their own
  return out.filter((p) => p !== "alerts/page-body.html").sort();
}

function wanted(all) {
  if (PAGE_FILTER === "all") return all;
  if (PAGE_FILTER === "key") return all.filter((p) => KEY_SHOTS.has(p));
  if (PAGE_FILTER === "live") return all.filter((p) => LIVE_PAGES.has(p));
  const set = new Set(PAGE_FILTER.split(",").map((s) => s.trim()).filter(Boolean));
  return all.filter((p) => set.has(p));
}
function wantsShot(p) {
  if (SHOT_FILTER === "none") return false;
  if (SHOT_FILTER === "all") return true;
  if (SHOT_FILTER === "key") return KEY_SHOTS.has(p);
  return new Set(SHOT_FILTER.split(",").map((s) => s.trim())).has(p);
}

/* ---- local mode: serve the working tree as the real Pages origin ---- */
function localFileFor(urlStr) {
  const u = new URL(urlStr);
  if (!u.pathname.startsWith(SITE_PREFIX)) return { status: 404 };
  let rel = decodeURIComponent(u.pathname.slice(SITE_PREFIX.length));
  if (rel.includes("..")) return { status: 404 };
  let file = path.join(REPO, rel);
  if (rel === "" || rel.endsWith("/")) file = path.join(file, "index.html");
  else if (fs.existsSync(file) && fs.statSync(file).isDirectory()) {
    return { status: 301, location: u.origin + u.pathname + "/" + u.search };
  }
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return { status: 404 };
  // .git / .github / node_modules are not part of the published site
  const first = rel.split("/")[0];
  if (first === ".git" || first === ".github" || first === "node_modules") return { status: 404 };
  return { status: 200, file };
}
async function installLocalRoutes(context, missing) {
  await context.route(SITE_ORIGIN + "/**", async (route) => {
    const req = route.request();
    const r = localFileFor(req.url());
    if (r.status === 301) {
      return route.fulfill({ status: 301, headers: { location: r.location }, body: "" });
    }
    if (r.status !== 200) {
      missing.add(req.url());
      return route.fulfill({ status: 404, contentType: "text/html", body: "<h1>404</h1>" });
    }
    const ext = path.extname(r.file).toLowerCase();
    return route.fulfill({
      status: 200,
      contentType: MIME[ext] || "application/octet-stream",
      body: fs.readFileSync(r.file),
    });
  });
}

/* ---- in-page DOM survey (runs inside the browser) ---- */
function surveyDom() {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const tables = [...document.querySelectorAll("table")];
  let bodyRows = 0, rowsNoLink = 0, emptyTables = 0, placeholderRows = 0;
  const tableInfo = [];
  for (const t of tables) {
    const rows = [...t.querySelectorAll("tbody tr")];
    const real = rows.filter((tr) => tr.querySelectorAll("td").length > 1 ||
      !tr.querySelector("td[colspan]"));
    const ph = rows.length - real.length;
    placeholderRows += ph;
    bodyRows += real.length;
    if (!real.length) emptyTables++;
    const noLink = real.filter((tr) => !tr.querySelector("a[href]")).length;
    rowsNoLink += noLink;
    const section = t.closest("section, .card, article, main, div[id]");
    const heading = section && section.querySelector("h1, h2, h3, h4");
    tableInfo.push({
      id: t.id || (t.parentElement && t.parentElement.id) || "",
      under: heading ? heading.textContent.trim().slice(0, 70) : "",
      rows: real.length, placeholder_rows: ph, rows_without_link: noLink,
      visible: vis(t),
      placeholder_text: ph ? rows.find((tr) => !real.includes(tr)).textContent.trim().slice(0, 140) : "",
    });
  }
  const canvases = [...document.querySelectorAll("canvas")].map((c) => {
    let painted = null, distinct = null;
    try {
      const ctx = c.getContext("2d");
      if (ctx && c.width && c.height) {
        const d = ctx.getImageData(0, 0, c.width, c.height).data;
        let n = 0; const seen = new Set();
        const step = Math.max(4, Math.floor(d.length / 4 / 60000) * 4);
        for (let i = 0; i < d.length; i += step) {
          if (d[i + 3] !== 0) { n++; if (seen.size < 64) seen.add((d[i] << 16) | (d[i + 1] << 8) | d[i + 2]); }
        }
        painted = n; distinct = seen.size;
      }
    } catch (e) { painted = null; }
    return { id: c.id || "", w: c.width, h: c.height, visible: vis(c),
      sampled_painted_pixels: painted, distinct_colors: distinct };
  });
  const svgs = [...document.querySelectorAll("svg")].map((s) => ({
    id: s.id || "", visible: vis(s),
    marks: s.querySelectorAll("path, polyline, line, rect, circle").length,
  })).filter((s) => s.marks > 0);
  // elements that still show a transient "busy" word once the page has settled
  const busy = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const txt = node.nodeValue.trim();
    if (!txt || txt.length > 90) continue;
    if (/^(loading|checking|fetching|discovering|connecting|waiting|scanning|polling)\b.*(…|\.\.\.)?$/i.test(txt) ||
        /(…|\.\.\.)$/.test(txt) && /^(loading|checking|fetching|discovering|connecting|waiting)/i.test(txt)) {
      const el = node.parentElement;
      if (el && vis(el) && !el.closest("script,style,select,option,button")) {
        busy.push({ text: txt.slice(0, 90), id: el.id || (el.parentElement && el.parentElement.id) || "" });
      }
    }
  }
  const alerts = [...document.querySelectorAll(
    ".error, .banner, [role=alert], .warn-banner, #banner, .notice.err, .err")]
    .filter((el) => vis(el) && el.textContent.trim().length > 0)
    .map((el) => ({ id: el.id || "", cls: el.className && String(el.className).slice(0, 40),
      text: el.textContent.trim().replace(/\s+/g, " ").slice(0, 300) }))
    .slice(0, 8);
  const links = [...document.querySelectorAll("a[href]")].map((a) => a.href);
  const nav = document.querySelector("nav");
  return {
    title: document.title,
    h1: (document.querySelector("h1") || {}).textContent || "",
    tables: tables.length, body_rows: bodyRows, rows_without_link: rowsNoLink,
    empty_tables: emptyTables, placeholder_rows: placeholderRows,
    table_info: tableInfo.slice(0, 40),
    canvases, svg_charts: svgs.slice(0, 12),
    busy_text: busy.slice(0, 12), visible_alerts: alerts,
    nav_links: nav ? nav.querySelectorAll("a[href]").length : 0,
    links,
    text_length: document.body.innerText.length,
    doc_height: document.documentElement.scrollHeight,
  };
}

function slug(p) { return p.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_|_$/g, ""); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function checkPage(browser, rel, missingLocal) {
  const started = Date.now();
  const rec = {
    page: rel, url: SITE_BASE + rel, mode: MODE, live_page: LIVE_PAGES.has(rel),
    document_status: null, console_errors: [], console_warnings: 0, page_errors: [],
    request_failed: [], bad_responses: [],
    api: { demo_requests: 0, by_status: {}, by_host: {}, production_requests: 0,
      sample_urls: [], cors_blocked: 0, rate_limited_429: 0 },
    other_hosts: {}, websockets: [], timeline: [], flow: null, dom: null,
    screenshot: null, error: null,
  };
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1,
    locale: "en-US", timezoneId: "UTC",
  });
  if (MODE === "local") await installLocalRoutes(context, missingLocal);
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") {
      if (rec.console_errors.length < 25) {
        rec.console_errors.push({ text: m.text().slice(0, 400), at: (m.location().url || "").replace(SITE_BASE, "") });
      }
    } else if (m.type() === "warning") rec.console_warnings++;
  });
  page.on("pageerror", (e) => {
    if (rec.page_errors.length < 25) rec.page_errors.push(String(e && e.message || e).slice(0, 400));
  });
  page.on("requestfailed", (r) => {
    const u = r.url();
    let host = ""; try { host = new URL(u).host; } catch (e) { /* data: urls */ }
    const failure = (r.failure() || {}).errorText || "";
    if (KALSHI_HOSTS.has(host) && /ERR_FAILED|CORS|ERR_BLOCKED/i.test(failure)) rec.api.cors_blocked++;
    if (rec.request_failed.length < 25) rec.request_failed.push({ url: u.slice(0, 260), failure });
  });
  page.on("response", (res) => {
    const u = res.url();
    let host = ""; try { host = new URL(u).host; } catch (e) { return; }
    const st = res.status();
    if (KALSHI_HOSTS.has(host)) {
      if (DEMO_HOSTS.has(host)) rec.api.demo_requests++; else rec.api.production_requests++;
      rec.api.by_status[st] = (rec.api.by_status[st] || 0) + 1;
      rec.api.by_host[host] = (rec.api.by_host[host] || 0) + 1;
      if (st === 429) rec.api.rate_limited_429++;
      if (rec.api.sample_urls.length < 6 && !rec.api.sample_urls.includes(u.slice(0, 200))) {
        rec.api.sample_urls.push(u.slice(0, 200));
      }
    } else if (host && host !== new URL(SITE_ORIGIN).host) {
      rec.other_hosts[host] = (rec.other_hosts[host] || 0) + 1;
    }
    if (st >= 400 && rec.bad_responses.length < 25) rec.bad_responses.push({ url: u.slice(0, 260), status: st });
  });
  page.on("websocket", (ws) => {
    const w = { url: ws.url().slice(0, 200), frames_received: 0, closed: false, error: "" };
    rec.websockets.push(w);
    ws.on("framereceived", () => { w.frames_received++; });
    ws.on("close", () => { w.closed = true; });
    ws.on("socketerror", (e) => { w.error = String(e).slice(0, 200); });
  });

  try {
    const resp = await page.goto(rec.url, { waitUntil: "domcontentloaded", timeout: 45000 });
    rec.document_status = resp ? resp.status() : null;
    const settle = rec.live_page ? LIVE_SETTLE_MS : STATIC_SETTLE_MS;
    const marks = rec.live_page ? [3000, 10000, 20000, settle] : [settle];
    let waited = 0;
    for (const m of marks) {
      await sleep(Math.max(0, m - waited)); waited = m;
      const quick = await page.evaluate(() => ({
        rows: [...document.querySelectorAll("table tbody tr")].filter((tr) =>
          tr.querySelectorAll("td").length > 1 || !tr.querySelector("td[colspan]")).length,
        text: document.body.innerText.length,
      })).catch(() => null);
      rec.timeline.push({ at_ms: m, rows: quick ? quick.rows : null, text: quick ? quick.text : null,
        demo_requests: rec.api.demo_requests });
    }
    const flow = FLOWS[rel];
    if (flow) {
      const shots = [];
      const shoot = async (name) => {
        if (!wantsShot(rel)) return;
        const f = path.join(SHOT_DIR, slug(rel) + "__" + name + ".jpg");
        await page.screenshot({ path: f, type: "jpeg", quality: 45, fullPage: false }).catch(() => {});
        shots.push(path.relative(OUT, f).split(path.sep).join("/"));
      };
      try {
        rec.flow = await flow(page, { sleep, shoot, rec });
      } catch (e) {
        rec.flow = { error: String(e && e.message || e).slice(0, 400) };
      }
      if (rec.flow && shots.length) rec.flow.screenshots = shots;
    }
    rec.dom = await page.evaluate(surveyDom);
    // same-origin links: do the targets exist?
    const links = [...new Set(rec.dom.links
      .filter((h) => h.startsWith(SITE_BASE))
      .map((h) => h.split("#")[0]))];
    rec.dom.links = undefined;
    rec.internal_links = links.length;
    rec._internal_link_list = links;
    if (wantsShot(rel)) {
      const f = path.join(SHOT_DIR, slug(rel) + ".jpg");
      const h = Math.min(rec.dom.doc_height || 900, 2400);
      await page.screenshot({ path: f, type: "jpeg", quality: 45,
        clip: { x: 0, y: 0, width: 1280, height: h }, fullPage: true }).catch(async () => {
        await page.screenshot({ path: f, type: "jpeg", quality: 55, fullPage: false }).catch(() => {});
      });
      if (fs.existsSync(f)) rec.screenshot = path.relative(OUT, f).split(path.sep).join("/");
    }
  } catch (e) {
    rec.error = String(e && e.message || e).slice(0, 400);
  } finally {
    await context.close().catch(() => {});
  }
  rec.elapsed_ms = Date.now() - started;
  return rec;
}

async function checkLinks(browser, pages, missingLocal) {
  // de-duplicated existence check of every same-origin link the rendered pages contain
  const from = new Map();
  for (const p of pages) for (const l of (p._internal_link_list || [])) {
    if (!from.has(l)) from.set(l, []);
    if (from.get(l).length < 3) from.get(l).push(p.page);
  }
  const broken = [];
  if (MODE === "local") {
    for (const [l, src] of from) {
      const r = localFileFor(l);
      if (r.status === 404) broken.push({ url: l.replace(SITE_BASE, ""), status: 404, linked_from: src });
    }
  } else {
    const ctx = await browser.newContext();
    const list = [...from.keys()];
    let i = 0;
    await Promise.all(Array.from({ length: 8 }, async () => {
      while (i < list.length) {
        const l = list[i++];
        try {
          const res = await ctx.request.get(l, { timeout: 20000, maxRedirects: 3 });
          if (res.status() >= 400) broken.push({ url: l.replace(SITE_BASE, ""), status: res.status(), linked_from: from.get(l) });
        } catch (e) {
          broken.push({ url: l.replace(SITE_BASE, ""), status: "error: " + String(e.message || e).slice(0, 80), linked_from: from.get(l) });
        }
      }
    }));
    await ctx.close();
  }
  return { checked: from.size, broken: broken.sort((a, b) => a.url.localeCompare(b.url)) };
}

function mdEscape(s) { return String(s).replace(/\|/g, "\\|").replace(/\n/g, " "); }

function writeSummary(report) {
  const L = [];
  const P = report.pages;
  L.push(`# Real-browser check — mode \`${report.mode}\``);
  L.push("");
  L.push(`Generated ${report.finished_at} by \`e2e/run.mjs\` (headless Chromium ${report.browser_version}, ` +
    `Playwright ${report.playwright_version}) on commit \`${report.commit || "unknown"}\`.`);
  L.push(report.mode === "local"
    ? "The checked-out tree was served to the browser as `https://karagemop466-tech.github.io/Demo3/`, so demo-API calls carried the real Pages `Origin`."
    : "The browser loaded the pages GitHub Pages was serving at that moment (nothing intercepted).");
  L.push("");
  const t = report.totals;
  L.push("| Measure | Value |");
  L.push("|---|---|");
  L.push(`| Pages opened | ${t.pages} |`);
  L.push(`| Pages whose document did not return HTTP 200 | ${t.document_not_200} |`);
  L.push(`| Pages with an uncaught script exception | ${t.pages_with_page_errors} |`);
  L.push(`| Pages with console errors | ${t.pages_with_console_errors} |`);
  L.push(`| Demo-API responses seen by the browser | ${t.demo_requests} (by status: ${JSON.stringify(t.by_status)}) |`);
  L.push(`| Demo-API requests blocked (CORS / network) | ${t.cors_blocked} |`);
  L.push(`| HTTP 429 (rate limited) | ${t.rate_limited_429} |`);
  L.push(`| Requests to Kalshi **production** hosts | ${t.production_requests} |`);
  L.push(`| Same-origin links checked / broken | ${report.links.checked} / ${report.links.broken.length} |`);
  L.push("");
  L.push("## Per page");
  L.push("");
  L.push("| Page | Doc | Demo API calls (statuses) | Table rows | Rows w/o link | Charts painted | Script errors | Still busy / banners |");
  L.push("|---|---|---|---|---|---|---|---|");
  for (const p of P) {
    const d = p.dom || {};
    const charts = (d.canvases || []).filter((c) => c.visible);
    const painted = charts.filter((c) => (c.sampled_painted_pixels || 0) > 0).length;
    const errs = p.page_errors.length + p.console_errors.length;
    const busy = (d.busy_text || []).map((b) => b.text).concat((d.visible_alerts || []).map((a) => a.text.slice(0, 80)));
    L.push(`| \`${p.page}\` | ${p.document_status ?? "—"}${p.error ? " ⚠" : ""} | ${p.api.demo_requests}` +
      `${p.api.demo_requests ? " " + mdEscape(JSON.stringify(p.api.by_status)) : ""}` +
      `${p.api.production_requests ? " · PROD " + p.api.production_requests : ""} | ${d.body_rows ?? "—"} | ` +
      `${d.rows_without_link ?? "—"} | ${charts.length ? painted + "/" + charts.length : "—"} | ${errs || ""} | ` +
      `${mdEscape(busy.slice(0, 2).join(" ; ").slice(0, 160))} |`);
  }
  L.push("");
  if (report.links.broken.length) {
    L.push("## Broken same-origin links");
    L.push("");
    L.push("| Target | Status | Linked from |");
    L.push("|---|---|---|");
    for (const b of report.links.broken) L.push(`| \`${mdEscape(b.url)}\` | ${b.status} | ${b.linked_from.map((x) => "`" + x + "`").join(", ")} |`);
    L.push("");
  }
  const withErr = P.filter((p) => p.page_errors.length || p.console_errors.length || p.error);
  if (withErr.length) {
    L.push("## Script errors (first lines)");
    L.push("");
    for (const p of withErr) {
      L.push(`- \`${p.page}\`` + (p.error ? ` — navigation: ${mdEscape(p.error)}` : ""));
      for (const e of p.page_errors.slice(0, 3)) L.push(`  - exception: ${mdEscape(e)}`);
      for (const e of p.console_errors.slice(0, 3)) L.push(`  - console: ${mdEscape(e.text)}`);
    }
    L.push("");
  }
  const flows = P.filter((p) => p.flow);
  if (flows.length) {
    L.push("## Scripted flows (what a trader would click)");
    L.push("");
    for (const p of flows) {
      L.push(`### \`${p.page}\``);
      L.push("");
      L.push("```json");
      L.push(JSON.stringify(p.flow, null, 1));
      L.push("```");
      L.push("");
    }
  }
  fs.writeFileSync(path.join(OUT, "summary.md"), L.join("\n") + "\n");
}

async function main() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const pages = wanted(listPages());
  const browser = await chromium.launch({ headless: true });
  const missingLocal = new Set();
  const results = [];
  const queue = pages.slice();
  // live pages first with low concurrency (they poll the demo API), then static ones
  const live = queue.filter((p) => LIVE_PAGES.has(p));
  const stat = queue.filter((p) => !LIVE_PAGES.has(p));
  async function pool(list, n) {
    let i = 0;
    await Promise.all(Array.from({ length: Math.min(n, list.length) }, async () => {
      while (i < list.length) {
        const rel = list[i++];
        const rec = await checkPage(browser, rel, missingLocal).catch((e) => ({
          page: rel, error: String(e && e.message || e), page_errors: [], console_errors: [],
          api: { demo_requests: 0, by_status: {}, production_requests: 0, cors_blocked: 0, rate_limited_429: 0 },
        }));
        results.push(rec);
        const d = rec.dom || {};
        console.log(`[${MODE}] ${rel}: doc=${rec.document_status} api=${rec.api.demo_requests} ` +
          `${JSON.stringify(rec.api.by_status)} rows=${d.body_rows} errs=${rec.page_errors.length + rec.console_errors.length}` +
          (rec.error ? " NAV-ERROR " + rec.error : ""));
      }
    }));
  }
  await pool(live, LIVE_CONCURRENCY);
  await pool(stat, CONCURRENCY + 2);
  results.sort((a, b) => a.page.localeCompare(b.page));
  const links = await checkLinks(browser, results, missingLocal);
  for (const r of results) delete r._internal_link_list;
  const byStatus = {};
  for (const r of results) for (const [k, v] of Object.entries(r.api.by_status || {})) byStatus[k] = (byStatus[k] || 0) + v;
  const report = {
    mode: MODE, site: SITE_BASE,
    started_at: new Date(startedAt).toISOString(), finished_at: new Date().toISOString(),
    commit: process.env.GITHUB_SHA || "", run_url: process.env.GITHUB_SERVER_URL && process.env.GITHUB_RUN_ID
      ? `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}` : "",
    browser_version: browser.version(),
    playwright_version: JSON.parse(fs.readFileSync(path.join(HERE, "node_modules", "playwright", "package.json"), "utf8")).version,
    settle_ms: { static: STATIC_SETTLE_MS, live: LIVE_SETTLE_MS },
    live_concurrency: LIVE_CONCURRENCY,
    sources: {
      demo_env: "https://docs.kalshi.com/getting_started/demo_env",
      market_data_no_auth: "https://docs.kalshi.com/getting_started/quick_start_market_data",
      rate_limits: "https://docs.kalshi.com/getting_started/rate_limits",
    },
    totals: {
      pages: results.length,
      document_not_200: results.filter((r) => r.document_status !== 200).length,
      pages_with_page_errors: results.filter((r) => r.page_errors.length).length,
      pages_with_console_errors: results.filter((r) => r.console_errors.length).length,
      demo_requests: results.reduce((a, r) => a + r.api.demo_requests, 0),
      by_status: byStatus,
      cors_blocked: results.reduce((a, r) => a + r.api.cors_blocked, 0),
      rate_limited_429: results.reduce((a, r) => a + r.api.rate_limited_429, 0),
      production_requests: results.reduce((a, r) => a + r.api.production_requests, 0),
    },
    links,
    local_404s: [...missingLocal].map((u) => u.replace(SITE_BASE, "")).sort(),
    pages: results,
  };
  await browser.close();
  fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 1) + "\n");
  writeSummary(report);
  console.log(`wrote ${path.relative(REPO, OUT)}/report.json — ${results.length} pages, ` +
    `${report.totals.demo_requests} demo-API responses ${JSON.stringify(byStatus)}, ` +
    `${links.broken.length} broken links`);
}

const startedAt = Date.now();
main().catch((e) => { console.error(e); process.exit(1); });
