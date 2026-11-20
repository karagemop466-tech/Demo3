"""
portfolio.py — demo-account portfolio ledger + performance, built only from API fields.

Reads (all signed, all documented):
  GET /portfolio/balance      balance (cents), balance_dollars (fp string), portfolio_value (cents),
                              updated_ts, balance_breakdown[]
                              https://docs.kalshi.com/api-reference/portfolio/get-balance.md
  GET /portfolio/positions    unsettled positions        https://docs.kalshi.com/api-reference/portfolio/get-positions.md
  GET /portfolio/fills        fill_id, order_id, ticker, outcome_side, book_side, count_fp,
                              yes_price_dollars, no_price_dollars, is_taker, created_time, fee_cost
                              https://docs.kalshi.com/api-reference/portfolio/get-fills.md
  GET /portfolio/settlements  settlement records         https://docs.kalshi.com/api-reference/portfolio/get-settlements.md
  GET /portfolio/orders       order history              https://docs.kalshi.com/api-reference/orders/get-orders.md

Accounting model (documented, not invented):
  * one contract pays `notional_value_dollars` to the winning side (verified "1.0000" on every
    market sampled live; payout rule in https://docs.kalshi.com/getting_started/market_settlement.md)
  * a fill with book_side='bid' buys YES  (cash out  = count x yes_price)
    a fill with book_side='ask' sells YES  (cash in   = count x yes_price)
    buy-NO / sell-NO are the mirror image; the API quotes only the YES leg
  * at settlement: cash += yes_qty x settlement_value_dollars, then yes_qty -> 0
  * fees are taken from the fill's own `fee_cost`; this module never estimates a fee

Without credentials this module reads data/paper_ledger.json instead and labels every number
`source_mode: "paper"`. It never prints a zero as if it were a measured balance.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kalshi_api import DEMO_REST, KalshiClient, KalshiError, Signer, fp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LEDGER_PATH = os.path.join(DATA, "portfolio_ledger.json")
PAPER_PATH = os.path.join(DATA, "paper_ledger.json")
ORDERS_PATH = os.path.join(DATA, "orders.json")   # raw log of every create/amend/cancel this repo recorded

FILL_ALIASES = {
    "fill_id": ("fill_id", "trade_id"),
    "order_id": ("order_id",),
    "ticker": ("ticker", "market_ticker"),
    "outcome_side": ("outcome_side", "side"),
    "book_side": ("book_side",),
    "count_fp": ("count_fp", "count"),
    "yes_price_dollars": ("yes_price_dollars", "price_dollars"),
    "no_price_dollars": ("no_price_dollars",),
    "is_taker": ("is_taker",),
    "fee_cost": ("fee_cost",),
    "created_time": ("created_time", "ts"),
}


def pick(record: dict, names: tuple[str, ...]) -> Any:
    for n in names:
        if n in record and record[n] not in (None, ""):
            return record[n]
    return None


def normalise_fill(raw: dict, *, source: str) -> dict:
    out = {alias: pick(raw, names) for alias, names in FILL_ALIASES.items()}
    out["unmapped_keys"] = sorted(set(raw) - {n for names in FILL_ALIASES.values() for n in names})
    out["source"] = source
    out["observed_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


class Portfolio:
    """Signed-state portfolio reader with a paper fallback."""

    def __init__(self, client: KalshiClient):
        self.client = client
        self.signer: Signer = client.signer

    @property
    def live(self) -> bool:
        return self.signer.enabled

    # ------------------------------------------------------------------ sources
    def fetch(self, *, pages: int = 5, limit: int = 1000) -> dict:
        if not self.live:
            return self.load_paper()
        fills: list[dict] = []
        cursor = ""
        for _ in range(pages):
            data = self.client.request("GET", "/portfolio/fills",
                                       params={"limit": limit, "cursor": cursor or None})
            fills.extend(data.get("fills", []))
            cursor = data.get("cursor") or ""
            if not cursor:
                break
        positions = self.client.request("GET", "/portfolio/positions").get("positions", [])
        settlements = self.client.request("GET", "/portfolio/settlements").get("settlements", [])
        balance = self.client.request("GET", "/portfolio/balance")
        return {
            "source_mode": "demo-live",
            "balance": {
                "available_balance_dollars": balance.get("balance_dollars"),
                "available_balance_cents": balance.get("balance"),
                "portfolio_value_cents": balance.get("portfolio_value"),
                "portfolio_value_dollars": fp(balance.get("portfolio_value")) / 100.0 if balance.get("portfolio_value") is not None else None,
                "updated_ts": balance.get("updated_ts"),
                "breakdown": balance.get("balance_breakdown"),
                "source": self.client.url_for("/portfolio/balance"),
                "note": "portfolio_value has no documented *_dollars sibling; the dollars figure is cents/100 — labelled derived",
            },
            "fills": [normalise_fill(f, source=self.client.url_for("/portfolio/fills")) for f in fills],
            "positions": positions,
            "settlements": settlements,
            "collected_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def load_paper(self) -> dict:
        """Paper fills produced by trade_engine.py --paper, mapped through the same schema."""
        rows: list[dict] = []
        # paper_ledger.json is written by trade_engine.py; if only the raw order log exists, read that
        src = PAPER_PATH if os.path.exists(PAPER_PATH) else ORDERS_PATH
        if os.path.exists(src):
            with open(src) as fh:
                for o in json.load(fh).get("orders", []):
                    resp = o.get("response") or {}
                    if not resp.get("filled") or o.get("mode") != "paper":
                        continue   # a plan/dry-run entry is not a fill and never becomes one
                    # prefer the simulated print price; the limit price is only a fallback
                    yes_px = fp(resp.get("average_fill_price")) or fp(o["request"]["price"])
                    rows.append({
                        "fill_id": resp.get("order_id"),
                        "order_id": resp.get("order_id"),
                        "ticker": o["request"]["ticker"],
                        "outcome_side": "yes" if o["request"]["side"] == "bid" else "no",
                        "book_side": o["request"]["side"],
                        "count_fp": resp.get("filled_count"),
                        "yes_price_dollars": f"{yes_px:.4f}",
                        "no_price_dollars": f"{1 - yes_px:.4f}",
                        "is_taker": True,
                        "fee_cost": None,   # never estimated — real fills carry fee_cost
                        "created_time": o.get("submitted_at_utc"),
                        "unmapped_keys": [],
                        "source": os.path.relpath(src, ROOT) + " (simulated against the public book)",
                        "observed_at_utc": o.get("submitted_at_utc"),
                        "strategy": o.get("strategy"),
                        "is_paper": True,
                        "quote_basis": (o.get("market_snapshot_used") or {}).get("quote_basis") or "live",
                    })
        return {
            "source_mode": "paper",
            "balance": None,
            "fills": rows,
            "paper_source_file": os.path.relpath(src, ROOT) if os.path.exists(src) else None,
            "positions": [],
            "settlements": [],
            "collected_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "empty_reason": ("No demo API key configured, so /portfolio/* was never called. "
                             "Create one at https://demo.kalshi.co/ — "
                             "https://docs.kalshi.com/getting_started/demo_env.md") if not rows else (
                "Ledger built by scripts/trade_engine.py --paper: fills are SIMULATED against public "
                "quotes and are not exchange acknowledgements. See flagged.html."),
            "simulated": True,
        }

    # ------------------------------------------------------------------ maths
    @staticmethod
    def compute(fills: list[dict], *, marks: dict[str, float] | None = None,
                settlements: dict[str, dict] | None = None, notional: float = 1.0) -> dict:
        marks = marks or {}
        settlements = settlements or {}
        pos: dict[str, dict] = defaultdict(lambda: {"yes_qty": 0.0, "cash": 0.0, "fees": 0.0,
                                                     "fills": 0, "notional_cost": 0.0})
        for f in fills:
            tkr = f.get("ticker")
            if not tkr:
                continue
            p = pos[tkr]
            qty = fp(f.get("count_fp"))
            px = fp(f.get("yes_price_dollars"))
            fee = fp(f.get("fee_cost"))
            p["fills"] += 1
            p["fees"] += fee
            if f.get("book_side") == "ask":
                p["yes_qty"] -= qty
                p["cash"] += qty * px
                p["notional_cost"] -= qty * px
            else:
                p["yes_qty"] += qty
                p["cash"] -= qty * px
                p["notional_cost"] += qty * px

        rows = []
        total_unreal = total_real = total_fees = 0.0
        settled_qty = 0.0
        for tkr, p in pos.items():
            mark = marks.get(tkr)
            s = settlements.get(tkr)
            cost_basis = p["notional_cost"]
            if s is not None:
                sv = fp(s.get("settlement_value_dollars"))
                realized = p["cash"] + p["yes_qty"] * sv - p["fees"]
                rows.append({
                    "ticker": tkr, "state": "settled", "yes_qty": p["yes_qty"],
                    "settled_from_yes_qty": p["yes_qty"],
                    "net_cash": round(p["cash"], 4), "fees": round(p["fees"], 4),
                    "settlement_value_dollars": s.get("settlement_value_dollars"),
                    "result": s.get("result"), "settlement_ts": s.get("settlement_ts"),
                    "realized_pnl": round(realized, 4), "unrealized_pnl": 0.0,
                })
                settled_qty += abs(p["yes_qty"])
                p["cash"] += p["yes_qty"] * sv
                p["yes_qty"] = 0.0
                total_real += realized
                continue
            unreal = (p["yes_qty"] * mark - cost_basis) if mark is not None else None
            rows.append({
                "ticker": tkr, "state": "open", "yes_qty": round(p["yes_qty"], 4),
                "net_cash": round(p["cash"], 4), "fees": round(p["fees"], 4),
                "mark_dollars": mark,
                "unrealized_pnl": round(unreal, 4) if unreal is not None else None,
                "realized_pnl": 0.0,
                "mark_source": "GET /markets/{ticker}.last_price_dollars" if mark is not None else None,
            })
            if unreal is not None:
                total_unreal += unreal
        total_fees = sum(p["fees"] for p in pos.values())
        return {
            "positions": rows,
            "totals": {
                "realized_pnl_dollars": round(total_real, 4),
                "unrealized_pnl_dollars": round(total_unreal, 4),
                "total_pnl_dollars": round(total_real + total_unreal, 4),
                "fees_paid_dollars": round(total_fees, 4),
                "settled_contract_qty": round(settled_qty, 4),
                "fills": len(fills),
                "notional_value_dollars_used": notional,
            },
            "method": {
                "cash": "buy YES: -count x yes_price | sell YES: +count x yes_price",
                "settlement": "cash += yes_qty x settlement_value_dollars",
                "unrealized": "yes_qty x mark - cost_basis",
                "fees": "sum of fill.fee_cost; never estimated",
                "sources": [
                    "https://docs.kalshi.com/api-reference/portfolio/get-fills.md",
                    "https://docs.kalshi.com/getting_started/market_settlement.md",
                    "https://docs.kalshi.com/api-reference/market/get-market.md",
                ],
            },
        }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="refresh", choices=["refresh", "show", "marks"])
    p.add_argument("--base", default="demo")
    p.add_argument("--pages", type=int, default=5)
    p.add_argument("--tickers", default="", help="comma list to mark against live prices")
    p.add_argument("--marks-from-snapshot", default=None, metavar="PATH",
                   help="mark positions from a collector snapshot instead of the network "
                        "(data/live_snapshot.json); each mark keeps the URL of the API read it came from")
    args = p.parse_args(argv)

    client = KalshiClient(DEMO_REST, signer=Signer())
    pf = Portfolio(client)
    data = pf.fetch(pages=args.pages)

    marks: dict[str, float] = {}
    mark_meta: dict[str, dict] = {}
    if args.marks_from_snapshot:
        with open(args.marks_from_snapshot) as fh:
            snap = json.load(fh)
        for ev in snap.get("ranked_events", []) or []:
            for m in ev.get("markets", []) or []:
                lp = fp(m.get("last_price_dollars"))
                if lp is not None:
                    marks[m["ticker"]] = lp
                    mark_meta[m["ticker"]] = {"mark_source": "capture", "source": m.get("source"),
                                              "captured_at": (snap.get("_meta") or {}).get("generated_at_utc")}
        print(f"# marks loaded from {args.marks_from_snapshot}: {len(marks)} markets "
              "(last_price_dollars as recorded by the collector — not a live price)", file=sys.stderr)
    tickers = [t for t in args.tickers.split(",") if t]
    if args.cmd == "marks" or tickers:
        for t in tickers or [f["ticker"] for f in data["fills"] if f.get("ticker")]:
            try:
                marks[t] = fp(client.market(t).get("last_price_dollars"))
                mark_meta[t] = {"mark_source": "live", "source": client.url_for(f"/markets/{t}")}
            except KalshiError as exc:
                print(f"  ! mark {t}: {exc}", file=sys.stderr)
    settlements = {}
    res_path = os.path.join(DATA, "resolutions.json")
    if os.path.exists(res_path):
        with open(res_path) as fh:
            settlements = {r["ticker"]: r for r in json.load(fh).get("resolutions", []) if r.get("result")}

    perf = Portfolio.compute(data["fills"], marks=marks, settlements=settlements)
    for pos in perf.get("positions", []):
        meta = mark_meta.get(pos.get("ticker")) or {}
        if meta and pos.get("mark_dollars") is not None:
            pos["mark_source"] = meta["mark_source"]
            pos["mark_quote_source"] = meta.get("source")
            pos["mark_captured_at_utc"] = meta.get("captured_at")
        elif pos.get("mark_dollars") is None:
            pos["mark_note"] = ("no mark available: the market is absent from the capture and the API was "
                                "unreachable, so unrealised P&L stays blank rather than being assumed 0")
    perf["marks_used"] = len(marks)
    perf["mark_basis"] = ("capture: last_price_dollars from data/live_snapshot.json" if args.marks_from_snapshot
                          else ("live: GET /markets/{ticker}" if marks else "none: no marks were available"))
    data["performance"] = perf
    os.makedirs(DATA, exist_ok=True)
    with open(LEDGER_PATH, "w") as fh:
        json.dump(data, fh, indent=2)
    print(json.dumps({"source_mode": data["source_mode"],
                      "fills": len(data["fills"]),
                      "totals": data["performance"]["totals"],
                      "written": LEDGER_PATH}, indent=2))
    if data["source_mode"] == "paper":
        print("\nNOTE: paper mode — " + data["empty_reason"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
