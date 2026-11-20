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
    # (topic, series_ticker regex, title regex) — checked BEFORE the category
    # overlay so specific ticker/title evidence wins over generic demo categories
    # GAS-PRICE markets only (CR-d7d7a733-1, 764c370e). Ticker prefixes are anchored; the old unanchored
    # `GAS[A-Z]` / `^KXGAS` rules matched KXGASTATELEG (Georgia legislature), KXPGASTROKEMARGIN (PGA),
    # KXLALIGASCORE (soccer) and similar. `DIESEL(?!EXPORT)` excludes the export-ban policy series.
    # Crude oil (WTI, Brent, crude inventories) is deliberately NOT gas: it is a separate commodity topic.
    ("gas", re.compile(r"^(KX)?(AAAGAS|NGAS|NATGAS|DIESEL(?!EXPORT)|GASMAX$|GASMIN$|GAS$|GASW$|TRUFGAS|CPIGAS$|HEATINGOIL)", re.I), re.compile(
        # title: a fuel-price word, unless the title is about production, inventories, tax, bans, trade or licences
        r"^(?!.*\b(?:production|inventor\w*|tax|ban|export|import|license|stove)\b)"
        r"(?=.*\b(?:gasoline|gas prices?|diesel prices?|natural gas|nat gas|heating oil|aaa gas)\b)", re.I)),
    ("crypto", re.compile(r"^KX(BTC|ETH|SOL|XRP|DOGE|CRYPTO|BINANCE|COINBASE|STABLE)", re.I), re.compile(
        r"\b(bitcoin|btc|ethereum|eth\b|solana|crypto|xrp|dogecoin|coinbase|stablecoin)\b", re.I)),
    ("golf", re.compile(r"^KX(GOLF|PGA|LIV|MASTERS|OPEN|USOPEN|RYDER|DPWT)", re.I), re.compile(
        r"\b(golf|pga|masters|ryder cup|open championship|us open golf|liv golf)\b", re.I)),
    ("elections", re.compile(r"^KX(PRES|SENATE|HOUSE|GOV|MAYOR|PRIMARY|ELECTION|FRENCHPRES|"
                             r"NEXT[A-Z]*PRES|POLIT|PARTISAN|NOMD|NATOSECGEN|KNESS|PARL)", re.I), re.compile(
        r"\b(election|president|senate|mayor|primary|nominee|nomination|electoral|parliament|"
        r"governor(?:ship)?|secretary of state|cabinet|vice president|congressional|"
        r"house (?:race|seat|election|vote|votes|majority|speaker|primary)|u\.?s\.? house|"
        r"control of (?:the )?(?:house|senate|government))\b", re.I)),
    ("culture", re.compile(r"^KX(OSCAR|EMMY|GRAMMY|GOLDENGLOBE|BAFTA|FEATURE|BILLBOARD|"
                           r"BESTPICTURE|MOVIE|FILM|ALBUM|SONG|CELEB|ROYAL|METGALA|COACHELLA)", re.I), re.compile(
        r"\b(oscar|emmy|grammy|golden globe|bafta|best picture|box office|movie|film|"
        r"album|billboard|celebrity|royal|tiktok|viral|culture|gta|video game|nobel|book of the year)\b", re.I)),
]

# Category/tag overlay (fallback after ticker/title rules; recorded per row so
# every classification is auditable on the Flagged-for-Review page).
CATEGORY_TOPIC = {
    "crypto": "crypto",
    "elections": "elections",
    "politics": "elections",   # taxonomy question Q-3 on the Questions page
    "entertainment": "culture",
    "culture": "culture",
}


# API tag overlay (tags asserted by the API; checked before title regexes so
# e.g. KXWTI "WTI oil election day" (tag "Oil & Gas") maps to gas, not elections).
TAG_TOPIC = [
    (re.compile(r"golf", re.I), "golf"),
    # exact fuel tags only; "Oil & Gas", "Oil and energy" and "Energy" are too broad (they carry WTI, ERCOT, test series)
    (re.compile(r"^(gas|gasoline|diesel|natural gas)$", re.I), "gas"),
    (re.compile(r"election", re.I), "elections"),
]


def classify(series_ticker: str, title: str, category: str = "", tags: list | None = None) -> tuple[str, str]:
    """Return (topic, rule_matched). 'other' means no target-topic rule matched.
    Order: series_ticker regex (most specific), then API tags, then title regex,
    then category overlay."""
    for topic, sre, tre in TOPIC_RULES:
        if sre.search(series_ticker or ""):
            return topic, f"series_ticker~/{sre.pattern}/"
    for tag in tags or []:
        for tre2, topic in TAG_TOPIC:
            if tre2.search(str(tag)):
                return topic, f"tag={tag}"
    for topic, sre, tre in TOPIC_RULES:
        if tre.search(title or ""):
            return topic, f"title~/{tre.pattern}/"
    cat = (category or "").strip().lower()
    if cat in CATEGORY_TOPIC:
        return CATEGORY_TOPIC[cat], f"category={category}"
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

    def paginate(self, path: str, params: dict, key: str, max_pages: int = 20) -> tuple[list[dict], bool]:
        out: list[dict] = []
        cursor = None
        limit = int(params.get("limit", 200))
        truncated = False
        for _ in range(max_pages):
            p = dict(params)
            p["limit"] = limit
            if cursor:
                p["cursor"] = cursor
            try:
                body = self.get(path, p)
            except RuntimeError as e:
                if "HTTP 400" in str(e) and limit > 50:  # limit cap varies per endpoint
                    limit = limit // 2
                    print(f"  400 on {path} — retrying with limit={limit}")
                    continue
                raise
            out.extend(body.get(key, []))
            cursor = body.get("cursor")
            if not cursor:
                break
        else:
            truncated = bool(cursor)
        return out, truncated


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


def market_row(m: dict, topic: str, rule: str, retrieved_at: str, series_ticker: str = "") -> dict:
    """One output row: verbatim API fields + classification + source URL."""
    ticker = m.get("ticker", "")
    row = {
        "ticker": ticker,
        "event_ticker": m.get("event_ticker", ""),
        "series_ticker": series_ticker or series_of(ticker),
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


def resolve_series(ticker: str, event_series: str, catalog: dict) -> str:
    """True series ticker: event join first, then progressively strip -SEGMENTs
    until a known series ticker is found (documented heuristic, recorded per row)."""
    if event_series:
        return event_series
    cand = series_of(ticker)
    while cand:
        if cand in catalog:
            return cand
        cand = cand.rsplit("-", 1)[0] if "-" in cand else ""
    return series_of(ticker)


def write_json(path: str, obj) -> None:
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"wrote {path}")


def main() -> int:
    col = Collector()
    retrieved_at = now_iso()

    # 1. Series catalog (used for topic metadata + verification of classification)
    print("fetching series ...")
    series_list, series_truncated = col.paginate(
        "/series", {"limit": 200, "include_volume": "true"}, "series", max_pages=20)
    series_catalog: dict[str, dict] = {}
    series_meta = []
    for s in series_list:
        topic, rule = classify(s.get("ticker", ""), s.get("title", ""),
                               s.get("category", ""), s.get("tags") or [])
        entry = {
            "ticker": s.get("ticker", ""),
            "title": s.get("title", ""),
            "category": s.get("category", ""),
            "tags": s.get("tags") or [],
            "volume_fp": s.get("volume_fp", ""),
            "topic": topic,
            "classification_rule": rule,
            "contract_terms_url": s.get("contract_terms_url", ""),
            "retrieved_at": retrieved_at,
            "source_url": f"{BASE}/series?{urllib.parse.urlencode({'ticker': s.get('ticker','')})}",
        }
        series_catalog[entry["ticker"]] = entry
        if topic in TOPICS:
            series_meta.append(entry)
        else:  # keep a lean audit stub for non-topic series
            series_meta.append({k: entry[k] for k in
                                ("ticker", "category", "topic", "classification_rule")})
    write_json(f"{REPO_DATA}/latest/series.json", {
        "retrieved_at": retrieved_at, "count": len(series_meta), "series": series_meta})

    # 2. Events (all pages; needed to join market -> event -> series)
    print("fetching events ...")
    events, events_truncated = col.paginate("/events", {"limit": 200}, "events", max_pages=40)
    ev_by_ticker: dict[str, dict] = {}
    for e in events:
        et = e.get("event_ticker", "")
        scat = e.get("category", "")
        s_ticker = e.get("series_ticker", "")
        s_entry = series_catalog.get(s_ticker, {})
        topic, rule = classify(s_ticker, e.get("title", ""),
                               scat or s_entry.get("category", ""),
                               s_entry.get("tags") or [])
        ev_by_ticker[et] = {
            "event_ticker": et,
            "series_ticker": s_ticker,
            "title": e.get("title", ""),
            "sub_title": e.get("sub_title", ""),
            "category": scat,
            "topic": topic,
            "classification_rule": rule,
            "settlement_sources": e.get("settlement_sources", []),
            "retrieved_at": retrieved_at,
            "source_url": f"{BASE}/events?{urllib.parse.urlencode({'series_ticker': s_ticker})}",
        }
    topic_events = [v for v in ev_by_ticker.values() if v["topic"] in TOPICS]
    topic_events.sort(key=lambda e: e["title"])
    write_json(f"{REPO_DATA}/latest/events.json", {
        "retrieved_at": retrieved_at, "count": len(topic_events), "events": topic_events})

    # 3. Markets: SERIES-FIRST, bounded per series. The /markets?status=open
    # listing is dominated by tens of thousands of crypto strike-ladder markets,
    # which truncates global pagination before elections/golf markets appear
    # (observed 2026-11-20: 80k rows hit the cap). The /series catalog IS
    # complete and carries volume_fp (include_volume=true), so we rank topic
    # series by volume and query their markets directly.
    def classify_market(m: dict) -> tuple[str, str, str]:
        """(topic, rule, true series ticker) using event/series joins."""
        et = m.get("event_ticker", "")
        ev = ev_by_ticker.get(et, {})
        s_ticker = resolve_series(m.get("ticker", ""), ev.get("series_ticker", ""), series_catalog)
        s_entry = series_catalog.get(s_ticker, {})
        scat = ev.get("category") or s_entry.get("category", "")
        topic, rule = classify(s_ticker, m.get("title", ""),
                               scat, s_entry.get("tags") or [])
        return topic, rule, s_ticker

    TOP_SERIES_PER_TOPIC = 25
    rows_open, rows_settled = [], []
    topic_counts = {t: 0 for t in list(TOPICS) + ["other"]}
    selection: dict[str, list] = {}
    open_truncated_series, settled_truncated_series = [], []
    for t in TOPICS:
        sers = [s for s in series_meta if s["topic"] == t]
        sers.sort(key=lambda s: -(to_float(s.get("volume_fp")) or 0.0))
        chosen = [s for s in sers if to_float(s.get("volume_fp")) or 0.0][:TOP_SERIES_PER_TOPIC] or sers[:5]
        selection[t] = chosen
        print(f"  topic {t}: {len(sers)} series; pulling markets for top {len(chosen)} by series volume")
        for s in chosen:
            try:
                mkts, tr = col.paginate("/markets", {"limit": 1000, "status": "open",
                                                     "series_ticker": s["ticker"]},
                                        "markets", max_pages=3)
            except RuntimeError as e:
                print(f"  open markets {s['ticker']}: {e}")
                continue
            if tr:
                open_truncated_series.append(s["ticker"])
            for m in mkts:
                topic, rule, s_t = classify_market(m)
                topic_counts[topic] += 1
                rows_open.append(market_row(m, topic, rule, retrieved_at, s_t))
    # resolutions: settled markets for the top 10 series per topic, last 30 days
    for t in TOPICS:
        for s in selection[t][:10]:
            try:
                mkts, tr = col.paginate("/markets", {"limit": 1000, "status": "settled",
                                                     "series_ticker": s["ticker"],
                                                     "min_close_ts": int(time.time()) - 30 * 86400},
                                        "markets", max_pages=2)
            except RuntimeError as e:
                print(f"  settled markets {s['ticker']}: {e}")
                continue
            if tr:
                settled_truncated_series.append(s["ticker"])
            for m in mkts:
                topic, rule, s_t = classify_market(m)
                rows_settled.append(market_row(m, topic, rule, retrieved_at, s_t))
    seen_t = set()
    deduped = []
    for r in rows_open:  # a market can appear under one series only, but be safe
        if r["ticker"] not in seen_t:
            seen_t.add(r["ticker"])
            deduped.append(r)
    rows_open = deduped

    rows_open.sort(key=lambda r: -(to_float(r.get("volume_fp")) or 0.0))
    rows_settled.sort(key=lambda r: -(to_float(r.get("volume_fp")) or 0.0))

    write_json(f"{REPO_DATA}/latest/markets_open.json", {
        "retrieved_at": retrieved_at, "count": len(rows_open), "markets": rows_open})
    write_json(f"{REPO_DATA}/latest/markets_settled.json", {
        "retrieved_at": retrieved_at, "count": len(rows_settled), "markets": rows_settled})

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

    # 5b. Per-topic bundles (small payloads for the site's category pages)
    for t in TOPICS:
        write_json(f"{REPO_DATA}/latest/topic_{t}.json", {
            "retrieved_at": retrieved_at,
            "topic": t,
            "count": sum(1 for r in rows_open if r["topic"] == t),
            "markets": [r for r in rows_open if r["topic"] == t][:300],
            "events": [e for e in topic_events if e["topic"] == t],
            "top_events": top_by_topic[t],
        })

    # 6. Resolution log: every settled/finalized market with result yes/no (topic scope)
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
    resolutions.sort(key=lambda x: x.get("settlement_ts") or "", reverse=True)
    result_counts: dict[str, int] = {}
    for row in resolutions:
        result_counts[row["result"]] = result_counts.get(row["result"], 0) + 1
    kept, per_topic = [], {t: 0 for t in TOPICS}
    for row in resolutions:  # balance topics: crypto ladders settle thousands/hour
        t = row["topic"]
        if per_topic.get(t, 0) >= 300:
            continue
        per_topic[t] = per_topic.get(t, 0) + 1
        kept.append(row)
        if len(kept) >= 1000:
            break
    resolutions = kept
    write_json(f"{REPO_DATA}/latest/resolutions.json", {
        "retrieved_at": retrieved_at,
        "count": len(resolutions),
        "result_counts_this_run": result_counts,
        "per_topic_caps": "max 300 rows per topic so ladder settlements cannot crowd out other topics",
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
    import os
    os.makedirs(f"{REPO_DATA}/history", exist_ok=True)
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

    # 8b. Accumulate resolutions across runs (track events until resolved)
    res_path = f"{REPO_DATA}/history/resolutions.jsonl"
    seen: set[str] = set()
    if os.path.exists(res_path):
        with open(res_path, encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line).get("ticker", ""))
                except json.JSONDecodeError:
                    pass
    with open(res_path, "a", encoding="utf-8") as f:
        for row in resolutions:
            if row["ticker"] not in seen:
                f.write(json.dumps(row, sort_keys=True) + "\n")

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
        "collection_method": (
            "series-first: /series catalog (complete, include_volume=true) classified into "
            "topics; markets pulled for the top %d series per topic by series volume_fp "
            "(open: 3 pages max per series; settled: top 10 series per topic, 30-day window, "
            "2 pages max). Global /markets pagination is truncated by crypto strike-ladder "
            "markets (observed 80k+ rows), so series-first selection avoids that blind spot."
            % TOP_SERIES_PER_TOPIC),
        "series_selection": {t: [{"ticker": s["ticker"], "volume_fp": s.get("volume_fp", "")}
                                 for s in selection[t]] for t in TOPICS},
        "truncated": {
            "series": series_truncated, "events": events_truncated,
            "open_markets_series": open_truncated_series,
            "settled_markets_series": settled_truncated_series,
        },
        "api_calls": col.call_count,
        "request_log": col.requests,
    })
    print(f"done. {col.call_count} API calls.")
    return 0


if __name__ == "__main__":
    import traceback
    status_path = f"{REPO_DATA}/latest/collector_status.json"
    try:
        rc = main()
        write_json(status_path, {"status": "ok", "finished_at": now_iso()})
        sys.exit(rc)
    except Exception as e:  # noqa: BLE001 — report and re-raise for CI visibility
        write_json(status_path, {
            "status": "error", "finished_at": now_iso(),
            "error": str(e), "traceback": traceback.format_exc()[-4000:]})
        raise
