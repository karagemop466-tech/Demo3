#!/usr/bin/env python3
"""
Kalshi market-data collector (v2) — precise, bounded, self-citing.

WHY IT RUNS IN GITHUB ACTIONS
------------------------------
The development sandbox has no network route to *.kalshi.co (TLS reset on 443 and 80; DNS
resolves but the handshake is dropped). GitHub Actions runners do reach it: verified by run
44727245939 (.github/workflows/smoke.yml) before this collector existed.

DESIGN DECISION: SELECT SERIES FIRST, THEN THEIR MARKETS
--------------------------------------------------------
v1 paged the global /markets feed, which is sorted newest-first. That flooded the dataset with
thousands of 15-minute crypto contracts and produced ~80 MB of artifacts while still missing
long-running high-volume events. v2 instead:
  1. pages the full series catalogue (GET /series, includes series-level volume_fp),
  2. classifies every series against the five requested topics (collector/topics.json),
  3. keeps the top-N series *per topic by series volume* — i.e. literally the highest-volume
     live events in scope,
  4. fetches only those series' markets (open + settled) via ?series_ticker=...,
  5. enriches the top markets with orderbook depth and candlesticks.

HONESTY RULES
-------------
* Nothing is inferred: every number is copied from a Kalshi response and every artifact stores
  the exact request URL it came from plus the fetch timestamp.
* Missing values are null and named in `_missing`; never back-filled.
* Portfolio/trade endpoints require an Ed25519 API key and are NOT called here. Their observed
  401s are recorded as evidence (`auth_probes`) instead of inventing holdings.
* "Dollar amount" is ambiguous in Kalshi's data model, so four explicitly-labelled metrics are
  published instead of one invented number:
      contracts_traded, traded_notional_dollars_derived, open_interest_dollars_derived,
      resting_liquidity_dollars
  Derived metrics carry `_derived` and a `price_basis` field explaining the multiplier.

OUTPUTS
-------
  data/live.json          in-scope series + open markets + orderbooks + candles (demo)
  data/live-prod.json     same for production (the brief says "on kalshi" for market data)
  data/resolutions.json   settled markets with the API's own result (yes/no/scalar)
  data/history/*.jsonl    append-only observation log used for the "live" chart
  data/meta.json          run metadata, counts, request log, auth-probe evidence
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
    # Kalshi docs -> "API Environments and Endpoints"
    # https://docs.kalshi.com/getting_started/api_environments.md
    "prod": "https://external-api.kalshi.com",
    "demo": "https://external-api.demo.kalshi.co",
}
TOPICS_FILE = ROOT / "collector" / "topics.json"

TOP_SERIES_PER_TOPIC = int(os.environ.get("TOP_SERIES_PER_TOPIC", "14"))
MAX_ORDERBOOKS = int(os.environ.get("MAX_ORDERBOOKS", "20"))
SETTLED_WINDOW_DAYS = int(os.environ.get("SETTLED_WINDOW_DAYS", "30"))
HISTORY_KEEP_DAYS = 21

_requests: list[dict] = []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- HTTP
def api_get(host: str, path: str, params: dict | None = None, *, attempts: int = 4,
            timeout: int = 45) -> tuple[int, object]:
    """GET path on host. Returns (status, body). Logs every call into `_requests`."""
    url = HOSTS[host] + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None},
                                            safe=",")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Demo3-kalshi-collector/2.0 (+https://github.com/karagemop466-tech/Demo3)",
    })
    t0 = time.time()
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
            try:
                body: object = json.loads(raw)
            except json.JSONDecodeError:
                body = {"_non_json": raw[:2000]}
            _requests.append({"url": url, "status": status,
                              "ms": int((time.time() - t0) * 1000), "at": _stamp()})
            return status, body
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            _requests.append({"url": url, "status": exc.code,
                              "ms": int((time.time() - t0) * 1000), "at": _stamp(),
                              "error": detail[:200]})
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            return exc.code, {"_http_error": exc.code, "_body": detail}
        except Exception as exc:  # noqa: BLE001
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            _requests.append({"url": url, "status": 0, "err": repr(exc)[:300], "at": _stamp()})
            return 0, {"_transport_error": repr(exc)[:300]}
    return 0, {"_transport_error": "exhausted"}


def api_paged(host: str, path: str, params: dict, list_key: str, max_pages: int = 40,
              max_items: int = 40000) -> list:
    params = dict(params)
    items: list = []
    cursor = None
    for _ in range(max_pages):
        if cursor:
            params["cursor"] = cursor
        status, body = api_get(host, path, params)
        if status != 200 or not isinstance(body, dict):
            break
        items.extend(body.get(list_key) or [])
        cursor = body.get("cursor") or ""
        if not cursor or len(items) >= max_items:
            break
        time.sleep(0.1)
    return items


# ------------------------------------------------------------------------ topics
def classify(series: dict, cfg: dict) -> list[str]:
    """Deterministic topic mapping. Exact matches only; see collector/topics.json."""
    hits: list[str] = []
    category = (series.get("category") or "").strip()
    cats = [c.strip() for c in (series.get("categories") or []) if c]
    tags = [str(t).strip().lower() for t in (series.get("tags") or [])]
    ticker = (series.get("ticker") or "").upper()
    title = (series.get("title") or "").lower()

    for topic, rule in cfg["topics"].items():
        matched = None
        if rule.get("categories"):
            if category in rule["categories"]:
                matched = f"category={category}"
            elif any(c in rule["categories"] for c in cats):
                matched = "categories[]"
        if not matched and rule.get("tags_any") and any(t in rule["tags_any"] for t in tags):
            matched = "tag"
        if not matched and rule.get("ticker_prefixes") and \
                any(ticker.startswith(p) for p in rule["ticker_prefixes"]):
            matched = "ticker_prefix"
        if not matched and rule.get("title_contains") and \
                any(s in title for s in rule["title_contains"]):
            matched = "title"
        if matched:
            hits.append({"topic": topic, "matched_by": matched})
    return hits


def series_of_market(market: dict, known: set[str]) -> str | None:
    """Resolve a market's series ticker from its event ticker, only if it is in the catalogue."""
    ev = market.get("event_ticker") or ""
    if not ev:
        return None
    parts = ev.split("-")
    for cut in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[:cut])
        if candidate in known:
            return candidate
    return None


def fnum(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money(value, nd=2):
    n = fnum(value)
    return None if n is None else round(n, nd)


# ------------------------------------------------------------------ orderbook math
def book_from(orderbook_body: dict) -> dict:
    """Normalise GET /markets/{t}/orderbook into price levels + liquidity.

    Docs (https://docs.kalshi.com/getting_started/orderbook_responses.md):
    only bids are returned; each level is ["price_dollars", "count_fp"]; arrays are
    ascending so the LAST entry is the best bid. A YES bid at X equals a NO ask at 1-X,
    so implied asks are labelled `_derived`.
    """
    body = orderbook_body or {}
    ob = body.get("orderbook_fp") or body.get("orderbook") or {}
    yes = [(money(p, 4), money(c, 2)) for p, c in (ob.get("yes_dollars") or [])]
    no = [(money(p, 4), money(c, 2)) for p, c in (ob.get("no_dollars") or [])]
    yes = [(p, c) for p, c in yes if p is not None and c is not None]
    no = [(p, c) for p, c in no if p is not None and c is not None]

    best_yes_bid = max((p for p, _ in yes), default=None)
    best_no_bid = max((p for p, _ in no), default=None)
    best_yes_ask = round(1 - best_no_bid, 4) if best_no_bid is not None else None
    best_no_ask = round(1 - best_yes_bid, 4) if best_yes_bid is not None else None

    def depth(levels):
        return round(sum(p * c for p, c in levels), 2)

    return {
        "best_yes_bid": best_yes_bid,
        "best_yes_ask_derived": best_yes_ask,
        "best_no_bid": best_no_bid,
        "best_no_ask_derived": best_no_ask,
        "spread_yes_derived": (round(best_yes_ask - best_yes_bid, 4)
                               if None not in (best_yes_ask, best_yes_bid) else None),
        "yes_resting_dollars": depth(yes),
        "no_resting_dollars": depth(no),
        "total_resting_dollars": round(depth(yes) + depth(no), 2),
        "yes_levels": len(yes),
        "no_levels": len(no),
        # Full ladder, best price first, so "how many contracts are available at a price"
        # is answerable straight from the artifact.
        "ladder": ([{"side": "yes", "price": p, "contracts": c} for p, c in sorted(yes, reverse=True)]
                   + [{"side": "no", "price": p, "contracts": c} for p, c in sorted(no, reverse=True)]),
    }


def size_metrics(market: dict, book: dict | None) -> dict:
    volume = fnum(market.get("volume_fp"))
    volume_24h = fnum(market.get("volume_24h_fp"))
    oi = fnum(market.get("open_interest_fp"))
    last = fnum(market.get("last_price_dollars"))
    bid = fnum(market.get("yes_bid_dollars"))
    ask = fnum(market.get("yes_ask_dollars"))
    mid = round((bid + ask) / 2, 4) if None not in (bid, ask) and ask >= bid else None
    basis_price = last if last is not None else mid
    return {
        "contracts_traded": money(volume, 2),
        "contracts_traded_24h": money(volume_24h, 2),
        "open_interest_contracts": money(oi, 2),
        "traded_notional_dollars_derived":
            round(volume * basis_price, 2) if volume is not None and basis_price is not None else None,
        "open_interest_dollars_derived":
            round(oi * basis_price, 2) if oi is not None and basis_price is not None else None,
        "resting_liquidity_dollars": book.get("total_resting_dollars") if book else None,
        "price_basis": ("last_trade" if last is not None else ("mid" if mid is not None else None)),
        "price_used": basis_price,
    }


# --------------------------------------------------------------------------- main
def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if host not in HOSTS:
        print(f"unknown host {host!r}", file=sys.stderr)
        return 2

    cfg = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    started = _now()

    out: dict = {"meta": {}, "status": {}, "topics": {}, "series": [], "markets": [],
                 "orderbooks": {}, "candles": {}, "auth_probes": []}

    # 1) exchange status -------------------------------------------------------
    st_status, st_body = api_get(host, "/trade-api/v2/exchange/status")
    out["status"] = {"http": st_status, "body": st_body,
                     "source": f"{HOSTS[host]}/trade-api/v2/exchange/status"}

    # 2) series catalogue ------------------------------------------------------
    catalogue = api_paged(host, "/trade-api/v2/series",
                          {"limit": 200, "include_volume": "true"}, "series", max_pages=100)
    known_series = {s.get("ticker") for s in catalogue if s.get("ticker")}
    by_ticker = {s["ticker"]: s for s in catalogue if s.get("ticker")}

    classified: dict[str, list] = {t: [] for t in cfg["topics"]}
    for s in catalogue:
        hits = classify(s, cfg)
        for hit in hits:
            classified[hit["topic"]].append({
                "series_ticker": s["ticker"],
                "title": s.get("title"),
                "category": s.get("category"),
                "tags": s.get("tags"),
                "volume_fp": s.get("volume_fp"),
                "matched_by": hit["matched_by"],
                "_volume": fnum(s.get("volume_fp"), 0.0) or 0.0,
            })

    selected: dict[str, dict] = {}
    for topic, rows in classified.items():
        rows.sort(key=lambda r: r["_volume"], reverse=True)
        keep = [r for r in rows if r["_volume"] > 0][:TOP_SERIES_PER_TOPIC]
        out["topics"][topic] = {
            "label": cfg["topics"][topic]["label"],
            "rule": cfg["topics"][topic],
            "series_matched_total": len(rows),
            "series_with_volume": sum(1 for r in rows if r["_volume"] > 0),
            "selected": [{k: v for k, v in r.items() if k != "_volume"} for r in keep],
        }
        for r in keep:
            selected.setdefault(r["series_ticker"], []).append(topic)

    # 3) per-series market fetch ----------------------------------------------
    open_markets: list[dict] = []
    settled_markets: list[dict] = []
    min_settled = int(started.timestamp()) - SETTLED_WINDOW_DAYS * 86400
    for series_ticker in selected:
        st, body = api_get(host, "/trade-api/v2/markets", {
            "series_ticker": series_ticker, "status": "open",
            "mve_filter": "exclude", "limit": 1000,
        })
        if st == 200 and isinstance(body, dict):
            open_markets.extend(body.get("markets") or [])
        time.sleep(0.1)

        st, body = api_get(host, "/trade-api/v2/markets", {
            "series_ticker": series_ticker, "status": "settled",
            "mve_filter": "exclude", "limit": 200,
            "min_settled_ts": min_settled,
        })
        if st == 200 and isinstance(body, dict):
            for m in body.get("markets") or []:
                m["_series_hint"] = series_ticker
                settled_markets.append(m)
        time.sleep(0.1)

    # 4) series reference rows for the selected series only --------------------
    for st_ticker, topics in selected.items():
        s = by_ticker.get(st_ticker) or {}
        out["series"].append({
            "series_ticker": st_ticker,
            "title": s.get("title"),
            "category": s.get("category"),
            "categories": s.get("categories"),
            "tags": s.get("tags"),
            "frequency": s.get("frequency"),
            "volume_fp": s.get("volume_fp"),
            "topics": topics,
            "settlement_sources": [
                {"name": x.get("name"), "url": x.get("url")}
                for x in (s.get("settlement_sources") or [])
            ][:6],
            "contract_terms_url": s.get("contract_terms_url"),
            "contract_url": s.get("contract_url"),
            "source": f"{HOSTS[host]}/trade-api/v2/series",
        })

    # 5) rank open markets; enrich the top ones -------------------------------
    for m in open_markets:
        m["_series"] = series_of_market(m, known_series) or m.pop("_series_hint", None)
    open_markets = [m for m in open_markets if m.get("_series") in selected]
    open_markets.sort(key=lambda m: fnum(m.get("volume_fp"), 0.0) or 0.0, reverse=True)
    enrich = [m.get("ticker") for m in open_markets[:MAX_ORDERBOOKS] if m.get("ticker")]

    for ticker in enrich:
        st, body = api_get(host, f"/trade-api/v2/markets/{ticker}/orderbook")
        src = f"{HOSTS[host]}/trade-api/v2/markets/{ticker}/orderbook"
        if st == 200 and isinstance(body, dict):
            book = book_from(body)
            book.update({"http": st, "source": src})
            out["orderbooks"][ticker] = book
        else:
            out["orderbooks"][ticker] = {"http": st, "source": src, "_missing": ["orderbook"]}
        time.sleep(0.12)

    for ticker in enrich:
        series_ticker = next((m["_series"] for m in open_markets if m.get("ticker") == ticker), None)
        if not series_ticker:
            continue
        sets = {}
        for period, days in ((1, 1), (60, 7), (1440, 90)):
            end = int(time.time())
            start = end - days * 86400
            st, body = api_get(
                host,
                f"/trade-api/v2/series/{series_ticker}/markets/{ticker}/candlesticks",
                {"start_ts": start, "end_ts": end, "period_interval": period})
            src = (f"{HOSTS[host]}/trade-api/v2/series/{series_ticker}/markets/{ticker}"
                   f"/candlesticks?start_ts={start}&end_ts={end}&period_interval={period}")
            candles = (body.get("candlesticks") if isinstance(body, dict) else None) or []
            sets[str(period)] = {"http": st, "source": src, "count": len(candles),
                                 "candlesticks": candles[:2000]}
            time.sleep(0.12)
        out["candles"][ticker] = sets

    # 6) build market rows ----------------------------------------------------
    for m in open_markets:
        ticker = m.get("ticker")
        book = out["orderbooks"].get(ticker)
        series_ticker = m["_series"]
        series_matches = [t for t in selected.get(series_ticker, [])]
        row = {
            "ticker": ticker,
            "event_ticker": m.get("event_ticker"),
            "series_ticker": series_ticker,
            "topics": series_matches,
            "title": (m.get("title") or m.get("yes_sub_title") or "")[:220],
            "yes_sub_title": (m.get("yes_sub_title") or "")[:160],
            "status": m.get("status"),
            "market_type": m.get("market_type"),
            "open_time": m.get("open_time"),
            "close_time": m.get("close_time"),
            "expected_expiration_time": m.get("expected_expiration_time"),
            "yes_bid_dollars": money(m.get("yes_bid_dollars"), 4),
            "yes_ask_dollars": money(m.get("yes_ask_dollars"), 4),
            "no_bid_dollars": money(m.get("no_bid_dollars"), 4),
            "no_ask_dollars": money(m.get("no_ask_dollars"), 4),
            "yes_bid_size_fp": money(m.get("yes_bid_size_fp"), 2),
            "yes_ask_size_fp": money(m.get("yes_ask_size_fp"), 2),
            "last_price_dollars": money(m.get("last_price_dollars"), 4),
            "volume_fp": money(m.get("volume_fp"), 2),
            "volume_24h_fp": money(m.get("volume_24h_fp"), 2),
            "open_interest_fp": money(m.get("open_interest_fp"), 2),
            "rules_primary": (m.get("rules_primary") or "")[:400],
            "metrics": size_metrics(m, book),
            "source": (f"{HOSTS[host]}/trade-api/v2/markets?series_ticker={series_ticker}"
                       f"&status=open&mve_filter=exclude&limit=1000"),
            "orderbook_source": (book or {}).get("source"),
            "candles_source": ((out["candles"].get(ticker) or {}).get("1") or {}).get("source"),
        }
        missing = [k for k in ("yes_bid_dollars", "yes_ask_dollars", "last_price_dollars",
                               "volume_fp", "open_interest_fp") if row.get(k) is None]
        if missing:
            row["_missing"] = missing
        out["markets"].append(row)

    # 7) settled rows ---------------------------------------------------------
    for m in settled_markets:
        series_ticker = m.get("_series_hint")
        out.setdefault("_settled_rows", []).append({
            "ticker": m.get("ticker"),
            "event_ticker": m.get("event_ticker"),
            "series_ticker": series_ticker,
            "topics": selected.get(series_ticker, []),
            "title": (m.get("title") or m.get("yes_sub_title") or "")[:220],
            "yes_sub_title": (m.get("yes_sub_title") or "")[:160],
            "result": m.get("result"),
            "settlement_value_dollars": money(m.get("settlement_value_dollars"), 4),
            "settlement_ts": m.get("settlement_ts"),
            "close_time": m.get("close_time"),
            "expiration_value": (m.get("expiration_value") or "")[:120],
            "last_price_dollars": money(m.get("last_price_dollars"), 4),
            "volume_fp": money(m.get("volume_fp"), 2),
            "open_interest_fp": money(m.get("open_interest_fp"), 2),
            "can_close_early": m.get("can_close_early"),
            "source": (f"{HOSTS[host]}/trade-api/v2/markets?series_ticker={series_ticker}"
                       f"&status=settled&mve_filter=exclude&limit=200"),
        })

    # 8) evidence that private data is unavailable ----------------------------
    for path in ("/trade-api/v2/portfolio/balance", "/trade-api/v2/portfolio/positions",
                 "/trade-api/v2/portfolio/orders"):
        st, body = api_get(host, path)
        out["auth_probes"].append({
            "url": HOSTS[host] + path,
            "status": st,
            "body_excerpt": json.dumps(body, default=str)[:240],
            "interpretation": ("401 = endpoint requires the signed API-key headers documented at "
                               "https://docs.kalshi.com/getting_started/api_keys.md; no key is "
                               "configured for this repository, so no portfolio data is published."),
        })

    finished = _now()
    out["meta"] = {
        "run_id": started.strftime("%Y%m%dT%H%M%SZ"),
        "environment": host,
        "base_url": HOSTS[host],
        "started_at_utc": started.isoformat(timespec="seconds"),
        "finished_at_utc": finished.isoformat(timespec="seconds"),
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "counts": {
            "series_in_catalogue": len(catalogue),
            "series_selected": len(selected),
            "open_markets_in_scope": len(out["markets"]),
            "settled_markets_in_scope": len(out.get("_settled_rows") or []),
            "orderbooks": len(out["orderbooks"]),
            "candlestick_sets": len(out["candles"]),
        },
        "topics": {t: {"label": v["label"],
                       "series_matched_total": v["series_matched_total"],
                       "series_selected": len(v["selected"])}
                   for t, v in out["topics"].items()},
        "parameters": {"top_series_per_topic": TOP_SERIES_PER_TOPIC,
                       "max_orderbooks": MAX_ORDERBOOKS,
                       "settled_window_days": SETTLED_WINDOW_DAYS},
        "request_count": len(_requests),
        "requests": _requests,
        "docs": {
            "api_environments": "https://docs.kalshi.com/getting_started/api_environments.md",
            "demo_env": "https://docs.kalshi.com/getting_started/demo_env.md",
            "quickstart_market_data": "https://docs.kalshi.com/getting_started/quick_start_market_data.md",
            "markets": "https://docs.kalshi.com/api-reference/market/get-markets.md",
            "series_list": "https://docs.kalshi.com/api-reference/market/get-series-list.md",
            "orderbook": "https://docs.kalshi.com/getting_started/orderbook_responses.md",
            "candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
            "settlement": "https://docs.kalshi.com/getting_started/market_settlement.md",
            "historical": "https://docs.kalshi.com/getting_started/historical_data.md",
            "api_keys": "https://docs.kalshi.com/getting_started/api_keys.md",
            "websockets": "https://docs.kalshi.com/getting_started/quick_start_websockets.md",
            "rate_limits": "https://docs.kalshi.com/getting_started/rate_limits.md",
        },
    }

    # 9) persist -------------------------------------------------------------
    data_dir = ROOT / "data"
    (data_dir / "history").mkdir(parents=True, exist_ok=True)
    live_path = data_dir / ("live.json" if host == "demo" else f"live-{host}.json")
    live_path.write_text(json.dumps(out, indent=0, separators=(",", ":")), encoding="utf-8")

    # resolutions accumulate
    res_path = data_dir / "resolutions.json"
    existing = {"rows": []}
    if res_path.exists():
        try:
            existing = json.loads(res_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    rows = {(r.get("environment"), r.get("ticker")): r for r in existing.get("rows", [])}
    for r in out.get("_settled_rows") or []:
        rows[(host, r["ticker"])] = {"environment": host, **r}
    res_path.write_text(json.dumps({
        "meta": {
            "updated_at_utc": finished.isoformat(timespec="seconds"),
            "note": ("One row per settled market seen via GET /markets?series_ticker=..."
                     "&status=settled. `result` is Kalshi's own field (yes | no | scalar | '')."
                     " Rows accumulate across runs and are never deleted, so the history of "
                     "resolutions stays auditable."),
            "docs": "https://docs.kalshi.com/getting_started/market_settlement.md",
        },
        "rows": sorted(rows.values(), key=lambda r: (r.get("settlement_ts") or "", r.get("ticker") or "")),
    }, indent=0, separators=(",", ":")), encoding="utf-8")

    # append-only observation log
    hist = data_dir / "history" / f"{started:%Y-%m-%d}.jsonl"
    with open(hist, "a", encoding="utf-8") as fh:
        for row in out["markets"]:
            m = row["metrics"]
            fh.write(json.dumps({
                "ts": started.isoformat(timespec="seconds"),
                "epoch": int(started.timestamp()),
                "env": host,
                "ticker": row["ticker"],
                "topics": row["topics"],
                "yes_bid": row["yes_bid_dollars"],
                "yes_ask": row["yes_ask_dollars"],
                "last": row["last_price_dollars"],
                "volume": row["volume_fp"],
                "oi": row["open_interest_fp"],
                "liq": m.get("resting_liquidity_dollars"),
            }, separators=(",", ":")) + "\n")

    cutoff = time.time() - HISTORY_KEEP_DAYS * 86400
    for p in (data_dir / "history").glob("*.jsonl"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass

    (data_dir / "meta.json").write_text(json.dumps(out["meta"], indent=1), encoding="utf-8")

    print(json.dumps({"environment": host, "counts": out["meta"]["counts"],
                      "requests": out["meta"]["request_count"],
                      "duration_seconds": out["meta"]["duration_seconds"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
