#!/usr/bin/env python3
"""
Copies the artifacts the site actually fetches into docs/data/.

Everything in data/ is collector output, but only a handful of files are read by the pages. The
raw outputs (live.json and live-prod.json are tens of megabytes of series, markets, order books and
candles) belong in the repository for the analysis step, not in the published site, where they would
add ~39 MB to every page load for nothing. This script keeps the list in one place so the workflow
and local development cannot disagree about it.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data"
DEST = ROOT / "docs" / "data"

# Every file fetched by docs/**/*.html.
PUBLISHED = [
    "dashboard.json",
    "expectancy.json",
    "meta.json",
    "order-rules.json",
    "portfolio.json",
    "resolutions-compact.json",
    "resolutions-summary.json",
]


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    missing = []
    copied = []
    for name in PUBLISHED:
        src = SRC / name
        if not src.exists():
            missing.append(name)
            continue
        shutil.copy2(src, DEST / name)
        copied.append((name, src.stat().st_size))

    # Remove anything published earlier that is no longer on the list, so a page cannot keep
    # working by accident against a file we stopped publishing.
    for stale in DEST.glob("*.json"):
        if stale.name not in PUBLISHED:
            stale.unlink()
            print(f"removed stale published artifact: {stale.name}")

    total = sum(size for _, size in copied)
    for name, size in copied:
        print(f"  {name:<28} {size/1024:9.1f} KB")
    print(f"published {len(copied)} artifact(s), {total/1024/1024:.2f} MB")

    if missing:
        # portfolio.json is legitimately absent when no demo credentials exist; the page handles it.
        optional = {"portfolio.json"}
        hard = [m for m in missing if m not in optional]
        for m in missing:
            print(f"  note: {m} not present" + (" (optional)" if m in optional else ""))
        if hard:
            print("FAIL: required artifacts missing: " + ", ".join(hard))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
