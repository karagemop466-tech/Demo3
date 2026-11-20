"""Automated simulated ("paper") trading desk for the Kalshi DEMO exchange.

What this does, unattended, on a schedule (GitHub Actions; `.github/workflows/
paper-desk.yml`):

1. reads the tracked universe from the collector snapshot `data/latest/top_events.json`
   (five focus topics only: gas prices, elections, culture, crypto, golf);
2. pulls LIVE quotes for those tickers from the official demo REST root
   `https://external-api.demo.kalshi.co/trade-api/v2` (`GET /markets?tickers=`,
   `GET /markets/{ticker}/orderbook`);
3. evaluates five deterministic strategy rules (`trading/paper_strategies.py`);
4. simulates fills against the quotes and the size actually resting at the touch,
   marks open positions to market, realizes P&L on settlement, and keeps a
   running journal, equity curve and per-trade-type analysis in `data/paper/`.

What it does NOT do:
- it never sends an order to Kalshi (no credentials are used, none are needed:
  every endpoint here is public market data, per
  https://docs.kalshi.com/getting_started/quick_start_market_data.md);
- it never invents an account balance, a fill, or a settlement. When liquidity,
  a price or a settlement value is not published, the trade is rejected with a
  reason or the field is left `null` — values are only ever arithmetic on fields
  the exchange returned;
- it is NOT the user's demo account. Real account tracking stays blocked until
  demo API credentials exist (see `data/latest/portfolio.json`, flag I-12).

Official semantics this file depends on (fetched 2026-11-20; full register in
`paper-desk/SOURCES.md`):
- demo root + "prices may not reflect real markets" warning —
  https://docs.kalshi.com/getting_started/demo_env.md
- Market fields and their meanings — https://docs.kalshi.com/api-reference/market/get-markets.md
- orderbook bids-only structure, ascending arrays, YES-bid/NO-ask reciprocity —
  https://docs.kalshi.com/getting_started/orderbook_responses.md
- `tickers=` filter: "When `event_ticker` or `tickers` is the only filter ... every
  matching market is returned in one response" (no paging, `limit` not applied) —
  https://docs.kalshi.com/api-reference/market/get-markets.md
- settlement: "Yes contract holders receive $1 per contract ... No contract holders
  receive $1 per contract"; settlement fee is zero for simple yes/no —
  https://docs.kalshi.com/getting_started/market_settlement.md
- `notional_value_dollars` = "The total value of a single contract at settlement in
  dollars"; `settlement_value_dollars` = "The settlement value of the YES/LONG side
  ... Only filled after determination" — get-markets.md / get-market.md
- responses are briefly cached, so quotes "can lag the exchange by several seconds" —
  get-markets.md (surfaced in the UI as a data limit)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "collector"))

from paper_strategies import (  # noqa: E402
    STRATEGIES, SWING_THRESHOLD_DOLLARS, categorize, evaluate_entries, evaluate_exits,
    grid_step, price_on_grid,
)

DEMO_REST_ROOT = "https://external-api.demo.kalshi.co/trade-api/v2"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR_DEFAULT = os.path.join(REPO_ROOT, "data")
SCHEMA_VERSION = 1

TOPICS = ("gas", "elections", "culture", "crypto", "golf")

# Demo-catalog series that are exchange test artefacts, not markets to trade.
# Evidence: session 4d10aedf flag I-15 (KXDEMOFUTHOURLY hourly demo BTC, KXQUICKSETTLE
# "1+1=2"), and `custom_strike: {"demo strike": "demo strike"}` on demo markets
# (observed live 2026-11-20 in GET /markets?tickers=KXOSCARPIC-27-DIG).
EXCLUDED_EVENT_PREFIXES = ("KXDEMOFUTHOURLY", "KXQUICKSETTLE", "KXMAXSHARDINGTEST",
                           "KXNOMINEECONF", "KXMVECROSSCATEGORY")

SOURCES = {
    "demo_env": "https://docs.kalshi.com/getting_started/demo_env.md",
    "api_environments": "https://docs.kalshi.com/getting_started/api_environments.md",
    "get_markets": "https://docs.kalshi.com/api-reference/market/get-markets.md",
    "get_market": "https://docs.kalshi.com/api-reference/market/get-market.md",
    "orderbook": "https://docs.kalshi.com/api-reference/market/get-market-orderbook.md",
    "orderbooks_batch": "https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md",
    "get_event": "https://docs.kalshi.com/api-reference/events/get-event.md",
    "candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
    "orderbook_structure": "https://docs.kalshi.com/getting_started/orderbook_responses.md",
    "market_settlement": "https://docs.kalshi.com/getting_started/market_settlement.md",
    "fixed_point": "https://docs.kalshi.com/getting_started/fixed_point_migration.md",
    "rate_limits": "https://docs.kalshi.com/getting_started/rate_limits.md",
    "public_data_no_auth": "https://docs.kalshi.com/getting_started/quick_start_market_data.md",
    "create_order": "https://docs.kalshi.com/getting_started/quick_start_create_order.md",
    "live_market_object_captured":
        "https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers="
        "KXPRESNOMD-28-AOC,KXBTCY-27JAN0100-B122500,KXAAAGASM-26NOV30-4.70,"
        "KXPGATOUR-THRC26-TMOO,KXOSCARPIC-27-DIG",
}

DEFAULT_CONFIG = {
    "starting_cash_dollars": 5000.0,
    "cash_floor_dollars": 500.0,
    "risk_per_trade_dollars": 25.0,
    "max_contracts_per_trade": 200,
    "max_open_notional_per_market_dollars": 50.0,
    "max_open_positions": 20,
    "max_new_orders_per_run": 6,
    "max_orderbook_tickers_per_run": 40,   # tickers whose books are pulled, batched
    "orderbook_batch_size": 100,           # documented max per /markets/orderbooks call
    "max_resting_runs": 24,
    "markets_per_event": 3,
    "events_per_topic": 15,
    "ticker_batch_size": 50,
    "swing_threshold_dollars": SWING_THRESHOLD_DOLLARS,
    "fees_modeled": False,
    "min_trade_count_for_derived_rules": 3,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def dollars(value):
    """FixedPointDollars string -> float, or None. Never a guessed default."""
    if value in (None, "", "null"):
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def count_fp(value):
    if value in (None, "", "null"):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------- clients
class LiveClient:
    """Public read-only client (no auth, no orders)."""

    name = "live-api"

    def __init__(self, root: str = DEMO_REST_ROOT, min_interval: float = 0.25):
        from kalshi_api import KalshiClient  # collector/kalshi_api.py
        self._c = KalshiClient(root=root, min_interval=min_interval, retries=3, timeout=25.0)
        self.root = self._c.root

    def get(self, path: str, params=None):
        return self._c.request("GET", path, params=params)

    def get_raw(self, path_with_query: str):
        """GET a path that already carries its query string (repeated params)."""
        return self._c.request("GET", path_with_query)

    def begin_run(self) -> None:
        """Hook called once per desk cycle (fixture clients reset their replay index)."""

    @property
    def requests(self) -> int:
        return self._c.request_count

    @property
    def errors(self) -> int:
        return self._c.error_count


class FixtureClient:
    """Offline replay of captured demo-API responses (`--fixtures`); test-only.

    Files are named after the request: `markets_tickers_<n>.json` for batch listings,
    `orderbook_<TICKER>.json` for books, `market_<TICKER>.json` for single reads.
    Output is labeled `data_mode: "offline-fixtures"` so it can never be mistaken for
    a live snapshot.
    """

    name = "offline-fixtures"

    def __init__(self, root: str, fixture_dir: str):
        self.root = root
        self.dir = fixture_dir
        self.requests = 0
        self.errors = 0
        self._batch = 0

    def begin_run(self) -> None:
        self._batch = 0

    def _load(self, fname: str):
        path = os.path.join(self.dir, fname)
        if not os.path.exists(path):
            self.errors += 1
            raise FileNotFoundError(path)
        with open(path) as fh:
            return json.load(fh)

    def get_raw(self, path_with_query: str):
        return self.get(path_with_query)

    def get(self, path: str, params=None):
        self.requests += 1
        if path.startswith("/markets/orderbooks"):
            try:
                return self._load("orderbooks.json")
            except FileNotFoundError:
                return {"orderbooks": []}
        if path == "/markets" and params and "tickers" in params:
            self._batch += 1
            return self._load(f"markets_tickers_{self._batch}.json")
        if "?" in path:
            path = path.split("?")[0]
        if path.startswith("/markets/") and path.endswith("/orderbook"):
            ticker = path.split("/")[2]
            return self._load(f"orderbook_{ticker}.json")
        if path.startswith("/markets/"):
            return self._load(f"market_{path.split('/')[2]}.json")
        raise KeyError(f"no fixture for {path}")


# ------------------------------------------------------------------- universe
def load_universe(data_dir: str, config: dict) -> tuple[list[dict], dict]:
    """Build the tracked ticker list from the collector snapshot, topic by topic."""
    path = os.path.join(data_dir, "latest", "top_events.json")
    meta = {"universe_source": path, "universe_source_ok": os.path.exists(path),
            "excluded": [], "snapshot_retrieved_at": None}
    if not meta["universe_source_ok"]:
        return [], meta
    with open(path) as fh:
        snap = json.load(fh)
    meta["snapshot_retrieved_at"] = snap.get("retrieved_at")
    by_topic = snap.get("by_topic") or {}
    universe: list[dict] = []
    for topic in TOPICS:
        events = by_topic.get(topic) or []
        for event in events[: config["events_per_topic"]]:
            ticker = event.get("event_ticker") or ""
            if any(ticker.startswith(p) for p in EXCLUDED_EVENT_PREFIXES):
                meta["excluded"].append({"event_ticker": ticker, "topic": topic,
                                         "reason": "demo test/placeholder series "
                                                   "(flag I-15 / I-2B-03)"})
                continue
            for m in (event.get("top_markets") or [])[: config["markets_per_event"]]:
                mt = m.get("ticker")
                if not mt:
                    continue
                universe.append({
                    "ticker": mt,
                    "event_ticker": ticker,
                    "series_ticker": m.get("series_ticker") or "",
                    "topic": topic,
                    "title": m.get("title") or event.get("title") or "",
                    "event_dollar_volume_snapshot": event.get("volume_dollars_derived"),
                    "snapshot_source_url": event.get("source_url"),
                })
    return universe, meta


# ---------------------------------------------------------------------- quotes
def quote_from_market(market: dict) -> dict:
    """Parse the published quote fields into floats (no derived numbers)."""
    return {
        "yes_bid": dollars(market.get("yes_bid_dollars")),
        "yes_ask": dollars(market.get("yes_ask_dollars")),
        "no_bid": dollars(market.get("no_bid_dollars")),
        "no_ask": dollars(market.get("no_ask_dollars")),
        "yes_bid_size": count_fp(market.get("yes_bid_size_fp")),
        "yes_ask_size": count_fp(market.get("yes_ask_size_fp")),
        "last": dollars(market.get("last_price_dollars")),
        "previous_yes_bid": dollars(market.get("previous_yes_bid_dollars")),
        "previous_yes_ask": dollars(market.get("previous_yes_ask_dollars")),
        "previous_price": dollars(market.get("previous_price_dollars")),
        "volume_fp": count_fp(market.get("volume_fp")),
        "volume_24h": count_fp(market.get("volume_24h_fp")),
        "open_interest": count_fp(market.get("open_interest_fp")),
        "notional": dollars(market.get("notional_value_dollars")),
        "settlement_value": dollars(market.get("settlement_value_dollars")),
        "settlement_ts": market.get("settlement_ts"),
        "expiration_value": market.get("expiration_value"),
        "close_time": market.get("close_time"),
        "status": market.get("status"),
        "result": market.get("result") or "",
        "title": market.get("title") or "",
        "event_ticker": market.get("event_ticker") or "",
        "market_type": market.get("market_type") or "",
    }


def fetch_quotes(client, tickers: list[str], batch: int) -> tuple[dict, dict]:
    """`GET /markets?tickers=` in batches; returns ({ticker: market}, stats)."""
    stats = {"requests": 0, "errors": 0, "markets": 0, "failed_batches": []}
    out: dict[str, dict] = {}
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        try:
            data = client.get("/markets", {"tickers": ",".join(chunk)})
            stats["requests"] += 1
        except Exception as exc:  # network/HTTP: record, keep the run alive
            stats["errors"] += 1
            stats["failed_batches"].append({"size": len(chunk), "error": str(exc)[:300]})
            continue
        for m in data.get("markets") or []:
            t = m.get("ticker")
            if t:
                out[t] = m
                stats["markets"] += 1
    return out, stats


def fetch_book(client, ticker: str, depth: int = 6) -> dict | None:
    """Single-market read; kept for spot checks (the desk batches via fetch_books)."""
    url = f"{client.root}/markets/{ticker}/orderbook?depth={depth}"
    try:
        data = client.get(f"/markets/{ticker}/orderbook", {"depth": depth})
    except Exception:
        return None
    return parse_book(ticker, data.get("orderbook_fp") or data.get("orderbook"), url, depth)


def parse_book(ticker: str, orderbook_fp: dict, source_url: str, depth: int | None = None) -> dict:
    """Normalize an `orderbook_fp` object (bids-only, ascending; best = last)."""
    book = orderbook_fp or {}
    yes = [[dollars(p), count_fp(s)] for p, s in (book.get("yes_dollars") or [])]
    no = [[dollars(p), count_fp(s)] for p, s in (book.get("no_dollars") or [])]
    out = {
        "ticker": ticker,
        "yes_bid_levels": yes,
        "no_bid_levels": no,
        "best_yes_bid": yes[-1] if yes else None,
        "best_no_bid": no[-1] if no else None,
        # implied best YES ask = 1 - best NO bid (documented reciprocity)
        "implied_yes_ask": (round(1.0 - no[-1][0], 4) if no and no[-1][0] is not None else None),
        "implied_no_ask": (round(1.0 - yes[-1][0], 4) if yes and yes[-1][0] is not None else None),
        "fetched_at": now_iso(),
        "source_url": source_url,
    }
    if depth:
        out["depth_requested"] = depth
    return out


def fetch_books(client, tickers: list[str], batch: int, depth: int = 6) -> tuple[dict, dict]:
    """`GET /markets/orderbooks?tickers=...&tickers=...` (form/explode, max 100).

    https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md:
    "Returns one orderbook per requested market ticker, in request order. A ticker
    that has no order book ... is returned with empty arrays."
    """
    from urllib.parse import quote
    stats = {"requests": 0, "errors": 0, "tickers": 0, "batches": []}
    out: dict[str, dict] = {}
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        query = "&".join(f"tickers={quote(t, safe='')}" for t in chunk)
        url = f"{client.root}/markets/orderbooks?{query}&depth={depth}"
        try:
            data = client.get_raw(f"/markets/orderbooks?{query}&depth={depth}")
            stats["requests"] += 1
            stats["batches"].append({"size": len(chunk), "status": 200})
        except Exception as exc:
            stats["errors"] += 1
            stats["batches"].append({"size": len(chunk), "error": str(exc)[:200]})
            continue
        for ob in data.get("orderbooks") or []:
            t = ob.get("ticker")
            if not t:
                continue
            out[t] = parse_book(t, ob.get("orderbook_fp"), url, depth)
        stats["tickers"] += len(chunk)
    return out, stats


def size_at_touch(side: str, want: str, quote: dict) -> float | None:
    """Contracts available at the top of book for this side/action.

    `yes_bid_size_fp` / `yes_ask_size_fp` are the documented sizes at the YES best bid
    / best ask. The NO side has no published size field, but orderbook_responses.md
    states a YES BID at X is equivalent to a NO ASK at (1 - X) — so the size resting
    behind each NO price is the size at the mirrored YES level. That identity is a
    structural equivalence, not a new number.
    """
    if want == "buy" and side == "yes":
        return quote.get("yes_ask_size")
    if want == "sell" and side == "yes":
        return quote.get("yes_bid_size")
    if want == "buy" and side == "no":
        return quote.get("yes_bid_size")   # mirrored: NO ask = 1 - YES bid
    if want == "sell" and side == "no":
        return quote.get("yes_ask_size")   # mirrored: NO bid = 1 - YES ask
    return None


def price_for(client_side: dict, want: str) -> float | None:
    """Executable taker price for (side, buy|sell) from published quotes only."""
    if want == "buy":
        return client_side.get("yes_ask") if client_side["side"] == "yes" else client_side.get("no_ask")
    return client_side.get("yes_bid") if client_side["side"] == "yes" else client_side.get("no_bid")


# ------------------------------------------------------------------ desk state
def init_state(config: dict, api_root: str, data_mode: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "simulated-paper",
        "data_mode": data_mode,
        "generated_at": now_iso(),
        "api_root": api_root,
        "config": config,
        "starting_cash_dollars": config["starting_cash_dollars"],
        "cash_dollars": config["starting_cash_dollars"],
        "realized_pnl_dollars": 0.0,
        "run_count": 0,
        "positions": [],
        "resting_orders": [],
        "tracked": {},
        "samples": [],
        "counters": {"fills": 0, "rejections": 0, "closes": 0, "settlements": 0,
                     "resting_placed": 0, "resting_filled": 0, "resting_cancelled": 0},
        "fees_note": "no fees modeled (see paper-desk flagged items); settlement of a "
                     "simple yes/no market carries no settlement fee per "
                     + SOURCES["market_settlement"],
        "sources": SOURCES,
    }


def load_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, path)


def append_records(path: str, key: str, records: list[dict], cap: int) -> dict:
    doc = load_json(path, {key: []}) or {key: []}
    items = doc.get(key) or []
    items.extend(records)
    if len(items) > cap:
        items = items[-cap:]
    doc[key] = items
    doc["updated_at"] = now_iso()
    write_json(path, doc)
    return doc


def position_index(state: dict) -> dict:
    return {p["key"]: p for p in state["positions"]}


def open_notional(state: dict, ticker: str) -> float:
    return sum((p.get("cost_basis_dollars") or 0.0) for p in state["positions"]
               if p.get("ticker") == ticker)


# ------------------------------------------------------------------ accounting
def do_open(state: dict, intent: dict, price: float, size: float, run: int,
            book: dict | None, api_root: str) -> dict:
    cost_cap = state["config"]["risk_per_trade_dollars"]
    spendable = max(0.0, state["cash_dollars"] - state["config"]["cash_floor_dollars"])
    budget = min(cost_cap, spendable,
                 max(0.0, state["config"]["max_open_notional_per_market_dollars"]
                     - open_notional(state, intent["ticker"])))
    by_cost = int(math.floor(budget / price)) if price > 0 else 0
    by_liquidity = int(math.floor(size)) if size else 0
    n = min(by_cost, by_liquidity, state["config"]["max_contracts_per_trade"])
    if n < 1:
        return {"status": "rejected",
                "reject_reason": (f"no fillable size: budget {budget:.2f} USD at "
                                  f"{price:.4f} USD allows {by_cost} contracts; size at "
                                  f"touch {size}"),
                "count": 0}
    cost = round(n * price, 4)
    key = f'{intent["ticker"]}|{intent["side"]}'
    idx = position_index(state)
    pos = idx.get(key)
    if pos:
        new_count = pos["count"] + n
        pos["avg_price_dollars"] = round(
            (pos["avg_price_dollars"] * pos["count"] + price * n) / new_count, 6)
        pos["count"] = new_count
        pos["cost_basis_dollars"] = round(pos["cost_basis_dollars"] + cost, 4)
    else:
        pos = {
            "key": key, "ticker": intent["ticker"], "event_ticker": intent["event_ticker"],
            "side": intent["side"], "count": n, "avg_price_dollars": round(price, 6),
            "cost_basis_dollars": round(cost, 4), "opened_at": now_iso(),
            "opened_run": run, "strategy": intent["strategy"],
            "strategy_label": intent["strategy_label"], "family": intent["family"],
            "topic": intent.get("topic"), "title": intent.get("title"),
            "last_mark_dollars": price, "unrealized_pnl_dollars": 0.0,
            "source_url": f"{api_root}/markets/{intent['ticker']}",
        }
        state["positions"].append(pos)
    state["cash_dollars"] = round(state["cash_dollars"] - cost, 4)
    state["counters"]["fills"] += 1
    rec = {
        "ts": now_iso(), "run": run, "action": "open", "status": "filled",
        "strategy": intent["strategy"], "strategy_label": intent["strategy_label"],
        "family": intent["family"], "role": intent["role"], "side": intent["side"],
        "ticker": intent["ticker"], "event_ticker": intent["event_ticker"],
        "topic": intent.get("topic"), "title": intent.get("title"),
        "count": n, "price_dollars": round(price, 4), "notional_dollars": cost,
        "proceeds_dollars": -cost, "realized_pnl_dollars": None,
        "reason": intent["reason"], "signal": intent["signal"],
        "size_at_touch_fp": size, "book": None if not book else {
            "best_yes_bid": book.get("best_yes_bid"), "best_no_bid": book.get("best_no_bid"),
            "source_url": book.get("source_url")},
        "classification": categorize(intent["quote"], "open", intent["side"], price,
                                     intent.get("topic")),
        "fill_basis": ("simulated taker fill at the published best ask (size capped by the "
                       "contracts resting at that price)"),
        "fees_modeled": False,
        "source_urls": {"markets": f"{api_root}/markets?tickers={intent['ticker']}",
                        "orderbook": None if not book else book.get("source_url")},
        "mode": "simulated-paper",
    }
    return {"status": "filled", "record": rec, "position_key": key}


def do_close(state: dict, pos: dict, price: float, size: float, n: int, run: int,
             reason: str, api_root: str, extra: dict | None = None) -> dict:
    n = min(n, int(math.floor(size)) if size else 0, pos["count"])
    if n < 1:
        return {"status": "rejected", "count": 0,
                "reject_reason": f"cannot exit: size at touch {size} contracts"}
    proceeds = round(n * price, 4)
    basis = round(n * pos["avg_price_dollars"], 4)
    realized = round(proceeds - basis, 4)
    pos["count"] -= n
    pos["cost_basis_dollars"] = round(pos["cost_basis_dollars"] - basis, 4)
    if pos["count"] <= 0:
        state["positions"] = [p for p in state["positions"] if p["key"] != pos["key"]]
    state["cash_dollars"] = round(state["cash_dollars"] + proceeds, 4)
    state["realized_pnl_dollars"] = round(state["realized_pnl_dollars"] + realized, 4)
    state["counters"]["closes"] += 1
    rec = {
        "ts": now_iso(), "run": run, "action": "close", "status": "filled",
        "strategy": pos["strategy"], "strategy_label": pos.get("strategy_label"),
        "family": pos.get("family"), "role": "taker", "side": pos["side"],
        "ticker": pos["ticker"], "event_ticker": pos.get("event_ticker"),
        "topic": pos.get("topic"), "title": pos.get("title"),
        "count": n, "price_dollars": round(price, 4), "notional_dollars": proceeds,
        "proceeds_dollars": proceeds, "realized_pnl_dollars": realized,
        "avg_entry_dollars": pos["avg_price_dollars"], "reason": reason,
        "classification": {"topic": pos.get("topic"), "action": "close",
                           "side": pos["side"], "price_dollars": round(price, 4),
                           "price_band": categorize({}, "close", pos["side"], price,
                                                    pos.get("topic"))["price_band"]},
        "fill_basis": "simulated taker exit at the published best bid for the held side",
        "fees_modeled": False,
        "source_urls": {"markets": f"{api_root}/markets?tickers={pos['ticker']}"},
        "mode": "simulated-paper",
    }
    if extra:
        rec.update(extra)
    return {"status": "filled", "record": rec}


def do_settlements(state: dict, quotes: dict, run: int, api_root: str):
    """Realize P&L for positions whose market has resolved (yes/no), per docs."""
    trades, resolutions, kept = [], [], []
    for pos in state["positions"]:
        m = quotes.get(pos["ticker"])
        # `result` is only published once the market has been determined
        # (get-market.md: `settlement_value_dollars` ... "Only filled after
        # determination"), so a non-empty yes/no result is the resolution signal.
        result = (m.get("result") or "") if m else ""
        status = (m.get("status") or "") if m else ""
        if result not in ("yes", "no"):
            kept.append(pos)
            continue
        # Payout per side. market_settlement.md: "Yes outcome: Yes contract holders
        # receive $1 per contract. No outcome: No contract holders receive $1 per
        # contract." `notional_value_dollars` is "the total value of a single contract
        # at settlement"; `settlement_value_dollars` is the determined value of the
        # YES/LONG side and wins over the generic notional when published.
        notional = m.get("notional")
        if notional is None:
            notional = 1.0  # documented $1 per winning contract
        yes_value = m.get("settlement_value")
        result_yes = (result == "yes")
        if pos["side"] == "yes":
            payout_each = yes_value if yes_value is not None else (notional if result_yes else 0.0)
        else:
            payout_each = 0.0 if result_yes else notional
        if payout_each is None:  # e.g. a `scalar` result — payout never guessed
            kept.append(pos)
            continue
        payout = round(pos["count"] * payout_each, 4)
        basis = round(pos["count"] * pos["avg_price_dollars"], 4)
        realized = round(payout - basis, 4)
        state["cash_dollars"] = round(state["cash_dollars"] + payout, 4)
        state["realized_pnl_dollars"] = round(state["realized_pnl_dollars"] + realized, 4)
        state["counters"]["settlements"] += 1
        won = (result == pos["side"])
        trades.append({
            "ts": now_iso(), "run": run, "action": "settle", "status": "settled",
            "strategy": pos["strategy"], "strategy_label": pos.get("strategy_label"),
            "family": pos.get("family"), "role": "settlement", "side": pos["side"],
            "ticker": pos["ticker"], "event_ticker": pos.get("event_ticker"),
            "topic": pos.get("topic"), "title": pos.get("title"),
            "count": pos["count"], "price_dollars": round(payout_each, 4),
            "proceeds_dollars": payout, "realized_pnl_dollars": realized,
            "avg_entry_dollars": pos["avg_price_dollars"],
            "reason": f"market resolved '{result}'; {'winning' if won else 'losing'} side",
            "settlement_result": result, "settlement_ts": m.get("settlement_ts"),
            "expiration_value": m.get("expiration_value"),
            "classification": {"topic": pos.get("topic"), "action": "settle",
                               "side": pos["side"],
                               "price_band": "settlement"},
            "fill_basis": "payout per official settlement rule: $1 per winning contract "
                          "(notional_value_dollars when the field is present)",
            "fees_modeled": False,
            "source_urls": {"markets": f"{api_root}/markets?tickers={pos['ticker']}"},
            "mode": "simulated-paper",
        })
        resolutions.append({
            "ticker": pos["ticker"], "event_ticker": pos.get("event_ticker"),
            "topic": pos.get("topic"), "title": m.get("title") or pos.get("title"),
            "result": result, "status": status,
            "settlement_ts": m.get("settlement_ts"),
            "expiration_value": m.get("expiration_value"),
            "notional_value_dollars": notional,
            "settlement_value_dollars": yes_value,
            "desk_position_side": pos["side"], "desk_outcome": "win" if won else "loss",
            "desk_realized_pnl_dollars": realized, "desk_count": pos["count"],
            "resolved_seen_at": now_iso(),
            "source_url": f"{api_root}/markets/{pos['ticker']}",
        })
    state["positions"] = kept
    return trades, resolutions


# ---------------------------------------------------------------- analysis
def _blank_bucket() -> dict:
    return {"trades": 0, "wins": 0, "losses": 0, "realized_pnl_dollars": 0.0,
            "notional_dollars": 0.0, "contracts": 0.0, "rejections": 0}


def _add_bucket(b: dict, rec: dict) -> None:
    b["trades"] += 1
    pnl = rec.get("realized_pnl_dollars")
    if pnl is not None:
        b["realized_pnl_dollars"] = round(b["realized_pnl_dollars"] + pnl, 4)
        if pnl > 0:
            b["wins"] += 1
        elif pnl < 0:
            b["losses"] += 1
    if rec.get("status") == "rejected":
        b["rejections"] += 1
    b["notional_dollars"] = round(b["notional_dollars"] + (rec.get("notional_dollars") or 0.0), 4)
    b["contracts"] = round(b["contracts"] + (rec.get("count") or 0.0), 2)


def _finish(name: str, b: dict) -> dict:
    closed = b["wins"] + b["losses"]
    out = {"key": name, **b, "closed_trades": closed,
           "win_rate": round(b["wins"] / closed, 4) if closed else None,
           "avg_realized_pnl_dollars": round(b["realized_pnl_dollars"] / closed, 4)
           if closed else None}
    return out


def analyze(trades: list[dict], state: dict, equity: list[dict]) -> dict:
    dims = {"by_strategy": "strategy", "by_topic": "topic", "by_side": "side",
            "by_price_band": None, "by_family": "family", "by_action": "action"}
    buckets: dict[str, dict] = {k: {} for k in dims}
    for rec in trades:
        for name, field in dims.items():
            if field:
                key = rec.get(field)
                if field == "action" and rec.get("status") == "rejected":
                    key = "rejected"
            else:
                key = ((rec.get("classification") or {}).get("price_band"))
            if not key:
                continue
            b = buckets[name].setdefault(str(key), _blank_bucket())
            _add_bucket(b, rec)
    grouped = {name: sorted((_finish(k, v) for k, v in b.items()),
                            key=lambda r: -r["realized_pnl_dollars"])
               for name, b in buckets.items()}

    min_n = state["config"]["min_trade_count_for_derived_rules"]
    derived = []
    for row in grouped["by_topic"]:
        derived.append({"type": f"topic={row['key']}", "closed_trades": row["closed_trades"],
                        "realized_pnl_dollars": row["realized_pnl_dollars"],
                        "win_rate": row["win_rate"]})
    combo: dict[str, dict] = {}
    for rec in trades:
        if rec.get("realized_pnl_dollars") is None:
            continue
        cls = rec.get("classification") or {}
        key = f"topic={rec.get('topic')} | side={rec.get('side')} | " \
              f"band={cls.get('price_band') or rec.get('classification', {}).get('price_band')}"
        b = combo.setdefault(key, _blank_bucket())
        _add_bucket(b, rec)
    combo_rows = [_finish(k, v) for k, v in combo.items()]
    combo_rows.sort(key=lambda r: -r["realized_pnl_dollars"])
    derived = [r for r in derived if r["closed_trades"] >= min_n] + [
        {"type": r["key"], "closed_trades": r["closed_trades"],
         "realized_pnl_dollars": r["realized_pnl_dollars"], "win_rate": r["win_rate"],
         "avg_realized_pnl_dollars": r["avg_realized_pnl_dollars"]}
        for r in combo_rows]
    derived.sort(key=lambda r: -(r["realized_pnl_dollars"] or 0.0))

    eq_vals = [s.get("equity_dollars") for s in equity if s.get("equity_dollars") is not None]
    peak, max_dd = None, 0.0
    for v in eq_vals:
        peak = v if peak is None else max(peak, v)
        max_dd = max(max_dd, round(peak - v, 4))
    unrealized = round(sum(p.get("unrealized_pnl_dollars") or 0.0 for p in state["positions"]), 4)
    closed_pnl = state["realized_pnl_dollars"]
    return {
        "generated_at": now_iso(),
        "mode": "simulated-paper",
        "totals": {
            "journal_records": len(trades),
            "fills": state["counters"]["fills"],
            "closes": state["counters"]["closes"],
            "settlements": state["counters"]["settlements"],
            "rejections": state["counters"]["rejections"],
            "resting_placed": state["counters"]["resting_placed"],
            "resting_filled": state["counters"]["resting_filled"],
            "resting_cancelled": state["counters"]["resting_cancelled"],
            "open_positions": len(state["positions"]),
            "resting_orders": len(state["resting_orders"]),
            "cash_dollars": state["cash_dollars"],
            "starting_cash_dollars": state["starting_cash_dollars"],
            "equity_dollars": round(state["cash_dollars"]
                                    + sum(p.get("market_value_dollars") or 0.0
                                          for p in state["positions"]), 4),
            "realized_pnl_dollars": closed_pnl,
            "unrealized_pnl_dollars": unrealized,
            "total_pnl_dollars": round(closed_pnl + unrealized, 4),
            "max_drawdown_dollars": max_dd,
            "samples": len(equity),
        },
        "grouped": grouped,
        "derived_rule_candidates": {
            "rows": derived[:20],
            "min_closed_trades_for_a_claim": min_n,
            "note": "descriptive ranking of realized results inside this demo run only; "
                    "small samples; not a forecast and not Kalshi data",
        },
        "caveats": {
            "demo_prices": "demo prices may not reflect real markets "
                           "(" + SOURCES["demo_env"] + ")",
            "fees": "no trading fees modeled in this ledger",
            "account": "not the user's demo account; account tracking needs demo API "
                       "credentials (data/latest/portfolio.json status credentials_missing)",
            "cache": "responses are briefly cached, so desk-to-desk deltas can lag the "
                     "exchange by seconds (" + SOURCES["get_markets"] + ")",
        },
    }


# ------------------------------------------------------------------ one cycle
def run_cycle(client, data_dir: str, config: dict, reset: bool = False,
              quiet: bool = False) -> dict:
    paper = os.path.join(data_dir, "paper")
    os.makedirs(paper, exist_ok=True)
    api_root = getattr(client, "root", DEMO_REST_ROOT)
    data_mode = "offline-fixtures" if isinstance(client, FixtureClient) else "live-api"
    state = load_json(os.path.join(paper, "state.json"))
    if reset or not state or state.get("schema_version") != SCHEMA_VERSION:
        state = init_state(config, api_root, data_mode)
    state["data_mode"] = data_mode
    state["config"] = config
    state["api_root"] = api_root
    run = state["run_count"] + 1
    journal_doc = load_json(os.path.join(paper, "trades.json"), {"trades": []}) or {"trades": []}
    journal: list[dict] = list(journal_doc.get("trades") or [])
    equity_doc = load_json(os.path.join(paper, "equity.json"), {"samples": []}) or {"samples": []}
    samples: list[dict] = list(equity_doc.get("samples") or [])
    new_trades: list[dict] = []
    log = {"run": run, "ts": now_iso(), "requests_start": client.requests,
           "errors_start": client.errors, "notes": []}

    begin = getattr(client, "begin_run", None)
    if callable(begin):
        begin()
    universe, umeta = load_universe(data_dir, config)
    tickers = sorted({u["ticker"] for u in universe})
    pos_tickers = sorted({p["ticker"] for p in state["positions"]}
                         | {o["ticker"] for o in state["resting_orders"]})
    quotes_raw, qstats = fetch_quotes(client, list(dict.fromkeys(tickers + pos_tickers)),
                                      config["ticker_batch_size"])
    log.update({"universe": len(tickers), "positions_queried": len(pos_tickers),
                "markets_returned": qstats["markets"], "quote_batches": qstats["requests"],
                "quote_errors": qstats["errors"]})

    quotes = {t: quote_from_market(m) for t, m in quotes_raw.items()}
    topic_by_ticker = {u["ticker"]: u["topic"] for u in universe}
    title_by_ticker = {u["ticker"]: u["title"] for u in universe}
    event_by_ticker = {u["ticker"]: u["event_ticker"] for u in universe}

    # 1) exits on open positions (frees cash before new risk is taken)
    now_dt = datetime.now(timezone.utc)
    for pos in list(state["positions"]):
        q = quotes.get(pos["ticker"])
        if not q:
            log["notes"].append(f"no quote for held {pos['ticker']} this run (kept)")
            continue
        exit_price = q["yes_bid"] if pos["side"] == "yes" else q["no_bid"]
        size = size_at_touch(pos["side"], "sell", q)
        runs_held = run - int(pos.get("opened_run") or run)
        intent = evaluate_exits({"avg_price_dollars": pos["avg_price_dollars"],
                                 "side": pos["side"]},
                                {"yes_bid": q["yes_bid"], "no_bid": q["no_bid"]}, runs_held)
        if not intent or exit_price is None:
            continue
        res = do_close(state, pos, exit_price, size if size is not None else 0.0,
                       pos["count"], run, intent["reason"], api_root)
        if res["status"] == "rejected":
            state["counters"]["rejections"] += 1
            rec = {"ts": now_iso(), "run": run, "action": "close", "status": "rejected",
                   "strategy": pos["strategy"], "side": pos["side"], "ticker": pos["ticker"],
                   "topic": pos.get("topic"), "title": pos.get("title"),
                   "reject_reason": res["reject_reason"], "count": 0,
                   "realized_pnl_dollars": None, "price_dollars": exit_price,
                   "source_urls": {"markets": f"{api_root}/markets?tickers={pos['ticker']}"},
                   "mode": "simulated-paper"}
            new_trades.append(rec)
        else:
            new_trades.append(res["record"])

    # 2) resting maker orders: fill only when the published ask crosses the limit
    kept_resting = []
    for order in state["resting_orders"]:
        q = quotes.get(order["ticker"])
        order["age_runs"] = int(order.get("age_runs") or 0) + 1
        if not q:
            kept_resting.append(order)
            continue
        crossed = q.get("yes_ask") is not None and q["yes_ask"] <= order["price_dollars"]
        expired = (order["age_runs"] >= config["max_resting_runs"]
                   or (parse_iso(q.get("close_time")) and q["close_time"] and
                       parse_iso(q["close_time"]) < now_dt))
        if crossed:
            price = min(order["price_dollars"], q["yes_ask"])
            size = size_at_touch("yes", "buy", q) or 0.0
            intent = {"strategy": order["strategy"], "strategy_label": STRATEGIES[
                          order["strategy"]]["label"],
                      "family": STRATEGIES[order["strategy"]]["family"], "role": "maker",
                      "action": "open", "side": "yes", "ticker": order["ticker"],
                      "event_ticker": order["event_ticker"],
                      "topic": order.get("topic"), "title": order.get("title"),
                      "quote": q,
                      "reason": f"resting bid {order['price_dollars']:.4f} crossed by the "
                                f"published ask {q['yes_ask']:.4f}",
                      "signal": {"rested_runs": order["age_runs"],
                                 "limit_dollars": order["price_dollars"]}}
            res = do_open(state, intent, price, size, run, None, api_root)
            if res["status"] == "filled":
                res["record"]["fill_basis"] = ("simulated maker fill: resting bid crossed by "
                                               "a later published ask")
                new_trades.append(res["record"])
                state["counters"]["resting_filled"] += 1
                continue
            order["last_block"] = res.get("reject_reason")
        elif expired:
            state["counters"]["resting_cancelled"] += 1
            new_trades.append({"ts": now_iso(), "run": run, "action": "cancel",
                               "status": "cancelled", "strategy": order["strategy"],
                               "side": "yes", "ticker": order["ticker"],
                               "topic": order.get("topic"), "title": order.get("title"),
                               "price_dollars": order["price_dollars"], "count": 0,
                               "realized_pnl_dollars": None,
                               "reason": "resting order expired (max_resting_runs or past "
                                         "close_time); no fill assumed",
                               "source_urls": {"markets":
                                               f"{api_root}/markets?tickers={order['ticker']}"},
                               "mode": "simulated-paper"})
            continue
        kept_resting.append(order)
    state["resting_orders"] = kept_resting

    # 3) entries
    held_keys = position_index(state)
    candidates = []
    for ticker in tickers:
        m = quotes_raw.get(ticker)
        if not m:
            continue
        q = quotes[ticker]
        prior = state["tracked"].get(ticker) or {}
        ctx = {
            "ticker": ticker, "event_ticker": event_by_ticker.get(ticker)
            or q.get("event_ticker") or "",
            "topic": topic_by_ticker.get(ticker),
            "title": q.get("title") or title_by_ticker.get(ticker) or "",
            "market": m, "quote": q, "prior": prior, "config": config,
            "status": q.get("status"),
            "hours_to_close": None,
        }
        close_dt = parse_iso(q.get("close_time"))
        if close_dt:
            ctx["hours_to_close"] = (close_dt - now_dt).total_seconds() / 3600.0
        intents = evaluate_entries(ctx)
        for it in intents:
            if it.get("resting"):
                exists = any(o["ticker"] == ticker and o["strategy"] == it["strategy"]
                             and o["price_dollars"] == it["price_dollars"]
                             for o in state["resting_orders"])
                if not exists and len(state["resting_orders"]) < config["max_new_orders_per_run"]:
                    it["quote"] = q
                    candidates.append((it, ctx, "maker"))
                continue
            if f'{ticker}|{it["side"]}' in held_keys:
                continue  # one position per (market, side)
            it["quote"] = q
            candidates.append((it, ctx, "taker"))
    # deterministic ordering: biggest desk-to-desk move first, then ticker
    candidates.sort(key=lambda c: (
        -abs(((c[0].get("signal") or {}).get("delta_desk_dollars")) or 0.0), c[0]["ticker"]))

    books_doc_prev = load_json(os.path.join(paper, "books.json"), {"books": []}) or {"books": []}
    book_rows = list(books_doc_prev.get("books") or [])
    placed = 0
    want_books = list(dict.fromkeys(c[0]["ticker"] for c in candidates))
    want_books = want_books[: config.get("max_orderbook_tickers_per_run", 40)]
    books_by_ticker, bstats = fetch_books(client, want_books,
                                          config.get("orderbook_batch_size", 100))
    log.update({"book_requests": bstats["requests"], "book_errors": bstats["errors"],
                "book_tickers": bstats["tickers"]})
    for intent, ctx, kind in candidates:
        if placed >= config["max_new_orders_per_run"]:
            log["notes"].append("max_new_orders_per_run reached; remaining intents not sent")
            break
        if len(state["positions"]) >= config["max_open_positions"]:
            log["notes"].append("max_open_positions reached")
            break
        ticker = intent["ticker"]
        book = books_by_ticker.get(ticker)
        if book:
            book = dict(book, topic=intent.get("topic"))
            book_rows.append(book)
        if intent["role"] == "maker":
            if not price_on_grid(intent["price_dollars"], ctx["market"]):
                state["counters"]["rejections"] += 1
                rec = {k: intent.get(k) for k in
                       ("strategy", "strategy_label", "family", "role", "side", "ticker",
                        "event_ticker", "topic", "title", "price_dollars", "signal")}
                rec.update({"ts": now_iso(), "run": run, "action": "rest",
                            "status": "rejected", "count": 0, "realized_pnl_dollars": None,
                            "reject_reason": "limit price not on this market's published "
                                             "price grid (would be an `invalid_price` order)",
                            "mode": "simulated-paper"})
                new_trades.append(rec)
                continue
            state["resting_orders"].append({
                "ticker": ticker, "event_ticker": intent["event_ticker"],
                "side": "yes", "price_dollars": intent["price_dollars"],
                "strategy": intent["strategy"], "topic": intent.get("topic"),
                "title": intent.get("title"), "placed_at": now_iso(), "age_runs": 0,
                "source_url": f"{api_root}/markets?tickers={ticker}",
            })
            state["counters"]["resting_placed"] += 1
            rec = {k: intent[k] for k in ("strategy", "strategy_label", "family", "role",
                                          "action", "side", "ticker", "event_ticker",
                                          "topic", "title", "price_dollars", "reason",
                                          "signal", "classification")}
            rec.update({"ts": now_iso(), "run": run, "status": "resting", "count": 0,
                        "realized_pnl_dollars": None, "fees_modeled": False,
                        "fill_basis": "order rests; fills only if a later published ask "
                                      "crosses it",
                        "source_urls": {"markets":
                                        f"{api_root}/markets?tickers={ticker}"},
                        "mode": "simulated-paper"})
            new_trades.append(rec)
            placed += 1
            continue
        want_price = price_for({"side": intent["side"], **{k: ctx["quote"][k] for k in
                                 ("yes_bid", "yes_ask", "no_bid", "no_ask")}}, "buy")
        if want_price is None:
            continue
        size = size_at_touch(intent["side"], "buy", ctx["quote"])
        res = do_open(state, intent, want_price, size or 0.0, run, book, api_root)
        if res["status"] == "rejected":
            state["counters"]["rejections"] += 1
            rec = {k: intent[k] for k in ("strategy", "strategy_label", "family", "role",
                                          "action", "side", "ticker", "event_ticker",
                                          "topic", "title", "reason", "signal")}
            rec.update({"ts": now_iso(), "run": run, "status": "rejected", "count": 0,
                        "price_dollars": want_price, "realized_pnl_dollars": None,
                        "reject_reason": res["reject_reason"], "size_at_touch_fp": size,
                        "classification": categorize(ctx["quote"], "open", intent["side"],
                                                      want_price, intent.get("topic")),
                        "source_urls": {"markets":
                                        f"{api_root}/markets?tickers={ticker}"},
                        "mode": "simulated-paper"})
            new_trades.append(rec)
        else:
            new_trades.append(res["record"])
        placed += 1

    # 4) settlements (uses the same batch response — no extra requests)
    settle_trades, resolutions = do_settlements(state, quotes, run, api_root)
    new_trades.extend(settle_trades)

    # 5) marks + sample
    for pos in state["positions"]:
        q = quotes.get(pos["ticker"])
        if not q:
            continue
        mark = q["yes_bid"] if pos["side"] == "yes" else q["no_bid"]
        if mark is None:
            continue
        pos["last_mark_dollars"] = round(mark, 4)
        pos["market_value_dollars"] = round(pos["count"] * mark, 4)
        pos["unrealized_pnl_dollars"] = round(pos["market_value_dollars"]
                                              - pos["cost_basis_dollars"], 4)
        pos["marked_at"] = now_iso()
        pos["source_url"] = f"{api_root}/markets/{pos['ticker']}"
    positions_value = round(sum(p.get("market_value_dollars") or 0.0
                                for p in state["positions"]), 4)
    # tracked samples for next run's swing measure (published fields only)
    for ticker, q in quotes.items():
        state["tracked"][ticker] = {
            "ts": now_iso(), "run": run, "yes_bid": q["yes_bid"], "yes_ask": q["yes_ask"],
            "no_bid": q["no_bid"], "no_ask": q["no_ask"], "last": q["last"],
            "volume_24h": q["volume_24h"],
            "source_url": f"{api_root}/markets?tickers={ticker}",
        }
    # keep the tracked map bounded to the current universe + positions
    keep = set(tickers) | {p["ticker"] for p in state["positions"]}
    state["tracked"] = {k: v for k, v in state["tracked"].items() if k in keep}

    state["run_count"] = run
    state["generated_at"] = now_iso()
    state["cash_dollars"] = round(state["cash_dollars"], 4)
    equity = round(state["cash_dollars"] + positions_value, 4)
    samples.append({"ts": now_iso(), "run": run, "cash_dollars": state["cash_dollars"],
                    "positions_value_dollars": positions_value, "equity_dollars": equity,
                    "open_positions": len(state["positions"]),
                    "resting_orders": len(state["resting_orders"]),
                    "realized_pnl_dollars": state["realized_pnl_dollars"],
                    "unrealized_pnl_dollars": round(sum(
                        p.get("unrealized_pnl_dollars") or 0.0 for p in state["positions"]), 4),
                    "source_url": f"{api_root}/markets?tickers=" + ",".join(
                        sorted({p["ticker"] for p in state["positions"]})[:3])
                    if state["positions"] else f"{api_root}/exchange/status"})
    state["samples"] = samples[-500:]
    journal.extend(new_trades)
    journal = journal[-4000:]

    analysis = analyze(journal, state, samples)
    analysis["universe"] = {"markets_tracked": len(tickers),
                            "markets_quoted": qstats["markets"],
                            "markets_with_a_two_sided_quote": sum(
                                1 for q in quotes.values()
                                if q["yes_bid"] and q["yes_ask"] and q["yes_ask"] < 1.0),
                            "universe_source": umeta}
    analysis["requests"] = {"this_run": client.requests - log["requests_start"],
                            "errors_this_run": client.errors - log["errors_start"],
                            "quote_batches": qstats["requests"],
                            "orderbook_batches": bstats["requests"],
                            "orderbook_tickers": bstats["tickers"],
                            "note": "unauthenticated public requests have their own limits "
                                    "and no published number; this desk throttles to "
                                    f"{config['ticker_batch_size']} tickers/request (books batched at "
                                    f"{config.get('orderbook_batch_size', 100)}/request) and backs "
                                    "off on 429 (" + SOURCES["rate_limits"] + ")"}
    run_row = dict(log)
    run_row.update({
        "requests": client.requests - log["requests_start"],
        "errors": client.errors - log["errors_start"],
        "intents": placed, "new_journal_rows": len(new_trades),
        "fills": state["counters"]["fills"], "rejections": state["counters"]["rejections"],
        "settlements": len(resolutions), "equity_dollars": equity,
        "cash_dollars": state["cash_dollars"], "open_positions": len(state["positions"]),
        "data_mode": data_mode, "api_root": api_root,
    })

    # persist
    write_json(os.path.join(paper, "state.json"), state)
    append_records(os.path.join(paper, "trades.json"), "trades", new_trades, 4000)
    doc = load_json(os.path.join(paper, "trades.json"), {"trades": []})
    doc["analysis_ref"] = "analysis.json"
    doc["mode"] = "simulated-paper"
    doc["sources"] = SOURCES
    write_json(os.path.join(paper, "trades.json"), doc)
    write_json(os.path.join(paper, "equity.json"),
               {"samples": samples[-2000:], "generated_at": now_iso(),
                "mode": "simulated-paper", "sources": SOURCES})
    write_json(os.path.join(paper, "analysis.json"), analysis)
    books_doc = {"books": book_rows[-40:], "generated_at": now_iso(),
                 "note": "point-in-time orderbook snapshots taken at decision time "
                         "(contracts resting at each price); bids-only per "
                         + SOURCES["orderbook_structure"],
                 "sources": SOURCES}
    write_json(os.path.join(paper, "books.json"), books_doc)
    res_doc = load_json(os.path.join(paper, "resolutions.json"), {"resolved": []}) or {"resolved": []}
    res_doc["resolved"] = (res_doc.get("resolved") + resolutions)[-1000:]
    res_doc["generated_at"] = now_iso()
    res_doc["open_tracked"] = len(state["positions"])
    res_doc["note"] = ("resolution = the market's own `result` field ('yes'/'no') from "
                       "the demo API; desk P&L uses $1 per winning contract ("
                       + SOURCES["market_settlement"] + ")")
    res_doc["sources"] = SOURCES
    write_json(os.path.join(paper, "resolutions.json"), res_doc)
    runs_doc = load_json(os.path.join(paper, "runs.json"), {"runs": []}) or {"runs": []}
    runs_doc["runs"] = (runs_doc.get("runs") + [run_row])[-200:]
    runs_doc["generated_at"] = now_iso()
    runs_doc["sources"] = SOURCES
    write_json(os.path.join(paper, "runs.json"), runs_doc)
    write_json(os.path.join(paper, "sources.json"),
               {"generated_at": now_iso(), "api_root": api_root, "docs": SOURCES,
                "universe": umeta, "config": config,
                "strategy_rules": list(STRATEGIES.values())})

    if not quiet:
        print(json.dumps({"run": run, "universe": len(tickers),
                          "quotes": qstats["markets"], "journal_rows": len(new_trades),
                          "fills": state["counters"]["fills"],
                          "rejections": state["counters"]["rejections"],
                          "settlements": len(resolutions),
                          "equity_dollars": equity,
                          "cash_dollars": state["cash_dollars"],
                          "requests": run_row["requests"],
                          "data_mode": data_mode}, indent=2), flush=True)
    return {"state": state, "analysis": analysis, "run": run_row,
            "new_trades": new_trades, "resolutions": resolutions}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Kalshi demo automated paper-trading desk")
    sub = ap.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="one desk cycle: quotes -> rules -> simulated fills")
    p_run.add_argument("--data-dir", default=os.environ.get("KALSHI_DATA_DIR", DATA_DIR_DEFAULT))
    p_run.add_argument("--api-root", default=os.environ.get("KALSHI_API_ROOT", DEMO_REST_ROOT))
    p_run.add_argument("--fixtures", default=None,
                       help="replay captured responses from this directory (test mode only)")
    p_run.add_argument("--reset", action="store_true", help="start a fresh paper ledger")
    p_run.add_argument("--starting-cash", type=float, default=None)
    p_run.add_argument("--max-orders", type=int, default=None)
    p_run.add_argument("--quiet", action="store_true")
    p_stat = sub.add_parser("status", help="print the current ledger summary")
    p_stat.add_argument("--data-dir", default=os.path.join(DATA_DIR_DEFAULT))
    args = ap.parse_args(argv)

    if args.command == "status":
        doc = load_json(os.path.join(args.data_dir, "paper", "analysis.json"))
        if not doc:
            print("no paper ledger yet (data/paper/analysis.json missing)")
            return 1
        print(json.dumps(doc.get("totals", {}), indent=2))
        return 0

    config = dict(DEFAULT_CONFIG)
    if args.starting_cash is not None:
        config["starting_cash_dollars"] = float(args.starting_cash)
    if args.max_orders is not None:
        config["max_new_orders_per_run"] = int(args.max_orders)
    if args.fixtures:
        client = FixtureClient(args.api_root, args.fixtures)
    else:
        client = LiveClient(root=args.api_root)
    out = run_cycle(client, args.data_dir, config, reset=args.reset, quiet=args.quiet)
    totals = out["analysis"]["totals"]
    print(f"desk run {out['run']['run']}: {out['run']['intents']} order(s) sent, "
          f"{totals['open_positions']} open position(s), equity ${totals['equity_dollars']}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
