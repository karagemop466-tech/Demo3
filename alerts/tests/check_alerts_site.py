#!/usr/bin/env python3
"""Link and source check for the live alerts pages (offline).

- every internal href/src resolves to a file in the repo
- every external link is on an official Kalshi host, or is the one labelled news-search link
- every table row in alerts/*.html carries at least one link
Exit code 1 on any failure.
"""
import html.parser
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PAGES = ["alerts/index.html", "alerts/flagged.html"]
OFFICIAL_HOSTS = ("docs.kalshi.com", "external-api.demo.kalshi.co")
NEWS_SEARCH_PREFIX = "https://www.google.com/search?tbm=nws&q="


class Collector(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.rows_without_link = 0
        self._in_row = False
        self._row_has_link = False
        self._row_cells = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("a", "link", "script") and (a.get("href") or a.get("src")):
            self.links.append(a.get("href") or a.get("src"))
        if tag == "tr":
            if self._in_row and self._row_cells and not self._row_has_link:
                self.rows_without_link += 1
            self._in_row, self._row_has_link, self._row_cells = True, False, 0
        if tag in ("td",):
            self._row_cells += 1
        if tag == "a" and self._in_row:
            self._row_has_link = True

    def handle_endtag(self, tag):
        if tag == "table" and self._in_row:
            pass

    def close(self):
        super().close()
        if self._in_row and self._row_cells and not self._row_has_link:
            self.rows_without_link += 1


def main():
    failures = []
    for page in PAGES:
        path = os.path.join(ROOT, page)
        text = open(path, encoding="utf-8").read()
        c = Collector()
        c.feed(text)
        c.close()
        base = os.path.dirname(path)
        for href in c.links:
            if href.startswith(("http://", "https://")):
                host = re.sub(r"^https?://([^/]+).*", r"\1", href)
                if host in OFFICIAL_HOSTS or href.startswith(NEWS_SEARCH_PREFIX):
                    continue
                failures.append(f"{page}: external link not on an official host: {href}")
            elif href.startswith(("#", "mailto:")):
                continue
            else:
                target = os.path.normpath(os.path.join(base, href.split("#")[0]))
                if not os.path.exists(target):
                    failures.append(f"{page}: broken internal link: {href}")
        if c.rows_without_link:
            failures.append(f"{page}: {c.rows_without_link} table row(s) without a source link")
        print(f"{page}: {len(c.links)} links checked")
    for f in failures:
        print("FAIL", f)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
