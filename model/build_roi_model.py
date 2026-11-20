#!/usr/bin/env python3
"""Build the high-ROI screen definition + measured context for the alert chats.

The dashboard's second scrolling chat is meant to show "events that our model likes
as high ROI". No model was defined anywhere in this repo (board flag F-alert-01), so
the live code used an inline magic number. This script replaces that with a published,
reproducible screen plus the DEMO measurements a trader can actually stand behind, and
it states plainly when the data cannot support a claim.

Inputs (committed snapshots only - no network, no invented rows):
  data/latest/markets_settled.json  settled demo markets with `result`,
                                    `last_price_dollars`, `previous_price_dollars`,
                                    `settlement_value_dollars`, `settlement_ts`
  data/latest/candles.json          recorded candle windows (for the calibration
                                    feasibility check only)

Output: data/latest/roi_model.json  (consumed by assets/roi-model.js in the browser)

Every published number is recomputed from the input file's own records, and each record
carries its `source_url` back to the official demo API, so any row can be replayed.
Field semantics come from the official docs:
  Get Markets   https://docs.kalshi.com/api-reference/market/get-markets
  Market settle https://docs.kalshi.com/getting_started/market_settlement

Usage:
  python3 model/build_roi_model.py            # write data/latest/roi_model.json
  python3 model/build_roi_model.py --check    # fail if the committed file is stale
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTLED = ROOT / "data" / "latest" / "markets_settled.json"
CANDLES = ROOT / "data" / "latest" / "candles.json"
OUT = ROOT / "data" / "latest" / "roi_model.json"

SWING_THRESHOLD_DOLLARS = 0.10          # from the brief: >= $0.10 in either direction
MIN_BAND_N = 25                          # a band is reported only with n >= 25
TOPICS = ("gas", "elections", "culture", "crypto", "golf")

DOCS = {
    "get_markets": "https://docs.kalshi.com/api-reference/market/get-markets",
    "market_settlement": "https://docs.kalshi.com/getting_started/market_settlement",
    "get_event": "https://docs.kalshi.com/api-reference/events/get-event",
    "get_candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
    "demo_env": "https://docs.kalshi.com/getting_started/demo_env",
}


def dollars(x):
    """Parse a *_dollars string exactly; return None when absent or non-numeric."""
    if x is None or x == "":
        return None
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def group_stats(rows):
    """rows: list of (result_yes, entry_dollars). Mean ROI of buying YES at entry:
    a winning YES contract pays $1.00 (docs: market_settlement), so
    roi = 1/entry - 1 when it resolves yes, and -1 when it resolves no.
    Returns None for any figure that has no observations - never a guess."""
    n = len(rows)
    if n == 0:
        return {"n": 0, "p_yes": None, "mean_roi_buy_yes": None,
                "median_entry_dollars": None}
    yes = sum(1 for y, _ in rows if y)
    rois = [(1.0 / e - 1.0) if y else -1.0 for y, e in rows if e and e > 0]
    entries = sorted(e for _, e in rows if e is not None)
    med = None
    if entries:
        mid = len(entries) // 2
        med = entries[mid] if len(entries) % 2 else round((entries[mid - 1] + entries[mid]) / 2, 4)
    return {
        "n": n,
        "p_yes": round(yes / n, 4),
        "mean_roi_buy_yes": round(sum(rois) / len(rois), 4) if rois else None,
        "median_entry_dollars": med,
    }


def strip_small(st):
    """A rate computed from n < MIN_BAND_N is not published at all: the fields are
    emptied rather than shown, so nothing downstream can quote a 1-sample rate."""
    if st["n"] < MIN_BAND_N:
        st["p_yes"] = None
        st["mean_roi_buy_yes"] = None
        st["median_entry_dollars"] = None
    return st


def measure():
    payload = json.loads(SETTLED.read_text())
    markets = payload.get("markets", [])
    rows = []
    skipped = {"no_result": 0, "no_last": 0, "no_previous": 0}
    for m in markets:
        result = (m.get("result") or "").strip().lower()
        if result not in ("yes", "no"):
            skipped["no_result"] += 1
            continue
        last = dollars(m.get("last_price_dollars"))
        prev = dollars(m.get("previous_price_dollars"))
        if last is None:
            skipped["no_last"] += 1
            continue
        if prev is None:
            skipped["no_previous"] += 1
            continue
        rows.append({
            "ticker": m.get("ticker"),
            "topic": m.get("topic") or "",
            "yes": result == "yes",
            "last": last,
            "prev": prev,
            "change": round(last - prev, 4),
            "settlement_value": dollars(m.get("settlement_value_dollars")),
            "source_url": m.get("source_url") or "",
        })

    all_stats = group_stats([(r["yes"], r["last"]) for r in rows])

    swings = [r for r in rows if abs(r["change"]) >= SWING_THRESHOLD_DOLLARS]
    up = [r for r in swings if r["change"] > 0]
    down = [r for r in swings if r["change"] < 0]

    bands = []
    for lo, hi in [(0.0, 0.05), (0.05, 0.10), (0.10, 0.30), (0.30, 0.50),
                   (0.50, 0.70), (0.70, 0.90), (0.90, 1.01)]:
        grp = [r for r in up if lo <= r["prev"] < hi]
        st = strip_small(group_stats([(r["yes"], r["last"]) for r in grp]))
        st.update({"prior_band": [lo, hi], "reported": st["n"] >= MIN_BAND_N})
        bands.append(st)

    by_topic = []
    for t in TOPICS:
        grp = [r for r in rows if r["topic"] == t]
        sw = [r for r in grp if abs(r["change"]) >= SWING_THRESHOLD_DOLLARS]
        st = strip_small(group_stats([(r["yes"], r["last"]) for r in sw]))
        st.update({"topic": t,
                   "n_settled": len(grp),
                   "n_swing": len(sw),
                   "reported": st["n"] >= MIN_BAND_N})
        by_topic.append(st)
    other = [r for r in rows if r["topic"] not in TOPICS]
    other_sw = [r for r in other if abs(r["change"]) >= SWING_THRESHOLD_DOLLARS]

    # Feasibility of a real calibration: a screen needs a price path before the
    # settlement print, i.e. candles. Count markets that have both candles and a result.
    candle_markets = 0
    if CANDLES.exists():
        cj = json.loads(CANDLES.read_text())
        candle_markets = len(cj.get("by_market", {}))

    return {
        "n_records_in_file": len(markets),
        "n_usable": len(rows),
        "skipped": skipped,
        "retrieved_at": payload.get("retrieved_at"),
        "base_rate": all_stats,
        "swing_threshold_dollars": SWING_THRESHOLD_DOLLARS,
        "n_swing": len(swings),
        "n_up_swing": len(up),
        "n_down_swing": len(down),
        "up_swing": group_stats([(r["yes"], r["last"]) for r in up]),
        "down_swing": group_stats([(r["yes"], r["last"]) for r in down]),
        "prior_band_breakdown": bands,
        "by_topic": by_topic,
        "n_other_topic_settled": len(other),
        "n_other_topic_swing": len(other_sw),
        "n_up_below_5c": sum(1 for r in up if r["prev"] < 0.05),
        "candle_markets_available": candle_markets,
        "example_swing_rows": [
            {"ticker": r["ticker"], "topic": r["topic"], "prev": r["prev"],
             "last": r["last"], "change": r["change"],
             "result": "yes" if r["yes"] else "no",
             "settlement_value_dollars": r["settlement_value"],
             "source_url": r["source_url"]}
            for r in (up + down)[:10]
        ],
    }


SCREEN = {
    "id": "roi-screen-v1",
    "description": (
        "Deterministic screen for the second scrolling chat. A swing alert is admitted only "
        "when the price move is at least $0.10 in either direction (the brief's threshold) AND "
        "the move is at least 10% of the prior price, so a 1c->11c jump on a longshot is not "
        "treated the same as a 45c->55c jump on a coin-flip. No edge is claimed."
    ),
    "params": {
        "min_abs_swing_dollars": SWING_THRESHOLD_DOLLARS,
        "min_move_pct_of_prior": 0.10,
    },
    "status": "uncalibrated-thresholds",
    "status_note": (
        "The 10%-of-prior parameter is a stated choice, not a fitted value: the committed demo "
        "data cannot fit or validate it (see calibration_feasibility). The chat labels every "
        "admitted row with this status instead of implying a validated model."
    ),
}


def build():
    meas = measure()
    bands_ok = [b for b in meas["prior_band_breakdown"] if b["reported"]]
    doc = {
        "schema_version": 1,
        "generated_by": "model/build_roi_model.py",
        "inputs": {
            "settled_snapshot": {
                "path": "data/latest/markets_settled.json",
                "sha256": sha256(SETTLED),
                "retrieved_at": meas["retrieved_at"],
                "official_endpoint": "https://external-api.demo.kalshi.co/trade-api/v2/markets?status=settled",
            },
            "candle_snapshot": {
                "path": "data/latest/candles.json",
                "sha256": sha256(CANDLES) if CANDLES.exists() else None,
            },
        },
        "docs": DOCS,
        "screen": SCREEN,
        "measured": {
            "universe": {
                "n_records_in_file": meas["n_records_in_file"],
                "n_usable": meas["n_usable"],
                "skipped": meas["skipped"],
            },
            "base_rate_all_settled": meas["base_rate"],
            "swing_market_counts": {
                "swing_threshold_dollars": meas["swing_threshold_dollars"],
                "n_swing": meas["n_swing"],
                "n_up_swing": meas["n_up_swing"],
                "n_down_swing": meas["n_down_swing"],
                "share_of_settled": round(meas["n_swing"] / meas["n_usable"], 4)
                if meas["n_usable"] else None,
            },
            "up_swing": meas["up_swing"],
            "down_swing": meas["down_swing"],
            "up_swing_by_prior_band": meas["prior_band_breakdown"],
            "by_topic": meas["by_topic"],
            "n_other_topic_settled": meas["n_other_topic_settled"],
            "n_other_topic_swing": meas["n_other_topic_swing"],
        },
        "calibration_feasibility": {
            "candle_markets_available": meas["candle_markets_available"],
            "min_series_for_calibration": 30,
            "n_swing_with_prior_below_0_05": meas["n_up_below_5c"],
            "conclusion": (
                "insufficient: a >= $0.10 move has to be measured BEFORE the settlement print. "
                "The settled snapshot carries only `previous_price_dollars` and "
                "`last_price_dollars`, and "
                f"{meas['n_up_below_5c']} of its {meas['n_swing']} qualifying moves have a prior "
                "price below $0.05 - the field is not a tick-by-tick price path. Recorded candles "
                f"cover {meas['candle_markets_available']} markets, so no threshold can be fitted "
                "or back-tested on this data. Publishing a calibrated ROI number here would be a "
                "fabrication."
            ),
            "prior_band_recount": len(bands_ok),
        },
        "caveats": [
            "Demo environment only (mock funds). Kalshi warns demo prices and behaviour may not "
            "reflect real markets: " + DOCS["demo_env"],
            "Entry-price proxy is `last_price_dollars` on a settled market, i.e. the last trade "
            "before resolution; it is not an achievable fill for a live alert. Figures are "
            "descriptive of the snapshot, not a forecast.",
            "ROI of a winning YES contract uses the $1.00 payout per " + DOCS["market_settlement"] +
            "; fees are not modelled because the docs do not state a demo fee schedule "
            "(board flag ST-U1).",
            "Every rate above is a raw count on the snapshot; n < 25 in a band means that band is "
            "not reported as a rate at all (reported=false).",
            "The screen ranks events to look at. It is not investment advice and not a verified "
            "return model.",
        ],
        "examples": meas["example_swing_rows"],
    }
    return doc


def main():
    check = "--check" in sys.argv
    doc = build()
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if check:
        if not OUT.exists():
            print("CHECK FAIL: data/latest/roi_model.json is missing")
            return 1
        if OUT.read_text() != text:
            print("CHECK FAIL: committed roi_model.json differs from recomputed output")
            return 1
        print("CHECK OK: data/latest/roi_model.json matches model/build_roi_model.py")
        return 0
    OUT.write_text(text)
    print("wrote", OUT.relative_to(ROOT), f"({len(text)} bytes)")
    print(f"  usable settled markets : {doc['measured']['universe']['n_usable']}")
    print(f"  base P(yes)            : {doc['measured']['base_rate_all_settled']['p_yes']}")
    print(f"  swings >= $0.10        : {doc['measured']['swing_market_counts']['n_swing']}")
    print(f"  up-swing P(yes)        : {doc['measured']['up_swing']['p_yes']} "
          f"(n={doc['measured']['up_swing']['n']})")
    print(f"  calibratable bands     : {doc['calibration_feasibility']['prior_band_recount']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
