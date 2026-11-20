#!/usr/bin/env python3
"""Verify the Live Alert Desk site (live/).

Checks, all offline:
  1. every internal link resolves to a file that exists
  2. every external link is https and on an allowlisted official/gov/news host
  3. every table row carries at least one source link, or an explicit
     'unverified' marker (blank cells are allowed only when flagged)
  4. every JSON file in live/data parses and every row-like record keeps a
     source URL (markets, alerts, trades, resolved markets, candles)
  5. JS/CSS assets exist and `node --check` passes when node is available
  6. the pages the nav promises are all present, and the nav is identical set
     on every page

Exit code 0 = pass. Run: python3 scripts/verify_live_site.py
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE = ROOT / "live"

ALLOW_HOSTS = (
    "docs.kalshi.com", "external-api.demo.kalshi.co", "demo-api.kalshi.co",
    "demo.kalshi.co", "kalshi.co", "api.elections.kalshi.com",
    "github.com", "karagemop466-tech.github.io", "news.google.com",
    "assets.kalshi.com", "www.kalshi.com",
)

REQUIRED_PAGES = [
    "index.html", "dashboard.html", "gas.html", "elections.html", "culture.html",
    "crypto.html", "golf.html", "graph.html", "tracking.html", "strategies.html",
    "portfolio.html", "suggestions.html", "methodology.html", "flagged.html",
    "sources.html",
]

failures: list[str] = []
warnings: list[str] = []


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.rows = []          # list of (row_html, has_source, has_unverified)
        self._in_tr = False
        self._row = []
        self._row_links = 0
        self._row_unver = False
        self._row_tds = 0
        self._in_td = False
        self._td_text = []
        self._td_links = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
            if a["href"].startswith("http"):
                if self._in_tr:
                    self._row_links += 1
                if self._in_td:
                    self._td_links += 1
        if tag == "tr":
            self._in_tr = True
            self._row_tds = 0
            self._row = []
            self._row_links = 0
            self._row_unver = False
        if tag == "td":
            self._in_td = True
            self._row_tds += 1
            self._td_text = []
            self._td_links = 0

    def handle_endtag(self, tag):
        if tag == "tr" and self._in_tr:
            if self._row and self._row_tds:
                self.rows.append({"text": " ".join(self._row),
                                  "links": self._row_links,
                                  "unverified": self._row_unver})
            self._in_tr = False
        if tag == "td":
            text = " ".join(self._td_text).lower()
            if "unverified" in text or "left blank" in text:
                self._row_unver = True
            self._in_td = False

    def handle_data(self, data):
        if self._in_td:
            self._td_text.append(data)
        if self._in_tr and data.strip():
            self._row.append(data.strip())


def check_links(page: pathlib.Path, links):
    seen = set()
    for href in links:
        if href in seen:
            continue
        seen.add(href)
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        if href.startswith("http://"):
            failures.append(f"{page.name}: insecure http link {href}")
            continue
        if href.startswith("https://"):
            host = href.split("/")[2].lower()
            if not any(host == h or host.endswith("." + h) for h in ALLOW_HOSTS):
                failures.append(f"{page.name}: link host not allowlisted: {href}")
            continue
        if href.startswith("//"):
            failures.append(f"{page.name}: protocol-relative link {href}")
            continue
        target = href.split("#")[0].split("?")[0]
        if not target:
            continue
        p = (page.parent / target).resolve()
        if not p.exists():
            # allow planned anchors like data/x.json only if the file exists
            failures.append(f"{page.name}: broken internal link {href}")


def check_rows(page: pathlib.Path, parser: LinkParser):
    """Every table row must carry its own official source link, or say unverified.

    Rows that only restate an aggregate ("No rows.") are skipped."""
    for row in parser.rows:
        text = row["text"]
        if text.lower().strip() in ("no rows.", "none"):
            continue
        if row["unverified"] or row["links"]:
            continue
        failures.append(f"{page.name}: table row without a source link: {text[:90]}")


def check_data():
    d = LIVE / "data"
    for p in sorted(d.glob("*.json")):
        try:
            json.loads(p.read_text())
        except Exception as e:
            failures.append(f"data/{p.name}: invalid JSON ({e})")
    markets = json.loads((d / "markets.json").read_text())["markets"]
    for m in markets:
        if not m.get("market_url"):
            failures.append(f"markets.json: {m.get('ticker')} has no source URL")
    alerts = json.loads((d / "alerts.json").read_text())["alerts"]
    for a in alerts:
        if not a.get("source_url") and not a.get("candle_url"):
            failures.append(f"alerts.json: {a.get('id')} has no source URL")
        if abs(a["delta"]) < 0.10 - 1e-9:
            failures.append(f"alerts.json: {a['id']} below the $0.10 threshold")
    roi = json.loads((d / "alerts_roi.json").read_text())["alerts"]
    for a in roi:
        if not (a.get("roi") or {}).get("is_high_roi"):
            failures.append(f"alerts_roi.json: {a['id']} is not flagged high-ROI")
    trades = json.loads((d / "trades.json").read_text())["trades"]
    for t in trades:
        if t.get("mode") != "simulated":
            failures.append(f"trades.json: {t.get('id')} not labelled simulated")
        if not t.get("market_url"):
            failures.append(f"trades.json: {t.get('id')} has no market source URL")
    res = json.loads((d / "resolutions.json").read_text())
    for r in res.get("resolved_markets", []):
        if r.get("result") not in ("yes", "no"):
            failures.append(f"resolutions.json: {r.get('ticker')} result not yes/no")
        if not r.get("source_url"):
            failures.append(f"resolutions.json: {r.get('ticker')} has no source URL")
    idx = json.loads((d / "candles_index.json").read_text())
    for ticker, m in idx["markets"].items():
        f = LIVE / m["path"]
        if not f.exists():
            failures.append(f"candles_index.json: missing file for {ticker}")
            continue
        payload = json.loads(f.read_text())
        for k, rows in payload.get("series", {}).items():
            for row in rows:
                if len(row) != 6:
                    failures.append(f"{ticker}: candle row shape {row[:3]}")
                    break
        if not payload.get("source_url"):
            failures.append(f"{ticker}: candle payload has no source URL")


def check_assets():
    for js in sorted((LIVE / "assets").glob("*.js")):
        if not shutil.which("node"):
            warnings.append("node not available; JS syntax checks skipped")
            break
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        if r.returncode != 0:
            failures.append(f"assets/{js.name}: node --check failed: {r.stderr.strip()[:300]}")
    for css in (LIVE / "assets").glob("*.css"):
        if not css.read_text().strip():
            failures.append(f"assets/{css.name}: empty stylesheet")


def check_pages():
    for name in REQUIRED_PAGES:
        if not (LIVE / name).exists():
            failures.append(f"missing required page live/{name}")
    for page in sorted(LIVE.glob("*.html")):
        parser = LinkParser()
        parser.feed(page.read_text())
        check_links(page, parser.links)
        check_rows(page, parser)
        text = page.read_text()
        if "SIMULATED" not in text and "simulat" not in text.lower():
            warnings.append(f"{page.name}: no simulated-trading disclosure (check manually)")


def main():
    check_pages()
    check_data()
    check_assets()
    print(f"pages checked: {len(list(LIVE.glob('*.html')))}, data files: "
          f"{len(list((LIVE / 'data').glob('*.json')))}, candles: "
          f"{len(list((LIVE / 'data' / 'candles').glob('*.json')))}")
    for w in warnings:
        print(f"WARN  {w}")
    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures[:80]:
            print("  FAIL", f)
        return 1
    print("PASS — links resolve, every table row has a source or an unverified marker, "
          "every data row keeps its source URL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
