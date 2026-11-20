"""
build_site.py — assemble the deployable static site.

`site/` holds hand-written pages and assets; `data/` holds machine-generated evidence.
The site must load its data over HTTP, so the build copies the data files into
`site/data/` (and nothing else) instead of duplicating them in git.

  python3 scripts/build_site.py            # -> site/ is complete, .nojekyll written
  python3 scripts/build_site.py --check     # fail if site/data is stale vs data/
"""

from __future__ import annotations

import argparse
import hashlib
import re
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "site")
DEST = os.path.join(SITE, "data")

# Only these are published; raw captures and the ledger stay in the repo, not on the site.
# NOTE: live_snapshot.json is NOT copied from data/ — it is assembled into site/data/ by
# scripts/publish_snapshot.py, which is also what writes its provenance blocks.
PUBLISH = ["snapshot.json", "topics.json", "tape_analysis.json",
           "resolutions.json", "analysis.json", "analysis_tape.json",
           "portfolio_ledger.json", "orders.json", "questions.json", "sources.json"]


def digest(path: str) -> str:
    if not os.path.exists(path):
        return "missing"
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    os.makedirs(DEST, exist_ok=True)
    pub = os.path.join(DEST, "live_snapshot.json")
    if not os.path.exists(pub):
        print("site/data/live_snapshot.json is missing — run scripts/publish_snapshot.py first", file=sys.stderr)
        return 1
    copied, skipped, stale = 0, 0, []
    for name in PUBLISH:
        src = os.path.join(DATA, name)
        dst = os.path.join(DEST, name)
        if not os.path.exists(src):
            skipped += 1
            continue
        with open(src) as fh:
            json.load(fh)                      # a broken data file must never reach Pages
        if args.check:
            if digest(src) != digest(dst):
                stale.append(name)
            continue
        shutil.copyfile(src, dst)
        copied += 1

    # validate that every page's internal links resolve to a real file
    pages = sorted(f for f in os.listdir(SITE) if f.endswith(".html"))
    missing = []
    for page in pages:
        html = open(os.path.join(SITE, page)).read()
        # strip <script> blocks: JS template strings contain href= fragments that are not real links
        html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
        for token in ("href=\"", "src=\""):
            i = 0
            while True:
                i = html.find(token, i)
                if i < 0:
                    break
                start = i + len(token)
                end = html.find("\"", start)
                if end < 0:
                    break
                ref = html[start:end]
                i = end
                if ref.startswith(("http", "mailto:", "#", "data:")) or "{" in ref:
                    continue
                target = os.path.normpath(os.path.join(SITE, ref.split("#")[0].split("?")[0]))
                if not os.path.exists(target):
                    missing.append((page, ref))

    nojekyll = os.path.join(SITE, ".nojekyll")
    if not args.check and not os.path.exists(nojekyll):
        open(nojekyll, "w").close()

    if args.check:
        if stale:
            print("STALE site/data files: " + ", ".join(stale), file=sys.stderr)
        if missing:
            print("BROKEN internal links:", file=sys.stderr)
            for m in missing:
                print("  " + m[0] + " -> " + m[1], file=sys.stderr)
        if stale or missing:
            return 1
        print(f"build check ok · {len(pages)} pages · data fresh · no broken links")
        return 0

    print(f"build ok · {copied} data files copied · {skipped} absent (optional) · {len(pages)} pages · "
          f"no .nojekyll problems · {len(missing)} broken links")
    for m in missing:
        print("  BROKEN " + m[0] + " -> " + m[1], file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
