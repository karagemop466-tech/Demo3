#!/usr/bin/env python3
"""Swing ledger + candidate-catalyst attribution for the Kalshi demo dashboard.

Brief line this implements
--------------------------
"Live charts should include events and website links that may have caused a sharp jump
in contract price, greater than or equal to $0.10 in either direction."

What it does
------------
1. Reads the price tape (samples of `last_price_dollars` per market, ISO timestamps):
   `data/history/prices.jsonl` written by the repo collector, plus its own tape
   `catalysts/data/tape.jsonl` so sampling keeps accumulating across runs.
2. When the network is reachable, polls the official demo REST API for the watchlist
   (`GET /markets?tickers=...`) and appends fresh samples, so detection improves on
   every run. Public market data needs no API key
   (https://docs.kalshi.com/getting_started/quick_start_market_data.md).
3. Detects swings of >= $0.10 in EITHER direction between consecutive samples of the
   same market, using exact decimal arithmetic in dollars (never float subtraction).
4. Enriches every swing with links that are verifiable by construction:
   - the exact market API URL (per-row source link),
   - the event API URL,
   - the series API URL and the series `settlement_sources` the EXCHANGE itself cites,
   - news items from a probe-gated allowlist (`catalysts/feeds.json`) whose publish
     time falls inside the swing window and whose title shares keywords with the
     market. These are CANDIDATE catalysts — the tool never claims causation.
5. Tracks each market until it resolves: a finalized/settled market records
   `result` (yes/no), `settlement_ts` and `settlement_value_dollars` from the API and
   is then dropped from the live watchlist (per brief: "track live events until the
   events have resolved").
6. Writes `catalysts/data/swings.json`, `catalysts/data/status.json` and
   `catalysts/data/feed_health.json` for the static page to render.

Fail-closed rules (no hallucination by construction)
----------------------------------------------------
- No feed fetches are trusted unless that run actually parsed items from them; every
  feed's HTTP status and item count is published in `feed_health.json`.
- A swing with no qualifying news item keeps an EMPTY catalyst list plus a
  machine-readable `match_status` reason. Nothing is inferred, back-filled or guessed.
- Prices come only from API fields (`last_price_dollars`, else legacy `last_price`
  cents) or from tape rows; the field used is recorded per sample.

Offline mode
------------
`--offline` (or automatic when the demo API is unreachable — e.g. this repository's
build sandbox, whose egress allowlist blocks kalshi.co) skips all network calls and
works purely on the committed tape, so the pipeline is testable and reproducible.

Usage
-----
    python3 catalysts/scan.py                 # live poll + feeds (CI runner)
    python3 catalysts/scan.py --offline       # tape-only
    python3 catalysts/scan.py --probe-feeds   # feed allowlist check only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
DATA_DIR = os.path.join(HERE, "data")

DEMO_REST_ROOT = "https://external-api.demo.kalshi.co/trade-api/v2"
DEMO_REST_ROOT_ALT = "https://demo-api.kalshi.co/trade-api/v2"

SWING_THRESHOLD_DOLLARS = Decimal("0.10")   # brief: >= $0.10 in either direction
MAX_TAPE_ROWS = 20000                       # tape file cap (oldest rows trimmed)
MAX_SWINGS_KEPT = 500                       # swings.json cap (newest kept)
MAX_CATALYSTS_PER_SWING = 3
TICKER_BATCH = 25                           # tickers per /markets?tickers= request
DEFAULT_LOOKBACK_HOURS = 72
DEFAULT_WINDOW_PRE_MIN = 180                # a link "may have caused" a jump only if
DEFAULT_WINDOW_POST_MIN = 60                # published at/near the move
USER_AGENT = "kalshi-demo-tracker/1.0 (catalyst scan; research use)"

DOCS = {
    "demo_env": "https://docs.kalshi.com/getting_started/demo_env",
    "environments": "https://docs.kalshi.com/getting_started/api_environments",
    "market_data_no_auth": "https://docs.kalshi.com/getting_started/quick_start_market_data",
    "get_markets": "https://docs.kalshi.com/api-reference/market/get-markets",
    "get_series": "https://docs.kalshi.com/api-reference/market/get-series",
    "get_events": "https://docs.kalshi.com/api-reference/market/get-events",
    "market_settlement": "https://docs.kalshi.com/getting_started/market_settlement",
    "fixed_point": "https://docs.kalshi.com/getting_started/fixed_point_migration",
}

STOPWORDS = {
    "will", "the", "and", "for", "with", "that", "this", "from", "before", "after",
    "than", "then", "into", "over", "under", "its", "it's", "who", "what", "when",
    "where", "which", "does", "did", "have", "has", "had", "been", "being", "were",
    "are", "was", "not", "get", "gets", "gotten", "new", "next", "first", "last",
    "market", "markets", "price", "prices", "resolves", "resolve", "resolved",
    "above", "below", "between", "each", "per", "any", "all", "one", "two", "time",
    "usd", "dollars", "cents", "day", "days", "am", "pm", "est", "utc", "kalshi",
}


# --------------------------------------------------------------------------- utils
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_root_marker(path: str) -> str:
    """Best-effort repo root for a tape path, so `origin` stays a repo-relative label."""
    marker = os.path.join("data", "history")
    idx = path.find(marker)
    return path[:idx] if idx > 0 else os.path.dirname(os.path.dirname(os.path.abspath(path)))


def parse_ts(value):
    """Parse an ISO-8601 timestamp (with Z or offset) to an aware UTC datetime."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dollars(value):
    """Parse a fixed-point dollar string ('0.6500') -> Decimal. None if absent/garbage.

    Field names/shape per https://docs.kalshi.com/getting_started/fixed_point_migration
    (verified live 2026-11-20: markets return e.g. "last_price_dollars":"0.6500").
    """
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def market_price(market: dict):
    """Return (Decimal dollars, field_used) for a market's last traded price.

    Prefers the fixed-point field; falls back to the legacy integer-cents field and
    records which one was used, so no unit is ever assumed silently.
    """
    dollars = parse_dollars(market.get("last_price_dollars"))
    if dollars is not None:
        return dollars, "last_price_dollars"
    cents = market.get("last_price")
    if isinstance(cents, (int, float)) and not isinstance(cents, bool):
        return (Decimal(str(cents)) / Decimal(100)).quantize(Decimal("0.0001")), "last_price (cents/100)"
    return None, None


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=False, ensure_ascii=True)
        fh.write("\n")
    os.replace(tmp, path)


def sha16(*parts) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8", "replace"))
    return h.hexdigest()[:16]


class Http:
    """Minimal urllib client with retry, backoff and per-run accounting."""

    def __init__(self, timeout: float = 20.0, retries: int = 3, min_interval: float = 0.2,
                 log=None):
        self.timeout = timeout
        self.retries = max(1, retries)
        self.min_interval = min_interval
        self.log = log or (lambda m: None)
        self.requests = 0
        self.errors = 0
        self._last = 0.0

    def _throttle(self):
        import time
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def get(self, url: str, as_text: bool = False):
        import time
        last_err = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            self.requests += 1
            req = urllib.request.Request(url, headers={
                "Accept": "application/json, application/rss+xml, application/xml;q=0.9, */*;q=0.5",
                "User-Agent": USER_AGENT,
            })
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                text = body.decode("utf-8", "replace")
                return text if as_text else json.loads(text or "{}")
            except urllib.error.HTTPError as exc:
                self.errors += 1
                last_err = f"HTTP {exc.code}"
                if exc.code not in (429, 500, 502, 503, 504) and 400 <= exc.code < 500:
                    break                                   # 4xx will not improve
                time.sleep(0.8 * attempt)
            except Exception as exc:                          # noqa: BLE001 - network
                self.errors += 1
                last_err = f"{type(exc).__name__}: {exc}"
                time.sleep(0.4 * attempt)
        self.log(f"GET {url} failed: {last_err}")
        raise RuntimeError(last_err or "request failed")


# ------------------------------------------------------------------------ the tape
def load_tape(paths, repo: str | None = None) -> list[dict]:
    """Read JSONL price samples; keep only rows with a ticker, ts and price."""
    rows, seen = [], set()
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ticker = rec.get("ticker")
                ts = parse_ts(rec.get("ts") or rec.get("retrieved_at"))
                price = parse_dollars(rec.get("last_price_dollars"))
                if not ticker or ts is None or price is None:
                    continue
                key = (ticker, ts.strftime("%Y%m%dT%H%M%S"), str(price))
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "ticker": ticker,
                    "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "last_price_dollars": f"{price:.4f}",
                    "event_ticker": rec.get("event_ticker") or "",
                    "series_ticker": rec.get("series_ticker") or "",
                    "topic": rec.get("topic") or "",
                    "volume_fp": rec.get("volume_fp") or "",
                    "open_interest_fp": rec.get("open_interest_fp") or "",
                    "yes_bid_dollars": rec.get("yes_bid_dollars") or "",
                    "yes_ask_dollars": rec.get("yes_ask_dollars") or "",
                    "price_field": rec.get("price_field") or "last_price_dollars",
                    "origin": os.path.relpath(path, repo or repo_root_marker(path)),
                })
    rows.sort(key=lambda r: (r["ticker"], r["ts"]))
    return rows


def append_tape(path: str, new_rows: list[dict]) -> int:
    """Append samples to the tape file, trimming to the newest MAX_TAPE_ROWS lines."""
    if not new_rows:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            existing = [ln for ln in fh.read().splitlines() if ln.strip()]
    out = existing + [json.dumps(r, sort_keys=True) for r in new_rows]
    if len(out) > MAX_TAPE_ROWS:
        out = out[-MAX_TAPE_ROWS:]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    return len(new_rows)


def detect_swings(tape: list[dict], threshold: Decimal, lookback_hours: float,
                  now: datetime, known_ids: set) -> list[dict]:
    """Consecutive-sample moves of >= threshold dollars in either direction."""
    by_ticker = defaultdict(list)
    for row in tape:
        by_ticker[row["ticker"]].append(row)

    cutoff = now - timedelta(hours=lookback_hours) if lookback_hours else None
    swings = []
    for ticker, rows in by_ticker.items():
        rows = sorted(rows, key=lambda r: r["ts"])
        for prev, cur in zip(rows, rows[1:]):
            d0 = parse_dollars(prev.get("last_price_dollars"))
            d1 = parse_dollars(cur.get("last_price_dollars"))
            if d0 is None or d1 is None:
                continue
            delta = d1 - d0
            if abs(delta) < threshold:
                continue
            p0, p1 = prev["last_price_dollars"], cur["last_price_dollars"]
            ts0, ts1 = parse_ts(prev["ts"]), parse_ts(cur["ts"])
            if ts0 is None or ts1 is None:
                continue
            if cutoff and ts1 < cutoff:
                continue
            swing_id = sha16(ticker, prev["ts"], cur["ts"], p0, p1)
            if swing_id in known_ids:
                continue
            swings.append({
                "id": swing_id,
                "ticker": ticker,
                "topic": cur.get("topic") or prev.get("topic") or "",
                "event_ticker": cur.get("event_ticker") or prev.get("event_ticker") or "",
                "series_ticker": cur.get("series_ticker") or "",
                "direction": "up" if delta > 0 else "down",
                "delta_dollars": f"{delta:.4f}",
                "abs_delta_dollars": f"{abs(delta):.4f}",
                "from": {"ts": prev["ts"], "last_price_dollars": p0,
                        "price_field": prev.get("price_field", "")},
                "to": {"ts": cur["ts"], "last_price_dollars": p1,
                       "price_field": cur.get("price_field", "")},
                "sample_gap_seconds": int((ts1 - ts0).total_seconds()),
                "detected_by": "price_tape",
                "origin": cur.get("origin", ""),
                "detected_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
    swings.sort(key=lambda s: s["to"]["ts"], reverse=True)
    return swings


# ------------------------------------------------------------------- live market API
def feeds_path_default() -> str:
    return os.path.join(HERE, "feeds.json")


def market_url(root: str, ticker: str) -> str:
    return f"{root}/markets/{ticker}"


def poll_markets(http: Http, root: str, tickers: list[str], log) -> tuple[list[dict], list[str]]:
    """Batch `GET /markets?tickers=a,b,...`; shrink the batch on error.

    Endpoint and the `tickers` (comma-separated) filter:
    https://docs.kalshi.com/api-reference/market/get-markets
    """
    markets, failed = [], []
    queue = [tickers[i:i + TICKER_BATCH] for i in range(0, len(tickers), TICKER_BATCH)]
    while queue:
        batch = queue.pop(0)
        if not batch:
            continue
        url = f"{root}/markets?tickers={','.join(batch)}&limit={len(batch)}"
        try:
            data = http.get(url)
            got = data.get("markets") or []
            for m in got:
                m["_source_url"] = url
                m["_single_source_url"] = market_url(root, m.get("ticker", ""))
            markets.extend(got)
            for m in got:
                m["_source_kind"] = "live"
            found = {m.get("ticker") for m in got}
            missing = [t for t in batch if t not in found]
            if missing:
                failed.extend(missing)          # e.g. settled markets need status=settled
        except Exception as exc:                 # noqa: BLE001
            log(f"batch poll failed ({len(batch)} tickers): {exc}")
            if len(batch) > 1:
                mid = len(batch) // 2
                queue.insert(0, batch[mid:])
                queue.insert(0, batch[:mid])
            else:
                failed.append(batch[0])
    return markets, failed


def poll_settled(http: Http, root: str, tickers: list[str], log) -> list[dict]:
    """Re-poll tickers that vanished from the open book, with status=settled.

    Status values verified live 2026-11-20: the query accepts open/settled/closed;
    responses use "active" (open) and "finalized"/"settled" (after resolution) —
    see https://docs.kalshi.com/getting_started/market_settlement.md
    """
    out = []
    for i in range(0, len(tickers), TICKER_BATCH):
        batch = tickers[i:i + TICKER_BATCH]
        url = f"{root}/markets?tickers={','.join(batch)}&status=settled&limit={len(batch)}"
        try:
            for m in (http.get(url).get("markets") or []):
                m["_source_url"] = url
                m["_single_source_url"] = market_url(root, m.get("ticker", ""))
                m["_source_kind"] = "live"
                out.append(m)
        except Exception as exc:                   # noqa: BLE001
            log(f"settled poll failed: {exc}")
    return out


def derive_series(event_ticker: str) -> str:
    """Series-ticker lookup KEY for an event ticker ("KXFOO-26NOV20H12" -> "KXFOO").

    Kalshi ticker format (event = SERIES-SUFFIX) per
    https://docs.kalshi.com/api-reference/market/get-events . Nothing is claimed from
    this string: it is only used as the key of a `GET /series/{ticker}` request, and
    the series data published for a swing comes back from that response — if the
    request does not return a series with this exact ticker, the fields stay blank.
    """
    if not event_ticker or "-" not in event_ticker:
        return ""
    head = event_ticker.split("-", 1)[0].strip()
    return head if re.fullmatch(r"[A-Z0-9]{3,}", head) else ""


def snapshot_index(repo: str) -> dict:
    """Market/event records already committed by the collector, for OFFLINE enrichment.

    Those files (data/latest/topic_*.json, markets_open.json, markets_settled.json,
    data/resolutions.json) are demo-API responses with a `source_url` on every row, so
    an offline run still links the exact official request the values came from —
    nothing is invented, and no ticker is guessed.
    """
    markets: dict = {}

    def remember(m: dict, origin: str, retrieved: str) -> None:
        t = m.get("ticker")
        if not t or t in markets:
            return
        m["_source_kind"] = "snapshot"
        m["_snapshot_file"] = origin
        m["_snapshot_retrieved_at"] = m.get("retrieved_at") or retrieved or ""
        m["_single_source_url"] = m.get("source_url") or market_url(DEMO_REST_ROOT, t)
        markets[t] = m

    for name in ("markets_open.json", "markets_settled.json"):
        blob = read_json(os.path.join(repo, "data", "latest", name)) or {}
        for m in (blob.get("markets") or []):
            remember(m, f"data/latest/{name}", blob.get("retrieved_at", ""))
    for topic in ("gas", "elections", "culture", "crypto", "golf"):
        path = os.path.join(repo, "data", "latest", f"topic_{topic}.json")
        blob = read_json(path) or {}
        for m in (blob.get("markets") or []):
            remember(m, f"data/latest/topic_{topic}.json", blob.get("retrieved_at", ""))
    res = read_json(os.path.join(repo, "data", "resolutions.json")) or {}
    by_market = res.get("by_market") or {}
    pairs = list(by_market.items()) if isinstance(by_market, dict) else [(m.get("ticker"), m)
                                                                         for m in by_market]
    for ticker_key, m in pairs:
        # by_market rows are keyed by ticker and carry no `ticker` field of their own;
        # the key comes straight from the collector's index (no guessing: it is the
        # same ticker the row's source_url requests).
        if isinstance(m, dict) and m.get("ticker") != ticker_key:
            m = dict(m)
            m["ticker"] = ticker_key
        if isinstance(m, dict) and (m.get("result") or m.get("settled_time")):
            m.setdefault("close_time", m.get("settled_time") or "")
            m.setdefault("settlement_ts", m.get("settled_time") or "")
            m.setdefault("status", "finalized" if m.get("result") else "")
            m.setdefault("topic", "")
            remember(m, "data/resolutions.json", res.get("updated_at", ""))

    events: dict = {}
    market_to_event: dict = {}
    ev_src = read_json(os.path.join(repo, "data", "resolutions.json")) or {}
    for ev_ticker, ev in (ev_src.get("resolved") or {}).items():
        if isinstance(ev, dict):
            ev.setdefault("event_ticker", ev_ticker)
            events.setdefault(ev_ticker, ev)
            for w in (ev.get("winners") or []):
                if isinstance(w, dict) and w.get("ticker"):
                    market_to_event[w["ticker"]] = ev_ticker
    for topic in ("gas", "elections", "culture", "crypto", "golf"):
        blob = read_json(os.path.join(repo, "data", "latest", f"topic_{topic}.json")) or {}
        for ev in (blob.get("events") or []):
            t = ev.get("event_ticker")
            if t and t not in events:
                ev["_snapshot_file"] = f"data/latest/topic_{topic}.json"
                events[t] = ev
    for t, m in markets.items():
        et = m.get("event_ticker")
        if et:
            market_to_event.setdefault(t, et)
    return {"markets": markets, "events": events, "market_to_event": market_to_event,
            "files": ["data/latest/markets_open.json", "data/latest/markets_settled.json",
                      "data/latest/topic_{gas,elections,culture,crypto,golf}.json",
                      "data/resolutions.json"]}


def fetch_series(http: Http, root: str, series_ticker: str, log) -> dict:
    """`GET /series/{ticker}` — the exchange's own record for the series.

    https://docs.kalshi.com/api-reference/market/get-series
    Returns only fields the API actually reported (no inferred values).
    """
    if not series_ticker:
        return {}
    url = f"{root}/series/{series_ticker}"
    try:
        data = http.get(url)
        raw = data.get("series") if isinstance(data, dict) else None
        if isinstance(raw, list):                     # /series?category= returns a list
            s = next((x for x in raw if isinstance(x, dict)
                      and x.get("ticker") == series_ticker), {})
        elif isinstance(raw, dict):
            s = raw
        else:
            s = data if isinstance(data, dict) else {}
        if (s.get("ticker") or "") != series_ticker:
            # The response must describe exactly the series asked for, otherwise the
            # fields are not attributable and stay blank.
            return {"series_ticker": series_ticker, "source_url": url,
                    "error": "response did not carry this series ticker"}
        srcs = []
        for item in (s.get("settlement_sources") or []):
            if isinstance(item, dict) and (item.get("name") or item.get("url")):
                srcs.append({"name": item.get("name") or "", "url": item.get("url") or ""})
        return {
            "series_ticker": s.get("ticker") or series_ticker,
            "title": s.get("title") or "",
            "category": s.get("category") or "",
            "frequency": s.get("frequency") or "",
            "settlement_sources": srcs,
            "contract_terms_url": s.get("contract_terms_url") or "",
            "source_url": url,
        }
    except Exception as exc:                        # noqa: BLE001
        log(f"series poll failed for {series_ticker}: {exc}")
        return {"series_ticker": series_ticker, "error": str(exc), "source_url": url}


def market_links(root: str, market: dict, event_from_api: str = "") -> dict:
    ticker = market.get("ticker") or ""
    event = event_from_api or market.get("event_ticker") or ""
    series = market.get("series_ticker") or ""
    return {
        "market_api_url": market.get("_single_source_url") or market_url(root, ticker),
        "event_api_url": (f"{root}/events/{event}" if event else ""),
        "kalshi_market_page": (f"https://demo.kalshi.co/market/{event}" if event
                               else ("https://demo.kalshi.co/" if not event else "")),
        "series_ticker": series,
    }


# ---------------------------------------------------------------- news feed layer
def _strip_tags(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text or "", flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).replace("&amp;", "&").strip()


def _item_time(entry) -> str:
    for tag in ("pubDate", "published", "updated", "date"):
        for el in list(entry.iter()):
            if el.tag.split("}")[-1] == tag and (el.text or "").strip():
                raw = el.text.strip()
                dt = parsedate_to_datetime_safe(raw) or parse_ts(raw)
                if dt:
                    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ""


def parsedate_to_datetime_safe(raw: str):
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_feed(xml_text: str, feed: dict) -> list[dict]:
    """Parse RSS 2.0 / Atom into [{title, link, published_ts}]; empty list on failure."""
    try:
        root_el = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    entries = []
    if root_el.tag.split("}")[-1] == "feed":                 # Atom
        entries = [e for e in root_el if e.tag.split("}")[-1] == "entry"]
    else:                                                     # RSS
        for node in root_el.iter():
            if node.tag.split("}")[-1] == "item":
                entries.append(node)
    items = []
    for entry in entries[:400]:
        title = link = ""
        for child in list(entry):
            name = child.tag.split("}")[-1]
            if name == "title" and not title:
                title = _strip_tags(child.text or "")
            elif name == "link":
                if not link:
                    if (child.text or "").strip():
                        link = child.text.strip()
                    elif child.get("href"):
                        link = child.get("href").strip()
        published = _item_time(entry)
        if not link:
            continue
        items.append({"title": title, "link": link, "published_ts": published,
                      "feed_name": feed.get("name", ""), "feed_url": feed.get("url", "")})
    return items


def tokens_of(text: str) -> set:
    out = set()
    for raw in re.findall(r"[A-Za-z0-9$][A-Za-z0-9$.'-]*", (text or "").lower()):
        tok = raw.strip(".'-")
        if len(tok) < 3 or tok in STOPWORDS or tok.isdigit():
            continue
        out.add(tok)
    return out


def match_catalyst_items(items: list[dict], market_text: str, t0: datetime, t1: datetime,
                         pre_min: int, post_min: int, limit: int) -> dict:
    """News items published in the swing window that share keywords with the market.

    Matching is transparent keyword overlap; the matched keywords are published with
    every link so a reader can judge the relevance. No causal claim is made.
    """
    keywords = tokens_of(market_text)
    window_start = t0 - timedelta(minutes=pre_min)
    window_end = t1 + timedelta(minutes=post_min)
    matched = []
    in_window = 0
    for it in items:
        pub = parse_ts(it.get("published_ts"))
        if pub is None or not (window_start <= pub <= window_end):
            continue
        in_window += 1
        hits = sorted(keywords & tokens_of(it.get("title", "")))
        strong = [h for h in hits if len(h) >= 6]
        if len(hits) >= 2 or (hits and strong):
            matched.append({
                "title": it.get("title", ""),
                "link": it.get("link", ""),
                "published_ts": it.get("published_ts", ""),
                "feed_name": it.get("feed_name", ""),
                "feed_url": it.get("feed_url", ""),
                "matched_keywords": hits,
                "lead_seconds": int((t1 - pub).total_seconds()),
                "in_window_before_swing": pub <= t1,
            })
    matched.sort(key=lambda m: (not m["in_window_before_swing"], abs(m["lead_seconds"])))
    if matched:
        status = "matched"
    elif in_window:
        status = "items_in_window_but_no_keyword_overlap"
    else:
        status = "no_feed_item_in_window"
    return {"candidates": matched[:limit], "items_in_window": in_window,
            "match_status": status,
            "window_start_ts": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end_ts": window_end.strftime("%Y-%m-%dT%H:%M:%SZ")}


def load_feeds(path: str) -> list[dict]:
    cfg = read_json(path, {"feeds": []}) or {}
    feeds = [f for f in (cfg.get("feeds") or []) if f.get("url") and f.get("enabled", True)]
    return feeds


def fetch_feeds(http: Http, feeds: list[dict], log) -> tuple[list[dict], list[dict]]:
    items, health = [], []
    for feed in feeds:
        rec = {"name": feed.get("name", ""), "url": feed.get("url", ""),
               "topics": feed.get("topics") or [], "items_parsed": 0,
               "http_status": None, "ok": False, "error": "", "checked_at": now_iso()}
        try:
            text = http.get(feed["url"], as_text=True)
            parsed = parse_feed(text, feed)
            rec["items_parsed"] = len(parsed)
            rec["ok"] = bool(parsed)
            rec["http_status"] = 200 if parsed else "parse_empty"
            for it in parsed:
                it["topics"] = feed.get("topics") or []
            items.extend(parsed)
            if not parsed:
                rec["error"] = "fetched but no items parsed"
        except Exception as exc:                   # noqa: BLE001
            rec["error"] = str(exc)
            log(f"feed {feed.get('name')} failed: {exc}")
        health.append(rec)
    return items, health


# ------------------------------------------------------------------------ enrich
def enrich(swing: dict, market: dict | None, series_info: dict | None, root: str,
           event_info: dict | None = None) -> None:
    """Attach verifiable links + resolution state to a swing record."""
    ticker = swing["ticker"]
    title = ""
    if market:
        title = market.get("title") or ""
        sub = " / ".join(x for x in (market.get("yes_sub_title"), market.get("no_sub_title"))
                         if x)
        if sub:
            title = f"{title} — {sub}"
        swing["status"] = market.get("status") or ""
        swing["result"] = market.get("result") or ""
        swing["close_time"] = market.get("close_time") or ""
        swing["settlement_ts"] = market.get("settlement_ts") or ""
        swing["settlement_value_dollars"] = market.get("settlement_value_dollars") or ""
        swing["volume_fp"] = market.get("volume_fp") or ""
        swing["open_interest_fp"] = market.get("open_interest_fp") or ""
        swing["event_ticker"] = market.get("event_ticker") or swing.get("event_ticker") or ""
        swing["series_ticker"] = market.get("series_ticker") or swing.get("series_ticker") or ""
        swing["market_url_pair"] = market.get("_source_url") or ""
    else:
        swing["status"] = ""
        swing["result"] = ""
        swing["close_time"] = ""
        swing["settlement_ts"] = ""
        swing["settlement_value_dollars"] = ""
        swing["volume_fp"] = swing.get("volume_fp", "")
        swing["open_interest_fp"] = swing.get("open_interest_fp", "")
    if not swing.get("event_ticker") and event_info:
        swing["event_ticker"] = event_info.get("event_ticker") or ""
    swing["title"] = title
    swing["resolved"] = bool(swing.get("status") in ("settled", "finalized")) or bool(
        swing.get("result") in ("yes", "no"))
    swing["tracking"] = "stopped_resolved" if swing["resolved"] else "active"
    swing["links"] = market_links(root, {"ticker": ticker, **(market or {})},
                                  swing.get("event_ticker", ""))
    if series_info and series_info.get("settlement_sources"):
        info = dict(series_info)
        info.setdefault("provenance", "GET /series/{ticker} (this run)")
        swing["series"] = info
    elif series_info or event_info:
        srcs = (series_info or {}).get("settlement_sources") or \
            (event_info or {}).get("settlement_sources") or []
        swing["series"] = {
            "series_ticker": (series_info or {}).get("series_ticker")
            or (event_info or {}).get("series_ticker") or "",
            "title": (series_info or {}).get("title") or (event_info or {}).get("title") or "",
            "category": (series_info or {}).get("category") or "",
            "frequency": (series_info or {}).get("frequency") or "",
            "settlement_sources": srcs,
            "contract_terms_url": (series_info or {}).get("contract_terms_url") or "",
            "source_url": (series_info or {}).get("source_url")
            or (event_info or {}).get("source_url") or "",
            "error": (series_info or {}).get("error") or "",
            "provenance": ("GET /series/{ticker} (this run)" if (srcs and series_info
                           and not series_info.get("error")) else
                           (f"committed snapshot: {(event_info or {}).get('_snapshot_file', 'data/resolutions.json')}"
                            if srcs else ("not_fetched: " + str((series_info or {}).get("error", ""))
                                         if series_info else ""))),
        }
    else:
        swing["series"] = {}
    if not swing["series"].get("settlement_sources"):
        swing["series_note"] = "blank_settlement_sources"
    swing["title_source"] = "api:markets" if market else "blank_no_market_record"
    swing["resolution_label"] = ("YES" if swing.get("result") == "yes" else
                                 "NO" if swing.get("result") == "no" else "")


ENDPOINTS_TO_PROBE = [
    ("GET", "/exchange/status", "no key required",
     "https://docs.kalshi.com/getting_started/quick_start_market_data"),
    ("GET", "/markets?limit=1&status=open", "open market page",
     "https://docs.kalshi.com/api-reference/market/get-markets"),
    ("GET", "/markets/KXDEMOFUTHOURLY-26NOV20H12-UP", "single market by ticker "
     "(ticker from the 2026-11-20 verified swing row)",
     "https://docs.kalshi.com/api-reference/market/get-market"),
    ("GET", "/markets?tickers=KXDEMOFUTHOURLY-26NOV20H12-UP&status=settled",
     "settled lookup used for resolution tracking",
     "https://docs.kalshi.com/api-reference/market/get-markets"),
    ("GET", "/events?event_tickers=KXDEMOFUTHOURLY-26NOV20H12&with_nested_markets=false",
     "event lookup by ticker — used only to test whether the demo deployment honours the "
     "event_tickers filter (irregularity F-cat-05)",
     "https://docs.kalshi.com/api-reference/market/get-events"),
    ("GET", "/series/KXDEMOFUTHOURLY?include_volume=true", "series record (settlement sources)",
     "https://docs.kalshi.com/api-reference/market/get-series"),
    ("GET", "/markets/KXDEMOFUTHOURLY-26NOV20H12-UP/orderbook?depth=8",
     "liquidity ladder used for the contracts-per-price panel",
     "https://docs.kalshi.com/api-reference/market/get-market-orderbook"),
]


def probe_endpoints(http: Http, root: str, out_path: str, log) -> dict:
    """Record the real HTTP result of every endpoint this layer depends on.

    Published on the site so a reviewer sees which official requests succeed from the
    runtime that actually serves the data (the Actions runner), instead of taking the
    build sandbox's word for it. No response body is stored — only status + field
    names, so the file stays small and free of market values.
    """
    rows = []
    for method, path, purpose, doc in ENDPOINTS_TO_PROBE:
        url = root + path
        rec = {"method": method, "url": url, "purpose": purpose, "doc": doc,
               "http_status": None, "ok": False, "top_level_fields": [], "error": "",
               "checked_at": now_iso()}
        try:
            data = http.get(url)
            rec["http_status"] = 200
            rec["ok"] = True
            if isinstance(data, dict):
                rec["top_level_fields"] = sorted(data.keys())[:14]
                for key in ("markets", "events", "series"):
                    val = data.get(key)
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        rec["item_count"] = len(val)
                        rec["item_fields"] = sorted(val[0].keys())[:40]
                        if key == "events":
                            want = "KXDEMOFUTHOURLY-26NOV20H12"
                            rec["filter_honoured"] = any(
                                (e.get("event_ticker") == want) for e in val)
        except Exception as exc:                     # noqa: BLE001
            msg = str(exc)
            m = re.search(r"HTTP (\d{3})", msg)
            if m:
                rec["http_status"] = int(m.group(1))
            rec["error"] = msg[:240]
            log(f"probe {path}: {rec['error']}")
        rows.append(rec)
    payload = {"probed_at": now_iso(), "api_root": root, "endpoints": rows,
               "note": ("status = what the runner observed on this run; blank/unverified "
                        "rows stay blank on the site, they are never back-filled")}
    write_json(out_path, payload)
    return payload


# ------------------------------------------------------------------ strategies
STRATEGY_MIN_N = int(os.environ.get("CATALYST_MIN_N", "30"))
STRATEGY_DOCS = "https://docs.kalshi.com/getting_started/market_settlement"


def strategy_study(swings: list[dict], tape: list[dict]) -> dict:
    """Score two automated paper strategies on the published swings.

    Only values the exchange actually published are used: the post-swing last price as
    the entry, `settlement_value_dollars` as the hold-to-resolution exit (winning
    contracts pay $1, losing contracts pay $0 — Market Settlement doc), and the next
    recorded sample for the flat-exit variant. Simulated: no order was sent, no fill,
    slippage or fee is modelled (the public API returns none for a hypothetical order),
    so every figure is labelled gross. A category with fewer than STRATEGY_MIN_N
    observations is published but marked NOT evaluable — no expectancy claim is made on
    a two-trade sample.
    """
    by_ticker_samples: dict = defaultdict(list)
    for row in tape:
        by_ticker_samples[row["ticker"]].append(row)
    for rows in by_ticker_samples.values():
        rows.sort(key=lambda r: r["ts"])

    trades: list[dict] = []
    skipped = {"s1_hold_to_resolution": 0, "s2_flat_at_next_sample": 0}
    for s in swings:
        entry = parse_dollars((s.get("to") or {}).get("last_price_dollars"))
        ts_to = (s.get("to") or {}).get("ts") or ""
        if entry is None:
            continue
        rows = by_ticker_samples.get(s["ticker"], [])
        later = [r for r in rows if r["ts"] > ts_to]
        settle = parse_dollars(s.get("settlement_value_dollars"))
        base = {
            "ticker": s["ticker"], "topic": s.get("topic") or "other",
            "direction": s.get("direction") or "?",
            "swing_id": s.get("id") or "",
            "entry_ts": ts_to, "entry_dollars": f"{entry:.4f}",
            "market_api_url": (s.get("links") or {}).get("market_api_url") or "",
        }
        if s.get("resolved") and settle is None:
            skipped["s1_hold_to_resolution"] += 1   # no payout in the source record
        if s.get("resolved") and settle is not None:
            trades.append({**base, "strategy": "s1_hold_to_resolution",
                           "exit_ts": s.get("settlement_ts") or "",
                           "exit_dollars": f"{settle:.4f}",
                           "exit_basis": "settlement_value_dollars from the API",
                           "pnl_dollars": f"{settle - entry:.4f}",
                           "side": "YES"})
        if later:
            nxt = parse_dollars(later[0].get("last_price_dollars"))
            if nxt is None:
                skipped["s2_flat_at_next_sample"] += 1
            if nxt is not None:
                trades.append({**base, "strategy": "s2_flat_at_next_sample",
                               "exit_ts": later[0]["ts"], "exit_dollars": f"{nxt:.4f}",
                               "exit_basis": "next recorded sample of the same market",
                               "pnl_dollars": f"{nxt - entry:.4f}", "side": "YES"})

    def aggregate(rows: list[dict]) -> list[dict]:
        buckets: dict = defaultdict(list)
        for t in rows:
            buckets[(t["strategy"], f"{t['topic']}/{t['direction']}-follow")].append(t)
        out = []
        for (strategy, category), items in sorted(buckets.items()):
            pnls = [parse_dollars(t["pnl_dollars"]) for t in items]
            total = sum(pnls, Decimal("0"))
            out.append({
                "strategy": strategy, "category": category, "n": len(items),
                "wins": sum(1 for p in pnls if p > 0),
                "losses": sum(1 for p in pnls if p < 0),
                "pushes": sum(1 for p in pnls if p == 0),
                "net_pnl_dollars_per_contract": f"{total:.4f}",
                "mean_pnl_dollars_per_contract": f"{(total / len(items)):.4f}",
                "evaluable": len(items) >= STRATEGY_MIN_N,
                "markets": [{"ticker": t["ticker"], "pnl_dollars": t["pnl_dollars"],
                             "market_api_url": t["market_api_url"]} for t in items[:8]],
            })
        return out

    return {
        "generated_at": now_iso(),
        "threshold_dollars": f"{SWING_THRESHOLD_DOLLARS:.2f}",
        "skipped_observations": skipped,
        "skipped_note": ("s1 rows are skipped when the source record carries no "
                         "settlement_value_dollars (the payout is NOT derived from the "
                         "yes/no result here — the scheduled run reads it from the market "
                         "record itself); s2 rows are skipped when no later sample exists."),
        "min_n_for_a_claim": STRATEGY_MIN_N,
        "strategies": [
            {"id": "s1_hold_to_resolution",
             "name": "Momentum follow, hold to resolution",
             "entry_rule": "buy YES at the market's last traded price on the sample that "
                           "triggered the >= $0.10 alert",
             "exit_rule": "hold until the API reports settlement_value_dollars "
                          "($1.00 if it resolves yes, $0.00 if no)",
             "docs": STRATEGY_DOCS},
            {"id": "s2_flat_at_next_sample",
             "name": "Momentum follow, flat at the next sample",
             "entry_rule": "same entry as s1",
             "exit_rule": "exit at the next recorded sample of the same market (the tape's "
                          "sampling interval, not a real order book)",
             "docs": STRATEGY_DOCS},
        ],
        "results": aggregate(trades),
        "trade_count": len(trades),
        "disclaimer": ("Simulated trades on demo prices. Gross of fees, spread and slippage: the "
                        "public API publishes no fee estimate for a hypothetical order, so none is "
                        "assumed. Entry is a trade print, not a book quote — a real order would "
                        "cross the spread. Not evidence of profitability."),
    }


# --------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Kalshi demo swing + catalyst scan")
    ap.add_argument("--root", default=os.environ.get("KALSHI_API_ROOT", DEMO_REST_ROOT))
    ap.add_argument("--offline", action="store_true", help="no network calls at all")
    ap.add_argument("--probe-feeds", action="store_true", help="only check the feed allowlist")
    ap.add_argument("--probe-endpoints", action="store_true",
                    help="only record HTTP status for the official endpoints used here")
    ap.add_argument("--lookback-hours", type=float, default=float(
        os.environ.get("CATALYST_LOOKBACK_HOURS", DEFAULT_LOOKBACK_HOURS)))
    ap.add_argument("--window-pre", type=int, default=int(
        os.environ.get("CATALYST_WINDOW_PRE_MIN", DEFAULT_WINDOW_PRE_MIN)))
    ap.add_argument("--window-post", type=int, default=int(
        os.environ.get("CATALYST_WINDOW_POST_MIN", DEFAULT_WINDOW_POST_MIN)))
    ap.add_argument("--max-watch", type=int, default=int(os.environ.get("CATALYST_MAX_WATCH", "120")))
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--repo", default=REPO, help="repository root (tape + snapshot lookup)")
    ap.add_argument("--feeds", default=feeds_path_default(), help="feed allowlist path")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    log = (lambda m: None) if args.quiet else (lambda m: print(f"[scan] {m}", file=sys.stderr))
    link_root_note = ""
    now = datetime.now(timezone.utc)
    data_dir = args.data_dir
    os.makedirs(data_dir, exist_ok=True)
    repo = os.path.abspath(args.repo)
    tape_paths = [os.path.join(repo, "data", "history", "prices.jsonl"),
                  os.path.join(data_dir, "tape.jsonl")]
    feeds_path = os.path.abspath(args.feeds)
    out_swings = os.path.join(data_dir, "swings.json")
    out_status = os.path.join(data_dir, "status.json")
    out_health = os.path.join(data_dir, "feed_health.json")
    out_endpoints = os.path.join(data_dir, "endpoints.json")

    http = Http(timeout=float(os.environ.get("CATALYST_TIMEOUT", "20")), log=log)
    mode = "offline"
    if not args.offline:
        # Reachability probe against the recommended demo root (exchange status needs
        # no key: https://docs.kalshi.com/getting_started/quick_start_market_data.md).
        try:
            http.get(f"{args.root}/exchange/status")
            mode = "live"
        except Exception as exc:                    # noqa: BLE001
            alt = DEMO_REST_ROOT_ALT
            try:
                http.get(f"{alt}/exchange/status")
                args.root, mode = alt, "live(alt-root)"
                log(f"recommended root unreachable; using also-supported demo root {alt}")
            except Exception:                        # noqa: BLE001
                mode = "offline(no-network)"
                log(f"demo API unreachable ({exc}); running tape-only")

    if mode != "offline":
        prior_ep = read_json(out_endpoints, {}) or {}
        age_ok = parse_ts(prior_ep.get("probed_at")) if prior_ep else None
        if args.probe_endpoints or age_ok is None or (now - age_ok) > timedelta(hours=6):
            probe_endpoints(http, args.root, out_endpoints, log)

    feeds_cfg = load_feeds(feeds_path)
    if args.probe_feeds:
        items, health = (fetch_feeds(http, feeds_cfg, log) if mode != "offline"
                         else ([], [{"name": f.get("name", ""), "url": f.get("url", ""),
                                     "topics": f.get("topics") or [], "items_parsed": 0,
                                     "http_status": None, "ok": False,
                                     "error": "skipped_offline",
                                     "checked_at": now_iso()} for f in feeds_cfg]))
        write_json(out_health, {"checked_at": now_iso(), "mode": mode, "feeds": health,
                               "docs": DOCS})
        ok = sum(1 for f in health if f["ok"])
        print(json.dumps({"feeds_ok": ok, "feeds_total": len(health), "mode": mode}))
        return 0

    if args.probe_endpoints:
        if mode == "offline":
            write_json(out_endpoints, {
                "probed_at": now_iso(), "api_root": args.root, "endpoints": [],
                "note": ("skipped: this runner has no egress to the demo API "
                         "(the build sandbox allowlists github.com / npmjs / pypi only). "
                         "The scheduled GitHub Actions run rewrites this file with real "
                         "HTTP statuses."),
            })
            print(json.dumps({"mode": mode, "endpoints_probed": 0,
                              "note": "skipped_offline"}))
            return 0
        payload = probe_endpoints(http, args.root, out_endpoints, log)
        print(json.dumps({"mode": mode, "endpoints_probed": len(payload["endpoints"]),
                          "ok": sum(1 for e in payload["endpoints"] if e["ok"])}))
        return 0

    # Published links must always point at a real, official host. A test or a
    # non-default --root may not exist publicly, so in offline mode links are
    # rewritten to the recommended demo root and the substitution is disclosed.
    link_root = args.root
    if mode == "offline" and args.root not in (DEMO_REST_ROOT, DEMO_REST_ROOT_ALT):
        link_root = DEMO_REST_ROOT
        link_root_note = (f"links rewritten from --root {args.root} to the official demo root "
                          "(offline run: never publish a host that was not actually queried)")
    tape = load_tape(tape_paths, repo)
    prior = read_json(out_swings, {"swings": []}) or {"swings": []}
    prior_swings = prior.get("swings") or []
    known_ids = {s.get("id") for s in prior_swings}
    watch_state = read_json(os.path.join(data_dir, "watch_state.json"), {}) or {}
    tracked = watch_state.get("markets") or {}

    new_samples: list[dict] = []
    markets_by_ticker: dict[str, dict] = {}
    poll_errors: list[str] = []

    if mode != "offline":
        watch = set()
        top = read_json(os.path.join(repo, "data", "latest", "top_events.json"), {}) or {}
        for topic, events in (top.get("by_topic") or {}).items():
            for ev in events or []:
                for m in (ev.get("top_markets") or []):
                    if m.get("ticker"):
                        watch.add(m["ticker"])
        for row in tape[-3000:]:
            if row.get("ticker"):
                watch.add(row["ticker"])
        watch = {t for t in watch if not (tracked.get(t) or {}).get("resolved")}
        watch_list = sorted(watch)[:args.max_watch]
        log(f"watchlist: {len(watch_list)} unresolved markets")
        markets, missing = poll_markets(http, args.root, watch_list, log)
        for m in markets:
            t = m.get("ticker")
            price, field = market_price(m)
            if not t or price is None:
                continue
            markets_by_ticker[t] = m
            new_samples.append({
                "ticker": t, "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last_price_dollars": f"{price:.4f}",
                "event_ticker": m.get("event_ticker") or "",
                "series_ticker": m.get("series_ticker") or "",
                "topic": (tracked.get(t) or {}).get("topic", ""),
                "volume_fp": m.get("volume_fp") or "",
                "open_interest_fp": m.get("open_interest_fp") or "",
                "yes_bid_dollars": m.get("yes_bid_dollars") or "",
                "yes_ask_dollars": m.get("yes_ask_dollars") or "",
                "price_field": field,
            })
            tracked.setdefault(t, {})["topic"] = tracked.get(t, {}).get(
                "topic", "") or classify(m)
        if missing:
            settled = poll_settled(http, args.root, missing[:80], log)
            for m in settled:
                t = m.get("ticker")
                if not t:
                    continue
                markets_by_ticker[t] = m
                tracked.setdefault(t, {})
                tracked[t].update({"resolved": True, "result": m.get("result") or "",
                                   "settlement_ts": m.get("settlement_ts") or "",
                                   "settlement_value_dollars": m.get(
                                       "settlement_value_dollars") or "",
                                   "source_url": m.get("_single_source_url") or "",
                                   "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
                price, field = market_price(m)
                if price is not None:
                    new_samples.append({
                        "ticker": t, "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "last_price_dollars": f"{price:.4f}",
                        "event_ticker": m.get("event_ticker") or "",
                        "series_ticker": m.get("series_ticker") or "",
                        "topic": tracked[t].get("topic", ""),
                        "volume_fp": m.get("volume_fp") or "",
                        "open_interest_fp": m.get("open_interest_fp") or "",
                        "yes_bid_dollars": "", "yes_ask_dollars": "",
                        "price_field": field,
                    })
            poll_errors.extend(f"missing_from_open_book:{len(missing)}")
        written = append_tape(os.path.join(data_dir, "tape.jsonl"), new_samples)
        log(f"tape: +{written} samples from {len(markets)} live market records")
        tape = load_tape(tape_paths, repo)

    swings = detect_swings(tape, SWING_THRESHOLD_DOLLARS, args.lookback_hours, now, known_ids)
    log(f"swings >= ${SWING_THRESHOLD_DOLLARS}: {len(swings)} new")

    feed_items: list[dict] = []
    feed_health: list[dict] = []
    if mode != "offline" and feeds_cfg:
        feed_items, feed_health = fetch_feeds(http, feeds_cfg, log)
        write_json(out_health, {"checked_at": now_iso(), "mode": mode,
                                "feeds": feed_health, "docs": DOCS})

    series_cache: dict[str, dict] = {}
    need_snap = any(s["ticker"] not in markets_by_ticker for s in swings)
    snap = (snapshot_index(repo) if need_snap
            else {"markets": {}, "events": {}, "market_to_event": {}, "files": []})
    snap_markets, snap_events = snap["markets"], snap["events"]
    snap_m2e = snap["market_to_event"]
    for s in swings:
        mkt = markets_by_ticker.get(s["ticker"])
        snapshot_used = False
        if mkt is None and snap_markets:
            mkt = snap_markets.get(s["ticker"])
            snapshot_used = mkt is not None
        ev_ticker = ((mkt or {}).get("event_ticker") or s.get("event_ticker")
                     or snap_m2e.get(s["ticker"]) or "")
        ev_info = snap_events.get(ev_ticker) or {}
        if not s.get("topic") and (mkt or {}).get("topic"):
            s["topic"] = mkt["topic"]
        if not s.get("topic") and ev_info.get("topic"):
            s["topic"] = ev_info["topic"]
        if mkt is not None:
            s["record_source"] = {
                "live": "GET /markets?tickers= (demo API, this run)",
                "snapshot": f"committed demo-API snapshot {mkt.get('_snapshot_file', '')} "
                            f"(retrieved {mkt.get('_snapshot_retrieved_at') or 'n/a'})",
            }.get(mkt.get("_source_kind", "live"), "demo API record (this run)")
        st = (s.get("series_ticker") or (mkt or {}).get("series_ticker")
              or ev_info.get("series_ticker") or "")
        st = st or derive_series(ev_ticker or s.get("event_ticker", ""))
        if st and st not in series_cache:
            series_cache[st] = (fetch_series(http, args.root, st, log) if mode != "offline"
                                else {"series_ticker": st, "title": "", "category": "",
                                      "frequency": "", "settlement_sources": [],
                                      "contract_terms_url": "",
                                      "source_url": f"{args.root}/series/{st}",
                                      "error": "not_fetched_offline"})
        enrich(s, mkt, series_cache.get(st), link_root, ev_info)
        if mkt is None:
            s["record_source"] = "blank_no_market_record (not in live poll or committed snapshots)"
            s["links"]["market_api_url"] = market_url(link_root, s["ticker"])
        topic = s.get("topic") or classify(mkt or {})
        s["topic"] = topic or "other"
        pool = [it for it in feed_items
                if not it.get("topics") or topic in it["topics"]]
        text = " ".join([s.get("title", ""), st, s.get("event_ticker", "")])
        if mode == "offline" or not feed_items:
            s["catalysts"] = []
            s["catalyst_match"] = {"candidates": [], "items_in_window": 0,
                                   "match_status": ("feeds_not_polled_offline"
                                                    if mode == "offline"
                                                    else "no_feed_items_available"),
                                   "note": ("The build sandbox has no egress to news hosts; "
                                            "the scheduled CI run performs feed matching. "
                                            "Nothing is inferred here.")}
        else:
            t0 = parse_ts(s["from"]["ts"]) or now
            t1 = parse_ts(s["to"]["ts"]) or now
            res = match_catalyst_items(pool, text, t0, t1, args.window_pre,
                                       args.window_post, MAX_CATALYSTS_PER_SWING)
            s["catalysts"] = res.pop("candidates")
            s["catalyst_match"] = res
        s["threshold_dollars"] = f"{SWING_THRESHOLD_DOLLARS:.4f}"

    merged = swings + prior_swings
    merged.sort(key=lambda x: x.get("to", {}).get("ts", ""), reverse=True)
    merged = merged[:MAX_SWINGS_KEPT]
    write_json(out_swings, {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_root": args.root,
        "threshold_dollars": f"{SWING_THRESHOLD_DOLLARS:.2f}",
        "threshold_note": (">= $0.10 (10 cents) per contract between consecutive samples, "
                          "either direction; exact decimal arithmetic."),
        "window_minutes": {"pre": args.window_pre, "post": args.window_post},
        "mode": mode,
        "swings": merged,
        "link_root_note": link_root_note,
        "docs": DOCS,
        "disclaimer": ("Catalyst links are CANDIDATE explanations: a feed item inside the "
                       "swing window that shares keywords with the market title. Correlation "
                       "only — the API exposes no news field and nothing here proves cause. "
                       "Demo prices are simulated (see docs demo_env)."),
    })

    for s in swings:
        if s.get("resolved"):
            tracked.setdefault(s["ticker"], {})
            tracked[s["ticker"]].update({"resolved": True, "topic": s.get("topic", ""),
                                         "result": s.get("result", ""),
                                         "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
        else:
            tracked.setdefault(s["ticker"], {})
            tracked[s["ticker"]].setdefault("topic", s.get("topic", ""))
            tracked[s["ticker"]].setdefault("resolved", False)
    for t, v in tracked.items():
        if v.get("resolved"):
            v["tracking"] = "stopped_resolved"
    watch_state["markets"] = dict(list(tracked.items())[:2000])
    watch_state["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    watch_state["policy"] = ("A market is polled until the API reports it settled/finalized "
                             "with a result; then tracking stops and the yes/no outcome is kept.")
    write_json(os.path.join(data_dir, "watch_state.json"), watch_state)

    strat = strategy_study(merged, tape)
    write_json(os.path.join(data_dir, "strategies.json"), strat)

    matched = sum(1 for s in merged if s.get("catalysts"))
    write_json(out_status, {
        "status": "ok",
        "finished_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "api_root": args.root,
        "requests": http.requests,
        "request_errors": http.errors,
        "poll_errors": poll_errors,
        "tape_rows": len(tape),
        "tape_new_samples": len(new_samples),
        "swings_total": len(merged),
        "swings_new": len(swings),
        "swings_with_catalyst_links": matched,
        "feeds_ok": sum(1 for f in feed_health if f.get("ok")),
        "feeds_total": len(feed_health),
        "tracked_markets": len(tracked),
        "tracked_resolved": sum(1 for v in tracked.values() if v.get("resolved")),
        "simulated_trades_scored": strat["trade_count"],
        "strategy_categories_evaluable": sum(1 for r in strat["results"] if r["evaluable"]),
        "strategy_categories_total": len(strat["results"]),
        "docs": DOCS,
    })
    print(json.dumps({"mode": mode, "swings_new": len(swings), "swings_total": len(merged),
                      "with_links": matched, "simulated_trades": strat["trade_count"],
                      "strategy_categories": len(strat["results"]),
                      "requests": http.requests, "errors": http.errors}))
    return 0


def classify(market: dict) -> str:
    """Topic tag for the five brief topics — same classification order as the repo
    collector (series ticker, then API category/tags, then title keywords)."""
    series = (market.get("series_ticker") or "").upper()
    title = (market.get("title") or "").lower()
    tags = " ".join(market.get("tags") or []).lower() if isinstance(
        market.get("tags"), list) else ""
    category = (market.get("category") or "").lower()
    if re.search(r"GAS|GASOLINE|FUEL", series) or "gas price" in title:
        return "gas"
    if re.search(r"PGA|GOLF|MAJOR|RYDER|SOLHEIM", series) or category == "sports" and "golf" in (title + tags):
        return "golf"
    if re.search(r"BTC|ETH|XRP|SOL|DOGE|CRYPT|COIN|DOGEO", series) or category == "crypto":
        return "crypto"
    if re.search(r"PRES|SENATE|HOUSE|GOV|MAYOR|ELECTION|PRIMARY|NOM|PARL|SEJM|NATO", series) \
            or category == "elections":
        return "elections"
    if category == "culture" or re.search(r"OSCAR|GRAMMY|ALBUM|MOVIE|BOX OFFICE|SIMPSON|HARRY",
                                          series + title):
        return "culture"
    if "election" in category or any(w in title for w in ("election", "senate", "mayor",
                                                           "president")):
        return "elections"
    if any(w in title for w in ("gas", "gasoline", "fuel")):
        return "gas"
    if any(w in title for w in ("bitcoin", "ethereum", "btc", "eth", "solana", "crypto")):
        return "crypto"
    if any(w in title for w in ("golf", "pga", "masters", "open championship", "ryder")):
        return "golf"
    return "other"


if __name__ == "__main__":
    raise SystemExit(main())
