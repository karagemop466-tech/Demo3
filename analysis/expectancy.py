#!/usr/bin/env python3
"""
Resolution study: what actually happened when Kalshi markets settled, bucketed by the price the
side was trading at. This is the evidence that decides whether a strategy is worth running.

Method (fully reproducible from the artifacts):
  1. Take every settled row in data/resolutions-compact.json that has BOTH a result (yes/no) and
     a last traded YES price (last_price_dollars). Rows missing either are excluded and counted.
  2. Bucket by last YES price: <=0.10, 0.10-0.20, 0.20-0.40, 0.40-0.60, 0.60-0.80, 0.80-0.90,
     0.90-0.99, >=0.99.
  3. For each bucket compute:
        n, yes_count, no_count, win_rate
        avg_yes_price  -> buying YES at that price pays 1.00 on yes, 0.00 on no
        yes_expectancy_per_contract = win_rate * 1.00 - avg_yes_price
        no_expectancy_per_contract  = (1 - win_rate) * 1.00 - (1 - avg_yes_price)
  4. Optionally weight by traded volume to show where the money actually is.

Caveats stated on the site, not hidden here:
  * `last_price_dollars` is the last trade, not the average price paid by holders.
  * Fees are excluded (fee_type is quadratic per series; see the official fee schedule).
  * Survivorship: only markets that settled within the collection window appear.
  * This is historical, not predictive.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

BUCKETS = [
    (0.00, 0.10, "<=0.10"),
    (0.10, 0.20, "0.10-0.20"),
    (0.20, 0.40, "0.20-0.40"),
    (0.40, 0.60, "0.40-0.60"),
    (0.60, 0.80, "0.60-0.80"),
    (0.80, 0.90, "0.80-0.90"),
    (0.90, 0.99, "0.90-0.99"),
    (0.99, 1.01, ">=0.99"),
]


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def bucket_of(price: float) -> str:
    for lo, hi, label in BUCKETS:
        if lo <= price < hi:
            return label
    return ">=0.99"


def study(rows: list[dict]) -> dict:
    usable = []
    excluded = {"no_result": 0, "no_price": 0, "scalar_result": 0}
    for r in rows:
        result = (r.get("result") or "").strip().lower()
        price = num(r.get("last_price_dollars"))
        if result == "scalar":
            excluded["scalar_result"] += 1
            continue
        if result not in ("yes", "no"):
            excluded["no_result"] += 1
            continue
        if price is None:
            excluded["no_price"] += 1
            continue
        usable.append({"price": price, "yes": result == "yes",
                       "volume": num(r.get("volume_fp")) or 0.0,
                       "topic": (r.get("topics") or ["unmapped"])[0]})

    out_buckets = []
    for lo, hi, label in BUCKETS:
        sub = [u for u in usable if lo <= u["price"] < hi]
        if not sub:
            out_buckets.append({"bucket": label, "n": 0})
            continue
        wins = sum(1 for u in sub if u["yes"])
        n = len(sub)
        win_rate = wins / n
        avg_price = statistics.fmean(u["price"] for u in sub)
        volume = sum(u["volume"] for u in sub)
        out_buckets.append({
            "bucket": label,
            "n": n,
            "yes": wins,
            "no": n - wins,
            "win_rate_yes": round(win_rate, 4),
            "avg_yes_price": round(avg_price, 4),
            "yes_expectancy_per_contract": round(win_rate - avg_price, 4),
            "no_expectancy_per_contract": round((1 - win_rate) - (1 - avg_price), 4),
            "volume_weighted_win_rate": round(
                sum(u["volume"] for u in sub if u["yes"]) / volume, 4) if volume else None,
            "contracts_traded": round(volume, 2),
        })

    def agg(pred):
        sub = [u for u in usable if pred(u["price"])]
        if not sub:
            return None
        wins = sum(1 for u in sub if u["yes"])
        n = len(sub)
        avg = statistics.fmean(u["price"] for u in sub)
        return {
            "n": n,
            "win_rate_yes": round(wins / n, 4),
            "avg_yes_price": round(avg, 4),
            "yes_expectancy_per_contract": round(wins / n - avg, 4),
            "no_expectancy_per_contract": round((1 - wins / n) - (1 - avg), 4),
        }

    per_topic = {}
    for topic in sorted({u["topic"] for u in usable}):
        per_topic[topic] = agg(lambda p, t=topic: any(u["topic"] == t and u["price"] == p for u in usable))

    return {
        "formula": "yes_expectancy = win_rate_yes - avg_yes_price; "
                   "no_expectancy = (1 - win_rate_yes) - (1 - avg_yes_price). "
                   "Both in dollars per contract, fees excluded.",
        "input": "data/resolutions-compact.json (settled markets with a result and a last price)",
        "rows_usable": len(usable),
        "rows_excluded": excluded,
        "buckets": out_buckets,
        "favourite_band_0_80_to_0_99": agg(lambda p: 0.80 <= p <= 0.99),
        "longshot_band_0_01_to_0_20": agg(lambda p: 0.01 <= p <= 0.20),
        "all_rows": agg(lambda p: True),
        "caveats": [
            "last_price_dollars is the last traded price, not the average price paid by holders.",
            "Fees are excluded; Kalshi series carry fee_type (quadratic/flat) and a fee_multiplier.",
            "Only markets that settled inside the collection window are counted.",
            "Historical expectancy does not predict future results.",
        ],
    }


def main() -> int:
    path = DATA / "resolutions-compact.json"
    if not path.exists():
        print("resolutions-compact.json missing")
        return 1
    rows = json.loads(path.read_text(encoding="utf-8")).get("rows") or []
    result = study(rows)
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (DATA / "expectancy.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({b["bucket"]: {k: b.get(k) for k in ("n", "win_rate_yes", "avg_yes_price")}
                      for b in result["buckets"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
