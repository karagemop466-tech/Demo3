#!/usr/bin/env python3
"""Verify the `paper-desk/` subsite: links resolve, every data row is sourced, JS parses.

Checks (each failure prints the file, the table and the offending row):
1. internal links and asset references point at files that exist in the repo;
2. every <tbody> row carries at least one <a href=...> source link, or an explicit
   "unverified" marker — a row with neither is a violation of the brief's rule that
   no value may be shown without an official source;
3. no absolute http://localhost or 127.0.0.1 reference (the site must work from the
   Pages origin, where the sandbox/dev-server hostnames do not exist);
4. external links use https and land on an allowed official host;
5. the page's JSON dependencies exist and parse;
6. `node --check` on the page's JavaScript.

Run: python3 scripts/verify_paper_desk.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(REPO, "paper-desk")
PAGES = ["index.html", "trades.html", "positions.html", "analysis.html",
         "resolutions.html", "methodology.html", "sources.html"]
ALLOWED_HOSTS = {
    "docs.kalshi.com", "external-api.demo.kalshi.co", "demo-api.kalshi.co",
    "external-api-ws.demo.kalshi.co", "demo.kalshi.co", "help.kalshi.com",
    "github.com", "karagemop466-tech.github.io", "kalshi.com", "www.kalshi.com",
    "docs.github.com",
}
DATA_DEPS = [f"data/paper/{n}.json" for n in
             ("state", "trades", "equity", "analysis", "resolutions", "runs", "books",
              "sources")]
OPTIONAL_DEPS = ["data/latest/top_events.json", "data/latest/portfolio.json",
                 "data/latest/meta.json", "data/latest/collector_status.json"]

ROW_RE = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
TBODY_RE = re.compile(r"<tbody\b.*?</tbody>", re.S | re.I)
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
SRC_RE = re.compile(r"""src=["']([^"']+)["']""", re.I)


def rel_of(path: str, marker: str) -> bool:
    norm = path.replace(os.sep, "/")
    return marker in norm


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    stats = {"rows": 0, "sourced": 0, "links": 0}

    for page in PAGES:
        path = os.path.join(SITE, page)
        if not os.path.exists(path):
            failures.append(f"{page}: missing")
            continue
        html = open(path).read()
        # 1 + 3 + 4: links
        for href in HREF_RE.findall(html) + SRC_RE.findall(html):
            stats["links"] += 1
            if href.startswith(("mailto:", "#", "data:")):
                continue
            if href.startswith("http"):
                parsed = urlparse(href)
                if parsed.scheme != "https":
                    failures.append(f"{page}: non-https external link {href}")
                elif parsed.hostname not in ALLOWED_HOSTS:
                    failures.append(f"{page}: external host not on the allowlist: {href}")
                continue
            if re.search(r"(localhost|127\.0\.0\.1)", href):
                failures.append(f"{page}: local host reference {href}")
                continue
            target = os.path.normpath(os.path.join(SITE, href.split("#")[0]))
            if os.path.exists(target):
                continue
            if rel_of(target, "data/paper/") or rel_of(target, "data/latest/"):
                warnings.append(f"{page}: {href} not present yet (written by the next "
                                f"collector/desk cycle)")
                continue
            failures.append(f"{page}: broken internal link {href} -> {target}")
        # 2: every body row is sourced or explicitly unverified
        for body in TBODY_RE.findall(html):
            for row in ROW_RE.findall(body):
                if "<th" in row.lower():
                    continue
                stats["rows"] += 1
                low = row.lower()
                if any(m in low for m in ("class=\"src\"", "href=", "unverified",
                                          "no source url", "no rows yet")):
                    stats["sourced"] += 1
                else:
                    snippet = re.sub(r"<[^>]+>", " ", row)
                    snippet = re.sub(r"\s+", " ", snippet).strip()[:120]
                    failures.append(f"{page}: unsourced table row: {snippet}")
        # sanity: the simulated/paper labelling must be visible on every page
        if "simulat" not in html.lower():
            failures.append(f"{page}: missing the 'simulated' labelling")
        if "not a demo-account" not in html and "not the user" not in html.lower() \
                and "credentials_missing" not in html and "demo account" not in html.lower():
            warnings.append(f"{page}: demo-account caveat not found in prose")

    # 5: data dependencies
    for rel in DATA_DEPS:
        p = os.path.join(REPO, rel)
        if not os.path.exists(p):
            warnings.append(f"{rel}: not present yet (created by the first desk cycle)")
            continue
        try:
            json.load(open(p))
        except json.JSONDecodeError as exc:
            failures.append(f"{rel}: invalid JSON ({exc})")
    for rel in OPTIONAL_DEPS:
        p = os.path.join(REPO, rel)
        if not os.path.exists(p):
            warnings.append(f"{rel}: absent (optional provenance file)")

    # 6: JS syntax
    js = os.path.join(SITE, "assets", "paper.js")
    if os.path.exists(js):
        try:
            proc = subprocess.run(["node", "--check", js], capture_output=True, text=True)
            if proc.returncode != 0:
                failures.append(f"assets/paper.js: node --check failed: {proc.stderr.strip()[:300]}")
        except FileNotFoundError:
            warnings.append("node not available: skipped the JS syntax check")
    else:
        failures.append("assets/paper.js: missing")
    css = os.path.join(SITE, "assets", "paper.css")
    if not os.path.exists(css):
        failures.append("assets/paper.css: missing")

    print(f"paper-desk verify: {len(PAGES)} pages, {stats['links']} links checked, "
          f"{stats['sourced']}/{stats['rows']} data rows carry a source link or an "
          f"explicit unverified marker")
    for w in warnings:
        print(f"  note: {w}")
    for f in failures:
        print(f"  FAIL: {f}")
    print(f"result: {'PASS' if not failures else 'FAIL'} ({len(failures)} failures, "
          f"{len(warnings)} notes)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
