#!/usr/bin/env python3
"""Measured strategy backtest over COMMITTED Kalshi demo snapshots (session 26973298).

What this does
--------------
Simulates one-contract trades on recorded demo candlestick series, for a small set of
fully published rules, and writes every trade plus per-strategy metrics to
`strategy/data/backtest.json`. Nothing is fetched from the network here: the inputs are
files already committed to this repository, so every number is reproducible offline.

Inputs (committed, each with its own retrieval timestamp)
  strategy/data/raw/*.json  2 RESOLVED gas markets, official 1440-minute candles.
                            These are the only series in the repository that have BOTH a
                            recorded price path and a documented yes/no settlement.
  data/latest/candles.json  12 markets, 60-minute and 1-minute windows  (collector, demo API)
  data/history/*.json       37 markets, 1m / 60m / 1440m series         (collector, demo API)
  data/latest/markets_settled.json   22,065 settled demo markets       (collector, demo API)

  The two sources are simulated separately because they answer different questions:
  `resolved`  -> trades that actually settle YES/NO (2 markets, 12 trades).
  `exploratory` -> the larger recorded sample, marked to market ONLY (no settlement
                   available for any of those 49 series at capture time, verified by
                   ?status=settled&tickers=... returning an empty list for every batch).

Exit rule
  * If the market's settlement is present in the committed settled snapshot, the position
    is exited at the official `settlement_value_dollars` (settled).
  * Otherwise it is marked to market at the recorded candle close (mark-to-market). Those
    trades are labelled, never presented as settled results.

Fill model (documented, deliberately conservative)
  * ONE fill price per trade: the candle's `price.close_dollars`, i.e. the last traded YES
    price in that period (official field description: "Last traded YES contract price on
    the market during the candlestick period"). Buying YES costs that price; buying NO
    costs 1 - that price (the documented complement identity for binary markets).
  * The quote columns (`yes_bid` / `yes_ask` closes) are reported alongside, and the
    spread is reported as an execution-cost estimate, but the simulated fill does NOT use
    them: bid and ask can invert around a stale quote (observed in the raw captures), so a
    single traded price is the only defensible fill.
  * A candle with no traded price (price.close_dollars null) is skipped; a fill is never
    invented.

Fee model (official formula, see strategy/SPEC.md for the citation)
  fees = round_up( M * 0.07 * C * P * (1 - P) )  with M = 1 (documented default)
  A taker fee is charged on entry and on an early (marked) exit; a settlement exit
  charges no settlement fee (official fee schedule: "There is no settlement fee").
  Demo-account fee behaviour is NOT verified; the fee is a stated modelling assumption.

Usage
  python3 scripts/backtest_strategies.py          # writes strategy/data/backtest.json
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "strategy" / "data" / "backtest.json"

# ---------------------------------------------------------------- official constants
FEE_COEFF = 0.07          # kalshi.com/docs/kalshi-fee-schedule.pdf
FEE_MULTIPLIER = 1        # documented default ("M = ... default is 1")
MAKER_COEFF = 0.0175      # documented; not used: every modelled fill is a taker fill
SWING = 0.10              # project brief: alert threshold, >= $0.10 in either direction
CONTRACTS = 1.0

FEE_PDF = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
FEE_PAGE = "https://kalshi.com/fee-schedule"
CANDLE_DOC = "https://docs.kalshi.com/api-reference/market/get-market-candlesticks"
BOOK_DOC = "https://docs.kalshi.com/getting_started/orderbook_responses"
SETTLE_DOC = "https://docs.kalshi.com/getting_started/market_settlement"
FP_DOC = "https://docs.kalshi.com/getting_started/fixed_point_migration"


def fee(price: float, contracts: float = CONTRACTS, multiplier: float = FEE_MULTIPLIER) -> float:
    """Official taker fee, rounded up to the next cent (centicent per the PDF wording).

    The PDF says "round up = rounds up such that the fee + positionCost is rounded to a
    centicent"; its worked table (100 contracts) is reproduced exactly by rounding the fee
    up to a whole cent, which is what this function does. Verified in scripts/tests/
    test_backtest.py against all 21 rows of the official table.
    """
    raw = multiplier * FEE_COEFF * contracts * price * (1.0 - price)
    if raw <= 0:
        return 0.0
    return math.ceil(round(raw * 100.0, 9)) / 100.0


# ---------------------------------------------------------------- inputs
def load(rel):
    return json.loads((ROOT / rel).read_text())


def num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def settled_index():
    """ticker -> {result, settlement_value_dollars, source_url, ...} from committed snapshot."""
    out = {}
    p = ROOT / "data" / "latest" / "markets_settled.json"
    if not p.exists():
        return out
    for m in load("data/latest/markets_settled.json").get("markets", []):
        if m.get("status") != "finalized":
            continue
        sv = num(m.get("settlement_value_dollars"))
        if sv is None or m.get("result") not in ("yes", "no"):
            continue
        out[m["ticker"]] = {
            "result": m["result"],
            "settlement_value": sv,
            "source_url": m.get("source_url"),
            "close_time": m.get("close_time"),
            "title": m.get("title"),
            "topic": m.get("topic"),
        }
    return out


def candle_series():
    """Yield (ticker, topic, granularity_minutes, points, source_url).

    A point is a dict with ts, open/close traded price and the YES bid/ask closes.
    Duplicate (ticker, granularity, ts) points across the two committed sources are
    de-duplicated later, keeping the first (data/latest/candles.json) occurrence.
    """
    seen = set()
    topic_of = {}
    p = ROOT / "data" / "latest" / "candles.json"
    if p.exists():
        doc = load("data/latest/candles.json")
        for ticker, rec in (doc.get("by_market") or {}).items():
            for win, block in (rec.get("windows") or {}).items():
                minutes = block.get("period_interval_minutes") or (1 if win.startswith("1m") else 60)
                pts = []
                for c in block.get("candlesticks", []):
                    pr = c.get("price") or {}
                    pts.append({
                        "ts": c.get("end_period_ts"),
                        "open": num(pr.get("open_dollars")),
                        "close": num(pr.get("close_dollars")),
                        "yes_bid": num((c.get("yes_bid") or {}).get("close_dollars")),
                        "yes_ask": num((c.get("yes_ask") or {}).get("close_dollars")),
                        "volume": num(c.get("volume_fp")),
                    })
                if pts:
                    yield (ticker, topic_of.get(ticker), int(minutes), pts,
                           block.get("source_url"), seen)
    for f in sorted((ROOT / "data" / "history").glob("*.json")):
        d = json.loads(f.read_text())
        if "ticker" not in d:
            continue
        ticker = d["ticker"]
        for key, minutes in (("1m", 1), ("60m", 60), ("1440m", 1440)):
            rows = d.get(key) or []
            pts = []
            for r in rows:
                # compact format written by collector/collect.py:
                # [end_period_ts, open, close, high, low, volume]
                if not isinstance(r, list) or len(r) < 3:
                    continue
                pts.append({"ts": r[0], "open": r[1], "close": r[2],
                            "yes_bid": None, "yes_ask": None,
                            "volume": r[5] if len(r) > 5 else None})
            if pts:
                url = ("https://external-api.demo.kalshi.co/trade-api/v2/series/{s}/markets/"
                       "{t}/candlesticks?period_interval={m}").format(
                           s=d.get("series_ticker", ""), t=ticker, m=minutes)
                yield (ticker, None, minutes, pts, url, seen)


# ---------------------------------------------------------------- strategy rules
# Each rule returns a side ("yes" or "no") when it fires at index i, else None.
def rule_swing(direction):
    """Momentum / fade on a >= $0.10 close-to-close move (the brief's alert threshold)."""
    def fn(pts, i):
        a, b = pts[i - 1].get("close"), pts[i].get("close")
        if a is None or b is None:
            return None
        delta = b - a
        if abs(delta) + 1e-12 < SWING:
            return None
        up = delta > 0
        return direction if up else ("no" if direction == "yes" else "yes")
    return fn


def rule_threshold(side, level):
    """Buy the side whose price is at/below `level` (cheap YES, or cheap NO = rich YES)."""
    def fn(pts, i):
        p = pts[i].get("close")
        if p is None:
            return None
        if side == "yes" and p <= level:
            return "yes"
        if side == "no" and (1.0 - p) <= level:
            return "no"
        return None
    return fn


STRATEGIES = [
    # id, family, human label, rule, horizon in candles, description
    ("MOM_1", "momentum", "Momentum after ≥$0.10 move (1 candle)",
     rule_swing("yes"), 1, "Follow the direction of a ≥$0.10 close-to-close move for 1 candle."),
    ("MOM_3", "momentum", "Momentum after ≥$0.10 move (3 candles)",
     rule_swing("yes"), 3, "Follow the direction of a ≥$0.10 close-to-close move for 3 candles."),
    ("MOM_6", "momentum", "Momentum after ≥$0.10 move (6 candles)",
     rule_swing("yes"), 6, "Follow the direction of a ≥$0.10 close-to-close move for 6 candles."),
    ("FADE_1", "reversion", "Fade after ≥$0.10 move (1 candle)",
     rule_swing("no"), 1, "Take the opposite side of a ≥$0.10 move for 1 candle."),
    ("FADE_3", "reversion", "Fade after ≥$0.10 move (3 candles)",
     rule_swing("no"), 3, "Take the opposite side of a ≥$0.10 move for 3 candles."),
    ("FADE_6", "reversion", "Fade after ≥$0.10 move (6 candles)",
     rule_swing("no"), 6, "Take the opposite side of a ≥$0.10 move for 6 candles."),
    ("CHEAP_YES_15", "threshold", "Buy YES while YES ≤ $0.15 (hold 6 candles)",
     rule_threshold("yes", 0.15), 6, "Buy YES when the recorded close is ≤ $0.15, i.e. a "
     "long-shot YES priced at 15¢ or less."),
    ("CHEAP_NO_15", "threshold", "Buy NO while NO ≤ $0.15 (hold 6 candles)",
     rule_threshold("no", 0.15), 6, "Buy NO when (1 − YES close) ≤ $0.15, i.e. YES ≥ $0.85, a "
     "cheap NO against a heavy favourite."),
]


# ---------------------------------------------------------------- simulation
def fill_prices(side, pt):
    """Single documented fill price for `side` in the given candle (see module docstring)."""
    c = pt.get("close")
    if c is None or not (0.0 <= c <= 1.0):
        return None
    return c if side == "yes" else 1.0 - c


def spread_cost(pt):
    """YES ask - YES bid (execution-cost estimate; reported, not applied to fills)."""
    bid, ask = pt.get("yes_bid"), pt.get("yes_ask")
    if bid is None or ask is None or ask < bid:
        return None
    return ask - bid


def simulate(ticker, topic, minutes, pts, src_url, settled):
    """Run every strategy over one series; return trade dicts."""
    trades = []
    n = len(pts)
    if n < 2:
        return trades
    for sid, family, _label, rule, horizon, _desc in STRATEGIES:
        for i in range(1, n):
            side = rule(pts, i)
            if side is None:
                continue
            j = i + horizon
            if j >= n:
                continue                      # no room to exit inside the recorded window
            entry_pt, exit_pt = pts[i], pts[j]
            entry_px = fill_prices(side, entry_pt)
            if entry_px is None:
                continue
            exit_px = fill_prices(side, exit_pt)
            if exit_px is None:
                continue
            if not (0.0 < entry_px < 1.0):
                continue                      # cannot pay 0 or 1 for a side
            # Liquidity filter: require recorded volume on the entry candle.
            vol = entry_pt.get("volume")
            if vol is not None and vol <= 0:
                continue
            is_settled = ticker in settled and settled[ticker]["result"] in ("yes", "no")
            if is_settled:
                sv = settled[ticker]["settlement_value"]
                exit_kind = "settlement"
                payoff = sv if side == "yes" else 1.0 - sv
                exit_reason_px = payoff      # side-adjusted: what this side was paid
            else:
                exit_kind = "mark"
                payoff = exit_px
                exit_reason_px = exit_px
            f_in = fee(entry_px)
            f_out = 0.0 if exit_kind == "settlement" else fee(exit_px)
            gross = payoff - entry_px
            net = gross - f_in - f_out
            trades.append({
                "strategy": sid,
                "family": family,
                "ticker": ticker,
                "topic": topic,
                "granularity_minutes": minutes,
                "side": side,
                "entry_ts": entry_pt.get("ts"),
                "exit_ts": exit_pt.get("ts"),
                "hold_candles": horizon,
                "entry_price": round(entry_px, 4),
                "exit_price": round(exit_reason_px, 4),
                "exit_kind": exit_kind,
                "settled_result": settled[ticker]["result"] if is_settled else None,
                "gross_pnl": round(gross, 4),
                "fees": round(f_in + f_out, 4),
                "net_pnl": round(net, 4),
                "deployed": round(entry_px, 4),
                "entry_spread": spread_cost(entry_pt),
                "exit_spread": spread_cost(exit_pt),
                "source_url": src_url,
                "settlement_source_url": settled[ticker]["source_url"] if is_settled else None,
            })
    return trades


# ---------------------------------------------------------------- metrics
def max_drawdown(pnls):
    """Peak-to-trough of the cumulative net PnL, in dollars per contract."""
    cum = peak = dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return round(dd, 4)


def metrics(rows):
    n = len(rows)
    if not n:
        return {"trades": 0}
    net = [r["net_pnl"] for r in rows]
    gross = [r["gross_pnl"] for r in rows]
    deployed = sum(r["deployed"] for r in rows)
    wins = sum(1 for x in net if x > 0)
    fees = sum(r["fees"] for r in rows)
    gross_pnl = sum(gross)
    net_pnl = sum(net)
    return {
        "trades": n,
        "wins": wins,
        "win_rate": round(wins / n * 100, 1),
        "gross_pnl": round(gross_pnl, 2),
        "fees": round(fees, 2),
        "net_pnl": round(net_pnl, 2),
        "expectancy_per_trade": round(net_pnl / n, 4),
        "capital_deployed": round(deployed, 2),
        "roi_pct": round(net_pnl / deployed * 100, 2) if deployed else None,
        "max_drawdown": max_drawdown(net),
        "settled_trades": sum(1 for r in rows if r["exit_kind"] == "settlement"),
        "markets": len({r["ticker"] for r in rows}),
        "topics": sorted({r["topic"] for r in rows if r["topic"]}),
        "avg_entry_price": round(sum(r["entry_price"] for r in rows) / n, 4),
        "temporal_split": temporal_split(rows),
    }


def temporal_split(rows):
    """Net PnL of the earlier half vs the later half of the trades (ordered by exit time).

    A rule that only earns in one half is not a stable edge; this keeps that visible.
    """
    ordered = sorted(rows, key=lambda r: (r["exit_ts"] or 0))
    half = len(ordered) // 2
    first, second = ordered[:half], ordered[half:]
    return {
        "first_half_trades": len(first),
        "first_half_net": round(sum(r["net_pnl"] for r in first), 2),
        "second_half_trades": len(second),
        "second_half_net": round(sum(r["net_pnl"] for r in second), 2),
        "threshold_utc": ordered[half]["exit_ts"] if half < len(ordered) else None,
        "both_halves_positive": (sum(r["net_pnl"] for r in first) > 0 and
                                 sum(r["net_pnl"] for r in second) > 0),
    }



def data_as_of():
    """Newest `retrieved_at` among the committed inputs (never the wall clock)."""
    stamps = []
    for rel in ("data/latest/markets_settled.json", "data/latest/candles.json",
                "data/latest/markets_open.json"):
        p = ROOT / rel
        if not p.exists():
            continue
        v = json.loads(p.read_text()).get("retrieved_at")
        if v:
            stamps.append(v)
    for f in sorted((ROOT / "strategy" / "data" / "raw").glob("*.json")):
        v = json.loads(f.read_text()).get("retrieved_at_utc")
        if v:
            stamps.append(v)
    return max(stamps) if stamps else "unknown"


def load_raw_resolved(settled):
    """Yield (ticker, topic, minutes, points, source_url) for strategy/data/raw/*.json."""
    for f in sorted((ROOT / "strategy" / "data" / "raw").glob("*.json")):
        d = json.loads(f.read_text())
        ticker = d["ticker"]
        pts = []
        for c in d.get("candlesticks", []):
            pr = c.get("price") or {}
            pts.append({
                "ts": c.get("end_period_ts"),
                "open": num(pr.get("open_dollars")),
                "close": num(pr.get("close_dollars")),
                "yes_bid": num((c.get("yes_bid") or {}).get("close_dollars")),
                "yes_ask": num((c.get("yes_ask") or {}).get("close_dollars")),
                "volume": num(c.get("volume_fp")),
            })
        if not pts:
            continue
        topic = (settled.get(ticker) or {}).get("topic") or "gas"
        yield (ticker, topic, int(d.get("period_interval_minutes") or 1440), pts,
               d.get("request_url"))


def concentration(rows):
    """How much of a strategy's gross profit comes from its single best series."""
    if not rows:
        return None
    per = {}
    for r in rows:
        per[r["ticker"]] = per.get(r["ticker"], 0.0) + r["net_pnl"]
    gross_profit = sum(v for v in per.values() if v > 0)
    best_t, best = max(per.items(), key=lambda kv: kv[1])
    worst_t, worst = min(per.items(), key=lambda kv: kv[1])
    return {
        "series": len(per),
        "best_series": best_t,
        "best_series_pnl": round(best, 2),
        "worst_series": worst_t,
        "worst_series_pnl": round(worst, 2),
        "gross_profit_from_winning_series": round(gross_profit, 2),
        "share_of_gross_profit_from_best_series":
            (round(best / gross_profit * 100, 1) if gross_profit > 0 and best > 0 else None),
    }


def resolution_analysis(settled, series_meta):
    """Per recorded market: settlement result, and how a hold-to-settlement YES did.

    Answers the brief's "how the event was resolved, either yes or no" at the level this
    dataset supports, plus the price the market was showing at the last recorded candle.
    """
    rows = []
    for meta in series_meta:
        t = meta["ticker"]
        s = settled.get(t)
        row = {
            "ticker": t,
            "topic": meta["topic"],
            "title": (s or {}).get("title"),
            "last_recorded_close": meta.get("last_close"),
            "settled_result": (s or {}).get("result"),
            "settlement_value_dollars": (s or {}).get("settlement_value"),
            "settlement_source_url": (s or {}).get("source_url"),
            "close_time": (s or {}).get("close_time"),
            "candles_source_url": meta["source_url"],
        }
        if s and meta.get("last_close") is not None:
            entry = meta["last_close"]
            payoff = s["settlement_value"]
            f_in = fee(entry)
            row["hold_yes_entry"] = entry
            row["hold_yes_gross"] = round(payoff - entry, 4)
            row["hold_yes_fee"] = f_in
            row["hold_yes_net"] = round(payoff - entry - f_in, 4)
            row["hold_no_entry"] = round(1.0 - entry, 4)
            row["hold_no_fee"] = fee(1.0 - entry)
            row["hold_no_net"] = round((1.0 - payoff) - (1.0 - entry) - fee(1.0 - entry), 4)
        else:
            row["hold_yes_entry"] = None
            row["hold_yes_gross"] = None
            row["hold_yes_net"] = None
            row["hold_yes_fee"] = None
            row["hold_no_entry"] = None
            row["hold_no_net"] = None
            row["hold_no_fee"] = None
        rows.append(row)
    return rows


def main():
    settled = settled_index()
    datasets = {}

    # ---- dataset 1: resolved (has a documented yes/no settlement)
    rows_res, meta_res = [], []
    for ticker, topic, minutes, pts, url in load_raw_resolved(settled):
        rows = simulate(ticker, topic, minutes, pts, url, settled)
        rows_res.extend(rows)
        closes = [p["close"] for p in pts if p.get("close") is not None]
        meta_res.append({"ticker": ticker, "topic": topic, "granularity_minutes": minutes,
                         "points": len(pts), "source_url": url,
                         "settled": ticker in settled,
                         "last_close": closes[-1] if closes else None})
    datasets["resolved"] = (rows_res, meta_res)

    # ---- dataset 2: exploratory (recorded price paths, no settlement available)
    rows_exp, meta_exp = [], []
    for ticker, topic, minutes, pts, url, _seen in candle_series():
        rows = simulate(ticker, topic, minutes, pts, url, {})
        rows_exp.extend(rows)
        closes = [p["close"] for p in pts if p.get("close") is not None]
        meta_exp.append({"ticker": ticker, "topic": topic, "granularity_minutes": minutes,
                         "points": len(pts), "source_url": url, "settled": False,
                         "last_close": closes[-1] if closes else None})
    # de-duplicate markets modelled twice by the two committed sources
    seen = set()
    dedup_res, dedup_exp = [], []
    for r in rows_res + rows_exp:
        key = (r["strategy"], r["ticker"], r["granularity_minutes"], r["entry_ts"])
        if key in seen:
            continue
        seen.add(key)
        (dedup_res if r["exit_kind"] == "settlement" else dedup_exp).append(r)
    datasets["resolved"] = (dedup_res, meta_res)
    datasets["exploratory"] = (dedup_exp, [m for m in meta_exp if not m["settled"]])
    topic_by_ticker = {}
    for rel in ("data/latest/markets_settled.json", "data/latest/markets_open.json"):
        if (ROOT / rel).exists():
            for m in load(rel).get("markets", []):
                if m.get("topic") and m.get("ticker") not in topic_by_ticker:
                    topic_by_ticker[m["ticker"]] = m["topic"]
    for m in meta_exp:
        if not m["topic"]:
            m["topic"] = topic_by_ticker.get(m["ticker"], "unknown")

    # topic attribution for anything the sources left blank (built above)
    for rows, _m in datasets.values():
        for r in rows:
            if not r["topic"]:
                r["topic"] = topic_by_ticker.get(r["ticker"], "unknown")

    out = {}
    for name, (rows, meta) in datasets.items():
        by_strategy = {}
        for sid, family, label, _rule, horizon, desc in STRATEGIES:
            srows = [r for r in rows if r["strategy"] == sid]
            by_strategy[sid] = {
                "id": sid, "family": family, "label": label, "horizon_candles": horizon,
                "description": desc, "metrics": metrics(srows),
                "concentration": concentration(srows),
            }
        by_granularity = {}
        for minutes in sorted({r["granularity_minutes"] for r in rows}):
            g = [r for r in rows if r["granularity_minutes"] == minutes]
            by_granularity[str(minutes)] = {"granularity_minutes": minutes, "metrics": metrics(g)}
        by_topic = {}
        for topic in sorted({r["topic"] for r in rows}):
            for sid, *_ in STRATEGIES:
                trows = [r for r in rows if r["topic"] == topic and r["strategy"] == sid]
                if trows:
                    by_topic.setdefault(topic, {})[sid] = metrics(trows)
        curves = {}
        for sid, *_ in STRATEGIES:
            srows = sorted([r for r in rows if r["strategy"] == sid],
                           key=lambda r: (r["exit_ts"] or 0))
            cum, pts = 0.0, []
            for r in srows:
                cum += r["net_pnl"]
                pts.append([r["exit_ts"], round(cum, 4)])
            if len(pts) > 400:
                step = len(pts) / 400.0
                pts = [pts[int(k * step)] for k in range(400)] + [pts[-1]]
            curves[sid] = pts
        out[name] = {
            "series_count": len(meta),
            "series": meta,
            "strategies": [by_strategy[s[0]] for s in STRATEGIES],
            "by_granularity": by_granularity,
            "by_topic": by_topic,
            "equity_curves": curves,
            "trades_total": len(rows),
            "trades": sorted(rows, key=lambda r: (r["strategy"], r["exit_ts"] or 0)),
            "resolutions": resolution_analysis(settled, meta),
        }

    doc = {
        # Deterministic: the newest retrieval timestamp among the committed inputs, so a
        # rebuild against unchanged data is byte-identical (CI enforces this).
        "data_as_of_utc": data_as_of(),
        "contracts_per_trade": CONTRACTS,
        "swing_threshold": SWING,
        "fee_model": {
            "formula": "round_up(M * 0.07 * C * P * (1 - P))",
            "multiplier": FEE_MULTIPLIER,
            "charged_on": "entry taker and early (marked) exit taker; no fee on settlement exit",
            "sources": [FEE_PDF, FEE_PAGE, SETTLE_DOC],
            "verified": "formula reproduced against all 21 rows of the official PDF table "
                        "(see fee_verification)",
            "unverified": "whether the demo environment actually charges fees",
        },
        "fill_model": {
            "rule": "single fill price = candle price.close_dollars (last traded YES price)",
            "buy_yes": "price.close",
            "buy_no": "1 - price.close (binary complement)",
            "spread_reported": "yes_ask.close - yes_bid.close, reported as execution-cost "
                               "estimate and NOT applied to fills",
            "skipped": "candles without a traded price are skipped; no fill is invented",
            "liquidity_filter": "entry candle must record volume > 0",
            "sources": [CANDLE_DOC, BOOK_DOC, FP_DOC],
        },
        "exit_model": {
            "settlement": "settlement_value_dollars from data/latest/markets_settled.json",
            "mark": "recorded traded YES price at the horizon candle (marked, not settled)",
            "sources": [SETTLE_DOC, CANDLE_DOC],
        },
        "fee_verification": fee_table_check(),
        "topic_attribution": {
            "rule": "topic taken from the committed settled snapshot, else from the committed "
                    "open-market snapshot; markets in neither stay 'unknown' (never inferred)",
            "sources": ["data/latest/markets_settled.json", "data/latest/markets_open.json"],
        },
        "inputs": {
            "resolved_candles": "strategy/data/raw/*.json",
            "candles": "data/latest/candles.json",
            "history": "data/history/*.json",
            "settled": "data/latest/markets_settled.json",
        },
        "datasets": out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1))

    for name in ("resolved", "exploratory"):
        d = out[name]
        print(f"\n[{name}] {d['trades_total']} simulated trades over {d['series_count']} series")
        for s in d["strategies"]:
            m = s["metrics"]
            if not m.get("trades"):
                print(f"  {s['id']:14s} no trades")
                continue
            print(f"  {s['id']:14s} n={m['trades']:5d} net=${m['net_pnl']:>9.2f} "
                  f"roi={m['roi_pct']}% win={m['win_rate']}% settled_n={m['settled_trades']}")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


def fee_table_check():
    """Reproduce the official fee table (100 contracts) from the formula."""
    table = [(0.01, 0.07), (0.05, 0.34), (0.10, 0.63), (0.15, 0.90), (0.20, 1.12),
             (0.25, 1.32), (0.30, 1.47), (0.35, 1.60), (0.40, 1.68), (0.45, 1.74),
             (0.50, 1.75), (0.55, 1.74), (0.60, 1.68), (0.65, 1.60), (0.70, 1.47),
             (0.75, 1.32), (0.80, 1.12), (0.85, 0.90), (0.90, 0.63), (0.95, 0.34),
             (0.99, 0.07)]
    rows = []
    for price, official in table:
        computed = fee(price, 100.0)
        rows.append({"price": f"{price:.2f}", "official_fee_100": official,
                     "computed_fee_100": round(computed, 2),
                     "match": abs(computed - official) < 1e-9})
    return {"source": FEE_PDF, "contracts": 100, "rows": rows,
            "all_match": all(r["match"] for r in rows)}


if __name__ == "__main__":
    sys.exit(main())
