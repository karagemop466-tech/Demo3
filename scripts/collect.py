"""
collect.py — build the dashboard dataset from Kalshi demo public endpoints.

Pipeline
  1. /exchange/status                       gate: refuse to publish unless trading_active
  2. /search/tags_by_categories              confirm every topic selector still exists
  3. /series?category&tags                   topic -> series universe (official taxonomy)
  4. /markets/trades (paged)                 the tape -> exact per-event dollar volume
  5. /events?tickers                         titles, category, series for ranked events
  6. /markets?event_ticker                   live markets, prices, sizes, volume, OI
  7. /markets/{t}/orderbook                  depth ladder -> liquidity by price
  8. /series/{s}/markets/{t}/candlesticks    1m / 1h / 1d history for the chart
  9. /markets?status=settled                 resolved events -> yes/no outcome ledger

Output: data/live_snapshot.json  (+ data/resolutions.json appended, never overwritten)

Every emitted record carries `source` (the exact URL that produced it) and `observed_at_utc`.
A field the API did not return is emitted as null, never guessed.

Usage
  python3 scripts/collect.py --window-minutes 30 --pages 6 --top 40
  python3 scripts/collect.py --topics crypto,golf --no-candles
  python3 scripts/collect.py --resolutions-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kalshi_api import (  # noqa: E402
    DEMO_REST,
    DEMO_REST_ALT,
    PROD_REST,
    KalshiClient,
    KalshiError,
    best_bid,
    book_levels,
    depth_at_or_above,
    fp,
    trade_notional,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
TOPICS_PATH = os.path.join(DATA_DIR, "topics.json")

BASES = {"demo": DEMO_REST, "demo-alt": DEMO_REST_ALT, "prod": PROD_REST}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_topics() -> list[dict]:
    with open(TOPICS_PATH) as fh:
        return json.load(fh)["topics"]


def series_from_market_ticker(ticker: str) -> str:
    """First '-'-delimited segment.

    CONVENTION, not a documented Kalshi rule: every ticker sampled live in this session
    (KXPGATOUR-THRC26-HLEB, KXBTCY-27JAN0100-B127500, KXWTI..., KXMVECROSSCATEGORY-...)
    begins with its series ticker. It is used only as a *lookup key* into the authoritative
    /series universe; a trade whose parsed prefix is not in that universe is discarded, so a
    wrong parse can never publish a wrong label.
    """
    return ticker.split("-")[0]


def event_from_market_ticker(ticker: str) -> str:
    """Market tickers are <event>-<market-suffix>; binary one-market events are their own id."""
    parts = ticker.split("-")
    return "-".join(parts[:-1]) if len(parts) >= 3 else ticker


def topic_of(series: dict, topics: list[dict]) -> str | None:
    """Official-taxonomy classification. Returns the first topic whose selector matches."""
    cats = set(series.get("categories") or [])
    if series.get("category"):
        cats.add(series["category"])
    tags = set(series.get("tags") or [])
    for topic in topics:
        for sel in topic["selectors"]:
            if sel["category"] in cats and (not sel.get("tags") or tags & set(sel["tags"])):
                return topic["id"]
    return None


def series_universe(client: KalshiClient, topics: list[dict], *, per_topic_cap: int) -> dict[str, dict]:
    """series ticker -> {topic, volume_fp, title, category, tags, exchange_index, source}"""
    universe: dict[str, dict] = {}
    for topic in topics:
        for sel in topic["selectors"]:
            for tag in sel.get("tags") or [None]:
                url = client.url_for("/series", {"category": sel["category"], "tags": tag, "include_volume": "true"})
                try:
                    rows = client.request("GET", "/series", params={
                        "category": sel["category"], "tags": tag, "include_volume": "true"}).get("series", [])
                except KalshiError as exc:
                    print(f"  ! /series category={sel['category']} tags={tag}: {exc}", file=sys.stderr)
                    continue
                for s in rows:
                    tid = topic_of(s, topics)
                    if tid != topic["id"]:
                        continue  # a series can match several topics; keep the first, per topic order
                    prev = universe.get(s["ticker"])
                    rec = {
                        "series_ticker": s["ticker"],
                        "title": s.get("title"),
                        "topic": tid,
                        "category": s.get("category"),
                        "categories": s.get("categories"),
                        "tags": s.get("tags"),
                        "frequency": s.get("frequency"),
                        "fee_type": s.get("fee_type"),
                        "fee_multiplier": s.get("fee_multiplier"),
                        "exchange_index": s.get("exchange_index"),
                        "settlement_sources": s.get("settlement_sources"),
                        "contract_terms_url": s.get("contract_terms_url"),
                        "volume_fp": s.get("volume_fp"),
                        "volume_contracts": fp(s.get("volume_fp")),
                        "last_updated_ts": s.get("last_updated_ts"),
                        "source": url,
                        "selector": {"category": sel["category"], "tags": tag},
                    }
                    if prev is None or rec["volume_contracts"] > prev["volume_contracts"]:
                        universe[s["ticker"]] = rec
    ranked = sorted(universe.values(), key=lambda r: r["volume_contracts"], reverse=True)
    out: dict[str, dict] = {}
    per_topic: dict[str, int] = defaultdict(int)
    for rec in ranked:
        if per_topic[rec["topic"]] >= per_topic_cap:
            continue
        out[rec["series_ticker"]] = rec
        per_topic[rec["topic"]] += 1
    return out


def rank_events_from_tape(client: KalshiClient, universe: dict[str, dict], *, pages: int,
                          window_minutes: int, limit: int = 1000) -> tuple[dict[str, dict], int]:
    """Event -> dollar volume, from the trade tape.

    Dollar volume is DERIVED: sum over trades of count_fp x taker price. Kalshi has no
    dollar-volume field (verified 2026-11-20 on GET /markets and GET /series).
    """
    min_ts = int(time.time()) - window_minutes * 60
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "event_ticker": "", "dollar_volume": 0.0, "contracts": 0.0, "trades": 0,
        "yes_dollars": 0.0, "no_dollars": 0.0, "block_trades": 0, "last_trade_time": "",
        "markets": set(), "series": set(),
    })
    seen = 0
    cursor = ""
    stopped_early = False
    for _ in range(pages):
        data = client.request("GET", "/markets/trades",
                              params={"limit": limit, "cursor": cursor or None, "min_ts": min_ts})
        rows = data.get("trades", [])
        if not rows:
            break
        for t in rows:
            ts = t.get("created_time", "")
            if ts and ts < datetime.fromtimestamp(min_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"):
                stopped_early = True
                break
            series_ticker = series_from_market_ticker(t["ticker"])
            uni = universe.get(series_ticker)
            if uni is None:
                continue  # outside the five topics (authoritative universe lookup, no guessing)
            ev = event_from_market_ticker(t["ticker"])
            row = agg[ev]
            row["event_ticker"] = ev
            row["dollar_volume"] += trade_notional(t)
            row["contracts"] += fp(t.get("count_fp"))
            row["trades"] += 1
            side = t.get("taker_outcome_side") or t.get("taker_side")
            if side == "yes":
                row["yes_dollars"] += trade_notional(t)
            else:
                row["no_dollars"] += trade_notional(t)
            if t.get("is_block_trade"):
                row["block_trades"] += 1
            row["last_trade_time"] = max(row["last_trade_time"], ts)
            row["markets"].add(t["ticker"])
            row["series"].add(uni["series_ticker"])
            seen += 1
        cursor = data.get("cursor") or ""
        if not cursor or stopped_early:
            break
    for row in agg.values():
        row["markets"] = sorted(row["markets"])
        row["series"] = sorted(row["series"])
        row["topic"] = universe[row["series"][0]]["topic"] if row["series"] else None
        row["dollar_volume_formula"] = "sum(count_fp x (yes_price_dollars if taker_outcome_side=='yes' else no_price_dollars))"
        row["source"] = client.url_for("/markets/trades", {"limit": limit, "min_ts": min_ts})
    ranked = sorted(agg.values(), key=lambda r: r["dollar_volume"], reverse=True)
    return {r["event_ticker"]: r for r in ranked}, seen


def fetch_events(client: KalshiClient, event_tickers: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(event_tickers), 50):
        chunk = event_tickers[i:i + 50]
        data = client.request("GET", "/events", params={"tickers": ",".join(chunk), "with_nested_markets": "true"})
        for ev in data.get("events", []):
            out[ev["event_ticker"]] = ev
    return out


def depth_summary(book: dict) -> dict:
    yes = book_levels(book, "yes")
    no = book_levels(book, "no")
    best_yes = yes[-1][0] if yes else None
    best_no = no[-1][0] if no else None
    return {
        "yes_bid_levels": yes[-10:],
        "no_bid_levels": no[-10:],
        "best_yes_bid_dollars": best_yes,
        "best_no_bid_dollars": best_no,
        # implied, per https://docs.kalshi.com/getting_started/orderbook_responses.md
        "implied_yes_ask_dollars": None if best_no is None else round(1.0 - best_no, 6),
        "implied_no_ask_dollars": None if best_yes is None else round(1.0 - best_yes, 6),
        "yes_contracts_at_best": yes[-1][1] if yes else 0.0,
        "no_contracts_at_best": no[-1][1] if no else 0.0,
        "yes_contracts_total_depth": sum(c for _, c in yes),
        "no_contracts_total_depth": sum(c for _, c in no),
        "levels_returned": len(yes) + len(no),
        "note": "API returns bids only; asks are the reciprocal of the opposite-side bid. "
                "Source: https://docs.kalshi.com/getting_started/orderbook_responses.md",
    }


def build_snapshot(args) -> dict:
    client = KalshiClient(BASES[args.base])
    topics = load_topics()
    if args.topics:
        wanted = set(args.topics.split(","))
        topics = [t for t in topics if t["id"] in wanted]

    ts = utcnow()
    problems: list[dict] = []
    status = {}
    try:
        status = client.exchange_status()
    except KalshiError as exc:
        problems.append({"stage": "exchange/status", "error": str(exc)})

    taxo = {}
    try:
        taxo = client.request("GET", "/search/tags_by_categories").get("tags_by_categories", {})
    except KalshiError as exc:
        problems.append({"stage": "search/tags_by_categories", "error": str(exc)})

    for topic in topics:
        for sel in topic["selectors"]:
            if sel["category"] not in (taxo or {}):
                problems.append({
                    "stage": "taxonomy",
                    "severity": "blocker",
                    "detail": f"topic '{topic['id']}' selector category '{sel['category']}' is no longer "
                             f"in GET /search/tags_by_categories — re-map before trusting rankings",
                })

    print(f"[{ts}] base={BASES[args.base]} topics={[t['id'] for t in topics]}")
    print("  · series universe …")
    universe = series_universe(client, topics, per_topic_cap=args.series_per_topic)
    print(f"    {len(universe)} series")
    counts = defaultdict(int)
    for rec in universe.values():
        counts[rec["topic"]] += 1
    print(f"    per topic: {dict(counts)}")

    print(f"  · tape, last {args.window_minutes} min ({args.pages} pages x {args.trades_limit}) …")
    ranked, trades_seen = rank_events_from_tape(
        client, universe, pages=args.pages, window_minutes=args.window_minutes, limit=args.trades_limit)
    print(f"    {trades_seen} in-topic trades, {len(ranked)} events with volume")

    top = list(ranked.values())[: args.top]
    tickers = [r["event_ticker"] for r in top]
    print(f"  · events + markets for top {len(tickers)} …")
    events = fetch_events(client, tickers) if tickers else {}

    watchlist: list[dict] = []
    for rec in top:
        ev = events.get(rec["event_ticker"], {})
        markets = []
        try:
            markets = list(client.markets(event_ticker=rec["event_ticker"], status="open", max_pages=1))
        except KalshiError as exc:
            problems.append({"stage": f"markets:{rec['event_ticker']}", "error": str(exc)})
        if not markets:
            try:
                markets = list(client.markets(event_ticker=rec["event_ticker"], max_pages=1))
            except KalshiError as exc:
                problems.append({"stage": f"markets-open-or-any:{rec['event_ticker']}", "error": str(exc)})
        markets.sort(key=lambda m: fp(m.get("volume_fp")), reverse=True)
        picks = markets[: args.markets_per_event]
        rows = []
        for m in picks:
            ob = {}
            if not args.no_depth:
                try:
                    ob = client.orderbook(m["ticker"], depth=args.depth)
                except KalshiError as exc:
                    problems.append({"stage": f"orderbook:{m['ticker']}", "error": str(exc)})
            candles = []
            candle_series = m.get("event_ticker") and series_from_market_ticker(m["ticker"]) or m["ticker"].split("-")[0]
            if not args.no_candles and candle_series:
                end_ts = int(time.time())
                try:
                    candles = client.candlesticks(candle_series, m["ticker"],
                                                  end_ts - args.candle_hours * 3600, end_ts,
                                                  args.candle_period)
                except KalshiError as exc:
                    problems.append({"stage": f"candles:{m['ticker']}", "error": str(exc)})
            depth = depth_summary(ob) if ob else {}
            rows.append({
                "ticker": m.get("ticker"),
                "title": m.get("title"),
                "yes_sub_title": m.get("yes_sub_title"),
                "status": m.get("status"),
                "last_price_dollars": m.get("last_price_dollars"),
                "previous_price_dollars": m.get("previous_price_dollars"),
                "yes_bid_dollars": m.get("yes_bid_dollars"),
                "yes_ask_dollars": m.get("yes_ask_dollars"),
                "no_bid_dollars": m.get("no_bid_dollars"),
                "no_ask_dollars": m.get("no_ask_dollars"),
                "yes_bid_size_fp": m.get("yes_bid_size_fp"),
                "yes_ask_size_fp": m.get("yes_ask_size_fp"),
                "volume_fp": m.get("volume_fp"),
                "volume_24h_fp": m.get("volume_24h_fp"),
                "open_interest_fp": m.get("open_interest_fp"),
                "notional_value_dollars": m.get("notional_value_dollars"),
                "close_time": m.get("close_time"),
                "expected_expiration_time": m.get("expected_expiration_time"),
                "result": m.get("result") or None,
                "settlement_ts": m.get("settlement_ts") or None,
                "settlement_value_dollars": m.get("settlement_value_dollars") or None,
                "price_level_structure": m.get("price_level_structure"),
                "rules_primary": m.get("rules_primary"),
                "updated_time": m.get("updated_time"),
                "exchange_index": m.get("exchange_index"),
                "source": client.url_for("/markets", {"event_ticker": rec["event_ticker"], "status": "open"}),
                "orderbook_source": client.url_for(f"/markets/{m['ticker']}/orderbook", {"depth": args.depth}) if ob else None,
                "depth": depth,
                "candles": candles,
                "candles_source": client.url_for(
                    f"/series/{candle_series}/markets/{m['ticker']}/candlesticks",
                    {"period_interval": args.candle_period}) if candles else None,
                "liquidity_dollars_at_best_yes_bid": (
                    round((depth.get("yes_contracts_at_best") or 0) * (depth.get("best_yes_bid_dollars") or 0), 2)
                    if depth else None),
            })
        watchlist.append({
            "event_ticker": rec["event_ticker"],
            "title": ev.get("title"),
            "sub_title": ev.get("sub_title"),
            "series_ticker": ev.get("series_ticker") or (rec["series"][0] if rec["series"] else None),
            "category": ev.get("category"),
            "topic": rec["topic"],
            "mutually_exclusive": ev.get("mutually_exclusive"),
            "settlement_sources": ev.get("settlement_sources"),
            "dollar_volume_window": round(rec["dollar_volume"], 2),
            "contracts_window": round(rec["contracts"], 4),
            "trades_window": rec["trades"],
            "block_trades_window": rec["block_trades"],
            "yes_side_dollars": round(rec["yes_dollars"], 2),
            "no_side_dollars": round(rec["no_dollars"], 2),
            "flow_imbalance": (round((rec["yes_dollars"] - rec["no_dollars"]) / rec["dollar_volume"], 4)
                               if rec["dollar_volume"] else None),
            "dollar_volume_formula": rec["dollar_volume_formula"],
            "last_trade_time": rec["last_trade_time"],
            "window_minutes": args.window_minutes,
            "event_source": client.url_for("/events", {"tickers": rec["event_ticker"], "with_nested_markets": "true"}),
            "markets": rows,
        })

    resolutions = collect_resolutions(client, universe, topics, args) if not args.no_resolutions else []
    if resolutions:
        merge_resolutions(resolutions)

    snapshot = {
        "_meta": {
            "generated_at_utc": ts,
            "environment": args.base,
            "rest_base_url": BASES[args.base],
            "websocket_url": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
            "generator": "scripts/collect.py",
            "data_policy": "null = the API did not return it. Never substituted.",
            "window_minutes": args.window_minutes,
            "tape_trades_scanned": trades_seen,
            "trades_limit_per_page": args.trades_limit,
            "tapes_pages": args.pages,
            "collection_latency_seconds": round(time.time() - time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")), 1),
        },
        "exchange_status": {"source": client.url_for("/exchange/status"), "observed_at_utc": ts, "value": status or None},
        "taxonomy_categories": sorted((taxo or {}).keys()),
        "topics": [{k: t[k] for k in ("id", "label", "icon", "note", "verification")} for t in topics],
        "series_universe": sorted(universe.values(), key=lambda r: r["volume_contracts"], reverse=True)[: args.universe_out],
        "ranked_events": watchlist,
        "resolutions_recent": resolutions,
        "problems": problems,
    }
    if not status.get("trading_active"):
        snapshot["problems"].append({
            "stage": "exchange/status", "severity": "blocker",
            "detail": "trading_active is not true; price/liquidity panels must be shown as informational only",
        })
    return snapshot


def collect_resolutions(client: KalshiClient, universe: dict, topics: list[dict], args) -> list[dict]:
    """Markets that moved from open -> settled inside the lookback, with their yes/no outcome."""
    rows: list[dict] = []
    by_topic: dict[str, list[str]] = defaultdict(list)
    for st, rec in universe.items():
        by_topic[rec["topic"]].append(st)
    for topic in topics:
        for st in by_topic.get(topic["id"], [])[: args.settled_per_topic]:
            try:
                markets = client.request("GET", "/markets", params={
                    "series_ticker": st, "status": "settled", "limit": 20})
            except KalshiError as exc:
                rows.append({"series_ticker": st, "error": str(exc)})
                continue
            for m in markets.get("markets", []):
                rows.append({
                    "topic": topic["id"],
                    "series_ticker": st,
                    "event_ticker": m.get("event_ticker"),
                    "ticker": m.get("ticker"),
                    "title": m.get("title"),
                    "status": m.get("status"),
                    "result": m.get("result") or None,
                    "settlement_ts": m.get("settlement_ts") or None,
                    "settlement_value_dollars": m.get("settlement_value_dollars") or None,
                    "close_time": m.get("close_time"),
                    "volume_fp": m.get("volume_fp"),
                    "open_interest_fp": m.get("open_interest_fp"),
                    "final_yes_bid_dollars": m.get("yes_bid_dollars"),
                    "rules_primary": m.get("rules_primary"),
                    "source": client.url_for("/markets", {"series_ticker": st, "status": "settled", "limit": 20}),
                    "observed_at_utc": utcnow(),
                })
    return rows


RESOLUTIONS_PATH = os.path.join(DATA_DIR, "resolutions.json")


def merge_resolutions(new_rows: list[dict]) -> None:
    """Append-only ledger keyed by market ticker: a resolution never disappears."""
    existing: dict[str, dict] = {}
    if os.path.exists(RESOLUTIONS_PATH):
        try:
            with open(RESOLUTIONS_PATH) as fh:
                for r in json.load(fh).get("resolutions", []):
                    existing[r["ticker"]] = r
        except (json.JSONDecodeError, AttributeError):
            existing = {}
    for r in new_rows:
        if r.get("ticker") and r.get("result"):
            existing[r["ticker"]] = r
    rows = sorted(existing.values(), key=lambda r: r.get("settlement_ts") or "", reverse=True)
    with open(RESOLUTIONS_PATH, "w") as fh:
        json.dump({
            "_meta": {
                "purpose": "Resolution ledger: how each tracked market resolved (yes/no) and when.",
                "updated_at_utc": utcnow(),
                "written_by": "scripts/collect.py (append-only, keyed by market ticker)",
                "field_semantics": "result/settlement_ts/settlement_value_dollars are market fields; "
                                   "'no' means YES holders receive $0 and NO holders $1/contract. "
                                   "https://docs.kalshi.com/getting_started/market_settlement.md",
            },
            "resolutions": rows,
        }, fh, indent=2)
    print(f"    resolutions ledger: {len(rows)} rows -> data/resolutions.json")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", choices=list(BASES), default="demo")
    p.add_argument("--topics", default="", help="comma list; default all five")
    p.add_argument("--window-minutes", type=int, default=30)
    p.add_argument("--pages", type=int, default=6, help="tape pages (1000 trades each)")
    p.add_argument("--trades-limit", type=int, default=1000)
    p.add_argument("--top", type=int, default=40, help="events to publish in the leaderboard")
    p.add_argument("--series-per-topic", type=int, default=40)
    p.add_argument("--universe-out", type=int, default=200)
    p.add_argument("--markets-per-event", type=int, default=6)
    p.add_argument("--depth", type=int, default=12)
    p.add_argument("--candle-hours", type=int, default=6)
    p.add_argument("--candle-period", type=int, default=60, choices=[1, 60, 1440])
    p.add_argument("--settled-per-topic", type=int, default=8)
    p.add_argument("--no-candles", action="store_true")
    p.add_argument("--no-depth", action="store_true")
    p.add_argument("--no-resolutions", action="store_true")
    p.add_argument("--resolutions-only", action="store_true")
    p.add_argument("--out", default=os.path.join(DATA_DIR, "live_snapshot.json"))
    args = p.parse_args(argv)

    client = KalshiClient(BASES[args.base])
    if args.resolutions_only:
        rows = collect_resolutions(client, {t: {"topic": t} for t in
                                            [x["id"] for x in load_topics()]}, load_topics(), args)
        merge_resolutions(rows)
        return 0

    snap = build_snapshot(args)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(snap, fh, indent=2)
    size_kb = os.path.getsize(args.out) / 1024
    print(f"[done] {args.out} ({size_kb:,.0f} KB) — {len(snap['ranked_events'])} events, "
          f"{len(snap['problems'])} problems")
    if snap["problems"]:
        for pr in snap["problems"][:10]:
            print(f"  ! {pr.get('stage')}: {pr.get('error') or pr.get('detail')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
