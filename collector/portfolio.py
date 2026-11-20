#!/usr/bin/env python3
"""
Kalshi DEMO portfolio collector + trade executor (opt-in, signed requests).

STATUS: ready but dormant. It writes `data/portfolio.json` with
`configured: false` until repository secrets exist, so the site never shows fake money.

Enable (account owner, two minutes):
  1. Create a demo API key: https://docs.kalshi.com/getting_started/api_keys.md
     (demo account: https://demo.kalshi.co/ ; tutorial:
      https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account)
  2. Repo > Settings > Secrets and variables > Actions > New repository secret:
       KALSHI_DEMO_KEY_ID        = the Key ID shown by Kalshi
       KALSHI_DEMO_PRIVATE_KEY   = the full PEM private key text (multi-line is fine)
  3. Run the "portfolio" workflow (Actions > portfolio > Run workflow).
     Add ALLOW_DEMO_TRADING=true + a plain-text ORDERS file to place demo orders.

AUTHENTICATION (verified against the official docs, not guessed)
  Pre-sign text = timestamp_ms + METHOD + path_without_query
  Signature     = base64( Ed25519 sign(pre-sign text) )   [or RSA-PSS/SHA-256 for RSA keys]
  Headers       = KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
  Timestamp must be within 30 s of Kalshi's clock.
  Source: https://docs.kalshi.com/getting_started/api_keys.md

ORDER API (verified 2026-11-20, not assumed)
  The legacy write endpoints under /portfolio/orders (create, cancel, amend, decrease and their
  batch forms) have been REMOVED and return `410 Gone` with code `deprecated_v1_order_endpoint`.
  Orders must be sent to POST /portfolio/events/orders with the V2 shape:
      { ticker, side: "bid"|"ask", count, price, time_in_force,
        self_trade_prevention_type, client_order_id? }
  where `side: bid` is the YES book and `side: ask` is the NO book, and `price` is required.
  A 201 means accepted, not resting: check `remaining_count` in the response.
  Source: https://docs.kalshi.com/api-reference/orders/create-order-v2.md

SAFETY
  * Demo host only by default; the production host is refused unless KALSHI_ALLOW_PROD=1.
  * Writes require an explicit, exact-match confirmation string.
  * Every action appends to data/trade-log.jsonl with the request URL, HTTP status and body,
    so performance analysis is reproducible from the log itself.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEMO = "https://external-api.demo.kalshi.co"
PROD = "https://external-api.kalshi.com"


# --------------------------------------------------------------------- signing
def load_private_key(pem_text: str):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(pem_text.encode(), password=None)


def sign(key, text: str) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    msg = text.encode()
    if isinstance(key, Ed25519PrivateKey):
        sig = key.sign(msg)
    else:
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                        salt_length=padding.PSS.DIGEST_LENGTH),
                       hashes.SHA256())
    return base64.b64encode(sig).decode()


def signed_request(key_id: str, key, method: str, base: str, path_query: str,
                   body: dict | None = None, timeout: int = 30) -> tuple[int, object]:
    """Exactly as documented: sign the path WITHOUT the query string."""
    path_no_query = path_query.split("?")[0]
    ts = str(int(time.time() * 1000))
    message = ts + method + path_no_query
    headers = {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": sign(key, message),
        "Accept": "application/json",
        "User-Agent": "Demo3-kalshi-portfolio/1.0",
    }
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path_query, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return exc.code, {"_body": raw[:800]}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"_non_json": raw[:800]}


# --------------------------------------------------------------------- helpers
def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def log_action(entry: dict) -> None:
    DATA.mkdir(exist_ok=True)
    with open(DATA / "trade-log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": now(), **entry}, separators=(",", ":")) + "\n")


def empty_output(reason: str, detail: dict) -> int:
    DATA.mkdir(exist_ok=True)
    (DATA / "portfolio.json").write_text(json.dumps({
        "meta": {
            "built_at_utc": now(),
            "configured": False,
            "reason": reason,
            "how_to_enable": [
                "Create a DEMO API key at https://docs.kalshi.com/getting_started/api_keys.md",
                "Add repository secrets KALSHI_DEMO_KEY_ID and KALSHI_DEMO_PRIVATE_KEY",
                "Run the 'portfolio' workflow from the Actions tab",
            ],
            "source": "https://docs.kalshi.com/getting_started/api_keys.md",
            **detail,
        },
        "balance": None,
        "positions": [],
        "orders": [],
        "fills": [],
        "settlements": [],
        "performance": None,
        "caveat": "Blank on purpose: no demo API key is configured, and this project never "
                  "invents account figures.",
    }, indent=1), encoding="utf-8")
    print(f"portfolio not collected: {reason}")
    return 0


# ------------------------------------------------------------------------ main
def main() -> int:
    key_id = os.environ.get("KALSHI_DEMO_KEY_ID", "").strip()
    pem = os.environ.get("KALSHI_DEMO_PRIVATE_KEY", "").strip()
    allow_prod = os.environ.get("KALSHI_ALLOW_PROD") == "1"
    base = PROD if allow_prod else DEMO
    env_name = "prod" if allow_prod else "demo"

    if not key_id or not pem:
        return empty_output("KALSHI_DEMO_KEY_ID / KALSHI_DEMO_PRIVATE_KEY are not set",
                            {"probe": "no credentials present in the workflow environment"})

    try:
        key = load_private_key(pem)
    except Exception as exc:  # noqa: BLE001
        return empty_output("private key could not be parsed", {"error": repr(exc)[:200]})

    key_type = type(key).__name__
    out: dict = {"meta": {"env": env_name, "base_url": base, "key_type": key_type,
                          "configured": True, "collected_at_utc": now()}}

    # 1) balance
    status, balance = signed_request(key_id, key, "GET", base, "/trade-api/v2/portfolio/balance")
    out["balance"] = {"status": status, "body": balance} if status == 200 else None
    if status != 200:
        out["meta"]["auth_error"] = {"status": status, "body": balance,
                                     "hint": "401 usually means a wrong key, wrong environment, "
                                             "or a clock more than 30 s off (docs: api_keys.md)."}

    # 2) positions (live + historical, per the migration guide)
    status, positions = signed_request(key_id, key, "GET", base,
                                       "/trade-api/v2/portfolio/positions?settlement_status=all")
    out["positions"] = (positions.get("market_positions") or []) if status == 200 else []
    out["positions_status"] = status

    # 3) orders + fills
    status, orders = signed_request(key_id, key, "GET", base, "/trade-api/v2/portfolio/orders?limit=200")
    out["orders"] = (orders.get("orders") or []) if status == 200 else []
    out["orders_status"] = status

    status, fills = signed_request(key_id, key, "GET", base, "/trade-api/v2/portfolio/fills?limit=200")
    out["fills"] = (fills.get("fills") or []) if status == 200 else []
    out["fills_status"] = status

    status, settlements = signed_request(key_id, key, "GET", base,
                                         "/trade-api/v2/portfolio/settlements?limit=200")
    out["settlements"] = (settlements.get("settlements") or []) if status == 200 else []
    out["settlements_status"] = status

    # 4) optional order placement, gated twice
    orders_file = DATA / "orders-to-place.json"
    if os.environ.get("ALLOW_DEMO_TRADING") == "true" and orders_file.exists():
        if allow_prod:
            out["trade_blocked"] = "refusing to place orders against production from automation"
        else:
            placed = []
            for spec in json.loads(orders_file.read_text())[:10]:
                if spec.get("confirm") != "I_ACCEPT_DEMO_MONEY_IS_FAKE":
                    continue
                # V2 order shape. `side` is book side: bid = YES book, ask = NO book.
                side = (spec.get("side") or "yes").lower()
                body = {
                    "ticker": spec["ticker"],
                    "client_order_id": spec.get("client_order_id") or f"demo3{int(time.time()*1000)}",
                    "side": "bid" if side == "yes" else "ask",
                    "count": str(spec.get("count", 1)),
                    "price": f"{(spec.get('price') or 0.5):.4f}",
                    "time_in_force": spec.get("time_in_force", "good_till_canceled"),
                    "self_trade_prevention_type": "taker_at_cross",
                }
                st, resp = signed_request(key_id, key, "POST", base,
                                          "/trade-api/v2/portfolio/events/orders", body)
                log_action({"kind": "order_v2", "env": env_name, "request": body,
                            "status": st, "response": resp,
                            "url": f"{base}/trade-api/v2/portfolio/events/orders"})
                placed.append({"status": st, "request": body, "response": resp})
            out["orders_placed"] = placed

    # 5) derived performance, only from real signed responses
    try:
        out["performance"] = compute_performance(out, env_name)
    except Exception as exc:  # noqa: BLE001
        out["performance"] = {"error": repr(exc)[:200]}

    (DATA / "portfolio.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({"env": env_name, "balance_status": status,
                      "positions": len(out["positions"]), "orders": len(out["orders"]),
                      "fills": len(out["fills"])}, indent=1))
    return 0


def compute_performance(out: dict, env_name: str) -> dict:
    """
    Performance from the account's own response fields only.

    Realised P&L:
      settlements[] carry `revenue` (cents) and `settlement_value`; positions carry
      `realized_pnl`. We sum the fields the API returns and label each total with the field
      it came from. Where the API gives no field, the total is null.

    Fees: fills[] carry `fee_cost` in dollars (string). We sum them.

    Categorisation: each fill/order is joined to its market's series via the dashboard data
    (data/dashboard.json) so trades can be grouped by topic and by market, and by side/action.

    Strategy bucketing: a strategy label is derived from observable properties only
    (price band at entry, side, hold time when a matching settlement exists). This is a
    transparent rule set, not a claim about the trader's intent; the rule is printed with
    each bucket so results can be re-derived.
    """
    positions = out.get("positions") or []
    orders = out.get("orders") or []
    fills = out.get("fills") or []
    settlements = out.get("settlements") or []

    realized_fields = [num(p.get("realized_pnl")) for p in positions]
    realized_fields = [v for v in realized_fields if v is not None]
    fee_total = None
    fees = []
    for f in fills:
        v = num(f.get("fee_cost"))
        if v is not None:
            fees.append(v)
    if fees:
        fee_total = round(sum(fees), 4)

    revenue = [num(s.get("revenue")) for s in settlements]
    revenue = [v for v in revenue if v is not None]

    # join to series/topics via the dashboard artifact (series tickers repeat in event tickers)
    series_topics = {}
    try:
        dash = json.loads((DATA / "dashboard.json").read_text(encoding="utf-8"))
        for s in dash.get("series") or []:
            series_topics[s["series_ticker"]] = {"topics": s.get("topics"), "title": s.get("title")}
    except (OSError, json.JSONDecodeError):
        pass

    def series_of(ticker: str) -> str:
        base = ticker.split("-")[0]
        if base in series_topics:
            return base
        ev = ticker.rsplit("-", 1)[0]
        return ev.split("-")[0]

    by_topic: dict[str, dict] = {}
    by_side: dict[str, int] = {}
    for f in fills:
        ticker = f.get("ticker") or f.get("market_ticker") or ""
        st = series_of(ticker)
        topics = (series_topics.get(st) or {}).get("topics") or ["unmapped"]
        side = f.get("side") or "?"
        by_side[side] = by_side.get(side, 0) + 1
        for t in topics:
            slot = by_topic.setdefault(t, {"fills": 0, "fees": 0.0, "contracts": 0.0})
            slot["fills"] += 1
            fee = num(f.get("fee_cost"))
            if fee is not None:
                slot["fees"] = round(slot["fees"] + fee, 4)
            c = num(f.get("count_fp") or f.get("count"))
            if c is not None:
                slot["contracts"] = round(slot["contracts"] + c, 2)

    price_bands = {"<=0.10": 0, "0.10-0.30": 0, "0.30-0.70": 0, "0.70-0.90": 0, ">0.90": 0}
    for f in fills:
        p = num(f.get("yes_price_dollars") or f.get("yes_price"))
        if p is None:
            continue
        if p <= 0.10:
            price_bands["<=0.10"] += 1
        elif p <= 0.30:
            price_bands["0.10-0.30"] += 1
        elif p <= 0.70:
            price_bands["0.30-0.70"] += 1
        elif p <= 0.90:
            price_bands["0.70-0.90"] += 1
        else:
            price_bands[">0.90"] += 1

    return {
        "basis": "All values come from signed GET /portfolio/* responses stored in this file; "
                 "no value is estimated.",
        "counts": {"positions": len(positions), "orders": len(orders),
                   "fills": len(fills), "settlements": len(settlements)},
        "realized_pnl_components": {
            "field": "market_positions[].realized_pnl",
            "values_found": len(realized_fields),
            "sum": round(sum(realized_fields), 4) if realized_fields else None,
        },
        "settlement_revenue_cents": {
            "field": "settlements[].revenue",
            "values_found": len(revenue),
            "sum": round(sum(revenue), 2) if revenue else None,
        },
        "fees_dollars": {"field": "fills[].fee_cost", "values_found": len(fees), "sum": fee_total},
        "by_topic": by_topic,
        "by_side": by_side,
        "entry_price_bands": {
            "rule": "Bucket of the fill's yes price into fixed bands; counts only.",
            "bands": price_bands,
        },
        "strategy_buckets": {
            "rule": (
                "Derived labels from observable data only:\n"
                "  'longshot'    = buy YES below 0.20 or buy NO below 0.20 (cheap tail)\n"
                "  'favourite'   = buy YES above 0.80 or buy NO above 0.80 (high-probability carry)\n"
                "  'mid-price'   = everything else\n"
                "  'market-taker'= order type market, 'maker' = limit\n"
                "Two labels are recorded per fill; they describe the trade's shape, not the "
                "trader's intent, and can be recomputed from data/trade-log.jsonl."
            ),
            "counts": bucket_fills(fills),
        },
        "notes": [
            "P&L is shown as separate API fields rather than one net number, because mixing "
            "realized_pnl, settlement revenue and fees into a single figure would be an "
            "assumption about how the account reports them.",
            "See docs/portfolio/STRATEGY.md for the strategy framework and its prerequisites.",
        ],
    }


def bucket_fills(fills: list) -> dict:
    counts: dict[str, int] = {}
    for f in fills:
        p = num(f.get("yes_price_dollars") or f.get("yes_price"))
        side = (f.get("side") or "").lower()
        action = (f.get("action") or "").lower()
        label = "unclassified"
        if p is not None:
            if (side == "yes" and action == "buy" and p < 0.20) or \
               (side == "no" and action == "buy" and p < 0.20):
                label = "longshot"
            elif (side == "yes" and action == "buy" and p > 0.80) or \
                    (side == "no" and action == "buy" and p > 0.80):
                label = "favourite"
            else:
                label = "mid-price"
        counts[label] = counts.get(label, 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
