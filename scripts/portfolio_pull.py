#!/usr/bin/env python3
"""
portfolio_pull.py — Pull the Kalshi demo account portfolio state and trade
history, categorize trades, and write verified rows to data/.

Behavior:
  * If KALSHI_KEY_ID / KALSHI_PRIVATE_KEY are present (repo secrets), pull
    balance, positions, orders, fills and settlements from the official demo
    API and write them verbatim to data/latest/portfolio.json and append fills
    to data/history/trade_log.jsonl.
  * If credentials are absent, write data/latest/portfolio.json with
    status="credentials_missing" and NO fabricated numbers (dashboard shows
    blank + flagged rows until real credentials are configured).

Trade categorization (applied to API fill rows only; the taxonomy is published
on the Portfolio page and in VERIFICATION.md):
  price_bucket:   longshot (<0.10) | mid (0.10-0.90) | favorite (>0.90)
  direction:      buy_yes | buy_no | sell_yes | sell_no  (from taker/our side)
  topic:          gas | elections | culture | crypto | golf | other
                  (same rules as scripts/collect_kalshi_data.py)
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_kalshi_data import classify, to_float  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(rel: str, obj) -> None:
    path = os.path.join(DATA, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {path}")


def categorize_fill(fill: dict) -> dict:
    price = to_float(fill.get("yes_price") or fill.get("yes_price_dollars"))
    bucket = ("unverified" if price is None else
              "longshot" if price < 0.10 else
              "favorite" if price > 0.90 else "mid")
    side = fill.get("side") or fill.get("taker_side") or ""
    action = fill.get("action") or fill.get("taker_outcome_side") or ""
    direction = f"{side}_{action}".strip("_") or "unverified"
    topic, rule = classify(fill.get("ticker", ""), fill.get("title", ""))
    return {"price_bucket": bucket, "direction": direction,
            "topic": topic, "classification_rule": rule}


def main() -> int:
    key_id = os.environ.get("KALSHI_KEY_ID", "").strip()
    pem = os.environ.get("KALSHI_PRIVATE_KEY", "").strip()
    ts = now_iso()

    if not key_id or not pem:
        write_json("latest/portfolio.json", {
            "status": "credentials_missing",
            "retrieved_at": ts,
            "note": ("No demo-account API credentials are configured (repo secrets "
                     "KALSHI_KEY_ID, KALSHI_PRIVATE_KEY). Per official docs, portfolio "
                     "endpoints require authentication; no values are inferred."),
            "sources": {
                "api_keys": "https://docs.kalshi.com/getting_started/api_keys",
                "demo_env": "https://docs.kalshi.com/getting_started/demo_env",
                "auth_quickstart": "https://docs.kalshi.com/getting_started/quick_start_authenticated_requests",
            },
            "balance": {}, "positions": [], "orders": [], "fills": [], "settlements": [],
        })
        return 0

    from kalshi_client import KalshiClient  # imported only when creds exist

    client = KalshiClient(key_id=key_id, pem=pem)
    balance = client.get_balance()
    positions = client.get_positions(limit=1000)
    orders = client.get_orders(limit=1000)
    fills = client.get_fills(limit=1000)
    settlements = client.get_settlements(limit=1000)

    fill_rows = []
    for f in fills.get("fills", []):
        row = dict(f)
        row["retrieved_at"] = ts
        row["source_url"] = "https://external-api.demo.kalshi.co/trade-api/v2/portfolio/fills"
        row["categorization"] = categorize_fill(f)
        fill_rows.append(row)

    write_json("latest/portfolio.json", {
        "status": "ok",
        "retrieved_at": ts,
        "account_source_url": "https://external-api.demo.kalshi.co/trade-api/v2/portfolio",
        "balance": balance,
        "positions": positions.get("market_positions", positions.get("positions", [])),
        "orders": orders.get("orders", []),
        "fills": fill_rows,
        "settlements": settlements.get("settlements", []),
    })

    log_path = os.path.join(DATA, "history", "trade_log.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    seen = set()
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line).get("fill_id"))
                except json.JSONDecodeError:
                    pass
    with open(log_path, "a", encoding="utf-8") as f:
        for row in fill_rows:
            fid = row.get("fill_id") or str(uuid.uuid4())
            if fid not in seen:
                f.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"portfolio pulled: {len(fill_rows)} fills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
