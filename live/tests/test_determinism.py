#!/usr/bin/env python3
"""Determinism test: rebuilding the desk from the committed snapshots must
reproduce the committed simulated trades, portfolios and alerts exactly
(timestamps of the build itself excluded).

Run: python3 live/tests/test_determinism.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "live" / "data"
KEYS = ["markets.json", "alerts.json", "alerts_roi.json", "trades.json",
        "portfolio.json", "resolutions.json"]


def strip_time(obj):
    """Drop build timestamps only; keep every derived number."""
    if isinstance(obj, dict):
        return {k: strip_time(v) for k, v in obj.items()
                if k not in ("generated_at", "retrieved_at")}
    if isinstance(obj, list):
        return [strip_time(v) for v in obj]
    return obj


def main():
    before = {}
    for name in KEYS:
        p = DATA / name
        if not p.exists():
            print(f"missing {name} — run scripts/build_live_data.py first")
            return 2
        before[name] = strip_time(json.loads(p.read_text()))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_live_data.py")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("rebuild failed:", r.stderr[-800:])
        return 1
    failures = 0
    for name in KEYS:
        after = strip_time(json.loads((DATA / name).read_text()))
        if after != before[name]:
            failures += 1
            print(f"FAIL {name}: rebuild is not deterministic")
            a, b = before[name], after
            for key in (a if isinstance(a, dict) else {}):
                if a.get(key) != (b.get(key) if isinstance(b, dict) else None):
                    print(f"  differs at key {key!r}")
    # threshold invariant: no alert below $0.10
    alerts = json.loads((DATA / "alerts.json").read_text())["alerts"]
    below = [a["id"] for a in alerts if abs(a["delta"]) < 0.10 - 1e-9]
    if below:
        failures += 1
        print(f"FAIL {len(below)} alerts below $0.10, e.g. {below[:3]}")
    # every simulated trade carries a source and the simulated label
    trades = json.loads((DATA / "trades.json").read_text())["trades"]
    bad = [t["id"] for t in trades if t.get("mode") != "simulated" or not t.get("market_url")]
    if bad:
        failures += 1
        print(f"FAIL {len(bad)} trades missing the simulated label or source")
    print(f"{'FAIL' if failures else 'PASS'} — {len(KEYS)} files, "
          f"{len(alerts)} alerts, {len(trades)} simulated trades checked")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
