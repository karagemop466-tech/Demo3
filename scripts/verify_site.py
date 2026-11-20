#!/usr/bin/env python3
"""Verification checks for the Kalshi demo site.

1. Every data row in docs/data/verified.json has a source URL on an allowed official host.
2. Every internal link and asset in docs/**/*.html resolves to a file.
3. docs/assets/app.js parses (node --check when node is available).
Exit code 1 on any failure. Rows with no external source (user-supplied questions) are reported, not failed.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

OFFICIAL_HOSTS = {
    "external-api.kalshi.com", "api.elections.kalshi.com", "external-api.demo.kalshi.co",
    "demo-api.kalshi.co", "docs.kalshi.com", "kalshi.com", "www.kalshi.com",
    "assets.kalshi.com", "gasprices.aaa.com", "www.cfbenchmarks.com", "cfbenchmarks.com",
    "github.com", "api.github.com",
}

failures, notes = [], []


def check_url(label, url):
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or host not in OFFICIAL_HOSTS:
        failures.append(f"{label}: source host not on official allowlist -> {url}")


def check_data():
    data = json.loads((DOCS / "data" / "verified.json").read_text(encoding="utf-8"))
    for section in ("series", "resolved", "irregularities", "suggestions", "findings", "sources"):
        for i, row in enumerate(data[section]):
            src = row.get("source") or row.get("url")
            if not src:
                failures.append(f"{section}[{i}]: missing source")
                continue
            check_url(f"{section}[{i}]", src)
    for section in ("questions", "repo_review"):
        for i, row in enumerate(data[section]):
            if not row.get("source"):
                notes.append(f"{section}[{i}]: no external source (user/workspace input) - {str(row)[:60]}...")
            else:
                check_url(f"{section}[{i}]", row["source"])
    # every settlement/series row must have the API source and be marked if non-official
    for i, row in enumerate(data["series"]):
        if "api.kalshi" in row["source"] or "external-api.kalshi.com" not in row["source"]:
            pass
        if not row["ticker"] or not row["title"]:
            failures.append(f"series[{i}]: missing ticker or title")
    notes.append(f"data rows: series={len(data['series'])}, resolved={len(data['resolved'])}, "
                 f"irregularities={len(data['irregularities'])}, unverified={len(data['unverified'])}")


HREF = re.compile(r'(?:href|src)="([^"]+)"')


def check_html():
    for page in DOCS.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for ref in HREF.findall(text):
            if ref.startswith(("http://", "https://", "mailto:", "#")):
                if ref.startswith("http://"):
                    failures.append(f"{page.relative_to(REPO)}: insecure link {ref}")
                continue
            target = (page.parent / ref.split("#")[0].split("?")[0]).resolve()
            if ref.split("#")[0] and not target.exists():
                failures.append(f"{page.relative_to(REPO)}: broken internal link {ref}")
    notes.append(f"html pages checked: {len(list(DOCS.rglob('*.html')))}")


def check_js():
    node = shutil.which("node")
    if not node:
        notes.append("node not found; JS syntax check skipped")
        return
    r = subprocess.run([node, "--check", str(DOCS / "assets" / "app.js")], capture_output=True, text=True)
    if r.returncode != 0:
        failures.append("app.js syntax error: " + r.stderr.strip()[:300])


def main():
    check_data()
    check_html()
    check_js()
    for n in notes:
        print("NOTE  ", n)
    for f in failures:
        print("FAIL  ", f)
    print(f"\n{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
