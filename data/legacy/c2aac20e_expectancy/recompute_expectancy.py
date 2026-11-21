#!/usr/bin/env python3
"""
Recompute the c2aac20e expectancy study on current main data.

Session d8f4577a (arena/d8f4577a-demo3), 2026-11-21.

Why this exists
---------------
`data/legacy/c2aac20e_expectancy/README.md` states the preserved figures are
UNVERIFIED on `main` and gives the re-verification path. The original input
(`data/resolutions-compact.json`) was only on the originating branch and is
not in the repo; the preserved `expectancy.json` cannot be re-derived from
this repo's data as-is. This script instead recomputes the same formulas over
`data/latest/markets_settled.json`, which is per-row sourced to the official
demo API (each row carries `source_url`).

Input
-----
`data/latest/markets_settled.json` — dict with key `markets`, a list of
finalized demo markets. Rows used here must have:
  * `result`                    in {"yes", "no"}  (anything else is excluded and counted)
  * `last_price_dollars`        parseable float in [0, 1]
  * `volume_fp`                 parseable float >= 0 (used for volume-weighted stats)
Every row keeps its `source_url`; the aggregate does not hide it.

Formulas (identical to the preserved study)
-------------------------------------------
  win_rate_yes             = yes / (yes + no)
  avg_yes_price            = mean(last_price_dollars) over rows in the group
  yes_expectancy           = win_rate_yes - avg_yes_price        ($ per contract)
  no_expectancy            = (1 - win_rate_yes) - (1 - avg_yes_price)  ($ per contract)
  volume_weighted_win_rate = sum(volume_fp where result == "yes") / sum(volume_fp)
                             (definition chosen here; the preserved file's internal
                              definition is not recoverable from this repo — see
                              VERIFICATION.md)
  contracts_traded         = sum(volume_fp)
All expectancies are per $1 contract, fees EXCLUDED.

Buckets (lower exclusive, upper inclusive, after the first)
-----------------------------------------------------------
  <=0.10 : p <= 0.10
  0.10-0.20 : 0.10 < p <= 0.20
  0.20-0.40 : 0.20 < p <= 0.40
  0.40-0.60 : 0.40 < p <= 0.60
  0.60-0.80 : 0.60 < p <= 0.80
  0.80-0.90 : 0.80 < p <= 0.90
  0.90-0.99 : 0.90 < p <= 0.99
  >0.99     : p > 0.99        (the preserved file's ">=0.99" mixed a boundary here;
                               see VERIFICATION.md)

Bands (explicit, documented — NOT derived from the buckets)
------------------------------------------------------------
  favourite_band_0_80_to_0_99 : 0.80 <= p <= 0.99
  longshot_band_0_01_to_0_20  : 0.01 <= p <= 0.20
The preserved file's band row counts (n=929 favourite / n=1,820 longshot) are
not the union of its preserved bucket counts (323 / 10,621); the internal band
definition was not recoverable. These bands use the explicit ranges in their
names. Flagged as irregularity F-D8F-01.

Usage
-----
  python3 data/legacy/c2aac20e_expectancy/recompute_expectancy.py \
      [--input data/latest/markets_settled.json] [--output <path>]

Stdlib only. Deterministic given the same input file.
"""

import argparse
import json
import math
import sys
from collections import Counter

BUCKETS = [
    ("<=0.10", None, 0.10),
    ("0.10-0.20", 0.10, 0.20),
    ("0.20-0.40", 0.20, 0.40),
    ("0.40-0.60", 0.40, 0.60),
    ("0.60-0.80", 0.60, 0.80),
    ("0.80-0.90", 0.80, 0.90),
    ("0.90-0.99", 0.90, 0.99),
    (">0.99", 0.99, None),
]

FAV_LO, FAV_HI = 0.80, 0.99
LONG_LO, LONG_HI = 0.01, 0.20

# Demo-exchange synthetic exchange-test series prefixes, exactly as used elsewhere
# in this repo (scripts/build_live_data.py SYNTHETIC_SERIES; see also irregularity
# I-15 and the "demo test market" badge in assets/alerts.js). Markets in these
# series are synthetic and must not be read as real-world price discovery.
SYNTHETIC_SERIES = ("KXDEMOFUTHOURLY", "KXQUICKSETTLE", "KXMAXSHARDINGTEST",
                    "KXRFTEST", "KXTEST", "KXDEMO")


def is_synthetic(series_ticker):
    st = (series_ticker or "").upper()
    return any(st.startswith(p) for p in SYNTHETIC_SERIES)


def load_rows(path):
    with open(path) as fh:
        blob = json.load(fh)
    markets = blob.get("markets")
    if not isinstance(markets, list):
        raise SystemExit(f"{path}: expected a dict with a 'markets' list")
    return blob, markets


def clean(markets):
    rows, excluded = [], Counter()
    for m in markets:
        result = m.get("result")
        if result not in ("yes", "no"):
            excluded[f"result_{result!r}"] += 1
            continue
        try:
            price = float(m["last_price_dollars"])
        except (TypeError, ValueError, KeyError):
            excluded["price_unparseable"] += 1
            continue
        if not (0.0 <= price <= 1.0):
            excluded["price_out_of_range"] += 1
            continue
        try:
            volume = float(m.get("volume_fp") or 0.0)
        except (TypeError, ValueError):
            excluded["volume_unparseable"] += 1
            continue
        if volume < 0.0:
            excluded["volume_negative"] += 1
            continue
        rows.append({
            "ticker": m.get("ticker"),
            "topic": m.get("topic") or "unknown",
            "series_ticker": m.get("series_ticker"),
            "result": result,
            "price": price,
            "volume": volume,
            "source_url": m.get("source_url"),
        })
    return rows, excluded


def stats(rows):
    n = len(rows)
    if n == 0:
        return None
    yes = sum(1 for r in rows if r["result"] == "yes")
    no = n - yes
    win = yes / n
    avg = sum(r["price"] for r in rows) / n
    tot_vol = sum(r["volume"] for r in rows)
    yes_vol = sum(r["volume"] for r in rows if r["result"] == "yes")
    return {
        "n": n,
        "yes": yes,
        "no": no,
        "win_rate_yes": round(win, 4),
        "avg_yes_price": round(avg, 4),
        "yes_expectancy_per_contract": round(win - avg, 4),
        "no_expectancy_per_contract": round((1 - win) - (1 - avg), 4),
        "volume_weighted_win_rate": round(yes_vol / tot_vol, 4) if tot_vol > 0 else None,
        "contracts_traded": round(tot_vol, 2),
    }


def bucketize(rows):
    out = []
    for label, lo, hi in BUCKETS:
        members = [
            r for r in rows
            if (lo is None or r["price"] > lo) and (hi is None or r["price"] <= hi)
        ]
        s = stats(members)
        if s is None:
            s = {"n": 0, "yes": 0, "no": 0}
        s = {"bucket": label, **s}
        out.append(s)
    return out


def band(rows, lo, hi):
    members = [r for r in rows if lo <= r["price"] <= hi]
    s = stats(members)
    if s is None:
        s = {"n": 0, "yes": 0, "no": 0}
    return {"definition": f"{lo} <= last_price_dollars <= {hi}", **s}


def per_topic(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r["topic"], []).append(r)
    return {t: stats(members) for t, members in sorted(groups.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/latest/markets_settled.json")
    ap.add_argument("--output", default="data/legacy/c2aac20e_expectancy/expectancy.recomputed.json")
    args = ap.parse_args()

    blob, markets = load_rows(args.input)
    rows, excluded = clean(markets)

    real_rows = [r for r in rows if not is_synthetic(r.get("series_ticker"))]
    synthetic_rows = [r for r in rows if is_synthetic(r.get("series_ticker"))]

    def block(rs):
        return {
            "rows_usable": len(rs),
            "buckets": bucketize(rs),
            "favourite_band_0_80_to_0_99": band(rs, FAV_LO, FAV_HI),
            "longshot_band_0_01_to_0_20": band(rs, LONG_LO, LONG_HI),
            "all_rows": stats(rs),
            "per_topic": per_topic(rs),
        }

    out = {
        "title": "Expectancy, recomputed on current main data (session d8f4577a)",
        "formula": "yes_expectancy = win_rate_yes - avg_yes_price; no_expectancy = (1 - win_rate_yes) - (1 - avg_yes_price). Both in dollars per $1 contract, fees excluded.",
        "input_file": args.input,
        "input_retrieved_at": blob.get("retrieved_at"),
        "input_count_field": blob.get("count"),
        "rows_usable": len(rows),
        "rows_excluded": dict(excluded),
        "synthetic_series_prefixes": list(SYNTHETIC_SERIES),
        "synthetic_rows_included_in_totals": len(synthetic_rows),
        "buckets": bucketize(rows),
        "favourite_band_0_80_to_0_99": band(rows, FAV_LO, FAV_HI),
        "longshot_band_0_01_to_0_20": band(rows, LONG_LO, LONG_HI),
        "all_rows": stats(rows),
        "per_topic": per_topic(rows),
        "synthetic_excluded": block(real_rows),
        "buckets_excluded_note": (
            "synthetic_excluded re-runs the identical formulas over the rows whose "
            "series_ticker does NOT match the repo's SYNTHETIC_SERIES prefixes. The "
            "all_rows figures include those synthetic markets and are dominated by "
            "them; quote synthetic_excluded for anything strategy-related."
        ),
        "caveats": [
            "last_price_dollars is the last traded price, not the average price paid by holders.",
            "Fees are excluded; Kalshi series carry fee_type (quadratic/flat) and a fee_multiplier.",
            "Only markets in the collector's settled-market sweep (data/latest/markets_settled.json) are counted; coverage is capped and not exhaustive.",
            "market.result reflects the settlement outcome (yes/no); scalar/other results are excluded and counted above.",
            "Demo-environment data; demo prices may not reflect real markets.",
            "Historical expectancy does not predict future results.",
            "volume_weighted_win_rate is defined here as sum(volume_fp where result == 'yes') / sum(volume_fp); the preserved file's internal definition is not recoverable from this repo.",
        ],
        "sources": [
            "data/latest/markets_settled.json (per-row source_url → official demo API, e.g. https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=<TICKER>)",
            "https://docs.kalshi.com/getting_started/market_settlement (settlement semantics: market.result yes/no)",
            "https://docs.kalshi.com/getting_started/demo_env (demo data caveat)",
        ],
    }

    with open(args.output, "w") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")

    s = out["all_rows"]
    print(f"rows_usable={out['rows_usable']} excluded={out['rows_excluded']} "
          f"synthetic={out['synthetic_rows_included_in_totals']}")
    print(f"all_rows: n={s['n']} win_rate_yes={s['win_rate_yes']} avg={s['avg_yes_price']} "
          f"yes_exp={s['yes_expectancy_per_contract']} no_exp={s['no_expectancy_per_contract']}")
    se = out["synthetic_excluded"]
    print(f"synthetic_excluded: rows={se['rows_usable']}")
    print(f"  all_rows: win={se['all_rows']['win_rate_yes']} avg={se['all_rows']['avg_yes_price']} "
          f"yes_exp={se['all_rows']['yes_expectancy_per_contract']}")
    fav = se["favourite_band_0_80_to_0_99"]
    lng = se["longshot_band_0_01_to_0_20"]
    print(f"  favourite 0.80-0.99: n={fav['n']} win={fav.get('win_rate_yes')} yes_exp={fav.get('yes_expectancy_per_contract')}")
    print(f"  longshot  0.01-0.20: n={lng['n']} win={lng.get('win_rate_yes')} yes_exp={lng.get('yes_expectancy_per_contract')}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
