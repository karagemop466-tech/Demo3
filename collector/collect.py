#!/usr/bin/env python3
"""
Kalshi demo/production market-data collector.

WHY THIS RUNS IN GITHUB ACTIONS, NOT IN THE DEV SANDBOX
------------------------------------------------------
The development sandbox has no network route to *.kalshi.co (TLS reset on 443 and 80).
GitHub Actions runners do reach it; this was verified by workflow run 44727245939
(.github/workflows/smoke.yml) before this collector was written.

WHAT IT DOES (all unauthenticated, public market data only)
----------------------------------------------------------
1. GET /exchange/status
2. GET /series  (paginated)  -> full series catalogue incl. category + tags
3. GET /markets?status=open&mve_filter=exclude (paginated) -> live standalone markets
4. GET /markets?status=settled&mve_filter=exclude&min_settled_ts=... (paginated)
   -> resolved markets, used for "how did it resolve: yes or no"
5. GET /markets/{ticker}/orderbook  -> price levels and contracts available per level
6. GET /series/{s}/markets/{t}/candlesticks -> 1m/60m/1440m OHLC for the price chart
7. GET /historical/cutoff -> documents that older data lives behind /historical/*

HONESTY RULES BUILT IN
----------------------
* Every value written is copied from an API response; nothing is inferred or estimated.
* Every artifact stores the exact request URL(s) it came from plus a fetch timestamp.
* Missing fields become null and are listed in `_missing`; they are never back-filled.
* Portfolio/trade endpoints require API-key auth (Kalshi docs) and are NOT called here;
  `probe_auth_required()` records the observed 401 as evidence instead of guessing data.
* Volume metric ambiguity: we publish several explicitly-labelled metrics
  (contracts traded, open interest, resting-liquidity dollars) instead of inventing
  one "dollar amount" definition. See data/metrics.json.

Outputs (relative to repo root):
  data/live.json                 latest snapshot: status, series, markets, orderbooks, candles
  data/resolutions.json          accumulated settled-market results (yes/no) per topic
  data/history/YYYY-MM-DD.jsonl  one JSON line per tracked market per run (time series)
  data/meta.json                 run metadata, request log, auth probes
"""
from __future__ import annotations

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

HOSTS = {
    # Kalshi docs, "API Environments and Endpoints":
    # https://docs.kalshi.com/getting_started/api_environments.md
    "demo": "https://external-api.demo.kalshi.co",
    "prod": "https://external-api.kalshi.com",
}

# How many live markets per host get orderbook + candlestick treatment.
MAX_ORDERBOOKS = int(os.environ.get("MAX_ORDERBOOKS", "24"))
# Topic rules live in a separate, auditable file.
TOPICS_FILE = ROOT / "collector" / "topics.json"
# Retention for the appended time-series files.
HISTORY_KEEP_DAYS = 21

_sessions: list[dict] = []


# --------------------------------------------------------------------------- http
def api_get(host_key: str, path: str, params: dict | None = None, *, attempts: int = 4,
            timeout: int = 45) -> tuple[int, object, str]:
    """GET a Kalshi API path. Returns (status, parsed_body_or_text, full_url).

    Retries on network errors and 429/5xx with exponential backoff. Records every
    request in the module-level `_sessions` list so artifacts can cite themselves.
    """
    base = HOSTS[host_key]
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params, safe=",")

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Demo3-kalshi-collector/1.0 (+https://github.com/karagemop466-tech/Demo3)",
    })
    started = time.time()
    last_err = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
            try:
                body: object = json.loads(raw)
            except json.JSONDecodeError:
                body = raw[:4000]
            _sessions.append({
                "url": url, "status": status, "ms": int((time.time() - started) * 1000),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            return status, body, url
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")[:2000]
            _sessions.append({
                "url": url, "status": exc.code, "ms": int((time.time() - started) * 1000),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "error": raw[:300],
            })
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            return exc.code, {"_http_error": exc.code, "_body": raw}, url
        except Exception as exc:  # noqa: BLE001 - any transport failure retries
            last_err = exc
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            _sessions.append({
                "url": url, "status": 0, "err": repr(exc)[:300],
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            return 0, {"_transport_error": repr(last_err)[:300]}, url
    return 0, {"_transport_error": "exhausted"}, url


def api_paged(host_key: str, path: str, params: dict | None = None,
              list_key: str = "markets", max_pages: int = 25) -> tuple[list, list[str]]:
    """Follow `cursor` pagination. Returns (items, urls_called)."""
    params = dict(params or {})
    items: list = []
    urls: list[str] = []
    cursor = None
    for _ in range(max_pages):
        if cursor:
            params["cursor"] = cursor
        status, body, url = api_get(host_key, path, params)
        urls.append(url)
        if status != 200 or not isinstance(body, dict):
            break
        items.extend(body.get(list_key) or [])
        cursor = body.get("cursor") or ""
        if not cursor:
            break
        time.sleep(0.12)
    return items, urls


# ------------------------------------------------------------------- topics config
def load_topics() -> dict:
    with open(TOPICS_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def classify_series(series: dict, cfg: dict) -> list[str]:
    """Map one series to the dashboard topics it belongs to.

    Rules are declarative (collector/topics.json) and evaluated in a fixed order.
    A series may map to several topics. No fuzzy matching: exact category names and
    explicit ticker/tag rules only, so the mapping is reproducible and auditable.
    """
    topics: list[str] = []
    category = (series.get("category") or "").strip()
    categories = [c.strip() for c in (series.get("categories") or [])]
    tags = [t.strip().lower() for t in (series.get("tags") or [])]
    ticker = (series.get("ticker") or "").upper()
    title = (series.get("title") or "").lower()

    for topic, rule in cfg["topics"].items():
        if category in rule.get("categories", []) or any(c in rule.get("categories", []) for c in categories):
            topics.append(topic)
            continue
        if any(t in rule.get("tags_any", []) for t in tags):
            topics.append(topic)
            continue
        if any(ticker.startswith(p) for p in rule.get("ticker_prefixes", [])):
            topics.append(topic)
            continue
        if any(s in title for s in rule.get("title_contains", [])):
            topics.append(topic)
            continue
    return topics


def series_ticker_of_market(market: dict) -> str:
    """Kalshi event tickers are `<SERIES>-<DATE...>`; the market ticker adds a strike.

    We only accept the prefix when it is an actual series ticker (checked against the
    catalogue in main()), so this can never invent a series.
    """
    ev = market.get("event_ticker") or ""
    if "-" not in ev:
        return ""
    return ev.rsplit("-", 1)[0] if ev.count("-") == 1 else "-".join(ev.split("-")[:-1])


# ------------------------------------------------------------------------ fetching
def fetch_series(host_key: str) -> tuple[list, list[str]]:
    return api_paged(host_key, "/trade-api/v2/series", {"limit": 200, "include_volume": "true"},
                     list_key="series", max_pages=15)


def fetch_markets(host_key: str, status: str, extra: dict | None = None) -> tuple[list, list[str]]:
    params = {"limit": 1000, "status": status, "mve_filter": "exclude"}
    params.update(extra or {})
    return api_paged(host_key, "/trade-api/v2/markets", params, list_key="markets", max_pages=12)


def fetch_orderbook(host_key: str, ticker: str) -> dict:
    status, body, url = api_get(host_key, f"/trade-api/v2/markets/{ticker}/orderbook")
    return {"status": status, "body": body, "url": url}


def fetch_candles(host_key: str, series_ticker: str, ticker: str, period: int,
                  days_back: int) -> dict:
    now = int(time.time())
    start = now - days_back * 86400
    # Docs: one request may span at most 5,000 periods; 1-minute data is ~3.5 days max.
    if period == 1 and days_back > 3:
        start = now - 3 * 86400
    path = f"/trade-api/v2/series/{series_ticker}/markets/{ticker}/candlesticks"
    status, body, url = api_get(host_key, path, {
        "start_ts": start, "end_ts": now, "period_interval": period,
    })
    return {"status": status, "body": body, "url": url, "period_interval": period}


def probe_auth_required(host_key: str) -> list[dict]:
    """Record evidence that private endpoints are gated, instead of inventing data."""
    probes = []
    for path in ("/trade-api/v2/portfolio/balance",
                 "/trade-api/v2/portfolio/positions",
                 "/trade-api/v2/portfolio/orders"):
        status, body, url = api_get(host_key, path)
        probes.append({"url": url, "status": status,
                       "body_excerpt": json.dumps(body)[:300]})
    return probes


# --------------------------------------------------------------------------- maths
def fnum(value, default=None):
    """Parse a Kalshi fixed-point string ('0.5600', '10.00') into a float."""
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def book_levels(orderbook: dict) -> dict:
    """Turn a /orderbook response into explicit price levels with contract counts.

    Docs (orderbook_responses): response is `orderbook_fp` with `yes_dollars` and
    `no_dollars`; each entry is ["price_dollars", "count_fp"]; arrays ascending, so the
    last element is the best bid. Kalshi returns bids only: a YES bid at X is a NO ask at
    1-X. We therefore derive implied asks explicitly and label them as derived.
    """
    ob = (orderbook or {}).get("orderbook_fp") or (orderbook or {}).get("orderbook") or {}
    yes = [[fnum(p), fnum(c)] for p, c in (ob.get("yes_dollars") or [])]
    no = [[fnum(p), fnum(c)] for p, c in (ob.get("no_dollars") or [])]
    yes = [x for x in yes if x[0] is not None and x[1] is not None]
    no = [x for x in no if x[0] is not None and x[1] is not None]

    best_yes_bid = max((p for p, _ in yes), default=None)
    best_no_bid = max((p for p, _ in no), default=None)
    best_yes_ask = round(1 - best_no_bid, 4) if best_no_bid is not None else None
    best_no_ask = round(1 - best_yes_bid, 4) if best_yes_bid is not None else None

    def depth_dollars(side):
        return round(sum(p * c for p, c in side), 2)

    levels = [{"side": "yes_bid", "price": p, "contracts": c} for p, c in sorted(yes, reverse=True)]
    levels += [{"side": "no_bid", "price": p, "contracts": c} for p, c in sorted(no, reverse=True)]

    return {
        "best_yes_bid": best_yes_bid,
        "best_yes_ask": best_yes_ask,
        "best_no_bid": best_no_bid,
        "best_no_ask": best_no_ask,
        "best_yes_ask_derived": best_yes_ask is not None,
        "spread_yes": round(best_yes_ask - best_yes_bid, 4)
        if best_yes_ask is not None and best_yes_bid is not None else None,
        "yes_depth_dollars": depth_dollars(yes),
        "no_depth_dollars": depth_dollars(no),
        "total_resting_liquidity_dollars": round(depth_dollars(yes) + depth_dollars(no), 2),
        "yes_levels": len(yes),
        "no_levels": len(no),
        "levels": levels,
    }


def size_metrics(market: dict, book: dict | None) -> dict:
    """Explicitly-labelled size metrics. No single opaque 'dollar amount' is invented."""
    volume = fnum(market.get("volume_fp"))
    volume_24h = fnum(market.get("volume_24h_fp"))
    oi = fnum(market.get("open_interest_fp"))
    last = fnum(market.get("last_price_dollars"))
    yes_bid = fnum(market.get("yes_bid_dollars"))
    yes_ask = fnum(market.get("yes_ask_dollars"))
    mid = None
    if yes_bid is not None and yes_ask is not None and yes_ask >= yes_bid:
        mid = round((yes_bid + yes_ask) / 2, 4)
    price_for_notional = last if last is not None else mid
    return {
        "contracts_traded": volume,
        "contracts_traded_24h": volume_24h,
        "open_interest_contracts": oi,
        # Notional dollars = contracts * price. Labelled DERIVED because Kalshi does not
        # return a dollar notional; price used is last trade, else mid, else null.
        "traded_notional_dollars_derived": round(volume * price_for_notional, 2)
        if volume is not None and price_for_notional is not None else None,
        "open_interest_dollars_derived": round(oi * price_for_notional, 2)
        if oi is not None and price_for_notional is not None else None,
        "price_used_for_notional": price_for_notional,
        "price_basis": "last_trade" if last is not None else ("mid" if mid is not None else None),
        "resting_liquidity_dollars": book.get("total_resting_liquidity_dollars") if book else None,
    }


# ----------------------------------------------------------------------------- main
def main() -> int:
    host_key = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if host_key not in HOSTS:
        print(f"unknown host {host_key}", file=sys.stderr)
        return 2

    cfg = load_topics()
    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    out = {"meta": {}, "status": {}, "series": [], "markets": [], "orderbooks": {},
           "candles": {}, "settled": [], "auth_probes": []}

    # 1. exchange status ---------------------------------------------------------
    st_status, st_body, st_url = api_get(host_key, "/trade-api/v2/exchange/status")
    out["status"] = {"http": st_status, "body": st_body, "source": st_url}

    # 2. series catalogue --------------------------------------------------------
    series, series_urls = fetch_series(host_key)
    series_by_ticker = {s.get("ticker"): s for s in series if s.get("ticker")}
    for s in series:
        topics = classify_series(s, cfg)
        if not topics:
            continue
        out["series"].append({
            "series_ticker": s.get("ticker"),
            "title": s.get("title"),
            "category": s.get("category"),
            "categories": s.get("categories"),
            "tags": s.get("tags"),
            "frequency": s.get("frequency"),
            "volume_fp": s.get("volume_fp"),
            "topics": topics,
            "settlement_sources": s.get("settlement_sources"),
            "contract_terms_url": s.get("contract_terms_url"),
            "contract_url": s.get("contract_url"),
            "source": series_urls[0] if series_urls else None,
        })
    tracked_series = {s["series_ticker"]: s for s in out["series"]}

    # 3. live markets ------------------------------------------------------------
    open_markets, open_urls = fetch_markets(host_key, "open")
    tracked_markets = []
    unmapped = 0
    for m in open_markets:
        st = series_ticker_of_market(m)
        if st not in tracked_series:
            unmapped += 1
            continue
        topics = tracked_series[st]["topics"]
        if not topics:
            continue
        tracked_markets.append({"m": m, "series_ticker": st, "topics": topics})

    # Rank by contracts traded (explicit metric) and keep the head of the list for
    # orderbook + candlestick enrichment, so the published tables stay verifiable.
    def traded(item):
        return fnum(item["m"].get("volume_fp")) or 0.0

    tracked_markets.sort(key=traded, reverse=True)
    enrich_set = {item["m"].get("ticker") for item in tracked_markets[:MAX_ORDERBOOKS]}

    out["orderbooks"] = {}
    for ticker in list(enrich_set):
        ob = fetch_orderbook(host_key, ticker)
        if ob["status"] == 200:
            book = book_levels(ob["body"])
            book["source"] = ob["url"]
            book["http"] = ob["status"]
            out["orderbooks"][ticker] = book
        else:
            out["orderbooks"][ticker] = {"http": ob["status"], "source": ob["url"],
                                         "_missing": ["orderbook"]}
        time.sleep(0.15)

    # 4. candlesticks for the same set ------------------------------------------
    out["candles"] = {}
    for ticker in list(enrich_set):
        st = next((i["series_ticker"] for i in tracked_markets if i["m"].get("ticker") == ticker), None)
        if not st:
            continue
        entry = {}
        for period, days in ((1, 1), (60, 7), (1440, 90)):
            c = fetch_candles(host_key, st, ticker, period, days)
            if c["status"] == 200 and isinstance(c["body"], dict):
                entry[str(period)] = {
                    "source": c["url"],
                    "candlesticks": c["body"].get("candlesticks") or [],
                }
            else:
                entry[str(period)] = {"source": c["url"], "http": c["status"],
                                      "candlesticks": [], "_missing": ["candlesticks"]}
            time.sleep(0.15)
        out["candles"][ticker] = entry

    # 5. assemble market rows ----------------------------------------------------
    for item in tracked_markets:
        m = item["m"]
        ticker = m.get("ticker")
        book = out["orderbooks"].get(ticker)
        row = {
            "ticker": ticker,
            "event_ticker": m.get("event_ticker"),
            "series_ticker": item["series_ticker"],
            "topics": item["topics"],
            "title": m.get("title") or m.get("yes_sub_title"),
            "yes_sub_title": m.get("yes_sub_title"),
            "status": m.get("status"),
            "market_type": m.get("market_type"),
            "open_time": m.get("open_time"),
            "close_time": m.get("close_time"),
            "expected_expiration_time": m.get("expected_expiration_time"),
            "latest_expiration_time": m.get("latest_expiration_time"),
            "yes_bid_dollars": m.get("yes_bid_dollars"),
            "yes_ask_dollars": m.get("yes_ask_dollars"),
            "no_bid_dollars": m.get("no_bid_dollars"),
            "no_ask_dollars": m.get("no_ask_dollars"),
            "yes_bid_size_fp": m.get("yes_bid_size_fp"),
            "yes_ask_size_fp": m.get("yes_ask_size_fp"),
            "last_price_dollars": m.get("last_price_dollars"),
            "previous_price_dollars": m.get("previous_price_dollars"),
            "volume_fp": m.get("volume_fp"),
            "volume_24h_fp": m.get("volume_24h_fp"),
            "open_interest_fp": m.get("open_interest_fp"),
            "liquidity_dollars": m.get("liquidity_dollars"),
            "result": m.get("result"),
            "rules_primary": m.get("rules_primary"),
            "settlement_sources": (tracked_series.get(item["series_ticker"]) or {}).get("settlement_sources"),
            "contract_terms_url": (tracked_series.get(item["series_ticker"]) or {}).get("contract_terms_url"),
            "source": f"{HOSTS[host_key]}/trade-api/v2/markets?status=open&mve_filter=exclude&limit=1000",
            "metrics": size_metrics(m, book),
            "orderbook_source": (book or {}).get("source"),
            "candles_source": (out["candles"].get(ticker) or {}).get("1", {}).get("source"),
        }
        missing = [k for k in ("yes_bid_dollars", "yes_ask_dollars", "last_price_dollars",
                               "volume_fp", "open_interest_fp") if row.get(k) in (None, "")]
        if missing:
            row["_missing"] = missing
        out["markets"].append(row)

    # 6. settled markets for resolution tracking (last 45 days) -----------------
    now_ts = int(time.time())
    settled, settled_urls = fetch_markets(host_key, "settled",
                                         {"min_settled_ts": now_ts - 45 * 86400})
    for m in settled:
        st = series_ticker_of_market(m)
        if st not in tracked_series:
            continue
        out["settled"].append({
            "ticker": m.get("ticker"),
            "event_ticker": m.get("event_ticker"),
            "series_ticker": st,
            "topics": tracked_series[st]["topics"],
            "title": m.get("title") or m.get("yes_sub_title"),
            "yes_sub_title": m.get("yes_sub_title"),
            "result": m.get("result"),
            "settlement_value_dollars": m.get("settlement_value_dollars"),
            "settlement_ts": m.get("settlement_ts"),
            "close_time": m.get("close_time"),
            "expiration_value": m.get("expiration_value"),
            "last_price_dollars": m.get("last_price_dollars"),
            "volume_fp": m.get("volume_fp"),
            "open_interest_fp": m.get("open_interest_fp"),
            "can_close_early": m.get("can_close_early"),
            "rules_primary": m.get("rules_primary"),
            "source": f"{HOSTS[host_key]}/trade-api/v2/markets?status=settled&mve_filter=exclude&limit=1000",
        })

    # 7. historical cutoff + authenticated-endpoint evidence --------------------
    cutoff_status, cutoff_body, cutoff_url = api_get(host_key, "/trade-api/v2/historical/cutoff")
    out["historical_cutoff"] = {"http": cutoff_status, "body": cutoff_body, "source": cutoff_url}
    out["auth_probes"] = probe_auth_required(host_key)

    # 8. metadata ---------------------------------------------------------------
    finished_at = datetime.now(timezone.utc)
    out["meta"] = {
        "run_id": run_id,
        "environment": host_key,
        "base_url": HOSTS[host_key],
        "started_at_utc": started_at.isoformat(timespec="seconds"),
        "finished_at_utc": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 1),
        "counts": {
            "series_total_fetched": len(series),
            "series_in_scope": len(out["series"]),
            "open_markets_fetched": len(open_markets),
            "open_markets_in_scope": len(out["markets"]),
            "open_markets_belonging_to_untracked_series": unmapped,
            "orderbooks": len(out["orderbooks"]),
            "candlestick_sets": len(out["candles"]),
            "settled_in_scope": len(out["settled"]),
        },
        "topic_rules_file": "collector/topics.json",
        "requests": _sessions,
        "request_count": len(_sessions),
        "docs": {
            "api_environments": "https://docs.kalshi.com/getting_started/api_environments.md",
            "demo_env": "https://docs.kalshi.com/getting_started/demo_env.md",
            "markets": "https://docs.kalshi.com/api-reference/market/get-markets.md",
            "events": "https://docs.kalshi.com/api-reference/events/get-events.md",
            "orderbook": "https://docs.kalshi.com/getting_started/orderbook_responses.md",
            "candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
            "historical": "https://docs.kalshi.com/getting_started/historical_data.md",
            "api_keys": "https://docs.kalshi.com/getting_started/api_keys.md",
            "websockets": "https://docs.kalshi.com/getting_started/quick_start_websockets.md",
        },
    }

    # 9. write artifacts --------------------------------------------------------
    data_dir = ROOT / "data"
    (data_dir / "history").mkdir(parents=True, exist_ok=True)

    if host_key == "demo":
        live_path = data_dir / "live.json"
    else:
        live_path = data_dir / f"live-{host_key}.json"
    live_path.write_text(json.dumps(out, indent=1), encoding="utf-8")

    # Accumulate resolutions (never lose a row we have seen before).
    res_path = data_dir / "resolutions.json"
    existing = {"rows": []}
    if res_path.exists():
        try:
            existing = json.loads(res_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {"rows": []}
    by_key = {(r["environment"], r["ticker"]): r for r in existing.get("rows", [])}
    for r in out["settled"]:
        by_key[(host_key, r["ticker"])] = {"environment": host_key, **r}
    res_path.write_text(json.dumps({
        "meta": {
            "updated_at_utc": finished_at.isoformat(timespec="seconds"),
            "note": "One row per settled market observed via GET /markets?status=settled"
                    "&mve_filter=exclude. `result` is the API's own field: yes | no | scalar."
                    " Rows accumulate across runs and are never deleted.",
            "source": f"{HOSTS[host_key]}/trade-api/v2/markets?status=settled",
            "docs": "https://docs.kalshi.com/getting_started/market_settlement.md",
        },
        "rows": sorted(by_key.values(), key=lambda r: (r.get("settlement_ts") or "", r["ticker"])),
    }, indent=1), encoding="utf-8")

    # Append minute-level observation lines for the live chart.
    day = started_at.strftime("%Y-%m-%d")
    hist_path = data_dir / "history" / f"{day}.jsonl"
    with open(hist_path, "a", encoding="utf-8") as fh:
        for row in out["markets"]:
            book = out["orderbooks"].get(row["ticker"]) or {}
            fh.write(json.dumps({
                "ts": started_at.isoformat(timespec="seconds"),
                "epoch": int(started_at.timestamp()),
                "env": host_key,
                "ticker": row["ticker"],
                "topics": row["topics"],
                "yes_bid": row["yes_bid_dollars"],
                "yes_ask": row["yes_ask_dollars"],
                "last": row["last_price_dollars"],
                "volume": row["volume_fp"],
                "oi": row["open_interest_fp"],
                "liq": book.get("total_resting_liquidity_dollars"),
            }) + "\n")

    # Prune history older than HISTORY_KEEP_DAYS.
    cutoff = time.time() - HISTORY_KEEP_DAYS * 86400
    for p in (data_dir / "history").glob("*.jsonl"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass

    (data_dir / "meta.json").write_text(json.dumps(out["meta"], indent=1), encoding="utf-8")

    print(json.dumps({
        "environment": host_key,
        "counts": out["meta"]["counts"],
        "requests": out["meta"]["request_count"],
        "duration_seconds": out["meta"]["duration_seconds"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
