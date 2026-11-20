"""
analyze.py — categorise fills and evaluate the strategy catalogue.

Input:  data/portfolio_ledger.json (from portfolio.py) — demo-live fills or paper fills.
Output: data/analysis.json — per-trade categories, per-category performance, and a
        scoreboard per strategy with the metric that would confirm or refute it.

Categorisation uses ONLY fields the API returns; every dimension names its source field.
An unmappable field lands in `unresolved_fields` rather than being guessed.

Dimensions
  direction      from Fill.book_side ('bid' -> buy_yes, 'ask' -> sell_yes)
  liquidity      from Fill.is_taker  (true -> taker, false -> maker)
  size_bucket    from Fill.count_fp  (fixed thresholds, stated in the output)
  price_bucket   from Fill.yes_price_dollars (long-shot <0.10, mid 0.10-0.90, fav >0.90)
  edge_bps       yes_ask - yes_bid at the market read, when available
  time_bucket    created_time -> hour-of-day UTC and day-of-week (no calendar assumptions)
  horizon        close_time - created_time buckets (from GET /markets)
  topic          series prefix -> /series category+tags (via data/live_snapshot.json universe)
  outcome        market result at settlement ('yes'/'no'/None)
  block          is_block_trade where present

Field source: https://docs.kalshi.com/api-reference/portfolio/get-fills.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kalshi_api import DEMO_REST, KalshiClient, KalshiError, fp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

SIZE_BUCKETS = ((10, "micro<10"), (100, "small 10-100"), (1000, "medium 100-1k"), (float("inf"), "large >1k"))
HORIZON_BUCKETS = ((3600, "<1h"), (86400, "1h-1d"), (604800, "1-7d"), (float("inf"), ">7d"))


def utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def bucket(v: float, table) -> str:
    for limit, name in table:
        if v < limit:
            return name
    return table[-1][1]


def price_bucket(p: float) -> str:
    if p < 0.10:
        return "long-shot <10c"
    if p > 0.90:
        return "favourite >90c"
    return "mid 10-90c"


def seconds_between(a: datetime | None, b: datetime | None) -> float | None:
    if not a or not b:
        return None
    return (b - a).total_seconds()


def load(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def build_topic_lookup(snapshot: dict | None, topics_cfg: dict | None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in (snapshot or {}).get("series_universe", []) or []:
        lookup[row["series_ticker"]] = row["topic"]
    for topic in (topics_cfg or {}).get("topics", []):
        for pref in topic.get("ticker_prefixes", []):
            lookup.setdefault(pref, topic["id"])
    return lookup


def categorise(fills: list[dict], markets: dict[str, dict], topic_lookup: dict[str, str]) -> list[dict]:
    out = []
    for f in fills:
        qty = fp(f.get("count_fp"))
        yes_px = fp(f.get("yes_price_dollars"))
        ct = utc(f.get("created_time"))
        tkr = f.get("ticker") or ""
        series = tkr.split("-")[0]
        mkt = markets.get(tkr, {})
        close = utc(mkt.get("close_time"))
        horizon = seconds_between(ct, close)
        bid = fp(mkt.get("yes_bid_dollars")) if mkt.get("yes_bid_dollars") else None
        ask = fp(mkt.get("yes_ask_dollars")) if mkt.get("yes_ask_dollars") else None
        rec = {
            "fill_id": f.get("fill_id"),
            "order_id": f.get("order_id"),
            "ticker": tkr,
            "series_ticker": series,
            "topic": topic_lookup.get(series, "unmapped"),
            "direction": "buy_yes" if f.get("book_side") == "bid" else "sell_yes",
            "outcome_side": f.get("outcome_side"),
            "liquidity": ("taker" if f.get("is_taker") else "maker") if f.get("is_taker") is not None else "unknown",
            "size_bucket": bucket(qty, SIZE_BUCKETS),
            "contracts": round(qty, 4),
            "price_bucket": price_bucket(yes_px),
            "yes_price_dollars": yes_px,
            "no_price_dollars": fp(f.get("no_price_dollars")),
            "notional_dollars": round(qty * yes_px, 4),
            "fee_cost_dollars": fp(f.get("fee_cost")) if f.get("fee_cost") is not None else None,
            "utc_hour": ct.strftime("%H") if ct else None,
            "utc_weekday": ct.strftime("%a") if ct else None,
            "spread_dollars": (round(ask - bid, 4) if bid is not None and ask is not None else None),
            "horizon_bucket": bucket(horizon, HORIZON_BUCKETS) if horizon is not None else "unknown",
            "market_result": mkt.get("result") or None,
            "settlement_ts": mkt.get("settlement_ts") or None,
            "is_paper": f.get("source", "").startswith("data/paper_ledger.json"),
            "created_time": f.get("created_time"),
            "fill_id": f.get("fill_id"),
            "order_id": f.get("order_id"),
            "declared_strategy": f.get("strategy"),
            "basis": f.get("basis") or ("paper" if f.get("source", "").startswith("data/paper_ledger.json") else "demo-account"),
            "is_block_trade": f.get("is_block_trade"),
            "source": f.get("source"),
            "unresolved_fields": f.get("unmapped_keys", []),
        }
        out.append(rec)
    return out


def summarise(trades: list[dict], key: str) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {
        "trades": 0, "contracts": 0.0, "notional_dollars": 0.0, "fees_dollars": 0.0,
        "settled": 0, "won": 0, "lost": 0})
    for t in trades:
        g = groups[str(t.get(key))]
        g["trades"] += 1
        g["contracts"] += t["contracts"]
        g["notional_dollars"] += t["notional_dollars"]
        if t["fee_cost_dollars"]:
            g["fees_dollars"] += t["fee_cost_dollars"]
        if t["market_result"] in ("yes", "no"):
            g["settled"] += 1
            hit = (t["market_result"] == "yes") == (t["direction"] == "buy_yes")
            g["won" if hit else "lost"] += 1
    rows = []
    for name, g in groups.items():
        row = {"value": name, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in g.items()}}
        row["hit_rate"] = round(g["won"] / g["settled"], 4) if g["settled"] else None
        row["avg_notional_dollars"] = round(g["notional_dollars"] / g["trades"], 4) if g["trades"] else None
        row["avg_fee_bps_of_notional"] = (round(g["fees_dollars"] / g["notional_dollars"] * 10000, 2)
                                          if g["notional_dollars"] else None)
        rows.append(row)
    rows.sort(key=lambda r: r["trades"], reverse=True)
    return rows


STRATEGY_TESTS = [
    {"id": "S1-limit-resting", "dimension": "liquidity", "expect": "maker",
     "hypothesis": "maker entries pay less spread than taker entries",
     "metric": "compare avg |spread| paid and net notional-per-contract between maker and taker rows"},
    {"id": "S2-cross-the-spread", "dimension": "liquidity", "expect": "taker",
     "hypothesis": "taker entries get filled but give up the book spread",
     "metric": "fill rate vs spread cost; win rate at the same price bucket"},
    {"id": "S3-resolution-carry", "dimension": "price_bucket", "expect": "favourite >90c",
     "hypothesis": "buying >90c and holding to settlement wins often but loses big when it fails",
     "metric": "hit_rate vs (avg price paid x contracts) drawdown on the losing rows"},
    {"id": "S4-flow-follow", "dimension": "topic", "expect": None,
     "hypothesis": "tape imbalance predicts next-period price move",
     "metric": "need per-event flow (collect.py flow_imbalance) joined to candle close moves; "
               "not computable from fills alone — see Q-06"},
]


def score_strategies(trades: list[dict]) -> list[dict]:
    out = []
    for test in STRATEGY_TESTS:
        matched = [t for t in trades
                   if test["expect"] is None or str(t.get(test["dimension"])) == test["expect"]]
        settled = [t for t in matched if t["market_result"] in ("yes", "no")]
        won = [t for t in settled
               if (t["market_result"] == "yes") == (t["direction"] == "buy_yes")]
        out.append({
            "strategy": test["id"],
            "hypothesis": test["hypothesis"],
            "filter": {test["dimension"]: test["expect"]} if test["expect"] else {"topic": "any"},
            "trades_observed": len(matched),
            "settled": len(settled),
            "wins": len(won),
            "hit_rate": round(len(won) / len(settled), 4) if settled else None,
            "notional_dollars": round(sum(t["notional_dollars"] for t in matched), 4),
            "fees_dollars": round(sum(t["fee_cost_dollars"] or 0 for t in matched), 4),
            "confirming_metric": test["metric"],
            "verdict": "insufficient data" if len(settled) < 10 else "evaluable",
            "data_basis": "paper" if any(t["is_paper"] for t in matched) else "demo-live",
        })
    return out


def declared_scoreboard(trades: list[dict]) -> list[dict]:
    """Score by the strategy id stamped on the order, if the operator stamped one.

    This is the other half of 'derive strategies by trade type': STRATEGY_TESTS infers a style
    from observable trade features, while this groups by the label attached at order time.
    Rows with no label are reported as 'unlabelled' rather than dropped, so a gap in labelling
    is visible instead of silently shrinking the sample.
    """
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(t.get("declared_strategy") or "unlabelled", []).append(t)
    out = []
    for key, rows in groups.items():
        settled = [t for t in rows if t["market_result"] in ("yes", "no")]
        won = [t for t in settled if (t["market_result"] == "yes") == (t["direction"] == "buy_yes")]
        out.append({
            "declared_strategy": key,
            "trades": len(rows),
            "settled": len(settled),
            "wins": len(won),
            "hit_rate": round(len(won) / len(settled), 4) if settled else None,
            "notional_dollars": round(sum(t["notional_dollars"] for t in rows), 4),
            "fees_dollars": round(sum(t["fee_cost_dollars"] or 0 for t in rows), 4),
            "contracts": round(sum(t["contracts"] for t in rows), 4),
            "topics": sorted({t["topic"] for t in rows if t["topic"] != "unmapped"}),
            "directions": sorted({t["direction"] for t in rows}),
            "labels": sorted({t["size_bucket"] for t in rows}) + sorted({t["price_bucket"] for t in rows}),
            "tickers": sorted({t["ticker"] for t in rows}),
            "basis": sorted({t["basis"] for t in rows}),
        })
    return sorted(out, key=lambda r: -r["trades"])


def tape_as_fills(path: str) -> list[dict]:
    """Adapt a public-tape capture into the Fill-shaped records the categoriser expects.

    This is NOT a portfolio: these are other participants' fills, read from the public tape.
    It exists so the categorisation and strategy-scoreboard code paths run against real market
    data even while /portfolio/* is unreachable. Every row is marked basis='public tape'.
    Field mapping is 1:1 with the documented tape fields; nothing is added.
      tape taker_book_side -> Fill.book_side   (bid/ask)
      tape taker_outcome_side -> Fill.outcome_side
      is_taker = True for every tape record by construction (the tape reports the taker)
      fee_cost = None        (the tape carries no fee; never estimated)
    """
    with open(path) as fh:
        rows = json.load(fh)
    out = []
    for t in rows:
        out.append({
            "fill_id": t.get("trade_id"),
            "order_id": None,
            "ticker": t.get("ticker"),
            "outcome_side": t.get("taker_outcome_side") or t.get("taker_side"),
            "book_side": t.get("taker_book_side"),
            "count_fp": t.get("count_fp"),
            "yes_price_dollars": t.get("yes_price_dollars"),
            "no_price_dollars": t.get("no_price_dollars"),
            "is_taker": True,
            "fee_cost": None,
            "created_time": t.get("created_time"),
            "unmapped_keys": sorted(set(t) - {"trade_id", "ticker", "count_fp", "yes_price_dollars",
                                              "no_price_dollars", "taker_outcome_side", "taker_book_side",
                                              "taker_side", "created_time", "is_block_trade"}),
            "source": "https://external-api.demo.kalshi.co/trade-api/v2/markets/trades?limit=120",
            "observed_at_utc": t.get("created_time"),
            "is_block_trade": t.get("is_block_trade"),
            "basis": "public tape",
        })
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", default=os.path.join(DATA, "portfolio_ledger.json"))
    p.add_argument("--live", action="store_true", help="refresh market prices before categorising")
    p.add_argument("--from-tape", default=None, metavar="PATH",
                   help="categorise a public /markets/trades capture instead of a portfolio ledger")
    p.add_argument("--out", default=os.path.join(DATA, "analysis.json"))
    args = p.parse_args(argv)

    if args.from_tape:
        ledger = {"source_mode": "public-tape", "fills": tape_as_fills(args.from_tape),
                  "performance": {"totals": None}, "_note": "categorisation demo on the public tape, not a portfolio"}
    else:
        ledger = load(args.ledger)
        if not ledger:
            print(f"no ledger at {args.ledger}; run scripts/portfolio.py first", file=sys.stderr)
            return 1
    fills = ledger.get("fills", [])
    snapshot = load(os.path.join(DATA, "live_snapshot.json"), {}) or {}
    topics_cfg = load(os.path.join(DATA, "topics.json"), {}) or {}

    markets: dict[str, dict] = {}
    for row in snapshot.get("ranked_events", []):
        for m in row.get("markets", []):
            markets[m["ticker"]] = m
    if args.live:
        client = KalshiClient(DEMO_REST)
        for t in {f.get("ticker") for f in fills if f.get("ticker")}:
            try:
                markets[t] = client.market(t)
            except KalshiError as exc:
                print(f"  ! market {t}: {exc}", file=sys.stderr)

    trades = categorise(fills, markets, build_topic_lookup(snapshot, topics_cfg))
    result = {
        "_meta": {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_mode": ledger.get("source_mode"),
            "input": os.path.relpath(args.ledger, ROOT),
            "trade_count": len(trades),
            "definitions": {
                # the upper bound of the last bucket is unbounded; serialise it as a string because
                # JSON has no Infinity and a browser's JSON.parse throws on it
                "size_buckets": [["infinity" if lim == float("inf") else lim, name] for lim, name in SIZE_BUCKETS],
                "horizon_buckets": [["infinity" if lim == float("inf") else lim, name] for lim, name in HORIZON_BUCKETS],
                "price_buckets": ["long-shot <10c", "mid 10-90c", "favourite >90c"],
                "direction": "book_side bid=buy_yes, ask=sell_yes (YES-leg quoting)",
                "notional_dollars": "count_fp x yes_price_dollars — the YES-leg premium. Not the same "
                                    "quantity as the leaderboard's dollar volume, which prices each fill at "
                                    "the taker's own side (yes price for YES, no price for NO). Both formulas "
                                    "are printed wherever their number appears.",
                "win_definition": "(market.result == 'yes') == (direction == 'buy_yes')",
                "field_source": "https://docs.kalshi.com/api-reference/portfolio/get-fills.md",
            },
            "caveat": ("Counts here are contract counts. Kalshi reports volume in contracts, not "
                       "dollars; `notional_dollars` is count x yes_price and is derived."),
        },
        "trades": trades,
        "by_category": {
            "basis": summarise(trades, "basis"),
            "topic": summarise(trades, "topic"),
            "block": summarise(trades, "is_block_trade"),
            "declared_strategy": summarise(trades, "declared_strategy"),
            "direction": summarise(trades, "direction"),
            "liquidity": summarise(trades, "liquidity"),
            "size_bucket": summarise(trades, "size_bucket"),
            "price_bucket": summarise(trades, "price_bucket"),
            "horizon_bucket": summarise(trades, "horizon_bucket"),
            "utc_hour": summarise(trades, "utc_hour"),
        },
        "strategies": score_strategies(trades),
        "declared_strategies": declared_scoreboard(trades),
        "unresolved_fields": sorted({k for t in trades for k in t["unresolved_fields"]}),
        "totals": ledger.get("performance", {}).get("totals"),
    }
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps({"trades": len(trades), "source_mode": result["_meta"]["source_mode"],
                      "categories": {k: len(v) for k, v in result["by_category"].items()},
                      "strategies_evaluable": [s["strategy"] for s in result["strategies"] if s["verdict"] == "evaluable"],
                      "written": args.out}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
