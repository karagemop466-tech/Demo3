#!/usr/bin/env python3
"""Static checks for the analysis site (analysis/). Exit code 1 on any error (used by CI and before merge).

1. Every data/live and data/findings JSON file parses.
2. Every data row has a non-empty https source_url (Kalshi API or a registered source).
3. Every source ID cited in findings exists in the source registry, with an https URL.
4. Every internal href/src in the HTML resolves to a file in the repo.
5. External links in the HTML are listed (not fetched; CI may be offline).
"""
import json, pathlib, re, sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
ERRORS, NOTES = [], []
ALLOWED_DATA_HOSTS = ("https://api.elections.kalshi.com/", "https://external-api.kalshi.com/", "https://external-api.demo.kalshi.co/", "https://demo-api.kalshi.co/")

def err(msg): ERRORS.append(msg)

def load(path):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except Exception as exc:
        err(f"{path}: invalid JSON ({exc})")
        return None

# 1 + 2: data files and row sources
for name in ["meta", "markets", "resolutions", "orderbooks", "candles", "exchange"]:
    data = load(f"analysis/data/live/{name}.json")
    if data is None:
        continue
    rows = []
    if name == "markets":
        for t in data.get("topics", []):
            rows += t.get("top_markets", [])
    elif name == "resolutions":
        rows = data.get("items", [])
    elif name == "orderbooks":
        rows = list((data.get("books") or {}).values())
    elif name == "candles":
        for s in (data.get("series") or {}).values():
            for k, v in s.items():
                if isinstance(v, dict) and "source_url" in v:
                    rows.append(v)
    for r in rows:
        if r is None:
            continue
        url = r.get("source_url") or ""
        if not url.startswith(ALLOWED_DATA_HOSTS):
            err(f"analysis/data/live/{name}.json: row {r.get('ticker', '?')} has no official source_url ({url!r})")
        for forbidden in ("max_payout_usd",):
            if forbidden in r:
                err(f"analysis/data/live/{name}.json: derived field {forbidden} present")

findings = load("analysis/data/findings.json")
if findings:
    sources = {r["id"]: r for r in findings["sources"]["rows"]}
    for sid, r in sources.items():
        if not r["url"].startswith("https://"):
            err(f"{sid}: source URL is not https")
    cited = set()
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "src" and isinstance(v, list):
                    cited.update(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(findings)
    for sid in sorted(cited):
        if sid not in sources:
            err(f"findings cites unknown source {sid}")
    for sec in ["repo_review", "flagged", "questions", "suggestions", "portfolio", "strategies"]:
        for r in findings.get(sec, {}).get("rows", []):
            if sec in ("flagged", "repo_review", "questions", "suggestions") and not r.get("src"):
                err(f"findings {sec} {r.get('id')}: no source cited")
    NOTES.append(f"sources registered: {len(sources)}; cited: {len(cited)}")

# 4 + 5: HTML links
class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.refs = []
    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.refs.append((tag, v))

externals = set()
for html_file in [ROOT / "analysis/index.html"] + sorted((ROOT / "analysis/pages").glob("*.html")):
    p = Links(); p.feed(html_file.read_text(encoding="utf-8"))
    base = html_file.parent
    for tag, ref in p.refs:
        if ref.startswith(("http://", "https://")):
            externals.add(ref); continue
        if ref.startswith(("#", "mailto:")):
            continue
        target = (base / ref.split("#")[0]).resolve()
        if not target.exists():
            err(f"{html_file.relative_to(ROOT)}: broken internal {tag} -> {ref}")
    if "<script" in html_file.read_text(encoding="utf-8") and not (ROOT / "analysis/assets/app.js").exists():
        err("analysis/assets/app.js missing")

NOTES.append(f"external links listed (not fetched): {len(externals)}")
for n in NOTES: print("note:", n)
if ERRORS:
    for e in ERRORS: print("ERROR:", e)
    print(f"FAILED: {len(ERRORS)} error(s)")
    sys.exit(1)
print("site checks passed")
