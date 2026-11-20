#!/usr/bin/env python3
"""
trade_runner.py — Execute (or dry-run) demo-account trades through the official
Kalshi demo Trade API, and track their performance.

SAFETY RULES (enforced below):
  1. Dry-run is the DEFAULT. Nothing is sent unless --execute is passed AND
     both KALSHI_KEY_ID and KALSHI_PRIVATE_KEY are present.
  2. The runner only ever targets the DEMO environment
     (https://external-api.demo.kalshi.co/trade-api/v2). It cannot trade prod.
  3. Per-order size cap (--max-count, default 5 contracts) and per-run order
     cap (--max-orders, default 5). Exceeding either aborts the run.
  4. Every order carries a fresh client_order_id (UUID) for idempotent retries
     per https://docs.kalshi.com/getting_started/quick_start_create_order.
  5. No strategy is enabled implicitly. Strategies must be listed with
     --strategy and exist in STRATEGIES below (each is "proposed"; see the
     site's Portfolio page). Nothing auto-executes on a schedule.

Order shape and headers follow the official quick start:
  https://docs.kalshi.com/getting_started/quick_start_create_order
Signing follows the official starter code (RSA-PSS SHA-256):
  https://github.com/Kalshi/kalshi-starter-code-python

Usage:
  python scripts/trade_runner.py --dry-run --strategy S6 --ticker KX... --side bid \
      --count 1 --price 0.0500
  python scripts/trade_runner.py --execute --strategy S1 --ticker KX... --side bid \
      --count 2 --price 0.9200
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Proposed strategies (mirrors the site's playbook; all "proposed - not implemented")
STRATEGIES = {
    "S1": "Directional favorite (entry > $0.90)",
    "S2": "Longshot basket (entry < $0.10)",
    "S3": "Momentum on 1-minute candles",
    "S4": "Liquidity provision (spread >= 3c)",
    "S5": "Hold-to-settlement vs sell-before-close study",
    "S6": "Category rotation on dollar-volume rank",
    "MANUAL": "Manual order ticket (no strategy claim)",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true",
                    help="actually place the order on the demo API (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry run (default)")
    ap.add_argument("--strategy", default="MANUAL", choices=sorted(STRATEGIES))
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--side", required=True, choices=["bid", "ask"],
                    help="bid = buy, ask = sell (official quick-start terminology)")
    ap.add_argument("--count", default="1", help="contracts (integer string)")
    ap.add_argument("--price", default="0.0100", help="limit price in dollars, e.g. 0.0500")
    ap.add_argument("--time-in-force", default="good_till_canceled",
                    choices=["good_till_canceled", "immediate_or_cancel", "fill_or_kill"])
    ap.add_argument("--max-count", type=int, default=5, help="per-order contract cap")
    ap.add_argument("--max-orders", type=int, default=5, help="per-run order cap")
    args = ap.parse_args()

    count = int(args.count)
    if count < 1 or count > args.max_count:
        print(f"REFUSED: count {count} outside 1..{args.max_count} (--max-count)")
        return 2

    client_order_id = str(uuid.uuid4())
    body = {
        "ticker": args.ticker,
        "side": args.side,
        "count": str(count),
        "price": args.price,
        "time_in_force": args.time_in_force,
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": client_order_id,
    }
    record = {
        "ts": now_iso(), "strategy": args.strategy,
        "strategy_label": STRATEGIES[args.strategy],
        "dry_run": not args.execute, "request": body,
        "endpoint": "https://external-api.demo.kalshi.co/trade-api/v2/portfolio/orders",
        "order_shape_source": "https://docs.kalshi.com/getting_started/quick_start_create_order",
    }

    if not args.execute:
        print(json.dumps({**record, "status": "dry_run_only"}, indent=2))
        print("\nDry run. Nothing was sent. Re-run with --execute to place this order "
              "on the DEMO exchange (requires KALSHI_KEY_ID / KALSHI_PRIVATE_KEY).")
        return 0

    if args.max_orders < 1:
        print("REFUSED: --max-orders must be >= 1")
        return 2
    if not os.environ.get("KALSHI_KEY_ID") or not os.environ.get("KALSHI_PRIVATE_KEY"):
        print("REFUSED: --execute requires KALSHI_KEY_ID and KALSHI_PRIVATE_KEY env vars")
        return 2

    from kalshi_client import KalshiClient  # only imported when executing

    client = KalshiClient()
    try:
        resp = client.place_order(
            ticker=args.ticker, side=args.side, count=str(count),
            price=args.price, client_order_id=client_order_id,
            time_in_force=args.time_in_force)
        record["status"] = "submitted"
        record["response"] = resp
    except Exception as e:  # noqa: BLE001 — report and fail loudly
        record["status"] = "error"
        record["error"] = str(e)
        print(json.dumps(record, indent=2))
        return 1

    log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "history", "order_log.jsonl")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
