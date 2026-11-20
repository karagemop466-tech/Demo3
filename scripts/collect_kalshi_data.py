#!/usr/bin/env python3
"""
collect_kalshi_data.py — Collect market data from the official Kalshi DEMO Trade API.

Every row written to data/ is copied verbatim from the API response and carries a
`source_url` field naming the exact official endpoint URL that produced it, plus a
`retrieved_at` UTC timestamp. Values are never inferred: a field the API does not
return is simply absent (rendered as blank + "unverified" in the UI).

Official documentation sources (verified 2026-11-20):
  - API environments/endpoints: https://docs.kalshi.com/getting_started/api_environments
  - Demo environment:           https://docs.kalshi.com/getting_started/demo_env
  - Market data (no auth):      https://docs.kalshi.com/getting_started/quick_start_market_data
  - Candlesticks:               https://docs.kalshi.com/api-reference/market/get-market-candlesticks
  - Orderbook:                  https://docs.kalshi.com/api-reference/market/get-market-orderbook
  - Trades:                     https://docs.kalshi.com/api-reference/market/get-trades
  - Fixed-point fields (_fp):   https://docs.kalshi.com/getting_started/fixed_point_migration
  - Market settlement:          https://docs.kalshi.com/getting_started/market_settlement

Runs inside GitHub Actions (full egress), committing results to data/.
Public market-data endpoints require no authentication.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
REPO_DATA = "data"
TOPICS = ("gas", "elections", "culture", "crypto", "golf")

# ---------------------------------------------------------------------------
# Topic classification rules (published on the site and in VERIFICATION.md so
# every classification is reviewable). A market is classified by its series
# ticker first, then by title keywords. Classification is metadata added by
# this script; the underlying API fields are never altered.
# ---------------------------------------------------------------------------
TOPIC_RULES = [
    # (topic, series_ticker regex, title regex)
    ("gas", re.compile(r"^KXGAS", re.I), re.compile(
        r"\b(gasoline|gas price|nat(?:ural)?\s?gas|heating oil|diesel|gallon)\b", re.I)),
    ("crypto", re.compile(r"^KX(BTC|ETH|SOL|XRP|DOGE|CRYPTO|BINANCE|COINBASE)", re.I), re.compile(
        r"\b(bitcoin|btc|ethereum|eth\b|solana|crypto|xrp|dogecoin|coinbase|stablecoin)\b", re.I)),
    ("golf", re.compile(r"^KX(GOLF|PGA|LIV|MASTERS|OPEN|USOPEN|RYDER|DPWT)", re.I), re.compile(
        r"\b(golf|pga|masters|ryder cup|open championship|us open golf|liv golf)\b", re.I)),
    ("elections", re.compile(r"^KX(PRES|SENATE|HOUSE|GOV|MAYOR|PRIMARY|ELECTION|FRENCHPRES|"
                             r"NEXT[A-Z]*PRES|POLIT|PARTISAN|NOMD|NATOSECGEN|KNESS|PARL)", re.I), re.compile(
        r"\b(election|president|senate|house|governor|mayor|primary|nominee|nomination|"
        r"electoral|parliament|governm(?:ent)?|congress|secretary of state|cabinet)\b", re.I)),
    ("culture", re.compile(r"^KX(OSCAR|EMMY|GRAMMY|GOLDENGLOBE|BAFTA|FEATURE|BILLBOARD|"
                           r"BESTPICTURE|MOVIE|FILM|ALBUM|SONG|CELEB|ROYAL|METGALA|COACHELLA)", re.I), re.compile(
        r"\b(oscar|emmy|grammy|golden globe|bafta|best picture|box office|movie|film|"
        r"album|billboard|celebrity|royal|tiktok|viral|culture|gta|video game|nobel|book of the year)\b", re.I)),
]


def classify(series_ticker: str, title: str) -> tuple[str, str]:
    """Return (topic, rule_matched). 'other' means no target-topic rule matched."""
    for topic, sre, tre in TOPIC_RULES:
        if sre.search(series_ticker or ""):
            return topic, f"series_ticker~/{sre.pattern}/"
        if tre.search(title or ""):
            return topic, f"title~/{tre.pattern}/"
    return "other", ""


class Collector:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.call_count = 0

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET from the demo API with retry/backoff. Records the request URL."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        self.call_count += 1
        if self.call_count > 400:
            raise RuntimeError("API call budget exceeded (400) — pagination cap too high?")
        last_err = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "kalshi-demo3-collector/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                self.requests.append({"url": url, "status": resp.status, "ts": now_iso()})
                time.sleep(0.15)  # polite pacing
                return body
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}: {e.reason}"
                if e.code in (429, 500, 502, 503):
                    time.sleep(2 * (attempt + 1))
                    continue
                self.requests.append({"url": url, "status": e.code, "ts": now_iso(), "error": last_err})
                raise RuntimeError(f"GET {url} failed: {last_err}") from e
            except Exception as e:  # noqa: BLE001 — network retry
                last_err = str(e)
                time.sleep(2 * (attempt + 1))
        self.requests.append({"url": url, "status": 0, "ts": now_iso(), "error": last_err})
        raise RuntimeError(f"GET {url} failed after retries: {last_err}")

    def paginate(self, path: str, params: dict, key: str, max_pages: int = 20) -> list[dict]:
        out: list[dict] = []
        cursor = None
        for _ in range(max_pages):
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            body = self.get(path, p)
            out.extend(body.get(key, []))
            cursor = body.get("cursor")
            if not cursor:
                break
        return out


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_float(s) -> float | None:
    """Parse API fixed-point strings without ever inventing values."""
    if s is None or s == "":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def market_row(m: dict, topic: str, rule: str, retrieved_at: str) -> dict:
    """One output row: verbatim API fields + classification + source URL."""
    ticker = m.get("ticker", "")
    row = {
        "ticker": ticker,
        "event_ticker": m.get("event_ticker", ""),
        "series_ticker": series_of(ticker),
        "title": m.get("title", ""),
        "yes_sub_title": m.get("yes_sub_title", ""),
        "no_sub_title": m.get("no_sub_title", ""),
        "status": m.get("status", ""),
        "result": m.get("result", ""),  # yes/no once settled; "" while live
        "topic": topic,
        "classification_rule": rule,
        "last_price_dollars": m.get("last_price_dollars", ""),
        "previous_price_dollars": m.get("previous_price_dollars", ""),
        "yes_bid_dollars": m.get("yes_bid_dollars", ""),
        "yes_ask_dollars": m.get("yes_ask_dollars", ""),
        "no_bid_dollars": m.get("no_bid_dollars", ""),
        "no_ask_dollars": m.get("no_ask_dollars", ""),
        "yes_bid_size_fp": m.get("yes_bid_size_fp", ""),
        "yes_ask_size_fp": m.get("yes_ask_size_fp", ""),
        "volume_fp": m.get("volume_fp", ""),
        "volume_24h_fp": m.get("volume_24h_fp", ""),
        "open_interest_fp": m.get("open_interest_fp", ""),
        "notional_value_dollars": m.get("notional_value_dollars", ""),
        "open_time": m.get("open_time", ""),
        "close_time": m.get("close_time", ""),
        "settlement_ts": m.get("settlement_ts", ""),
        "settlement_value_dollars": m.get("settlement_value_dollars", ""),
        "rules_primary": m.get("rules_primary", ""),
        "retrieved_at": retrieved_at,
        "source_url": f"{BASE}/markets?tickers={urllib.parse.quote(ticker)}",
    }
    vol = to_float(m.get("volume_fp"))
    notional = to_float(m.get("notional_value_dollars"))
    if vol is not None and notional is not None:
        # derived display metric (arithmetic only, both inputs from the API)
        row["volume_dollars_derived"] = round(vol * notional, 2)
    return row


def series_of(ticker: str) -> str:
    """Best-effort series ticker = market ticker minus final -SEGMENT segment."""
    if "-" in ticker:
        return ticker.rsplit("-", 1)[0]
    return ticker


def write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {path}")


def main() -> int:
    col = Collector()
    retrieved_at = now_iso()

    # 1. Series catalog (used for topic metadata + verification of classification)
    print("fetching series ...")
    series_list = col.paginate("/series", {"limit": 200}, "series", max_pages=10)
    series_meta = []
    for s in series_list:
        topic, rule = classify(s.get("ticker", ""), s.get("title", ""))
        series_meta.append({
            "ticker": s.get("ticker", ""),
            "title": s.get("title", ""),
            "category": s.get("category", ""),
            "tags": s.get("tags") or [],
            "topic": topic,
            "classification_rule": rule,
            "contract_terms_url": s.get("contract_terms_url", ""),
            "retrieved_at": retrieved_at,
            "source_url": f"{BASE}/series?{urllib.parse.urlencode({'ticker': s.get('ticker','')})}",
        })
    write_json(f"{REPO_DATA}/latest/series.json", {
        "retrieved_at": retrieved_at, "count": len(series_meta), "series": series_meta})

    # 2. Open markets (all, then classified — no topic blind spots)
    print("fetching open markets ...")
    open_markets = col.paginate("/markets", {"limit": 1000, "status": "open"}, "markets", max_pages=15)
    print(f"  {len(open_markets)} open markets")

    # 3. Recently settled/closed markets for resolution tracking
    print("fetching settled markets ...")
    settled_markets = col.paginate("/markets", {"limit": 1000, "status": "settled"}, "markets", max_pages=5)
    print(f"  {len(settled_markets)} settled markets")

    rows_open, rows_settled = [], []
    topic_counts = {t: 0 for t in list(TOPICS) + ["other"]}
    for m in open_markets:
        topic, rule = classify(m.get("ticker", ""), m.get("title", ""))
        topic_counts[topic] += 1
        rows_open.append(market_row(m, topic, rule, retrieved_at))
    for m in settled_markets:
        topic, rule = classify(m.get("ticker", ""), m.get("title", ""))
        topic_counts[topic] += 1
        rows_settled.append(market_row(m, topic, rule, retrieved_at))

    rows_open.sort(key=lambda r: -(to_float(r.get("volume_fp")) or 0.0))
    rows_settled.sort(key=lambda r: -(to_float(r.get("volume_fp")) or 0.0))

    write_json(f"{REPO_DATA}/latest/markets_open.json", {
        "retrieved_at": retrieved_at, "count": len(rows_open), "markets": rows_open})
    write_json(f"{REPO_DATA}/latest/markets_settled.json", {
        "retrieved_at": retrieved_at, "count": len(rows_settled), "markets": rows_settled})

    # 4. Events for open markets (titles, categories, settlement sources)
    print("fetching events ...")
    events = col.paginate("/events", {"limit": 500}, "events", max_pages=10)
    ev_by_ticker = {}
    for e in events:
        topic, rule = classify(e.get("series_ticker", ""), e.get("title", ""))
        ev_by_ticker[e.get("event_ticker", "")] = {
            "event_ticker": e.get("event_ticker", ""),
            "series_ticker": e.get("series_ticker", ""),
            "title": e.get("title", ""),
            "sub_title": e.get("sub_title", ""),
            "category": e.get("category", ""),
            "topic": topic,
            "classification_rule": rule,
            "settlement_sources": e.get("settlement_sources", []),
            "retrieved_at": retrieved_at,
            "source_url": f"{BASE}/events?{urllib.parse.urlencode({'series_ticker': e.get('series_ticker','')})}",
        }
    topic_events = [v for v in ev_by_ticker.values() if v["topic"] in TOPICS]
    topic_events.sort(key=lambda e: e["title"])
    write_json(f"{REPO_DATA}/latest/events.json", {
        "retrieved_at": retrieved_at, "count": len(topic_events), "events": topic_events})

    # 5. Top events by dollar volume (derived arithmetic on API fields only)
    print("ranking events by dollar volume ...")
    agg: dict[str, dict] = {}
    for r in rows_open:
        et = r["event_ticker"]
        a = agg.setdefault(et, {
            "event_ticker": et,
            "topic": r["topic"],
            "title": ev_by_ticker.get(et, {}).get("title", "") or r["title"],
            "category": ev_by_ticker.get(et, {}).get("category", ""),
            "market_count": 0,
            "volume_dollars_derived": 0.0,
            "volume_24h_dollars_derived": 0.0,
            "open_interest_dollars_derived": 0.0,
            "top_markets": [],
        })
        a["market_count"] += 1
        a["volume_dollars_derived"] += to_float(r.get("volume_dollars_derived")) or 0.0
        v24 = to_float(r.get("volume_24h_fp"))
        notional = to_float(r.get("notional_value_dollars")) or 0.0
        a["volume_24h_dollars_derived"] += (v24 or 0.0) * notional
        oi = to_float(r.get("open_interest_fp"))
        a["open_interest_dollars_derived"] += (oi or 0.0) * notional
        a["top_markets"].append({"ticker": r["ticker"], "title": r["title"],
                                 "last_price_dollars": r["last_price_dollars"],
                                 "volume_dollars_derived": r.get("volume_dollars_derived", "")})
    for a in agg.values():
        a["volume_dollars_derived"] = round(a["volume_dollars_derived"], 2)
        a["volume_24h_dollars_derived"] = round(a["volume_24h_dollars_derived"], 2)
        a["open_interest_dollars_derived"] = round(a["open_interest_dollars_derived"], 2)
        a["top_markets"].sort(key=lambda x: -(x.get("volume_dollars_derived") or 0))
        a["top_markets"] = a["top_markets"][:5]
        a["source_url"] = f"{BASE}/markets?{urllib.parse.urlencode({'event_ticker': a['event_ticker']})}"

    top_all = sorted(agg.values(), key=lambda a: -a["volume_dollars_derived"])[:40]
    top_by_topic = {}
    for t in TOPICS:
        top_by_topic[t] = [a for a in sorted(agg.values(), key=lambda a: -a["volume_dollars_derived"])
                           if a["topic"] == t][:15]
    write_json(f"{REPO_DATA}/latest/top_events.json", {
        "retrieved_at": retrieved_at,
        "ranking_metric": "volume_dollars_derived = volume_fp x notional_value_dollars (arithmetic on API fields)",
        "overall": top_all,
        "by_topic": top_by_topic,
    })

    # 6. Resolution log: every settled/finalized market with result yes/no
    print("building resolution log ...")
    resolutions = []
    for r in rows_settled:
        if r["result"] in ("yes", "no"):
            resolutions.append({
                "ticker": r["ticker"],
                "event_ticker": r["event_ticker"],
                "title": r["title"],
                "topic": r["topic"],
                "result": r["result"],
                "settlement_ts": r["settlement_ts"],
                "settlement_value_dollars": r["settlement_value_dollars"],
                "close_time": r["close_time"],
                "retrieved_at": retrieved_at,
                "source_url": r["source_url"],
            })
    write_json(f"{REPO_DATA}/latest/resolutions.json", {
        "retrieved_at": retrieved_at,
        "count": len(resolutions),
        "resolution_field": "market.result (yes|no) per https://docs.kalshi.com/getting_started/market_settlement",
        "resolutions": resolutions,
    })

    # 7. Liquidity (orderbooks) + trades + candles for the highest-dollar topic markets
    focus = [r for r in rows_open if r["topic"] in TOPICS]
    focus.sort(key=lambda r: -(to_float(r.get("volume_dollars_derived")) or 0.0))
    focus = focus[:12]
    print(f"focus markets for depth/candles/trades: {[r['ticker'] for r in focus]}")

    orderbooks = {}
    for r in focus:
        t = r["ticker"]
        try:
            ob = col.get(f"/markets/{urllib.parse.quote(t)}/orderbook", {"depth": 25})
            orderbooks[t] = {
                "orderbook_fp": ob.get("orderbook_fp", {}),
                "retrieved_at": retrieved_at,
                "source_url": f"{BASE}/markets/{urllib.parse.quote(t)}/orderbook?depth=25",
                "doc": "https://docs.kalshi.com/api-reference/market/get-market-orderbook",
            }
        except RuntimeError as e:
            print(f"  orderbook {t}: {e}")
    write_json(f"{REPO_DATA}/latest/orderbooks.json", {
        "retrieved_at": retrieved_at, "count": len(orderbooks), "orderbooks": orderbooks})

    trades_out = {}
    for r in focus:
        t = r["ticker"]
        try:
            tr = col.get("/markets/trades", {"limit": 100, "ticker": t})
            trades_out[t] = {
                "trades": tr.get("trades", []),
                "retrieved_at": retrieved_at,
                "source_url": f"{BASE}/markets/trades?ticker={urllib.parse.quote(t)}&limit=100",
            }
        except RuntimeError as e:
            print(f"  trades {t}: {e}")
    write_json(f"{REPO_DATA}/latest/trades.json", {
        "retrieved_at": retrieved_at, "count": len(trades_out), "by_market": trades_out})

    now_ts = int(time.time())
    candles_out = {}
    for r in focus:
        t, s = r["ticker"], r["series_ticker"]
        entry = {"series_ticker": s, "ticker": t, "windows": {}}
        for label, span, period in (("1m_2h", 2 * 3600, 1), ("1h_7d", 7 * 24 * 3600, 60)):
            try:
                cb = col.get(
                    f"/series/{urllib.parse.quote(s)}/markets/{urllib.parse.quote(t)}/candlesticks",
                    {"start_ts": now_ts - span, "end_ts": now_ts, "period_interval": period})
                entry["windows"][label] = {
                    "period_interval_minutes": period,
                    "candlesticks": cb.get("candlesticks", []),
                    "source_url": (f"{BASE}/series/{urllib.parse.quote(s)}/markets/{urllib.parse.quote(t)}"
                                   f"/candlesticks?start_ts={now_ts - span}&end_ts={now_ts}"
                                   f"&period_interval={period}"),
                }
            except RuntimeError as e:
                print(f"  candles {t} {label}: {e}")
        candles_out[t] = entry
    write_json(f"{REPO_DATA}/latest/candles.json", {
        "retrieved_at": retrieved_at,
        "doc": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
        "count": len(candles_out), "by_market": candles_out})

    # 8. Long-run price samples (appended by every run; trimmed by the workflow)
    sample_lines = []
    for r in focus:
        sample_lines.append(json.dumps({
            "ts": retrieved_at, "ticker": r["ticker"], "topic": r["topic"],
            "last_price_dollars": r["last_price_dollars"],
            "yes_bid_dollars": r["yes_bid_dollars"], "yes_ask_dollars": r["yes_ask_dollars"],
            "volume_fp": r["volume_fp"], "open_interest_fp": r["open_interest_fp"],
        }, sort_keys=True))
    with open(f"{REPO_DATA}/history/prices.jsonl", "a", encoding="utf-8") as f:
        f.write("\n".join(sample_lines) + "\n")

    # 9. Meta: request log + counts (the audit trail for verification)
    write_json(f"{REPO_DATA}/latest/meta.json", {
        "generated_at": retrieved_at,
        "tool": "scripts/collect_kalshi_data.py v1",
        "base_url": BASE,
        "official_docs": {
            "environments": "https://docs.kalshi.com/getting_started/api_environments",
            "demo_env": "https://docs.kalshi.com/getting_started/demo_env",
            "market_data_no_auth": "https://docs.kalshi.com/getting_started/quick_start_market_data",
            "candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
            "orderbook": "https://docs.kalshi.com/api-reference/market/get-market-orderbook",
            "trades": "https://docs.kalshi.com/api-reference/market/get-trades",
            "fixed_point": "https://docs.kalshi.com/getting_started/fixed_point_migration",
            "settlement": "https://docs.kalshi.com/getting_started/market_settlement",
        },
        "topic_counts": topic_counts,
        "api_calls": col.call_count,
        "request_log": col.requests,
    })
    print(f"done. {col.call_count} API calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
