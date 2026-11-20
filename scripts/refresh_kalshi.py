#!/usr/bin/env python3
"""Refresh the Kalshi dashboard data in analysis/data/live/.

Only PUBLIC, unauthenticated read endpoints of the Kalshi Trade API are used
(see https://docs.kalshi.com/llms.txt -> "Quick Start: Market Data").
Standard library only, so it runs on a bare GitHub Actions runner.

Every stored row keeps `source_url`: the exact official API URL whose response
produced the value, plus `fetched_at`. Nothing is estimated or back-filled.
No derived or estimated values are stored; every field is copied from the API response.

Outputs
  analysis/data/live/meta.json         run metadata, call counts, errors
  analysis/data/live/markets.json      top open markets by contract volume, per topic
  analysis/data/live/resolutions.json  settled markets with their recorded result (yes/no)
  analysis/data/live/orderbooks.json   top-of-book depth for top markets
  analysis/data/live/candles.json      price history (1-hour and 1-day candlesticks)
  analysis/data/live/exchange.json     exchange status from GET /exchange/status

Environment overrides
  KALSHI_BASE   API base URL (used by the offline test harness)
  KALSHI_SLEEP  seconds between requests (default 0.25)
  KALSHI_OUT    output directory (default analysis/data/live; used by the offline test)
"""
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "scripts" / "config.json").read_text(encoding="utf-8"))
BASE = os.environ.get("KALSHI_BASE", CONFIG["api_base"]).rstrip("/")
SLEEP = float(os.environ.get("KALSHI_SLEEP", "0.25"))
OUT = pathlib.Path(os.environ.get("KALSHI_OUT", ROOT / "analysis" / "data" / "live"))
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
NOW_ISO = NOW.isoformat().replace("+00:00", "Z")

ERRORS = []
CALLS = {"ok": 0, "failed": 0}


def get_json(path, params=None):
    """GET BASE+path. Returns (full_url, parsed_json). Raises on final failure."""
    query = {k: v for k, v in (params or {}).items() if v is not None}
    url = BASE + path + ("?" + urllib.parse.urlencode(query) if query else "")
    last_error = None
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "demo3-dashboard/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            CALLS["ok"] += 1
            time.sleep(SLEEP)
            return url, data
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code == 429 or exc.code >= 500:
                time.sleep(2 ** attempt)
                continue
            break  # other 4xx: do not retry
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2 ** attempt)
    CALLS["failed"] += 1
    raise RuntimeError(f"{url} -> {last_error}")


def safe(label, fn, default):
    try:
        return fn()
    except Exception as exc:  # keep the run going; record the failure
        ERRORS.append({"step": label, "error": str(exc)[:500]})
        return default


def num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_title(text):
    return re.sub(r"\*\*", "", text or "").strip()


def list_markets(series, status, max_pages):
    """Yield (page_url, market) for every page of GET /markets for one series and status."""
    cursor = None
    for _ in range(max_pages):
        url, data = get_json("/markets", {"series_ticker": series, "status": status, "limit": 200, "cursor": cursor})
        for market in data.get("markets", []):
            yield url, market
        cursor = data.get("cursor") or None
        if not cursor:
            return


def market_row(market, topic_id, series, url):
    volume = num(market.get("volume_fp"))
    notional = num(market.get("notional_value_dollars"))
    return {
        "topic": topic_id,
        "series": series,
        "event_ticker": market.get("event_ticker"),
        "ticker": market.get("ticker"),
        "title": clean_title(market.get("title")),
        "outcome": market.get("yes_sub_title") or "",
        "status": market.get("status"),
        "result": market.get("result") or "",
        "last_price": num(market.get("last_price_dollars")),
        "yes_bid": num(market.get("yes_bid_dollars")),
        "yes_ask": num(market.get("yes_ask_dollars")),
        "yes_bid_size": num(market.get("yes_bid_size_fp")),
        "yes_ask_size": num(market.get("yes_ask_size_fp")),
        "volume_contracts": volume,
        "volume_24h_contracts": num(market.get("volume_24h_fp")),
        "open_interest_contracts": num(market.get("open_interest_fp")),
        "notional_value_per_contract": notional,
        "close_time": market.get("close_time"),
        "expected_expiration_time": market.get("expected_expiration_time"),
        "settlement_ts": market.get("settlement_ts"),
        "expiration_value": market.get("expiration_value") or "",
        "source_url": url,
        "fetched_at": NOW_ISO,
    }


def orderbook_levels(levels, depth):
    rows = [{"price": num(p), "contracts": num(q)} for p, q in levels]
    rows = [r for r in rows if r["price"] is not None]
    rows.sort(key=lambda r: r["price"], reverse=True)  # best (highest) bid first
    return rows[:depth]


def candle_rows(candles):
    out = []
    for c in candles:
        price = c.get("price") or {}
        out.append({
            "end_period_ts": c.get("end_period_ts"),
            "end_period_utc": dt.datetime.fromtimestamp(c["end_period_ts"], dt.timezone.utc).isoformat().replace("+00:00", "Z") if c.get("end_period_ts") else None,
            "price_open": num(price.get("open_dollars")),
            "price_high": num(price.get("high_dollars")),
            "price_low": num(price.get("low_dollars")),
            "price_close": num(price.get("close_dollars")),
            "volume_contracts": num(c.get("volume_fp")),
            "open_interest_contracts": num(c.get("open_interest_fp")),
        })
    return out


def load_existing(name, default):
    path = OUT / name
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            ERRORS.append({"step": f"read {name}", "error": "existing file is not valid JSON; rebuilt"})
    return default


def write(name, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    max_pages = CONFIG["max_pages_per_series"]
    depth = CONFIG["orderbook_depth"]
    top_n = CONFIG["top_n"]

    exchange_url, exchange = safe("exchange status", lambda: get_json("/exchange/status"), (None, None))

    all_top = {"generated_at": NOW_ISO, "api_base": BASE, "ranking": "volume_contracts (descending) within markets returned by the open-market listing for each configured series", "topics": []}
    resolved_new = []
    orderbooks = {"generated_at": NOW_ISO, "api_base": BASE, "books": {}}
    candles_out = {"generated_at": NOW_ISO, "api_base": BASE, "series": {}}

    for topic in CONFIG["topics"]:
        topic_rows = []
        for series in topic["series"]:
            def fetch_open(series=series):
                rows = []
                for url, market in list_markets(series, "open", max_pages):
                    rows.append(market_row(market, topic["id"], series, url))
                return rows
            rows = safe(f"open markets {series}", fetch_open, [])
            topic_rows.extend(rows)

            def fetch_settled(series=series):
                rows = []
                url, data = get_json("/markets", {"series_ticker": series, "status": "settled", "limit": CONFIG["resolved_limit_per_series"]})
                for market in data.get("markets", []):
                    rows.append(market_row(market, topic["id"], series, url))
                return rows
            resolved_new.extend(safe(f"settled markets {series}", fetch_settled, []))

        topic_rows.sort(key=lambda r: (r["volume_contracts"] or 0), reverse=True)
        top = topic_rows[:top_n]
        all_top["topics"].append({
            "id": topic["id"],
            "label": topic["label"],
            "series": topic["series"],
            "settlement_source": topic["settlement_source"],
            "open_markets_fetched": len(topic_rows),
            "top_markets": top,
        })

        for row in top[: CONFIG["orderbook_markets_per_topic"]]:
            def fetch_book(row=row):
                url, data = get_json(f"/markets/{row['ticker']}/orderbook", {"depth": depth})
                book = data.get("orderbook_fp", {})
                return {
                    "ticker": row["ticker"],
                    "topic": topic["id"],
                    "title": row["title"],
                    "source_url": url,
                    "fetched_at": NOW_ISO,
                    # Kalshi returns YES bids and NO bids only. A NO bid at P is a YES ask at (1 - P) (docs: Get Market Orderbook).
                    "yes_bids": orderbook_levels(book.get("yes_dollars", []), depth),
                    "no_bids": orderbook_levels(book.get("no_dollars", []), depth),
                }
            orderbooks["books"][row["ticker"]] = safe(f"orderbook {row['ticker']}", fetch_book, None)

        for row in top[: CONFIG["candles_markets_per_topic"]]:
            def fetch_candles(row=row):
                end_ts = int(NOW.timestamp())
                out = {}
                for period, start_ts in ((60, end_ts - 72 * 3600), (1440, end_ts - 30 * 86400)):
                    url, data = get_json(
                        f"/series/{row['series']}/markets/{row['ticker']}/candlesticks",
                        {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period},
                    )
                    out[str(period)] = {"source_url": url, "candles": candle_rows(data.get("candlesticks", []))}
                return out
            result = safe(f"candles {row['ticker']}", fetch_candles, None)
            if result:
                candles_out["series"][row["ticker"]] = {"topic": topic["id"], "series": row["series"], "title": row["title"], "fetched_at": NOW_ISO, **result}

    # Resolutions: merge with history so a market stays listed after it leaves the open list.
    history = load_existing("resolutions.json", {"items": []})
    by_ticker = {item["ticker"]: item for item in history.get("items", [])}
    for row in resolved_new:
        if row["result"] in ("yes", "no"):
            by_ticker[row["ticker"]] = row
    resolved_items = sorted(by_ticker.values(), key=lambda r: r.get("settlement_ts") or "", reverse=True)[:2000]

    if CALLS["ok"] == 0:
        # Never overwrite good data with empty results when the API is unreachable.
        print("refresh aborted: no successful API call; existing data files left unchanged", file=sys.stderr)
        return 2
    write("exchange.json", {"fetched_at": NOW_ISO, "source_url": exchange_url, "response": exchange})
    write("markets.json", all_top)
    write("resolutions.json", {"generated_at": NOW_ISO, "api_base": BASE, "items": resolved_items})
    write("orderbooks.json", orderbooks)
    write("candles.json", candles_out)
    write("meta.json", {
        "generated_at": NOW_ISO,
        "api_base": BASE,
        "docs": CONFIG["api_docs"],
        "calls_ok": CALLS["ok"],
        "calls_failed": CALLS["failed"],
        "open_markets_per_topic": {t["id"]: next((x["open_markets_fetched"] for x in all_top["topics"] if x["id"] == t["id"]), 0) for t in CONFIG["topics"]},
        "resolved_markets_stored": len(resolved_items),
        "orderbooks_stored": sum(1 for v in orderbooks["books"].values() if v),
        "candle_series_stored": len(candles_out["series"]),
        "errors": ERRORS,
        "status": "ok" if not ERRORS else "partial",
    })
    print(f"refresh complete: calls ok={CALLS['ok']} failed={CALLS['failed']} errors={len(ERRORS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
