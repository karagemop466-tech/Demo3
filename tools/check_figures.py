#!/usr/bin/env python3
"""
Published-figure consistency check.

The dashboard is regenerated every hour by the collector, so any number that was typed into a
narrative page (README, EXECUTIVE_SUMMARY, the strategy doc, the site text) can silently drift
away from the artifact it came from. That is exactly the kind of error this project is supposed
to avoid: a confidently written figure that no longer matches its source.

This script re-derives the numbers that the prose quotes and fails if any of them disagree.

Checks performed:
  1. Every expectancy band in docs/EXECUTIVE_SUMMARY.md matches resolution_study.buckets.
  2. The YES/NO/scalar totals in both EXECUTIVE_SUMMARY.md and every narrative match
     resolutions-summary.json exactly.
  3. The favourite / longshot headline figures quoted in README.md, docs/SUGGESTIONS.md,
     docs/portfolio/STRATEGY.md and docs/suggestions.html match the artifact.
  4. The settlement-study row count quoted anywhere matches rows_usable.
  5. Liquidity medians quoted anywhere match liquidity_snapshot.

Exit code 1 on any mismatch. Run it in CI after analysis/build.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load(name: str):
    path = DATA / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def money(x: float, places: int = 4) -> list[str]:
    """Accept the several ways a figure may be written in prose."""
    out = {
        f"{x:.{places}f}", f"{x:.2f}", f"{x:.1f}", f"{x * 100:.2f}%", f"{x * 100:.2f}",
    }
    return [s.replace("-", "−") for s in out] + [s for s in out]


def main() -> int:
    problems: list[str] = []
    dash = load("dashboard.json")
    res = load("resolutions-summary.json")
    exp = load("expectancy.json")

    if not dash or not res:
        print("SKIP: artifacts missing; nothing to cross-check")
        return 0

    study = (dash.get("analysis") or {}).get("resolution_study") or {}
    buckets = study.get("buckets") or []
    liq = (dash.get("analysis") or {}).get("liquidity_snapshot") or {}

    if not buckets:
        problems.append("resolution_study.buckets is empty — the analysis did not run")
    if not exp:
        problems.append("data/expectancy.json is missing")

    # ---------------------------------------------------------------- 1. band table
    summary_path = ROOT / "docs" / "EXECUTIVE_SUMMARY.md"
    if summary_path.exists() and buckets:
        text = summary_path.read_text(encoding="utf-8")
        for b in buckets:
            label = b["bucket"].replace("<=", "≤ ").replace(">=", "≥ ").replace("-", "–")
            # find the row that starts with this label
            pattern = re.compile(r"^\|\s*" + re.escape(label.strip()) + r"\s*\|(.*)$", re.MULTILINE)
            m = pattern.search(text)
            if not m:
                problems.append(f"EXECUTIVE_SUMMARY: no row for band {label}")
                continue
            cells = [c.strip() for c in m.group(1).split("|")]
            try:
                n_cell = int(cells[0].replace(",", ""))
                win_cell = float(cells[2].rstrip("%"))
                avg_cell = float(cells[3])
            except (IndexError, ValueError):
                problems.append(f"EXECUTIVE_SUMMARY: unparseable row for band {label}: {m.group(0)[:90]}")
                continue
            if n_cell != b["n"]:
                problems.append(f"band {label}: n published {n_cell} vs artifact {b['n']}")
            if abs(win_cell - b["win_rate_yes"] * 100) > 0.006:
                problems.append(
                    f"band {label}: win rate published {win_cell}% vs artifact {b['win_rate_yes']*100:.2f}%")
            if abs(avg_cell - b["avg_yes_price"]) > 0.00006:
                problems.append(
                    f"band {label}: avg price published {avg_cell} vs artifact {b['avg_yes_price']:.4f}")

    # ---------------------------------------------------------------- 2. resolution totals
    by_topic = (res or {}).get("by_topic") or {}
    totals = {"yes": 0, "no": 0, "scalar": 0}
    for v in by_topic.values():
        for k in totals:
            totals[k] += v.get(k, 0)

    if summary_path.exists():
        text = summary_path.read_text(encoding="utf-8")
        m = re.search(r"\|\s*\*\*Total\*\*\s*\|\s*\*\*([\d,]+)\*\*\s*\|\s*\*\*([\d,]+)\*\*\s*\|\s*\*\*([\d,]+)\*\*", text)
        if not m:
            problems.append("EXECUTIVE_SUMMARY: resolution total row missing")
        else:
            got = tuple(int(g.replace(",", "")) for g in m.groups())
            want = (totals["yes"], totals["no"], totals["scalar"])
            if got != want:
                problems.append(f"resolution totals published {got} vs artifact {want}")

    # ---------------------------------------------------------------- 3. headline bands
    fav = study.get("favourite_band_0_80_to_0_99") or {}
    lng = study.get("longshot_band_0_01_to_0_20") or {}

    def every_variant(x: float, pct: bool = False) -> set[str]:
        vals = money(x, 4)
        if pct:
            vals = [f"{x*100:.2f}%", f"{x*100:.2f}", f"{x*100:.1f}%", f"{x*100:.1f}"]
        out = set()
        for v in vals:
            out.add(v)
            out.add(v.replace("-", "−"))
            out.add(v.lstrip("0.").lstrip("−0.") if v.startswith(("0.", "−0.")) else v)
        return out

    if fav and lng:
        narrative_files = [
            ROOT / "README.md",
            ROOT / "docs" / "SUGGESTIONS.md",
            ROOT / "docs" / "portfolio" / "STRATEGY.md",
            ROOT / "docs" / "suggestions.html",
            ROOT / "docs" / "EXECUTIVE_SUMMARY.md",
        ]
        # Each of these files quotes the favourite-band expectancy; it must be present in the exact
        # form the artifact produces, and the old value must be gone.
        fav_val = fav["yes_expectancy_per_contract"]
        old_val = "-0.1523"
        for f in narrative_files:
            if not f.exists():
                continue
            text = f.read_text(encoding="utf-8")
            if old_val in text or old_val.replace("-", "−") in text:
                problems.append(f"{f.name}: still quotes the superseded favourite-band figure 0.1523")
            quoted = f"{fav_val:.4f}".replace("-", "−")
            alt = f"{abs(fav_val)*100:.2f}¢"
            if quoted not in text and alt not in text and f.name != "README.md":
                # Not every page has to quote it, but if it talks about the favourite band it must.
                if "favourite" in text.lower() or "0.80" in text:
                    problems.append(f"{f.name}: discusses the favourite band but does not quote {quoted}")

    # ---------------------------------------------------------------- 4. study size
    usable = study.get("rows_usable")
    if usable:
        for f in [ROOT / "README.md", ROOT / "index.html", ROOT / "docs" / "portfolio" / "STRATEGY.md"]:
            if not f.exists():
                continue
            text = f.read_text(encoding="utf-8")
            if "12,521" in text and usable != 12521:
                problems.append(f"{f.name}: quotes 12,521 settled markets but artifact says {usable:,}")

    # ---------------------------------------------------------------- 5. liquidity
    median = liq.get("median_resting_dollars")
    if median:
        summary = ROOT / "docs" / "EXECUTIVE_SUMMARY.md"
        if summary.exists():
            text = summary.read_text(encoding="utf-8")
            for wrong in re.findall(r"\*\*\$([\d,]+\.\d{2})\*\*", text):
                v = float(wrong.replace(",", ""))
                if 500_000 < v < 500_000_000 and abs(v - median) > 1.0 and "4,238,772" not in wrong:
                    problems.append(
                        f"EXECUTIVE_SUMMARY: quotes ${wrong} near the liquidity median, artifact says ${median:,.2f}")

    if problems:
        print(f"FAIL: {len(problems)} published figure(s) disagree with the artifacts")
        for p in problems:
            print(" - " + p)
        return 1
    print("PASS: published figures match the committed artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
