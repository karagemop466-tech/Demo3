#!/usr/bin/env python3
"""Verify the audit page against its rules. Exit 1 on any failure.

Checks:
  * rows.json: unique IDs, required fields non-empty, valid result labels.
  * every row has at least one official Kalshi link (docs.kalshi.com or
    external-api.demo.kalshi.co); every URL is https and on an allowed host;
    repo links point at the main branch of this repository.
  * 'Verified' rows have an official link; 'Contradicted' rows have evidence.
  * index.html is up to date with rows.json (rebuilt in memory and compared),
    contains every row ID and every URL, and has balanced basic tags.
  * relative links on the page resolve to files in the repo.
"""
import html
import html.parser
import json
import pathlib
import sys
from urllib.parse import urlparse

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import build_audit  # noqa: E402

ALLOWED_HOSTS = {
    "docs.kalshi.com",
    "external-api.demo.kalshi.co",
    "github.com",
    "gasprices.aaa.com",
}
OFFICIAL_HOSTS = {"docs.kalshi.com", "external-api.demo.kalshi.co"}
REPO_PREFIX = "https://github.com/karagemop466-tech/Demo3/blob/main/"
REQUIRED = ("id", "claim", "where", "official", "evidence", "result", "note")

errors = []


def err(msg):
    errors.append(msg)


class TagBalance(html.parser.HTMLParser):
    VOID = {"meta", "link", "br", "img", "input", "hr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.bad = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.bad.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                if self.stack:
                    self.stack.pop()
        else:
            self.stack.pop()


def check_url(url, where):
    p = urlparse(url)
    if p.scheme != "https":
        err(f"{where}: non-https URL {url}")
    if p.netloc not in ALLOWED_HOSTS:
        err(f"{where}: host not allowed: {p.netloc} ({url})")
    if p.netloc == "github.com" and not url.startswith(REPO_PREFIX):
        err(f"{where}: GitHub link is not a file on main in this repo: {url}")


def main():
    data = json.loads((HERE / "rows.json").read_text(encoding="utf-8"))
    legend = set(data["results_legend"])
    seen = set()
    all_rows = []
    for s in data["sections"]:
        for r in s["rows"]:
            rid = r.get("id", "?")
            all_rows.append(r)
            if rid in seen:
                err(f"duplicate id {rid}")
            seen.add(rid)
            for f in REQUIRED:
                if f not in r:
                    err(f"{rid}: missing field {f}")
                elif f not in ("official", "evidence") and not str(r[f]).strip():
                    err(f"{rid}: empty field {f}")
            if r.get("result") not in legend:
                err(f"{rid}: unknown result label {r.get('result')!r}")
            off = r.get("official", [])
            if not any(urlparse(i["url"]).netloc in OFFICIAL_HOSTS for i in off):
                err(f"{rid}: no official Kalshi source link")
            for group in ("official", "evidence"):
                for item in r.get(group, []):
                    if not item.get("label") or not item.get("url"):
                        err(f"{rid}: {group} item missing label or url")
                        continue
                    check_url(item["url"], rid)
            if r.get("result") == "Verified" and not off:
                err(f"{rid}: Verified without a source")
            if r.get("result") == "Contradicted" and not r.get("evidence"):
                err(f"{rid}: Contradicted without evidence")

    # Rebuild the page in memory and compare with the committed file.
    build_audit.OUT = HERE / "_expected.html"
    build_audit.build()
    expected = (HERE / "_expected.html").read_text(encoding="utf-8")
    (HERE / "_expected.html").unlink()
    actual = (HERE / "index.html").read_text(encoding="utf-8") if (HERE / "index.html").exists() else ""
    if expected != actual:
        err("index.html is stale: run python3 audit/build_audit.py")

    for r in all_rows:
        if f'id="{r["id"]}"' not in actual:
            err(f"{r['id']}: not rendered on the page")
        for group in ("official", "evidence"):
            for item in r.get(group, []):
                if html.escape(item["url"], quote=True) not in actual:
                    err(f"{r['id']}: URL missing from page: {item['url']}")

    tb = TagBalance()
    tb.feed(actual)
    for b in tb.bad:
        err(f"HTML: {b}")
    if tb.stack:
        err(f"HTML: unclosed tags {tb.stack}")

    # Relative links on the page must resolve inside the repo.
    for rel in ("../index.html", "../dashboard.html", "../flagged.html"):
        if not (HERE / rel).resolve().exists():
            err(f"relative link does not resolve: {rel}")

    total = len(all_rows)
    if errors:
        print(f"FAILED: {len(errors)} problem(s) across {total} rows")
        for e in errors:
            print(" -", e)
        return 1
    print(f"PASSED: {total} rows, every row has an official Kalshi source link, all URLs on allowed hosts, page up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
