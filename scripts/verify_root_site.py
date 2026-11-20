#!/usr/bin/env python3
"""Verify the canonical root site (session arena-3a22fb0f integration checks):

  1. every internal link on every root page resolves to a tracked file;
  2. every generated table row has a source cell containing an <a class="src">/
     official link, or the 'unverified' flag pill (never a silent blank);
  3. all page scripts pass `node --check` and scripts pass `py_compile`;
  4. the pages reference only the canonical assets (no stale engine paths).

Exit code 0 = all checks pass.
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FAIL = []


def fail(msg):
    FAIL.append(msg)
    print("FAIL:", msg)


PAGES = [
    "index.html", "dashboard.html", "alerts.html", "portfolio.html", "trades.html",
    "gas-prices.html", "elections.html", "culture.html", "crypto.html", "golf.html",
    "questions.html", "suggestions.html", "flagged.html", "sources.html",
    "repo-review.html", "methodology.html", "api-reference.html",
    "requirements.html", "model.html",
]


def main():
    # 1. internal link crawl
    for page in PAGES:
        p = ROOT / page
        if not p.exists():
            fail(f"missing page {page}")
            continue
        html = p.read_text()
        for href in re.findall(r'href="([^"]+)"', html):
            if href.startswith(("http", "mailto:", "#")):
                continue
            target = href.split("#")[0].split("?")[0]
            if not target:
                continue
            if not (ROOT / target).exists():
                fail(f"{page}: broken internal link -> {href}")
        # 4. canonical assets only
        for stale in ("assets/css/", "assets/js/", "assets/vendor/"):
            if stale in html:
                fail(f"{page}: references stale path {stale}")

    # 2. per-row source discipline on generated pages
    for page in PAGES:
        p = ROOT / page
        if not p.exists():
            continue
        html = p.read_text()
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if not tds:
                continue  # header row
            joined = " ".join(tds)
            has_src = ('class="src"' in joined or 'class=\'src\'' in joined or
                       re.search(r'<a [^>]*href="https?://', joined) or
                       "unverified" in joined)
            if not has_src:
                text = re.sub(r"<[^>]+>", " ", tds[0]).strip()[:60]
                fail(f"{page}: table row without source link or unverified flag: {text!r}")

    # 3. syntax checks
    # assets/alerts.js is session a7ce6f14's dashboard chat engine; assets/alert-console.js +
    # assets/swing-core.js are session 5ab18dc3's alerts.html console and the rule it shares with
    # the CI backtest. Both ships exist (see COORDINATION.md); both must keep parsing.
    for js in ["assets/app.js", "assets/dashboard.js", "assets/trade.js", "assets/site.js",
               "assets/alerts.js", "assets/strategy.js", "assets/data-tracking.js",
               "assets/swing-core.js", "assets/alert-console.js"]:
        r = subprocess.run(["node", "--check", js], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"node --check {js}: {r.stderr.strip()[:200]}")
    for py in ROOT.glob("scripts/*.py"):
        r = subprocess.run([sys.executable, "-m", "py_compile", str(py)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"py_compile {py.name}: {r.stderr.strip()[:200]}")

    print(f"\nverify_root_site: {len(FAIL)} failures")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
