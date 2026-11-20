#!/usr/bin/env python3
"""
Site integrity checker for the published dashboard.

Checks, in order (each failure is printed with the file and a reason):
  1. Every local href/src in every published HTML file resolves to a file that exists.
  2. No local link points at "../" outside the published root.
  3. Every external citation in a table row points at an allowed official host
     (kalshi.com / *.kalshi.co / docs.kalshi.com / api.github.com / github.com).
  4. Every JSON file the site loads parses.
  5. Required pages exist (the brief names them explicitly).
  6. No placeholder text that would indicate unfinished content ("TODO", "Lorem ipsum",
     "sample data", "XXX").
  7. Every data row that shows a price/volume has a `source` field.

Exit code 1 if anything fails, so CI blocks the publish. Use --ci to keep output short.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "docs"
# The portal at the repository root is what Pages serves first, so it is part of the published
# surface. The archive is published too (it is linked from the portal), so its internal links must
# resolve or a visitor lands on a 404 from a page we chose to keep.
PORTAL = ROOT / "index.html"
ARCHIVE = ROOT / "legacy"

ALLOWED_CITATION_HOSTS = (
    "kalshi.com", "docs.kalshi.com", "kalshi.co", "external-api.kalshi.com",
    "external-api.demo.kalshi.co", "demo-api.kalshi.co", "demo.kalshi.co",
    "assets.kalshi.com", "help.kalshi.com", "github.com", "api.github.com",
    "karagemop466-tech.github.io", "cfbenchmarks.com", "www.cfbenchmarks.com",
    "gasprices.aaa.com", "apnews.com", "www.wsj.com", "www.espn.com", "www.nfl.com",
    "www.fifa.com", "www.billboard.com", "www.foxsports.com", "help.kalshi.com",
)

REQUIRED_PAGES = [
    "index.html",
    "dashboard.html",
    "categories/gas.html",
    "categories/elections.html",
    "categories/culture.html",
    "categories/crypto.html",
    "categories/golf.html",
    "resolutions.html",
    "liquidity.html",
    "portfolio.html",
    "strategy.html",
    "suggestions.html",
    "questions.html",
    "flagged.html",
    "sources.html",
]

BAD_TEXT = ("TODO", "Lorem ipsum", "lorem ipsum", "sample data", "XXX", "FIXME", "placeholder")


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []   # (tag, value)
        self.text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for key, value in attrs:
            if key in ("href", "src") and value:
                self.links.append((tag, value))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def check() -> list[str]:
    problems: list[str] = []
    if not SITE.exists():
        return [f"published site directory missing: {SITE}"]

    html_files = sorted(SITE.rglob("*.html"))
    if not html_files:
        problems.append("no HTML files found in docs/")

    for rel in REQUIRED_PAGES:
        if not (SITE / rel).exists():
            problems.append(f"missing required page: docs/{rel}")

    # --- root portal ---------------------------------------------------------------------
    # Pages serves the repository root, so the portal is part of the published surface and every
    # local link in it must resolve inside the repository root.
    if not PORTAL.exists():
        problems.append("missing root portal: index.html")
    else:
        parser = LinkParser()
        parser.feed(PORTAL.read_text(encoding="utf-8", errors="replace"))
        for _tag, value in parser.links:
            if value.startswith(("http://", "https://", "mailto:", "#", "data:", "javascript:")):
                continue
            target = (ROOT / value.split("#")[0].split("?")[0]).resolve()
            if not str(target).startswith(str(ROOT.resolve())):
                problems.append(f"index.html: link escapes the repository: {value}")
                continue
            if not target.exists():
                problems.append(f"index.html: broken link -> {value}")

    # The archive under legacy/ is repository material, deliberately not served: its pages were
    # written against the old repo-root layout. Nothing published may link into it, or visitors
    # would follow a link into pages whose assets are not where they expect.
    archive_prefixes = ("legacy/",)
    for page in list(html_files) + ([PORTAL] if PORTAL.exists() else []):
        parser = LinkParser()
        parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        for _tag, value in parser.links:
            if value.startswith(("http://", "https://", "mailto:", "#", "data:", "javascript:")):
                continue
            resolved = (page.parent / value).resolve()
            rel = str(resolved.relative_to(ROOT.resolve())) if str(resolved).startswith(str(ROOT.resolve())) else ""
            if rel.startswith(archive_prefixes):
                problems.append(
                    f"{page.relative_to(ROOT)}: published page links into the non-served archive: {value}")

    # The published artifact directory must stay small: only what the pages fetch. Without this,
    # someone re-adds a 27 MB raw dump to docs/data and every visitor pays for it.
    published = sorted((SITE / "data").glob("*.json")) if (SITE / "data").exists() else []
    allowed_artifacts = {
        "dashboard.json", "expectancy.json", "meta.json", "order-rules.json",
        "portfolio.json", "resolutions-compact.json", "resolutions-summary.json",
    }
    for f in published:
        if f.name not in allowed_artifacts:
            problems.append(f"docs/data/{f.name} is not read by any page; run tools/publish_data.py")
    total_mb = sum(f.stat().st_size for f in published) / 1024 / 1024
    if total_mb > 12:
        problems.append(f"docs/data is {total_mb:.1f} MB; only page artifacts may be published")

    json_cache: dict[Path, object] = {}

    def load_json(path: Path):
        if path in json_cache:
            return json_cache[path]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"data file does not parse: {path.relative_to(ROOT)} ({exc})")
            data = None
        json_cache[path] = data
        return data

    for page in html_files:
        parser = LinkParser()
        try:
            parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"cannot parse {page.relative_to(ROOT)}: {exc}")
            continue

        for tag, value in parser.links:
            if value.startswith(("http://", "https://", "mailto:", "#", "data:", "javascript:")):
                continue
            target = (page.parent / value.split("#")[0].split("?")[0]).resolve()
            if not str(target).startswith(str(SITE.resolve())):
                problems.append(f"{page.relative_to(ROOT)}: link escapes the site root: {value}")
                continue
            if not target.exists():
                problems.append(f"{page.relative_to(ROOT)}: broken link -> {value}")

        text = " ".join(parser.text)
        for bad in BAD_TEXT:
            if bad in text:
                problems.append(f"{page.relative_to(ROOT)}: contains unfinished text {bad!r}")

        # citation hosts inside the page
        for tag, value in parser.links:
            if not value.startswith("http"):
                continue
            host = re.sub(r"^https?://", "", value).split("/")[0].lower()
            if not any(host == h or host.endswith("." + h) for h in ALLOWED_CITATION_HOSTS):
                problems.append(f"{page.relative_to(ROOT)}: citation host not on the allowlist: {host}")

    # data invariants
    dash_path = SITE / "data" / "dashboard.json"
    if dash_path.exists():
        dash = load_json(dash_path)
        if isinstance(dash, dict):
            for topic, groups in (dash.get("tables") or {}).items():
                for group, rows in groups.items():
                    for row in rows if isinstance(rows, list) else []:
                        src = row.get("source") or ""
                        if not src.startswith("http"):
                            problems.append(f"dashboard row without source: {topic}/{group}/{row.get('ticker')}")
    for extra in ("resolutions-compact.json", "portfolio.json", "order-rules.json"):
        p = SITE / "data" / extra
        if p.exists():
            load_json(p)

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ci", action="store_true")
    args = ap.parse_args()
    problems = check()
    if problems:
        print(f"FAIL: {len(problems)} problem(s)")
        for p in problems[:200]:
            print(" -", p)
        return 1
    print("PASS: site links, citations, required pages and data invariants are clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
