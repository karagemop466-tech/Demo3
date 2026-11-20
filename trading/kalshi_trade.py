"""Demo-account trading & portfolio automation for the Kalshi DEMO exchange.

Official sources (verified 2026-11-20, see docs/API_VERIFICATION.md):
- Signing: https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md
  headers KALSHI-ACCESS-KEY / -TIMESTAMP (ms) / -SIGNATURE (base64);
  message = f"{timestamp}{METHOD}{path}" where path excludes query parameters;
  Ed25519 signs the message directly, RSA uses RSA-PSS SHA-256 (MGF1-SHA256,
  salt = digest length).
- Order placement: https://docs.kalshi.com/getting_started/quick_start_create_order.md
  POST /portfolio/events/orders with {"ticker", "side": "bid"|"ask", "count": "<int>",
  "price": "<dollars, 4dp>", "time_in_force": "good_till_canceled",
  "self_trade_prevention_type": "taker_at_cross", "client_order_id": "<uuid>"}.
  201 = accepted (not necessarily resting); cancel via
  DELETE /portfolio/events/orders/{order_id}.
- Environments: https://docs.kalshi.com/getting_started/api_environments.md
  Demo REST root https://external-api.demo.kalshi.co/trade-api/v2; demo credentials
  are NOT shared with production.

SECURITY: the private key is read from the KALSHI_DEMO_PRIVATE_KEY environment
variable (PEM text) and never written anywhere. KALSHI_DEMO_API_KEY_ID holds the
key id. Without both, every command exits with code 3 and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "collector"))

from kalshi_api import KalshiClient, utc_now_iso  # noqa: E402

DEMO_REST_ROOT = "https://external-api.demo.kalshi.co/trade-api/v2"
DATA_DIR = os.environ.get(
    "KALSHI_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
EXIT_NO_CREDS = 3

CONTRACT_PAYOUT = 1.0  # settled binary contracts pay $1 per winning contract


class MissingCredentials(RuntimeError):
    pass


def load_client() -> tuple[KalshiClient, str]:
    """Build a signed client from env credentials; raise MissingCredentials if absent."""
    key_id = os.environ.get("KALSHI_DEMO_API_KEY_ID", "").strip()
    pem = os.environ.get("KALSHI_DEMO_PRIVATE_KEY", "").strip()
    if not key_id or not pem:
        raise MissingCredentials(
            "Set KALSHI_DEMO_API_KEY_ID and KALSHI_DEMO_PRIVATE_KEY (PEM text) as "
            "repository secrets / environment variables. Demo keys only work against "
            "demo endpoints. Create a demo account at https://demo.kalshi.co and an "
            "API key under Account & security -> API Keys "
            "(https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md).")
    client = KalshiClient(root=os.environ.get("KALSHI_API_ROOT", DEMO_REST_ROOT),
                          min_interval=0.25, retries=2)
    client.load_private_key(pem)
    return client, key_id


def parse_cents(value) -> float | None:
    """Balance-style fields are dollars-as-cents (number or string)."""
    try:
        if value in (None, "", "null"):
            return None
        return round(float(value) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def parse_fp(value) -> float | None:
    try:
        if value in (None, "", "null"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------- commands
def cmd_portfolio(client: KalshiClient, out_dir: str) -> dict:
    """Snapshot balance + positions + fills + orders into data/portfolio.json."""
    def safe(path, params=None, list_keys=("items",)):
        try:
            data = client.request("GET", path, params=params)
            for k in list_keys:
                if k in data:
                    return data, data[k]
            return data, []
        except Exception as exc:
            return {"_error": str(exc)}, []

    balance_raw, _ = safe("/portfolio/balance")
    positions_raw, positions = safe("/portfolio/positions",
                                    {"limit": 500}, ("market_positions", "positions"))
    fills_raw, fills = safe("/portfolio/fills", {"limit": 500}, ("fills",))
    orders_raw, orders = safe("/portfolio/orders", {"limit": 500}, ("orders",))

    balance = parse_cents(balance_raw.get("balance") if isinstance(balance_raw, dict) else None)
    portfolio = {
        "generated_at": utc_now_iso(),
        "api_root": client.root,
        "account": {
            "balance_dollars": balance,
            "balance_raw_field": "portfolio/balance -> balance (dollars-as-cents, per "
                                 "docs.kalshi.com/getting_started/quick_start_authenticated_requests.md)",
        },
        "positions": positions,
        "position_count": len(positions),
        "fills_count": len(fills),
        "orders_count": len(orders),
        "fills_tail": fills[-50:],
        "orders_tail": orders[-50:],
        "raw_keys_seen": {
            "balance": sorted(balance_raw.keys()) if isinstance(balance_raw, dict) else None,
            "positions": sorted(positions_raw.keys()) if isinstance(positions_raw, dict) else None,
        },
        "verification": {
            "status": "live-demo-account",
            "sources": [
                "https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md",
                "https://docs.kalshi.com/getting_started/api_environments.md",
            ],
        },
    }
    path = os.path.join(out_dir, "portfolio.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(portfolio, fh, separators=(",", ":"))
    os.replace(tmp, path)
    print(f"wrote data/portfolio.json (balance={balance}, positions={len(positions)})",
          flush=True)
    return portfolio


def place_order(client: KalshiClient, ticker: str, action: str, side: str,
                count: int, price: float, order_type: str = "limit",
                client_order_id: str | None = None) -> dict:
    """Place one order via POST /portfolio/events/orders (official quick-start shape).

    action buy -> side "bid"; action sell -> side "ask" (order_direction doc:
    bid/ask are the V2 book-side semantics).
    """
    if action not in ("buy", "sell") or side not in ("yes", "no"):
        raise ValueError("action must be buy|sell and side yes|no")
    body = {
        "ticker": ticker,
        "side": "bid" if action == "buy" else "ask",
        "count": str(int(count)),
        "price": f"{float(price):.4f}",
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": client_order_id or str(uuid.uuid4()),
    }
    result = client.request("POST", "/portfolio/events/orders", body=body)
    return {"request": body, "response": result}


def cmd_trade(client: KalshiClient, out_dir: str, ticker: str, action: str, side: str,
              count: int, price: float, order_type: str, strategy_tag: str,
              topic: str | None, dry_run: bool) -> dict:
    from strategies import classify_trade

    # enrich with public market data for categorization (no auth needed)
    market = {}
    try:
        market = client.request("GET", f"/markets/{ticker}").get("market") or {}
    except Exception as exc:
        print(f"warning: could not fetch market {ticker}: {exc}", flush=True)
    event_ticker = market.get("event_ticker") or ticker.rsplit("-", 1)[0]

    record = {
        "placed_at": utc_now_iso(),
        "mode": "dry-run" if dry_run else "live",
        "ticker": ticker,
        "event_ticker": event_ticker,
        "title": market.get("title"),
        "action": action,
        "side": side,
        "count": int(count),
        "price_dollars": float(price),
        "order_type": order_type,
        "strategy_tag": strategy_tag,
        "topic": topic,
        "source_url": f"{client.root}/markets/{ticker}",
    }
    record["classification"] = classify_trade(
        action=action, side=side, price=float(price),
        market_last=parse_fp(market.get("last_price_dollars")),
        market_volume=parse_fp(market.get("volume_fp")))
    if not dry_run:
        placed = place_order(client, ticker, action, side, count, price, order_type)
        resp = placed.get("response") or {}
        record["order_id"] = resp.get("order_id") or resp.get("order", {}).get("order_id")
        record["client_order_id"] = placed["request"]["client_order_id"]
        record["remaining_count"] = resp.get("remaining_count")
        record["raw_response_status"] = "201" if resp else "error"
        record["raw_response"] = resp
    _append_trade(out_dir, record)
    print(json.dumps(record, indent=2)[:2000], flush=True)
    return record


def _append_trade(out_dir: str, record: dict) -> None:
    path = os.path.join(out_dir, "trades.json")
    trades = {"trades": [], "updated_at": utc_now_iso()}
    if os.path.exists(path):
        try:
            with open(path) as fh:
                trades = json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    trades.setdefault("trades", []).append(record)
    trades["updated_at"] = utc_now_iso()
    trades["summary"] = summarize(trades["trades"])
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(trades, fh, separators=(",", ":"))
    os.replace(tmp, path)
    print(f"wrote data/trades.json ({len(trades['trades'])} trades)", flush=True)


def cmd_settle(client: KalshiClient, out_dir: str) -> dict:
    """Re-check open trades: settled markets resolve yes/no and realize PnL.

    Payout rule (official): each winning settled contract pays $1
    (https://docs.kalshi.com/getting_started/market_settlement.md).
    Realized PnL for a filled trade = (payout_per_contract - entry_price) * count,
    where payout is $1 if the traded side won, $0 otherwise.
    """
    path = os.path.join(out_dir, "trades.json")
    if not os.path.exists(path):
        print("no data/trades.json yet - nothing to settle", flush=True)
        return {}
    with open(path) as fh:
        trades = json.load(fh)
    changed = 0
    for rec in trades.get("trades", []):
        if rec.get("mode") == "dry-run" or rec.get("settled_at"):
            continue
        ticker = rec.get("ticker")
        try:
            market = client.request("GET", f"/markets/{ticker}").get("market") or {}
        except Exception as exc:
            print(f"settle check skipped {ticker}: {exc}", flush=True)
            continue
        status = (market.get("status") or "").lower()
        if status not in ("settled", "finalized"):
            continue
        result = (market.get("result") or "").lower()  # "yes" | "no"
        side_won = (result == rec.get("side", "").lower())
        payout = CONTRACT_PAYOUT if side_won else 0.0
        entry = float(rec.get("price_dollars") or 0.0)
        pnl = (payout - entry) * float(rec.get("count") or 0)
        if rec.get("action") == "sell":
            pnl = -pnl  # short side: profit was booked at sale; realized delta inverted
        rec["settled_at"] = utc_now_iso()
        rec["result"] = result or None
        rec["outcome"] = "win" if (pnl > 0) else ("loss" if pnl < 0 else "flat")
        rec["realized_pnl_dollars"] = round(pnl, 2)
        rec["source_url"] = f"{client.root}/markets/{ticker}"
        changed += 1
    trades["updated_at"] = utc_now_iso()
    trades["summary"] = summarize(trades.get("trades", []))
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(trades, fh, separators=(",", ":"))
    os.replace(tmp, path)
    print(f"settle sweep: {changed} trades resolved", flush=True)
    return trades


def summarize(trades: list[dict]) -> dict:
    """Aggregate performance by topic and by trade structure (strategy categories)."""
    def bucket(rows):
        out = {}
        for r in rows:
            if r.get("settled_at") is None:
                continue
            key = r.get("_bucket") or "?"
            b = out.setdefault(key, {"trades": 0, "wins": 0, "losses": 0,
                                     "realized_pnl_dollars": 0.0})
            b["trades"] += 1
            b["realized_pnl_dollars"] = round(
                b["realized_pnl_dollars"] + (r.get("realized_pnl_dollars") or 0.0), 2)
            if r.get("outcome") == "win":
                b["wins"] += 1
            elif r.get("outcome") == "loss":
                b["losses"] += 1
        for b in out.values():
            b["win_rate"] = round(b["wins"] / b["trades"], 4) if b["trades"] else None
        return out

    by_topic_rows, by_structure_rows = [], []
    for r in trades:
        r2 = dict(r)
        r2["_bucket"] = (r.get("topic") or "unknown")
        by_topic_rows.append(r2)
        r3 = dict(r)
        r3["_bucket"] = ((r.get("classification") or {}).get("structure") or "unknown")
        by_structure_rows.append(r3)
    return {
        "settled_trades": sum(1 for t in trades if t.get("settled_at")),
        "open_trades": sum(1 for t in trades if not t.get("settled_at")),
        "by_topic": bucket(by_topic_rows),
        "by_structure": bucket(by_structure_rows),
        "updated_at": utc_now_iso(),
        "note": "performance aggregates computed only from settled trades with "
                "recorded realized PnL; nothing inferred",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Kalshi demo trading/portfolio automation")
    sub = ap.add_subparsers(dest="command", required=True)

    ap_p = sub.add_parser("portfolio", help="snapshot balance/positions/fills/orders")
    ap_t = sub.add_parser("trade", help="place a demo order and record it")
    ap_t.add_argument("--ticker", required=True)
    ap_t.add_argument("--action", required=True, choices=["buy", "sell"])
    ap_t.add_argument("--side", required=True, choices=["yes", "no"])
    ap_t.add_argument("--count", required=True, type=int)
    ap_t.add_argument("--price", required=True, type=float, help="dollars per contract, e.g. 0.55")
    ap_t.add_argument("--type", dest="order_type", default="limit", choices=["limit", "market"])
    ap_t.add_argument("--strategy-tag", default="directional")
    ap_t.add_argument("--topic", default=None)
    ap_t.add_argument("--dry-run", action="store_true",
                      help="record the trade locally without sending it")
    ap_s = sub.add_parser("settle", help="re-check open trades and realize PnL")

    args = ap.parse_args(argv)

    if args.command in ("portfolio", "trade") or args.command == "settle":
        try:
            client, _ = load_client()
        except MissingCredentials as exc:
            print("FLAGGED (unverified): no demo credentials — nothing executed.", flush=True)
            print(str(exc), flush=True)
            return EXIT_NO_CREDS

    out_dir = DATA_DIR
    os.makedirs(out_dir, exist_ok=True)
    if args.command == "portfolio":
        cmd_portfolio(client, out_dir)
    elif args.command == "trade":
        cmd_trade(client, out_dir, args.ticker, args.action, args.side, args.count,
                  args.price, args.order_type, args.strategy_tag, args.topic,
                  args.dry_run)
    elif args.command == "settle":
        cmd_settle(client, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
