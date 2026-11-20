#!/usr/bin/env python3
"""Dependency-free static-site checks for the Kalshi Demo Monitor."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SITE_ROOT = ROOT / "demo-monitor"
OFFICIAL_HOSTS = {
    "docs.kalshi.com",
    "external-api.demo.kalshi.co",
    "demo-api.kalshi.co",
    "docs.github.com",
    "api.github.com",
}
HTML_FILES = sorted(SITE_ROOT.glob("*.html"))
ERRORS: list[str] = []


class SiteParser(HTMLParser):
    def __init__(self, page: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.page = page
        self.local_references: list[tuple[str, str]] = []
        self.titles = 0
        self.main_ids = 0
        self.api_script_index = -1
        self.app_script_index = -1
        self.script_count = 0
        self.in_title = False
        self.in_row = False
        self.row_has_data_cell = False
        self.row_has_official_source = False
        self.row_number = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "main" and attributes.get("id") == "main":
            self.main_ids += 1
        if tag == "tr":
            self.in_row = True
            self.row_has_data_cell = False
            self.row_has_official_source = False
            self.row_number += 1
        if tag == "td" and self.in_row:
            self.row_has_data_cell = True
        if tag == "script":
            src = attributes.get("src") or ""
            if src:
                if src == "assets/api.js":
                    self.api_script_index = self.script_count
                elif src == "assets/app.js":
                    self.app_script_index = self.script_count
                self.script_count += 1
        for attr in ("href", "src"):
            value = attributes.get(attr)
            if value:
                self._check_reference(value, tag, attr)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "tr" and self.in_row:
            if self.row_has_data_cell and not self.row_has_official_source:
                ERRORS.append(f"{self.page.relative_to(ROOT)}: table row {self.row_number} has data but no official HTTPS source link")
            self.in_row = False

    def handle_data(self, data: str) -> None:
        if self.in_title and data.strip():
            self.titles += 1

    def _check_reference(self, value: str, tag: str, attr: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"}:
            if parsed.scheme != "https":
                ERRORS.append(f"{self.page.relative_to(ROOT)}: non-HTTPS external link: {value}")
            if parsed.hostname not in OFFICIAL_HOSTS:
                ERRORS.append(f"{self.page.relative_to(ROOT)}: external host is not allowlisted as an official source: {parsed.hostname}")
            if attr == "href" and self.in_row and parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS:
                self.row_has_official_source = True
            return
        if parsed.scheme or value.startswith("//") or value.startswith("data:"):
            ERRORS.append(f"{self.page.relative_to(ROOT)}: unsupported reference: {value}")
            return
        local_path = parsed.path
        if not local_path:
            return
        target = (self.page.parent / local_path).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            ERRORS.append(f"{self.page.relative_to(ROOT)}: local reference escapes repository: {value}")
            return
        if not target.is_file():
            ERRORS.append(f"{self.page.relative_to(ROOT)}: missing local {tag} {attr}: {value}")
        self.local_references.append((value, tag))


def main() -> int:
    if not HTML_FILES:
        print(f"ERROR: no HTML pages found under {SITE_ROOT.relative_to(ROOT)}")
        return 1

    for page in HTML_FILES:
        parser = SiteParser(page)
        try:
            parser.feed(page.read_text(encoding="utf-8"))
            parser.close()
        except Exception as exc:  # noqa: BLE001 - report malformed HTML/parser input.
            ERRORS.append(f"{page.relative_to(ROOT)}: HTML parser failed: {exc}")
            continue
        if not parser.titles:
            ERRORS.append(f"{page.relative_to(ROOT)}: missing document title")
        if parser.main_ids != 1:
            ERRORS.append(f"{page.relative_to(ROOT)}: expected exactly one <main id=\"main\">")
        if parser.api_script_index >= 0 and parser.app_script_index >= 0 and parser.api_script_index > parser.app_script_index:
            ERRORS.append(f"{page.relative_to(ROOT)}: assets/api.js must be loaded before assets/app.js")
        if page.name != "index.html" and parser.api_script_index < 0:
            ERRORS.append(f"{page.relative_to(ROOT)}: missing assets/api.js")

    app_js = SITE_ROOT / "assets" / "app.js"
    api_js = SITE_ROOT / "assets" / "api.js"
    for file in (app_js, api_js):
        if not file.is_file():
            ERRORS.append(f"Missing required client file: {file.relative_to(ROOT)}")
    if api_js.is_file():
        text = api_js.read_text(encoding="utf-8")
        if "external-api.kalshi.com/trade-api" in text or "api.elections.kalshi.com/trade-api" in text:
            ERRORS.append("assets/api.js must not call a production API host")
        if "BEGIN PRIVATE KEY" in text or "KALSHI-ACCESS-SIGNATURE" in text:
            ERRORS.append("assets/api.js must not contain signing keys or authenticated headers")

    if ERRORS:
        print("Site verification failed:")
        for error in ERRORS:
            print(f"- {error}")
        return 1

    print(f"PASS: checked {len(HTML_FILES)} HTML pages, local assets/links, official external hosts, script order, and source links for every static table row.")
    print("PASS: browser API client is demo-host-only and contains no signing key or authenticated header logic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
