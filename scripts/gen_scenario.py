#!/usr/bin/env python3
"""
gen_scenario.py — build a paper-order scenario from the collector snapshot, deterministically.

Rules (all enforced here, so the engine never has to invent a price):
  * only markets present in data/live_snapshot.json are used — the capture is the only quote source;
  * a quote is used only if 0 < price < 1 on that market's own recorded fields, in this order:
    best opposite quote (ask for a buy, bid for a sell) -> last_price_dollars -> skipped;
  * every skipped market stays in the file with its reason, so the "we could not price it"
    cases are visible instead of hidden;
  * nothing here is sent anywhere: scripts/trade_engine.py --paper runs it locally.

Run:  python3 scripts/gen_scenario.py > data/scenarios/paper-first-pass.json
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "data", "live_snapshot.json")
OUT = os.path.join(ROOT, "data", "scenarios", "paper-first-pass.json")

COUNTS = ["12.00", "250.00", "1250.00", "3.00"]
STRATS = ["S1-limit-resting", "S2-cross-the-spread", "S3-resolution-carry", "S4-flow-follow"]


def px(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0.0 < f < 1.0 else None


def main() -> int:
    with open(SNAP) as fh:
        snap = json.load(fh)
    orders, skipped = [], []
    for ev in snap.get("ranked_events", []):
        for i, m in enumerate(ev.get("markets", []) or []):
            side = "bid" if i % 3 else "ask"           # 2 buys per sell, deterministic
            quoted = px(m.get("yes_ask_dollars")) if side == "bid" else px(m.get("yes_bid_dollars"))
            why = None
            price = quoted
            if price is None:
                price = px(m.get("last_price_dollars"))
                why = "recorded best quote was outside (0,1); used the market's own last_price_dollars"
            if price is None:
                skipped.append({
                    "ticker": m["ticker"],
                    "yes_bid_dollars": m.get("yes_bid_dollars"),
                    "yes_ask_dollars": m.get("yes_ask_dollars"),
                    "last_price_dollars": m.get("last_price_dollars"),
                    "reason": ("no price in (0,1) exists on this row: bid 0.0000 / ask 1.0000 with "
                               "volume_fp 0.00 is an empty book, so the engine would have to invent a price"),
                    "source": m.get("source"),
                })
                continue
            strat = STRATS[i % 4]
            # a resting order is a bid below the touch or an ask above it; crossing is the taker case
            if side == "bid" and strat == "S1-limit-resting":
                strat = "S2-cross-the-spread"
            if side == "ask" and strat == "S2-cross-the-spread":
                strat = "S1-limit-resting"
            orders.append({
                "ticker": m["ticker"],
                "side": side,
                "count": COUNTS[i % 4],
                "price": f"{price:.4f}",
                "strategy": strat,
                "time_in_force": "immediate_or_cancel" if side == "bid" else "good_till_canceled",
                "self_trade_prevention_type": "taker_at_cross" if side == "bid" else "maker",
                "why": (f"paper {side} at {price:.4f}, the market's own recorded "
                        f"{'ask' if side == 'bid' else 'bid'}"
                        + (f" ({why})" if why else "")),
                "quote_source": m.get("source"),
                "topic": ev.get("topic"),
                "event_ticker": ev.get("event_ticker"),
            })
    doc = {
        "_meta": {
            "purpose": ("Paper-order scenario that exercises trade_engine -> portfolio -> analyze end to end "
                        "without credentials."),
            "generated_by": "scripts/gen_scenario.py from data/live_snapshot.json",
            "generated_at_utc": snap.get("_meta", {}).get("generated_at_utc"),
            "not_a_trade": ("Nothing in this file was sent to Kalshi. Run with --paper and fills are simulated "
                            "locally against the recorded quote; they are labelled mode=paper everywhere."),
            "semantics": {
                "side": "bid = buy YES, ask = sell YES (= buy NO) — the V2 API quotes the YES leg only",
                "price": "dollar string, must satisfy the market's price grid",
                "count": "contracts, fixed-point, 0.01 granularity",
                "time_in_force": "one of good_till_canceled, fill_or_kill, immediate_or_cancel, good_until_date",
            },
            "sources": [
                "https://docs.kalshi.com/api-reference/orders/create-order-v2.md",
                "https://docs.kalshi.com/getting_started/quick_start_create_order.md",
            ],
            "markets_offered": len(orders) + len(skipped),
            "priced": len(orders),
            "unpriceable": len(skipped),
        },
        "orders": orders,
        "skipped": skipped,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, "w"), indent=2)
    print(f"{len(orders)} priced orders, {len(skipped)} unpriceable -> {OUT}", file=sys.stderr)
    for s in skipped:
        print("  skip " + s["ticker"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
