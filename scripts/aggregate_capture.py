"""
aggregate_capture.py — machine-derive the tape aggregates published by the site.

Why this exists: every dollar-volume figure on the dashboard is DERIVED (Kalshi has no
dollar-volume field), so it must be computed by code from the raw capture, never typed by hand.

  in   data/raw/trades-capture.json   verbatim trade records copied from
                                      GET /markets/trades (two captures, 2026-11-20)
         data/topics.json             topic -> official category/tag selectors
         data/live_snapshot.json      verified series universe (authoritative membership)
  out  data/tape_analysis.json        per-event + per-topic aggregates, with the formula
        and the exact source URL of the capture
  and: data/live_snapshot.json         ranked_events[] aggregates re-written from the computation

Run:  python3 scripts/aggregate_capture.py [--write]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CAPTURE = os.path.join(DATA, "raw", "trades-capture.json")
SNAPSHOT = os.path.join(DATA, "live_snapshot.json")
TOPICS = os.path.join(DATA, "topics.json")
OUT = os.path.join(DATA, "tape_analysis.json")

SOURCE_URL = "https://external-api.demo.kalshi.co/trade-api/v2/markets/trades?limit=120"
SOURCE_URL_2 = "https://external-api.demo.kalshi.co/trade-api/v2/markets/trades?limit=2"
FORMULA = ("dollar_volume = SUM over trades of count_fp x (yes_price_dollars if "
           "taker_outcome_side=='yes' else no_price_dollars). Fields per "
           "https://docs.kalshi.com/api-reference/market/get-trades.md ; Kalshi publishes no "
           "dollar-volume field, so this figure is derived, not read.")


def num(v):
    if v in (None, ""):
        return None
    f = float(v)
    return f if f == f else None


def series_of(ticker: str) -> str:
    return ticker.split("-")[0]


def event_of(ticker: str) -> str:
    parts = ticker.split("-")
    return "-".join(parts[:-1]) if len(parts) >= 3 else ticker


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="patch data/live_snapshot.json too")
    args = ap.parse_args(argv)

    trades = load(CAPTURE)
    if not trades:
        print(f"missing capture: {CAPTURE}", file=sys.stderr)
        return 1
    snap = load(SNAPSHOT, {}) or {}
    topics_cfg = load(TOPICS, {}) or {}

    # membership: authoritative first (series rows read from /series or /events), prefix fallback second
    authoritative = {}
    for row in snap.get("series_universe", []):
        authoritative[row["series_ticker"]] = row
    provisional = {}
    for topic in topics_cfg.get("topics", []):
        for pref in topic.get("ticker_prefixes", []):
            provisional.setdefault(pref, topic["id"])

    events: dict[str, dict] = defaultdict(lambda: {
        "event_ticker": "", "series": "", "topic": None, "classified_by": None, "provisional": None,
        "dollar_volume": 0.0, "contracts": 0.0, "trades": 0, "yes_dollars": 0.0, "no_dollars": 0.0,
        "taker_yes_fills": 0, "taker_no_fills": 0, "maker_side_fills": 0, "block_trades": 0,
        "largest_fill_dollars": 0.0, "largest_fill_ticker": None, "markets": set(), "first_trade_time": None,
        "last_trade_time": None, "skipped_fields": 0})

    unmapped = []
    prefixes = sorted(provisional, key=len, reverse=True)
    for t in trades:
        srs = series_of(t["ticker"])
        row = authoritative.get(srs)
        if row:
            topic, by, prov = row.get("topic"), "series-universe", bool(row.get("provisional"))
        elif srs in provisional:
            topic, by, prov = provisional[srs], "ticker-prefix", True
        else:
            hit = next(((provisional[p], p) for p in prefixes if srs.startswith(p)), (None, None))
            if hit[0]:
                topic, by, prov = hit[0], f"longest-prefix:{hit[1]}", True
            else:
                unmapped.append({"ticker": t["ticker"], "series": srs})
                continue
        ev = event_of(t["ticker"])
        r = events[ev]
        r["event_ticker"] = ev
        r["series"] = srs
        r["topic"] = topic
        r["classified_by"] = by
        r["provisional"] = prov
        qty = num(t.get("count_fp")) or 0.0
        side = t.get("taker_outcome_side") or t.get("taker_side") or "yes"
        px = num(t.get("no_price_dollars") if side == "no" else t.get("yes_price_dollars"))
        dollars = qty * (px or 0.0)
        r["dollar_volume"] += dollars
        r["contracts"] += qty
        r["trades"] += 1
        r["yes_dollars" if side == "yes" else "no_dollars"] += dollars
        r["taker_yes_fills" if side == "yes" else "taker_no_fills"] += 1
        if t.get("taker_book_side") == "bid":
            r["maker_side_fills"] += 1
        if t.get("is_block_trade"):
            r["block_trades"] += 1
        if dollars > r["largest_fill_dollars"]:
            r["largest_fill_dollars"] = dollars
            r["largest_fill_ticker"] = t["ticker"]
        r["markets"].add(t["ticker"])
        ts = t.get("created_time")
        if ts:
            r["first_trade_time"] = min(r["first_trade_time"] or ts, ts)
            r["last_trade_time"] = max(r["last_trade_time"] or ts, ts)

    for r in events.values():
        r["markets"] = sorted(r["markets"])
        r["dollar_volume"] = round(r["dollar_volume"], 4)
        r["contracts"] = round(r["contracts"], 4)
        r["yes_dollars"] = round(r["yes_dollars"], 4)
        r["no_dollars"] = round(r["no_dollars"], 4)
        r["flow_imbalance"] = round((r["yes_dollars"] - r["no_dollars"]) / r["dollar_volume"], 4) if r["dollar_volume"] else None
        r["avg_fill_notional_dollars"] = round(r["dollar_volume"] / r["trades"], 4) if r["trades"] else None
        r["largest_fill_dollars"] = round(r["largest_fill_dollars"], 4)
        r["window_seconds"] = None
        if r["first_trade_time"] and r["last_trade_time"]:
            f = datetime.fromisoformat(r["first_trade_time"].replace("Z", "+00:00"))
            l = datetime.fromisoformat(r["last_trade_time"].replace("Z", "+00:00"))
            r["window_seconds"] = round((l - f).total_seconds(), 3)

    ranked = sorted(events.values(), key=lambda r: r["dollar_volume"], reverse=True)

    by_topic: dict[str, dict] = defaultdict(lambda: {"events": 0, "dollar_volume": 0.0, "contracts": 0.0,
                                                      "trades": 0, "yes_dollars": 0.0, "no_dollars": 0.0,
                                                      "series": set(), "top_event": None, "top_event_dollars": 0.0})
    for r in ranked:
        g = by_topic[r["topic"]]
        g["events"] += 1
        g["dollar_volume"] += r["dollar_volume"]
        g["contracts"] += r["contracts"]
        g["trades"] += r["trades"]
        g["yes_dollars"] += r["yes_dollars"]
        g["no_dollars"] += r["no_dollars"]
        g["series"].add(r["series"])
        if r["dollar_volume"] > g["top_event_dollars"]:
            g["top_event_dollars"] = r["dollar_volume"]
            g["top_event"] = r["event_ticker"]
    for g in by_topic.values():
        g["series"] = sorted(g["series"])
        g["dollar_volume"] = round(g["dollar_volume"], 4)
        g["contracts"] = round(g["contracts"], 4)
        g["yes_dollars"] = round(g["yes_dollars"], 4)
        g["no_dollars"] = round(g["no_dollars"], 4)
        g["flow_imbalance"] = round((g["yes_dollars"] - g["no_dollars"]) / g["dollar_volume"], 4) if g["dollar_volume"] else None

    all_ts = sorted([t["created_time"] for t in trades if t.get("created_time")])
    doc = {
        "_meta": {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "scripts/aggregate_capture.py",
            "formula": FORMULA,
            "capture": {
                "records": len(trades),
                "files": [os.path.relpath(CAPTURE, ROOT)],
                "sources": [SOURCE_URL, SOURCE_URL_2],
                "first_trade_time": all_ts[0] if all_ts else None,
                "last_trade_time": all_ts[-1] if all_ts else None,
                "span_seconds": (round((datetime.fromisoformat(all_ts[-1].replace("Z", "+00:00")) -
                                        datetime.fromisoformat(all_ts[0].replace("Z", "+00:00"))).total_seconds(), 3)
                                 if all_ts else None),
                "caveat": ("Two short captures taken through the agent's HTTP fetch tool because sandbox egress "
                           "to kalshi.co is blocked. The span is seconds, not minutes: this is a live-flow sample, "
                           "NOT a period volume total. scripts/collect.py produces the real windowed ranking where "
                           "network egress is allowed."),
            },
            "classification": {
                "authoritative_series_in_snapshot": len(authoritative),
                "rule": "a trade counts toward a topic only if its series prefix is present in the verified "
                        "series universe, or matches a topics.json prefix (then marked provisional)",
            },
        },
        "events": ranked,
        "by_topic": dict(sorted(by_topic.items(), key=lambda kv: kv[1]["dollar_volume"], reverse=True)),
        "unmapped_trades": unmapped,
    }

    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=2)

    print(f"capture: {len(trades)} trades, span {doc['_meta']['capture']['span_seconds']}s "
          f"({doc['_meta']['capture']['first_trade_time']} -> {doc['_meta']['capture']['last_trade_time']})")
    print(f"{'event':<34} {'topic':<12} {'USD':>12} {'contracts':>12} {'n':>3} {'imbalance':>10}  class")
    for r in ranked:
        print(f"{r['event_ticker']:<34} {str(r['topic']):<12} {r['dollar_volume']:>12,.2f} "
              f"{r['contracts']:>12,.2f} {r['trades']:>3} {str(r['flow_imbalance']):>10}  "
              f"{r['classified_by']}{' (provisional)' if r['provisional'] else ''}")
    print("\nby topic:")
    for k, g in doc["by_topic"].items():
        print(f"  {k:<12} usd {g['dollar_volume']:>12,.2f}  contracts {g['contracts']:>12,.2f}  "
              f"events {g['events']:>3}  top {g['top_event']}")
    if unmapped:
        print(f"\nunmapped (outside the five topics, excluded): {len(unmapped)} -> "
              f"{sorted({u['series'] for u in unmapped})}")

    if args.write:
        by_ev = {r["event_ticker"]: r for r in ranked}
        changed = 0
        for ev in snap.get("ranked_events", []):
            comp = by_ev.get(ev["event_ticker"])
            ev["dollar_volume_window"] = comp["dollar_volume"] if comp else 0.0
            ev["contracts_window"] = comp["contracts"] if comp else 0.0
            ev["trades_window"] = comp["trades"] if comp else 0
            ev["block_trades_window"] = comp["block_trades"] if comp else 0
            ev["yes_side_dollars"] = comp["yes_dollars"] if comp else 0.0
            ev["no_side_dollars"] = comp["no_dollars"] if comp else 0.0
            ev["flow_imbalance"] = comp["flow_imbalance"] if comp else None
            ev["avg_fill_notional_dollars"] = comp["avg_fill_notional_dollars"] if comp else None
            ev["tape_window_seconds"] = comp["window_seconds"] if comp else None
            ev["last_trade_time"] = comp["last_trade_time"] if comp else None
            ev["dollar_volume_source"] = SOURCE_URL
            ev["dollar_volume_formula"] = FORMULA
            changed += 1
        snap["topics_summary"] = [
            dict({"topic": k}, **{kk: vv for kk, vv in g.items() if kk != "series"},
                 series=g["series"],
                 source="computed from " + SOURCE_URL + " by scripts/aggregate_capture.py")
            for k, g in doc["by_topic"].items()
        ]
        snap["_meta"]["tape_trades_scanned"] = len(trades)
        snap["_meta"]["aggregates_computed_by"] = "scripts/aggregate_capture.py at " + doc["_meta"]["generated_at_utc"]
        with open(SNAPSHOT, "w") as fh:
            json.dump(snap, fh, indent=2)
        print(f"\npatched {SNAPSHOT}: {changed} events' aggregates rewritten from the computation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
