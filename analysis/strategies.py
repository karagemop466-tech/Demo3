#!/usr/bin/env python3
"""
Derives transparent, rule-based order/strategy candidates and simulations from the CURRENT
market snapshot. Nothing here places an order and nothing is a prediction of profit.

Two outputs:

  data/order-rules.json
      A machine-readable set of candidate orders (side, action, price band, size) generated
      only from fields present in the API response (price, spread, resting depth, volume,
      open interest, time to close). Each rule prints its own formula and the market fields
      it used. The portfolio workflow can consume this file when demo trading is enabled.

  data/strategy-sim.json
      A clearly-labelled SIMULATION of what those rules would have cost on the current
      orderbook: how many contracts the book could actually fill at or better than the target
      price, and the implied payout at settlement for YES=1.00 / NO=0.00. It is not a backtest
      and not a forecast; the P&L column assumes settlement at 1.00 or 0.00, which is the
      contract's definition, so the "outcome" is the unknown, not the arithmetic.

Rules (all thresholds are policy choices documented in docs/portfolio/STRATEGY.md):
  R1 value-favourite   : yes_ask <= 0.90 and open interest > 0 and spread <= 0.04
  R2 longshot-fade     : no_ask  <= 0.90 and volume_24h > 0 and spread <= 0.04
  R3 liquidity-provide : no candidate — requires resting orders and maker fees, see docs
  R4 avoid             : spread > 0.10 or resting depth < $50 -> no trade, listed as skipped

Why R3 does not generate orders: placing a resting limit order changes the book and depends on
maker fee treatment, which differs by series (`fee_type`); recommending it without a fill model
would be a guess. It is documented as a manual option instead.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MAX_PRICE = 0.90
MAX_SPREAD = 0.04
MIN_DEPTH = 50.0
SIZE_CONTRACTS = 10


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fillable(ladder: list, side: str, limit_price: float | None) -> tuple[float, float]:
    """How many contracts the current book shows at or better than `limit_price`, and cost.

    For a YES buy we can take NO bids as our counterparties at 1 - no_bid (an implied YES ask),
    so we walk the NO ladder from the best (highest) price down while 1 - price <= limit.
    Returns (contracts, cost_dollars). Uses only the ladder the API returned.
    """
    other = "no" if side == "yes" else "yes"
    levels = [l for l in ladder if l.get("side") == other]
    levels.sort(key=lambda l: l.get("price") or 0, reverse=True)
    contracts = 0.0
    cost = 0.0
    for level in levels:
        price = num(level.get("price"))
        count = num(level.get("contracts")) or 0.0
        if price is None:
            continue
        ask = round(1 - price, 4)
        if limit_price is not None and ask > limit_price + 1e-9:
            continue
        contracts += count
        cost += ask * count
    return round(contracts, 2), round(cost, 2)


def main() -> int:
    dash_path = DATA / "dashboard.json"
    if not dash_path.exists():
        print("data/dashboard.json missing; run analysis/build.py first")
        return 1
    dash = json.loads(dash_path.read_text(encoding="utf-8"))
    ladders = dash.get("ladders") or {}
    tables = dash.get("tables") or {}

    candidates: list[dict] = []
    skipped: list[dict] = []
    for topic, groups in tables.items():
        for row in groups.get("by_contracts_traded") or []:
            ticker = row["ticker"]
            book = ladders.get(ticker)
            if not book:
                skipped.append({"ticker": ticker, "topic": topic,
                                "reason": "no orderbook snapshot for this market "
                                          "(only the top markets by volume are sampled)"})
                continue
            bid = num(book.get("best_yes_bid"))
            ask = num(book.get("best_yes_ask_derived"))
            spread = num(book.get("spread_yes_derived"))
            depth = num(book.get("total_resting_dollars"))
            oi = num(row.get("open_interest_fp"))
            vol24 = num(row.get("volume_24h_fp"))

            if spread is not None and spread > 0.10:
                skipped.append({"ticker": ticker, "topic": topic,
                                "reason": f"spread {spread:.2f} > 0.10 — R4 avoid"})
                continue
            if depth is not None and depth < MIN_DEPTH:
                skipped.append({"ticker": ticker, "topic": topic,
                                "reason": f"resting depth ${depth:.2f} < ${MIN_DEPTH:.0f} — R4 avoid"})
                continue
            if spread is None:
                skipped.append({"ticker": ticker, "topic": topic,
                                "reason": "spread not derivable (one side of the book is empty)"})
                continue

            if ask is not None and ask <= MAX_PRICE and (oi or 0) > 0 and spread <= MAX_SPREAD:
                contracts, cost = fillable(book["ladder"], "yes", ask)
                candidates.append({
                    "rule": "R1_value_favourite",
                    "rule_text": "buy YES at or below the current implied ask when ask <= 0.90, "
                                 "open interest > 0 and derived spread <= 0.04",
                    "ticker": ticker,
                    "topic": topic,
                    "title": row.get("title"),
                    "side": "yes",
                    "action": "buy",
                    "limit_price": ask,
                    "size_contracts": min(SIZE_CONTRACTS, int(contracts)) if contracts else 0,
                    "book_contracts_available": contracts,
                    "immediate_cost_dollars": cost,
                    "inputs": {"implied_yes_ask": ask, "best_yes_bid": bid, "spread": spread,
                               "resting_depth_dollars": depth, "open_interest": oi,
                               "volume_24h": vol24, "close_time": row.get("close_time")},
                    "source": row.get("orderbook_source"),
                })

            no_ask = num(book.get("best_no_ask_derived"))
            if no_ask is not None and no_ask <= MAX_PRICE and (vol24 or 0) > 0 and spread <= MAX_SPREAD:
                contracts, cost = fillable(book["ladder"], "no", no_ask)
                candidates.append({
                    "rule": "R2_longshot_fade",
                    "rule_text": "buy NO at or below the current implied ask when no_ask <= 0.90, "
                                 "24h volume > 0 and derived spread <= 0.04",
                    "ticker": ticker,
                    "topic": topic,
                    "title": row.get("title"),
                    "side": "no",
                    "action": "buy",
                    "limit_price": no_ask,
                    "size_contracts": min(SIZE_CONTRACTS, int(contracts)) if contracts else 0,
                    "book_contracts_available": contracts,
                    "immediate_cost_dollars": cost,
                    "inputs": {"implied_no_ask": no_ask, "best_no_bid": num(book.get("best_no_bid")),
                               "spread": spread, "resting_depth_dollars": depth,
                               "volume_24h": vol24, "close_time": row.get("close_time")},
                    "source": row.get("orderbook_source"),
                })

    # de-duplicate on (rule, ticker)
    seen = set()
    uniq = []
    for c in candidates:
        key = (c["rule"], c["ticker"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    uniq.sort(key=lambda c: (c["limit_price"] or 1) * (c["size_contracts"] or 0), reverse=True)

    sim_rows = []
    for c in uniq[:40]:
        size = c["size_contracts"] or 0
        if not size:
            continue
        price = c["limit_price"]
        cost = round(price * size, 2)
        payout = float(size)            # 1.00 per contract if the side wins
        sim_rows.append({
            "rule": c["rule"], "ticker": c["ticker"], "side": c["side"],
            "contracts": size, "entry_price": price, "cost_dollars": cost,
            "payout_if_win_dollars": payout,
            "profit_if_win_dollars": round(payout - cost, 2),
            "loss_if_lose_dollars": round(-cost, 2),
            "breakeven_probability": round(cost / payout, 4) if payout else None,
            "note": "Arithmetic only. Kalshi contracts pay 1.00 if the side resolves YES, else 0. "
                    "Fees are excluded because fee treatment depends on the series `fee_type` and "
                    "must be computed per the official fee schedule before trading.",
        })

    breakevens = [r["breakeven_probability"] for r in sim_rows if r["breakeven_probability"]]
    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": {
            "max_price": MAX_PRICE, "max_spread": MAX_SPREAD,
            "min_resting_depth_dollars": MIN_DEPTH, "size_contracts": SIZE_CONTRACTS,
            "where": "docs/portfolio/STRATEGY.md",
        },
        "candidates": uniq,
        "skipped": skipped[:80],
        "simulation": {
            "rows": sim_rows,
            "summary": {
                "candidates": len(uniq),
                "simulated": len(sim_rows),
                "total_cost_dollars": round(sum(r["cost_dollars"] for r in sim_rows), 2),
                "median_breakeven_probability":
                    round(statistics.median(breakevens), 4) if breakevens else None,
            },
            "disclaimer": "Simulation, not a forecast or backtest. It answers 'what would these "
                          "orders cost right now given the visible book' and nothing more. The "
                          "probability that the market resolves in your favour is not knowable "
                          "from this dataset.",
        },
    }
    (DATA / "order-rules.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({"candidates": len(uniq), "simulated": len(sim_rows),
                      "skipped": len(skipped)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
