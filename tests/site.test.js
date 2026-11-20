import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const desk = path.join(repo, "demo-desk");

function htmlFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return htmlFiles(file);
    return entry.isFile() && file.endsWith(".html") ? [file] : [];
  });
}

function localReferences(html) {
  return [...html.matchAll(/\b(?:href|src)="([^"]+)"/gi)].map((match) => match[1]);
}

test("all Demo Desk HTML pages have resolvable local assets and links", () => {
  const pages = [path.join(desk, "index.html"), ...htmlFiles(path.join(desk, "pages"))];
  assert.equal(pages.length, 14);
  for (const page of pages) {
    const source = readFileSync(page, "utf8");
    assert.match(source, /<!doctype html>/i, `${path.relative(repo, page)} should declare HTML5`);
    assert.match(source, /<html lang="en">/i, `${path.relative(repo, page)} should declare its language`);
    for (const reference of localReferences(source)) {
      if (/^(?:https?:|mailto:|tel:|data:|javascript:|#)/i.test(reference)) continue;
      const pathname = decodeURIComponent(reference.split(/[?#]/, 1)[0]);
      let target = path.resolve(path.dirname(page), pathname || ".");
      if (reference.endsWith("/")) target = path.join(target, "index.html");
      assert.ok(existsSync(target), `${path.relative(repo, page)} links to missing ${reference}`);
    }
    const ids = [...source.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
    assert.equal(new Set(ids).size, ids.length, `${path.relative(repo, page)} should not duplicate HTML IDs`);
  }
});

test("the existing repository home links to the separately hosted Demo Desk without replacing its landing page", () => {
  const home = readFileSync(path.join(repo, "index.html"), "utf8");
  assert.match(home, /Kalshi Demo Tracker/);
  assert.match(home, /href="demo-desk\/index\.html"/);
  assert.ok(existsSync(path.join(desk, "index.html")));
  for (const reference of localReferences(home)) {
    if (/^(?:https?:|mailto:|tel:|data:|javascript:|#)/i.test(reference)) continue;
    const pathname = decodeURIComponent(reference.split(/[?#]/, 1)[0]);
    let target = path.resolve(repo, pathname || ".");
    if (reference.endsWith("/")) target = path.join(target, "index.html");
    assert.ok(existsSync(target), `root index.html links to missing ${reference}`);
  }
});

test("browser code uses no localhost endpoints, private key material, or third-party runtime font imports", () => {
  const files = [
    ...htmlFiles(desk),
    ...htmlFiles(path.join(desk, "pages")),
    ...["api.js", "chart.js", "content.js", "main.js", "metrics.js", "renderers.js", "shell.js", "topics.js", "utils.js"].map((name) => path.join(desk, "src", name)),
    path.join(desk, "assets", "css", "site.css"),
  ];
  for (const file of new Set(files)) {
    const content = readFileSync(file, "utf8");
    assert.doesNotMatch(content, /https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?/i, `${path.relative(repo, file)} must not call localhost`);
    assert.doesNotMatch(content, /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/, `${path.relative(repo, file)} must not contain a private key`);
  }
  const css = readFileSync(path.join(desk, "assets", "css", "site.css"), "utf8");
  assert.doesNotMatch(css, /@import\s+url\(/i, "the dashboard should not depend on a third-party font import");
});

test("portfolio and market tables expose row-level official sources or an explicit unverified state", () => {
  const portfolio = readFileSync(path.join(desk, "pages", "portfolio.html"), "utf8");
  const body = portfolio.match(/<tbody>([\s\S]*?)<\/tbody>/i)?.[1] ?? "";
  const rows = [...body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map((match) => match[1]);
  assert.equal(rows.length, 5);
  for (const row of rows) assert.match(row, /<a\b[^>]*href="https:\/\/docs\.kalshi\.com\//i);
  const main = readFileSync(path.join(desk, "index.html"), "utf8");
  assert.match(main, /Each event row has an official Kalshi API source link/i);
  assert.match(main, /Dollar ranking is not verified yet/);
});

test("package scripts check ES modules and run the local test suite", () => {
  const manifest = JSON.parse(readFileSync(path.join(repo, "package.json"), "utf8"));
  assert.equal(manifest.type, "module");
  assert.equal(manifest.scripts.test, "node --test");
  assert.match(manifest.scripts.check, /demo-desk\/src\/main\.js/);
  assert.ok(existsSync(path.join(repo, "tests", "core.test.js")));
  assert.ok(existsSync(path.join(repo, "tests", "api.test.js")));
});
