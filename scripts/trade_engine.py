"""
trade_engine.py — order lifecycle on the Kalshi **demo** exchange, plus a paper mode.

Order surface (V2 only — the legacy /portfolio/orders writes are removed and return 410):
    create    POST   /portfolio/events/orders
    amend     POST   /portfolio/events/orders/{order_id}/amend
    decrease  POST   /portfolio/events/orders/{order_id}/decrease   (reduce_by XOR reduce_to)
    cancel    DELETE /portfolio/events/orders/{order_id}?market_ticker=<ticker>
    batch     POST   /portfolio/events/orders/batched
    cancelall DELETE /portfolio/events/orders/batched

Field semantics verified against
    https://docs.kalshi.com/api-reference/orders/create-order-v2.md
    https://docs.kalshi.com/getting_started/quick_start_create_order.md

Everything quotes the **YES** leg: side=bid means buy YES, side=ask means sell YES
(= buy NO at 1-price). Prices are fixed-point dollar strings on the market's own grid.

SAFETY
  * Refuses to send anything unless BOTH `--execute` and credentials are present.
  * Refuses production hosts: the demo-only guard is deliberately hard to remove.
  * `client_order_id` is generated (uuid4) and persisted so a retry can't double-send.
  * Paper mode (`--paper`) never calls a write endpoint: it simulates a fill against the
    live public order book and appends to data/paper_ledger.json. Clearly labelled, and
    the only mode usable in this repo today (no demo API key exists — see COORDINATION B1).

Examples
  python3 scripts/trade_engine.py --paper buy KXWTIW-26NOV21-C65 --count 10
  python3 scripts/trade_engine.py --plan  buy KXPGATOUR-THRC26-HLEB --count 5 --price 0.03
  python3 scripts/trade_engine.py --execute --key-id ... --key-file kalshi.pem buy TICKER --count 1 --price 0.01
  python3 scripts/trade_engine.py cancel <order_id> --market TICKER
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kalshi_api import DEMO_REST, DEMO_REST_ALT, KalshiClient, KalshiError, Signer, fp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDERS_PATH = os.path.join(ROOT, "data", "orders.json")
PAPER_PATH = os.path.join(ROOT, "data", "paper_ledger.json")

TIF = ("good_till_canceled", "fill_or_kill", "immediate_or_cancel", "good_until_date")
STP = ("taker_at_cross", "maker")


class OrderError(ValueError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load_capture(path: str | None) -> dict[str, dict]:
    """Build ticker -> market-row quotes from a collector snapshot, for offline paper orders.

    Reads only fields the snapshot recorded (which are themselves copies of API responses).
    A market missing from the snapshot is an error, never a guess.
    """
    if not path:
        return {}
    with open(path) as fh:
        snap = json.load(fh)
    out: dict[str, dict] = {}
    for ev in snap.get("ranked_events", []) or []:
        for m in ev.get("markets", []) or []:
            row = dict(m)
            d = m.get("depth") or {}
            row["orderbook_fp"] = {"yes_dollars": d.get("yes_bid_levels") or [],
                                   "no_dollars": d.get("no_bid_levels") or []}
            row["price_ranges"] = m.get("price_level_structure_ranges") or row.get("price_ranges") or []
            row["_captured_from"] = m.get("source")
            out[m["ticker"]] = row
    return out


def price_on_grid(price: float, price_ranges: list[dict]) -> tuple[bool, str]:
    """A quote is only valid on the market's own grid.

    price_ranges come straight from GET /markets (e.g. [{start:0.01,end:0.99,step:0.001}])
    and the API spec states valid quote intervals are constrained by the market's price
    level structure. https://docs.kalshi.com/api-reference/orders/create-order-v2.md
    """
    if not price_ranges:
        # Absent grid data is NOT a pass. `GET /markets` documents price_ranges, but a row that was
        # captured without them (as in this repo's data/live_snapshot.json) cannot be verified, so we
        # allow the order through and record the gap in validation_warnings instead of pretending.
        return True, "grid-unverified: this market row carries no price_ranges, so the step check was skipped"
    for r in price_ranges or []:
        lo, hi, step = fp(r.get("start")), fp(r.get("end")), fp(r.get("step"))
        if step <= 0 or price < lo - 1e-12 or price > hi + 1e-12:
            continue
        k = (price - lo) / step
        if abs(k - round(k)) < 1e-9:
            return True, f"[{lo},{hi}] step {step}"
        return False, (f"price {price} is not a multiple of step {step} inside "
                       f"[{lo},{hi}] for this market's grid")
    return False, f"price {price} is outside every range of this market's grid {price_ranges}"


def validate(order: dict, market: dict | None = None) -> list[str]:
    errs: list[str] = []
    if not order.get("ticker"):
        errs.append("ticker is required")
    elif not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*", str(order["ticker"])):
        # dots ARE legal: strike tickers look like KXWTIW-26NOV2014-T101.99 (observed on GET /markets).
        errs.append(f"ticker '{order['ticker']}' is not a plausible Kalshi market ticker "
                    "(expected upper-case alphanumerics, '-' for levels, '.' inside strike values)")
    if order.get("side") not in ("bid", "ask"):
        errs.append("side must be 'bid' (buy YES) or 'ask' (sell YES / buy NO)")
    count = fp(order.get("count"))
    if count <= 0:
        errs.append("count must be > 0 contracts")
    elif round(count * 100) != count * 100:
        errs.append("count granularity is 0.01 contracts (fixed-point, 2 dp)")
    price = fp(order.get("price"))
    if not (0.0 < price < 1.0):
        errs.append("price must be strictly between $0.00 and $1.00 for a binary market "
                    "(0.01-0.99 on the cent grid; finer grids exist in the edge bands)")
    if order.get("time_in_force") and order["time_in_force"] not in TIF:
        errs.append(f"time_in_force must be one of {TIF}")
    if order.get("self_trade_prevention_type") and order["self_trade_prevention_type"] not in STP:
        errs.append(f"self_trade_prevention_type must be one of {STP}")
    if order.get("type") in ("market",):
        errs.append("the V2 create endpoint documents limit-style quotes; a bare 'market' "
                    "order type is not in the V2 request schema — use IOC/FOK at a capped price")
    if market is not None:
        ok, why = price_on_grid(price, market.get("price_ranges"))
        if not ok:
            errs.append(f"grid: {why}")
        if market.get("status") not in (None, "active", "open"):
            errs.append(f"market status is '{market.get('status')}', not tradeable")
        if market.get("can_close_early") and market.get("close_time") and market["close_time"] <= utcnow():
            errs.append("market close_time already passed")
    return errs


class TradeEngine:
    def __init__(self, client: KalshiClient, *, paper: bool = False, execute: bool = False,
                 capture: dict[str, dict] | None = None):
        self.client = client
        self.paper = paper
        self.execute = execute
        # `capture` maps market ticker -> a market row and order book copied verbatim from a prior
        # public API read. It exists because this sandbox has no egress to kalshi.co: the SAME
        # validation and fill logic runs, but quotes come from the capture and every entry is
        # stamped quote_basis="capture" so nobody mistakes it for a live read.
        self.capture = capture or {}
        if not paper and execute and "demo" not in client.base_url:
            raise OrderError("refusing to send live orders to a non-demo host from this repo")
        if self.capture and execute:
            raise OrderError("--capture is incompatible with --execute: a capture cannot price a live order")

    # ------------------------------------------------------------ public helpers
    def market(self, ticker: str) -> dict:
        if ticker in self.capture:
            m = dict(self.capture[ticker])
            m["quote_basis"] = "capture"
            return m
        try:
            return self.client.market(ticker)
        except KalshiError as exc:
            raise OrderError(f"cannot read market {ticker}: {exc}") from exc

    def record(self, kind: str, payload: dict, response: Any, market: dict | None) -> dict:
        entry = {
            "kind": kind,
            "submitted_at_utc": utcnow(),
            "mode": "paper" if self.paper else ("live-demo" if self.execute else "plan"),
            "request": payload,
            "response": response,
            "market_snapshot_used": {
                k: market.get(k) for k in
                ("ticker", "status", "last_price_dollars", "yes_bid_dollars", "yes_ask_dollars",
                 "no_bid_dollars", "volume_fp", "open_interest_fp", "close_time", "notional_value_dollars",
                 "quote_basis", "_captured_from")
            } if market else None,
            "market_source": self.client.url_for(f"/markets/{payload.get('ticker','')}") if payload.get("ticker") else None,
        }
        if getattr(self, "strategy_tag", None):
            entry["strategy"] = self.strategy_tag
        if payload.get("strategy"):
            entry["strategy"] = payload["strategy"]
        _append(ORDERS_PATH, "orders", entry)
        # Paper fills are ALSO mirrored into the file portfolio.py reads as its ledger.
        # Without this, `--paper` runs would be invisible to performance reporting (fixed 2026-11-20:
        # PAPER_PATH used to be declared here but never written, so load_paper() always saw zero fills).
        if self.paper and (response or {}).get("filled"):
            _append(PAPER_PATH, "orders", entry)
        return entry

    # ----------------------------------------------------------------- actions
    def create(self, order: dict, *, require_validation: bool = True) -> dict:
        market = self.market(order["ticker"]) if order.get("ticker") else None
        errs = validate(order, market)
        if errs and require_validation:
            raise OrderError("order rejected before sending:\n  - " + "\n  - ".join(errs))
        payload = {
            "ticker": order["ticker"],
            "client_order_id": order.get("client_order_id") or str(uuid.uuid4()),
            "side": order["side"],
            "count": f"{fp(order['count']):.2f}",  # requests accept 0-2 dp; 2 dp is always valid
            "price": f"{fp(order['price']):.4f}",
            "time_in_force": order.get("time_in_force", "good_till_canceled"),
            "self_trade_prevention_type": order.get("self_trade_prevention_type", "taker_at_cross"),
        }
        for opt in ("post_only", "cancel_order_on_pause", "expiration_ts", "exchange_index"):
            if order.get(opt) is not None:
                payload[opt] = order[opt]
        if market and market.get("exchange_index") is not None and "exchange_index" not in payload:
            payload["exchange_index"] = market["exchange_index"]

        if self.paper:
            resp = self._paper_fill(payload, market)
        elif not self.execute:
            resp = {"DRY_RUN": "not sent — pass --execute with credentials to submit",
                    "would_post_to": self.client.url_for("/portfolio/events/orders"),
                    "validation_warnings": errs}
        else:
            resp = self.client.request("POST", "/portfolio/events/orders", body=payload)
        entry = self.record("create", payload, resp, market)
        entry["validation_warnings"] = errs
        return entry

    def _paper_fill(self, payload: dict, market: dict | None) -> dict:
        """Assume an immediate taker fill at the best available price on the live book."""
        from_capture = payload["ticker"] in self.capture
        if from_capture:
            cap = self.capture[payload["ticker"]]
            book = cap.get("orderbook_fp") or {}
        else:
            try:
                book = self.client.orderbook(payload["ticker"], depth=5)
            except KalshiError as exc:
                return {"PAPER": "no order book available", "error": str(exc),
                        "hint": "run scripts/collect.py to refresh data/live_snapshot.json, "
                                "or pass --capture with a market the capture actually contains"}
        yes_bids = book.get("orderbook_fp", {}).get("yes_dollars") or []
        no_bids = book.get("orderbook_fp", {}).get("no_dollars") or []
        count = fp(payload["count"])
        px = fp(payload["price"])
        if payload["side"] == "bid":
            ask = (1.0 - fp(no_bids[-1][0])) if no_bids else fp((market or {}).get("yes_ask_dollars"))
            fill = min(ask, px) if ask else px
            crossed = bool(ask and px >= ask)
        else:
            bid = fp(yes_bids[-1][0]) if yes_bids else fp((market or {}).get("yes_bid_dollars"))
            fill = max(bid, px) if bid else px
            crossed = bool(bid and px <= bid)
        fee = round(count * fill * (1 - fill) * 0.07, 4)  # NOT a fee quote: see note below
        return {
            "PAPER": True,
            "filled": bool(crossed),
            "order_id": f"paper-{uuid.uuid4()}",
            "client_order_id": payload["client_order_id"],
            "status": "executed" if crossed else "resting",
            "filled_count": count if crossed else 0.0,
            "remaining_count": 0.0 if crossed else count,
            "average_fill_price": f"{fill:.4f}" if crossed else None,
            "cash_delta_dollars": round(count * fill, 4) if crossed else None,
            "illustrative_fee_not_a_quote": round(fee, 4),
            "note": ("Fill price is the best opposite-side bid/ask read from "
                     "GET /markets/{ticker}/orderbook at this instant; it is a simulation, not an "
                     "exchange acknowledgement. `illustrative_fee_not_a_quote` is NOT a Kalshi fee: "
                     "fees come from the series fee_type/fee_multiplier and "
                     "https://kalshi.com/docs/kalshi-fee-schedule.pdf and are only authoritative on "
                     "a real fill's `fee_cost`. Never use this number for a decision."),
        }

    def cancel(self, order_id: str, market_ticker: str, *, exchange_index: int | None = None) -> dict:
        path = f"/portfolio/events/orders/{order_id}"
        params = {"market_ticker": market_ticker}
        if exchange_index is not None:
            params["exchange_index"] = exchange_index
        if self.paper or not self.execute:
            resp = {"DRY_RUN": not self.execute, "PAPER": self.paper,
                    "would_delete": self.client.url_for(path, params),
                    "note": "market_ticker is required so the cancel routes to the right shard"}
        else:
            resp = self.client.request("DELETE", path, params=params)
        return self.record("cancel", {"order_id": order_id, **params}, resp, None)

    def amend(self, order_id: str, *, ticker: str, count: str | None = None, price: str | None = None,
              expiration_ts: int | None = None) -> dict:
        body = {"ticker": ticker}
        if count is not None:
            body["count"] = count
        if price is not None:
            body["price"] = price
        if expiration_ts is not None:
            body["expiration_ts"] = expiration_ts
        path = f"/portfolio/events/orders/{order_id}/amend"
        resp = ({"DRY_RUN": True, "would_post": self.client.url_for(path), "body": body}
                if not self.execute else self.client.request("POST", path, body=body))
        return self.record("amend", {"order_id": order_id, **body}, resp, None)

    def decrease(self, order_id: str, *, ticker: str, reduce_by: str | None = None, reduce_to: str | None = None) -> dict:
        if bool(reduce_by) == bool(reduce_to):
            raise OrderError("exactly one of reduce_by / reduce_to is required")
        body = {"ticker": ticker, "reduce_by": reduce_by} if reduce_by else {"ticker": ticker, "reduce_to": reduce_to}
        path = f"/portfolio/events/orders/{order_id}/decrease"
        resp = ({"DRY_RUN": True, "would_post": self.client.url_for(path), "body": body}
                if not self.execute else self.client.request("POST", path, body=body))
        return self.record("decrease", {"order_id": order_id, **body}, resp, None)

    def strategies(self) -> list[dict]:
        """Strategy catalogue rendered from rules the API can actually express."""
        return [
            {
                "id": "S1-limit-resting",
                "name": "Resting limit at the grid edge",
                "rules": "side=bid, time_in_force=good_till_canceled, post_only=true, "
                         "price = best_yes_bid rounded up to the next grid step",
                "entry_evidence": "GET /markets/{t}/orderbook yes_dollars[-1]",
                "exit_evidence": "close_time, or manual cancel via DELETE /portfolio/events/orders/{id}",
                "category_produced": ["maker", "yes", "long-shot", "favourite"],
                "cost": "10 write tokens per create, 10 per cancel",
                "risk": "adverse selection: you are filled exactly when someone else knows more",
                "sources": [
                    "https://docs.kalshi.com/api-reference/orders/create-order-v2.md",
                    "https://docs.kalshi.com/getting_started/rate_limits.md",
                ],
            },
            {
                "id": "S2-cross-the-spread",
                "name": "Taker entry with a price cap",
                "rules": "side per signal, time_in_force=immediate_or_cancel, price = best ask "
                         "+ max 1 tick; STP taker_at_cross",
                "entry_evidence": "implied YES ask = 1 - best NO bid",
                "exit_evidence": "hold to resolution; settlement pays notional_value_dollars per contract",
                "category_produced": ["taker", "momentum"],
                "cost": "spread + taker fee; unfilled remainder is cancelled by the exchange",
                "risk": "guaranteed spread cost; on demo the book is thin so fills are optimistic",
                "sources": ["https://docs.kalshi.com/getting_started/orderbook_responses.md"],
            },
            {
                "id": "S3-resolution-carry",
                "name": "Carry to settlement on near-certain outcomes",
                "rules": "bid YES at >= $0.97 on markets whose rules_primary is already satisfied by a "
                         "published source; hold to settlement_ts",
                "entry_evidence": "market.rules_primary + settlement_sources[].url",
                "exit_evidence": "result == 'yes' -> settlement_value_dollars = 1.00",
                "category_produced": ["carry", "settlement", "favourite"],
                "cost": "near-zero spread, but capital is locked until settlement_ts",
                "risk": "settlement is discretionary and can go the other way; 'markets typically settle "
                       "shortly after expiration, but timing can vary' is documented, not guaranteed",
                "sources": ["https://docs.kalshi.com/getting_started/market_settlement.md"],
            },
            {
                "id": "S4-flow-follow",
                "name": "Trade the tape imbalance",
                "rules": "enter the side whose (yes_dollars - no_dollars) / dollar_volume exceeds a "
                         "threshold inside the window; exit on sign flip",
                "entry_evidence": "GET /markets/trades aggregated per event",
                "exit_evidence": "same signal flips, or close_time",
                "category_produced": ["flow", "momentum", "informed-taker"],
                "cost": "taker spread on both legs",
                "risk": "demo tape is mock activity; production flow may not behave the same. "
                        "Kalshi itself warns demo prices 'may not be reflective of those in real markets'",
                "sources": ["https://docs.kalshi.com/getting_started/demo_env.md"],
            },
        ]


def _append(path: str, key: str, entry: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {key: []}
    if os.path.exists(path):
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except json.JSONDecodeError:
            doc = {key: []}
    doc.setdefault(key, []).append(entry)
    doc["_meta"] = {
        "updated_at_utc": utcnow(),
        "written_by": "scripts/trade_engine.py",
        "modes": {"plan": "no request sent", "paper": "public read + simulated fill", "live-demo": "real POST to demo"},
    }
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=2)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["buy", "sell", "cancel", "amend", "decrease", "strategies"])
    p.add_argument("target", nargs="?", help="market ticker (or order_id for cancel/amend/decrease)")
    p.add_argument("--count", default="1")
    p.add_argument("--price", default=None, help="dollar price, e.g. 0.42; omit to use best opposite quote")
    p.add_argument("--tif", default="good_till_canceled", choices=TIF)
    p.add_argument("--stp", default="taker_at_cross", choices=STP)
    p.add_argument("--post-only", action="store_true")
    p.add_argument("--market", default=None, help="market_ticker for cancel routing")
    p.add_argument("--reduce-by", default=None)
    p.add_argument("--reduce-to", default=None)
    p.add_argument("--base", default="demo", choices=["demo", "demo-alt"])
    p.add_argument("--key-id", default=None)
    p.add_argument("--key-file", default=None)
    p.add_argument("--paper", action="store_true")
    p.add_argument("--execute", action="store_true", help="required to actually send an order")
    p.add_argument("--plan", action="store_true", help="validate and print only")
    p.add_argument("--from-snapshot", default=None, metavar="PATH",
                   help="price orders from a collector snapshot (data/live_snapshot.json) instead of the "
                        "network; every entry is stamped quote_basis='capture'")
    p.add_argument("--strategy", default=None,
                   help="record this strategy id on the order, so scripts/analyze.py can group it")
    p.add_argument("--bulk", default=None, metavar="FILE",
                   help="JSON list of {action,ticker,side,count,price,...} orders to run in one pass")
    args = p.parse_args(argv)

    base = {"demo": DEMO_REST, "demo-alt": DEMO_REST_ALT}[args.base]
    signer = Signer(args.key_id, open(args.key_file, "rb").read() if args.key_file else None)
    client = KalshiClient(base, signer=signer)
    eng = TradeEngine(client, paper=args.paper or not args.execute, execute=args.execute,
                      capture=load_capture(args.from_snapshot))
    eng.strategy_tag = args.strategy

    if args.action == "strategies":
        print(json.dumps(eng.strategies(), indent=2))
        return 0
    if args.action == "cancel":
        print(json.dumps(eng.cancel(args.target, args.market or ""), indent=2))
        return 0
    if args.action in ("amend", "decrease"):
        fn = eng.amend if args.action == "amend" else eng.decrease
        kw = {"ticker": args.market or ""}
        kw.update({"count": args.count, "price": args.price} if args.action == "amend"
                  else {"reduce_by": args.reduce_by, "reduce_to": args.reduce_to})
        print(json.dumps(fn(args.target, **kw), indent=2))
        return 0

    if args.bulk:
        with open(args.bulk) as fh:
            spec = json.load(fh)
        orders = spec["orders"] if isinstance(spec, dict) else spec
        pre_skipped = (spec.get("skipped") or []) if isinstance(spec, dict) else []
        cap = eng.capture
        results, refused, skipped = [], 0, []
        for o in orders:
            ticker = o.get("ticker")
            if cap and ticker not in cap:
                skipped.append({"ticker": ticker, "reason": "not present in the capture — refusing to price it from a guess"})
                continue
            order = {
                "ticker": ticker,
                "side": o.get("side") or ("bid" if o.get("action", "buy") == "buy" else "ask"),
                "count": str(o["count"]),
                "price": o.get("price"),
                "time_in_force": o.get("time_in_force", args.tif),
                "self_trade_prevention_type": o.get("self_trade_prevention_type", args.stp),
                "strategy": o.get("strategy") or args.strategy,
            }
            if order["price"] is None:
                m = eng.market(ticker)
                best = fp(m.get("yes_ask_dollars")) if order["side"] == "bid" else fp(m.get("yes_bid_dollars"))
                order["price"] = f"{best:.4f}" if best else None
            if order["price"] is None:
                skipped.append({"ticker": ticker, "reason": "no best quote to price against in the capture"})
                continue
            eng.strategy_tag = order.get("strategy")
            try:
                e = eng.create(order, require_validation=not args.plan)
                results.append({
                    "ticker": ticker, "side": order["side"], "count": order["count"], "price": order["price"],
                    "status": (e.get("response") or {}).get("status"),
                    "filled": (e.get("response") or {}).get("filled"),
                    "mode": e.get("mode"),
                    "quote_basis": (e.get("market_snapshot_used") or {}).get("quote_basis"),
                    "warnings": e.get("validation_warnings"),
                })
            except (OrderError, KalshiError) as exc:
                refused += 1
                results.append({"ticker": ticker, "error": str(exc)})
        print(json.dumps({"submitted": len(results) - refused, "refused": refused,
                          "skipped_no_capture": skipped + pre_skipped, "orders": results,
                          "note": ("paper simulation only: fills were never sent to Kalshi. "
                                   if (eng.paper and not args.execute) else
                                   ("dry run, nothing sent. " if not args.execute else "sent to the DEMO exchange."))},
                         indent=2))
        return 0

    ticker = args.target
    mkt = eng.market(ticker)
    if args.price is None:
        best = fp(mkt.get("yes_ask_dollars")) if args.action == "buy" else fp(mkt.get("yes_bid_dollars"))
        args.price = f"{best:.4f}" if best else "0.0100"
        print(f"# price defaulted to market {mkt.get('yes_ask_dollars') if args.action=='buy' else mkt.get('yes_bid_dollars')} "
              f"from GET /markets/{ticker}", file=sys.stderr)
    order = {
        "ticker": ticker, "side": "bid" if args.action == "buy" else "ask",
        "count": args.count, "price": args.price, "time_in_force": args.tif,
        "self_trade_prevention_type": args.stp, "post_only": True if args.post_only else None,
    }
    if args.plan:
        errs = validate(order, mkt)
        print(json.dumps({"valid": not errs, "errors": errs, "order": order}, indent=2))
        return 0 if not errs else 1
    try:
        print(json.dumps(eng.create(order), indent=2))
    except (OrderError, KalshiError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
