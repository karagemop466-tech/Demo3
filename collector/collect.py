"""Collect + organize Kalshi demo market data for the tracked topics.

Topic scope (per project brief): gas prices, elections, culture, crypto, golf.
Ranking: estimated dollar volume per live event (see `estimate_event_dollars` — an
approximation, clearly labeled; Kalshi's public market object exposes contract volume
(`volume_fp`) and last price (`last_price_dollars`), not a dollar-volume field).

All endpoint shapes were verified against the official docs and live demo responses on
2026-11-20 — see docs/API_VERIFICATION.md for the per-field evidence table.

Design note (v2): one paginated pass over /markets?status=open aggregates per-event
volumes directly, replacing per-event nested-market fetches (the demo exchange has
6,000+ open events — per-event calls blew the request budget and triggered HTTP 429).

Outputs (committed under data/):
  data/meta.json            run log: times, counts, statuses, warnings
  data/events.json          tracked live events per topic, ranked, with market snapshots
  data/orderbooks/{t}.json  full bid ladders (yes/no) for the top markets
  data/history/{t}.json     candlestick series: 1m (24h), 60m (30d), 1440m (180d)
  data/resolutions.json     settled markets: per tracked event + per seed series
  data/tracked.json         persistent tracking state (events followed until resolution)
  data/cors_test.json       CORS probe result (browser live-fetch feasibility)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kalshi_api import DEMO_REST_ROOT, KalshiClient, KalshiError, utc_now_iso  # noqa: E402

DATA_DIR = os.environ.get(
    "KALSHI_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
MAX_ORDERBOOKS = 12          # top markets (by est dollar volume) that get ladder + candles
MAX_EVENTS_PER_TOPIC = 15
MAX_EVENTS_OVERALL = 40
MARKETS_PER_EVENT_CAP = 30   # keep the largest markets per event in the payload
TRACKED_CAP = 150
RESOLUTION_LOOKBACK_DAYS = 90
CANDLE_RANGES = {1: (1, 24 * 60), 60: (60, 30 * 24 * 60), 1440: (1440, 180 * 24 * 60)}
EVENT_PAGES = 45             # x200 = 9,000 open events incl. nested markets

# Seed series with OFFICIAL ticker evidence for the settled-resolution sweep
# (Kalshi fee schedule https://kalshi.com/docs/kalshi-fee-schedule.pdf:
#  KXAAAGASM "US gas price"; KXPGATOUR "PGA Tour"; KXPGARYDER "Ryder Cup";
#  KXPGASOLHEIM "Solheim Cup"). Series observed live in tracked.json are swept too,
# so crypto/culture/election resolutions are covered by discovered series instead of
# guessed tickers.
SERIES_SWEEP_SEEDS = {
    "gas": ("KXAAAGASM",),
    "golf": ("KXPGATOUR", "KXPGARYDER", "KXPGASOLHEIM"),
}

# --------------------------------------------------------------------------
# Topic rules. Each event is matched by (series ticker prefix, exact category,
# title/series keyword regex). Verified category strings on the demo exchange are
# logged to data/meta.json on every run so the rules can be audited.
# Keywords were tuned against the live demo corpus (e.g. "primary" alone matched
# "primary energy consumption" -> now "primary election").
# --------------------------------------------------------------------------
TOPIC_RULES = {
    "gas": {
        "label": "Gas prices",
        "series_prefixes": ("KXGAS", "KXAAAGAS"),
        "categories": ("gas",),
        "keywords": re.compile(r"\bgas price|\bgas prices|price of gas|regular gas", re.I),
    },
    "elections": {
        "label": "Elections",
        "series_prefixes": tuple(),
        "categories": ("election",),
        "keywords": re.compile(r"\belection|\belectoral|governor|senate seat|house seat|"
                               r"presidential|primary election|nominee|mayoral|mayor of|referendum", re.I),
    },
    "culture": {
        "label": "Culture",
        "series_prefixes": tuple(),
        "categories": ("culture", "entertainment"),
        "keywords": re.compile(r"oscar|academy award|grammy|emmy|golden globe|box office|"
                               r"spotify|billboard|met gala|eurovision|miss universe|"
                               r"nobel prize|rotten tomatoes|time person of the year|"
                               r"game of the year|album|super bowl halftime|severance|"
                               r"stranger things|knives out|squid game|taylor swift|mrbeast", re.I),
    },
    "crypto": {
        "label": "Crypto",
        "series_prefixes": ("KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE", "KXCRYPTO"),
        "categories": ("crypto",),
        "keywords": re.compile(r"\bbitcoin\b|\bbtc\b|\bethereum\b|\bether\b|\bsolana\b|"
                               r"\bxrp\b|\bdogecoin\b|\bdoge\b|\bcrypto\b|\bstablecoin\b|"
                               r"\btether\b|\busdc\b|\bblockchain\b", re.I),
    },
    "golf": {
        "label": "Golf",
        "series_prefixes": ("KXPGATOUR", "KXPGARYDER", "KXPGASOLHEIM", "KXGOLF", "KXLPGA",
                            "KXPGA", "KXDPWORLD"),
        "categories": ("golf",),
        "keywords": re.compile(r"\bgolf\b|\bpga\b|\bryder cup\b|\bsolheim\b|"
                               r"\bmasters\b|fedex cup|\blpga\b|open championship", re.I),
    },
}


def classify_event(event: dict, category_lower: str) -> str | None:
    """Return the topic key for an event, or None if it is out of scope."""
    series = (event.get("series_ticker") or "").upper()
    title = " ".join(filter(None, [event.get("title") or "", event.get("sub_title") or ""]))
    for topic, rules in TOPIC_RULES.items():
        if any(series.startswith(p) for p in rules["series_prefixes"]):
            return topic
        if any(cat in category_lower for cat in rules["categories"]):
            return topic
        if rules["keywords"].search(title):
            return topic
    return None


def fp(value) -> float | None:
    """Parse a fixed-point string field like '100.00' -> 100.0 (None if absent/garbage)."""
    try:
        if value in (None, "", "null"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_market_status(status: str | None) -> str:
    s = (status or "").lower()
    if s in ("active", "open", "finalized-active"):
        return "open"
    if s in ("settled", "finalized"):
        return "settled"
    if s in ("closed", "halted"):
        return "closed"
    return s or "unknown"


def estimate_event_dollars(markets: list[dict]) -> tuple[float, float, float]:
    """Estimated notional dollars traded per event.

    Kalshi's public market object exposes contract volume (`volume_fp`) and last trade
    price (`last_price_dollars`) but not dollar volume; dollar volume here is the
    standard approximation sum(volume * last_price). Labeled 'estimated' everywhere.
    Returns (total, last24h, open_interest).
    """
    total = oi = vol24 = 0.0
    for m in markets:
        price = fp(m.get("last_price_dollars")) or 0.0
        vol = fp(m.get("volume_fp")) or 0.0
        vol24 += (fp(m.get("volume_24h_fp")) or 0.0)
        oi += (fp(m.get("open_interest_fp")) or 0.0)
        total += vol * price
    return round(total, 2), round(vol24, 2), round(oi, 2)


def trim_market(m: dict) -> dict:
    keep = ("ticker", "event_ticker", "title", "yes_sub_title", "no_sub_title",
            "market_type", "status", "result", "can_close_early", "strike_type",
            "rules_primary", "custom_strike")
    out = {k: m.get(k) for k in keep if m.get(k) not in (None, "")}
    for k_src, k_dst in (("yes_bid_dollars", "yes_bid"), ("yes_ask_dollars", "yes_ask"),
                         ("no_bid_dollars", "no_bid"), ("no_ask_dollars", "no_ask"),
                         ("last_price_dollars", "last_price"),
                         ("previous_yes_bid_dollars", "prev_yes_bid"),
                         ("previous_yes_ask_dollars", "prev_yes_ask")):
        v = fp(m.get(k_src))
        if v is not None:
            out[k_dst] = v
    for k_src, k_dst in (("volume_fp", "volume"), ("volume_24h_fp", "volume_24h"),
                         ("open_interest_fp", "open_interest"),
                         ("yes_bid_size_fp", "yes_bid_size"),
                         ("yes_ask_size_fp", "yes_ask_size")):
        v = fp(m.get(k_src))
        if v is not None:
            out[k_dst] = v
    for k in ("open_time", "close_time", "game_start_time"):
        if m.get(k):
            out[k] = m[k]
    for k in ("expected_expiration_time", "latest_expiration_time"):
        if m.get(k):
            out["exp_close" if k.startswith("expected") else "hard_close"] = m[k]
    return out


def trim_event(event: dict) -> dict:
    return {
        "event_ticker": event.get("event_ticker"),
        "series_ticker": event.get("series_ticker"),
        "title": event.get("title"),
        "sub_title": event.get("sub_title"),
        "category": event.get("category"),
        "mutually_exclusive": event.get("mutually_exclusive"),
        "last_updated_ts": event.get("last_updated_ts"),
        "settlement_sources": [
            {"name": s.get("name"), "url": s.get("url")}
            for s in (event.get("settlement_sources") or [])[:6]
        ],
    }


class Collector:
    def __init__(self, api_root: str | None = None):
        self.warnings: list[str] = []
        self.category_counts: dict[str, int] = defaultdict(int)
        self.client = KalshiClient(
            root=api_root or os.environ.get("KALSHI_API_ROOT", DEMO_REST_ROOT),
            min_interval=0.3, logger=self.warn)
        self.meta = {
            "generated_at": utc_now_iso(),
            "api_root": api_root or os.environ.get("KALSHI_API_ROOT", DEMO_REST_ROOT),
            "api_root_alt_supported": "https://demo-api.kalshi.co/trade-api/v2",
            "topics": {k: v["label"] for k, v in TOPIC_RULES.items()},
            "ranking_method": "estimated dollar volume = sum(market volume_fp * last_price_dollars); "
                              "approximation - Kalshi public market object has no dollar-volume field",
            "sources": [
                "https://docs.kalshi.com/getting_started/api_environments.md",
                "https://docs.kalshi.com/getting_started/quick_start_market_data.md",
                "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
            ],
        }

    def warn(self, msg: str) -> None:
        line = f"[{utc_now_iso()}] {msg}"
        print(line, flush=True)
        self.warnings.append(msg)

    # ------------------------------------------------------------ file output
    def out_path(self, rel: str) -> str:
        path = os.path.normpath(os.path.join(DATA_DIR, rel))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def write_json(self, rel: str, payload) -> None:
        path = self.out_path(rel)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, path)
        print(f"wrote {rel} ({os.path.getsize(path)} bytes)", flush=True)

    def read_json(self, rel: str, default):
        path = os.path.join(DATA_DIR, rel)
        if not os.path.exists(path):
            return default
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            self.warn(f"could not read {rel}: {exc}")
            return default

    # ---------------------------------------------------------------- stages
    def probe_cors(self) -> None:
        """Record whether the demo API sends CORS headers to a browser origin.

        This decides whether the static site can fetch the API directly from the
        visitor's browser or must rely on committed snapshots + WebSocket.
        """
        url = self.client.root + "/exchange/status"
        req = urllib.request.Request(url, headers={
            "Origin": "https://karagemop466-tech.github.io",
            "Accept": "application/json",
        })
        result = {"tested_url": url, "tested_at": utc_now_iso(),
                  "origin_sent": "https://karagemop466-tech.github.io"}
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result["http_status"] = resp.status
                headers = {k.lower(): v for k, v in resp.headers.items()}
                result["acao"] = headers.get("access-control-allow-origin")
                result["acam"] = headers.get("access-control-allow-methods")
                result["acah"] = headers.get("access-control-allow-headers")
        except urllib.error.HTTPError as exc:
            result["http_status"] = exc.code
        except Exception as exc:  # network issue - record, don't fail the run
            result["http_status"] = None
            result["error"] = str(exc)
        result["browser_direct_fetch_allowed"] = (
            result.get("acao") in ("*", "https://karagemop466-tech.github.io", "null")
            and result.get("http_status") == 200
        )
        self.write_json("cors_test.json", result)

    def load_events_nested(self) -> dict[str, dict]:
        """One paginated pass over /events?status=open&with_nested_markets=true.

        /markets?status=open is ordered newest-first on the demo exchange and is
        continuously flooded by newly-created synthetic MVE (cross-category) markets,
        which pushed established events beyond any fixed page window (observed live
        2026-11-20: 9,000 newest markets covered only 445 events). The /events listing
        is ordered stably, so paginating it WITH nested markets gives complete,
        stable coverage of every open event and its markets in ~EVENT_PAGES requests.
        """
        events: dict[str, dict] = {}
        market_total = 0
        for e in self.client.paginate("/events", {"status": "open",
                                                  "with_nested_markets": "true"},
                                      "events", max_pages=EVENT_PAGES):
            ticker = e.get("event_ticker")
            if not ticker:
                continue
            # guard against duplicate deliveries across pages
            markets = {m.get("ticker"): m for m in (e.get("markets") or []) if m.get("ticker")}
            e = dict(e, markets=list(markets.values()))
            events[ticker] = e
            market_total += len(markets)
        self.warn(f"loaded {len(events)} open events / {market_total} nested markets "
                  "via /events?status=open&with_nested_markets=true")
        return events

    def collect(self) -> None:
        print(f"=== collect start {utc_now_iso()} ===", flush=True)
        self.probe_cors()

        events_nested = self.load_events_nested()

        # Stage 1: classify + estimate dollars from nested markets.
        staged: list[tuple[str, dict, list, float, float, float]] = []
        for ticker, e in events_nested.items():
            markets = e.get("markets") or []
            cat = (e.get("category") or "").lower()
            self.category_counts[e.get("category") or "(none)"] += 1
            topic = classify_event(e, cat)
            if not topic:
                continue
            if not markets:
                # event without nested markets (rare): fall back to per-event fetch
                markets = self.load_nested_markets(ticker)
                if markets:
                    e = dict(e, markets=markets)
            dollars, vol24, oi = estimate_event_dollars(markets)
            staged.append((topic, e, markets, dollars, vol24, oi))

        # Stage 2: rank and select.
        staged.sort(key=lambda t: t[3], reverse=True)
        by_topic: dict[str, list] = defaultdict(list)
        selected = []
        for topic, ev, markets, dollars, vol24, oi in staged:
            if len(by_topic[topic]) >= MAX_EVENTS_PER_TOPIC:
                continue
            if len(selected) >= MAX_EVENTS_OVERALL:
                break
            by_topic[topic].append((ev, markets, dollars, vol24, oi))
            selected.append((topic, ev, markets, dollars, vol24, oi))

        if not selected:
            self.warn("no in-scope live events found - check topic rules / API status")

        # Stage 3: build events.json payload.
        markets_flat: dict[str, dict] = {}
        events_json = {
            "generated_at": utc_now_iso(),
            "api_root": self.client.root,
            "topics": {},
        }
        ranked_all = []
        for topic, ev, markets, dollars, vol24, oi in selected:
            trimmed = [trim_market(m) for m in markets]
            trimmed.sort(key=lambda m: -(m.get("volume") or 0) * (m.get("last_price") or 0))
            kept = trimmed[:MARKETS_PER_EVENT_CAP]
            for m in kept:
                if m.get("ticker"):
                    markets_flat[m["ticker"]] = m
            payload_event = trim_event(ev)
            payload_event.update({
                "topic": topic,
                "topic_label": TOPIC_RULES[topic]["label"],
                "est_dollar_volume": dollars,
                "est_dollar_volume_24h": vol24,
                "open_interest": oi,
                "markets": kept,
                "market_count": len(markets),
                "market_count_total": len(trimmed),
                "source_url": f"{self.client.root}/events/{ev.get('event_ticker')}",
            })
            events_json["topics"].setdefault(topic, []).append(payload_event)
            ranked_all.append(payload_event)

        events_json["ranked"] = sorted(
            ranked_all, key=lambda e: -(e["est_dollar_volume"] or 0))
        events_json["category_counts_open_exchange"] = dict(self.category_counts)
        events_json["topic_counts"] = {t: len(v) for t, v in events_json["topics"].items()}
        self.write_json("events.json", events_json)

        # Stage 4: orderbooks + candlesticks for the top markets.
        def market_dollars(t: str) -> float:
            m = markets_flat.get(t) or {}
            return (m.get("last_price") or 0) * (m.get("volume") or 0)
        top_markets = sorted(
            [t for t, m in markets_flat.items()
             if classify_market_status(m.get("status")) == "open"],
            key=market_dollars, reverse=True)[:MAX_ORDERBOOKS]
        for ticker in top_markets:
            self.fetch_orderbook(ticker)
            self.fetch_history(ticker, markets_flat.get(ticker) or {})

        # Stage 5: tracking + resolutions.
        self.update_tracking(events_json)
        self.sweep_resolutions()
        self.sweep_series_resolutions()

        # Stage 6: meta.
        self.meta.update({
            "request_count": self.client.request_count,
            "error_count": self.client.error_count,
            "tracked_open_events": len(ranked_all),
            "open_events_seen": len(events_nested),
            "top_event": ({ "title": ranked_all[0]["title"],
                            "est_dollar_volume": ranked_all[0]["est_dollar_volume"] }
                          if ranked_all else None),
            "category_counts_open_exchange": dict(self.category_counts),
            "warnings": self.warnings[-50:],
        })
        self.write_json("meta.json", self.meta)
        print(f"=== collect done {utc_now_iso()} ===", flush=True)

    # ------------------------------------------------------------- orderbooks
    def fetch_orderbook(self, ticker: str) -> None:
        """GET /markets/{ticker}/orderbook -> orderbook_fp.yes_dollars/no_dollars.

        Official semantics (docs.kalshi.com/getting_started/orderbook_responses.md and
        quick_start_market_data.md): bids only; arrays of [price_dollars, count_fp]
        sorted ASCENDING, best bid is the LAST element.
        """
        try:
            data = self.client.request("GET", f"/markets/{ticker}/orderbook")
            book = data.get("orderbook_fp") or data.get("orderbook") or {}
            yes = book.get("yes_dollars") or []
            no = book.get("no_dollars") or []
            payload = {
                "ticker": ticker,
                "fetched_at": utc_now_iso(),
                "source_url": f"{self.client.root}/markets/{ticker}/orderbook",
                "yes_bids": [[str(p), str(q)] for p, q in yes],
                "no_bids": [[str(p), str(q)] for p, q in no],
                "best_yes_bid": {"price": str(yes[-1][0]), "contracts": str(yes[-1][1])} if yes else None,
                "best_no_bid": {"price": str(no[-1][0]), "contracts": str(no[-1][1])} if no else None,
            }
            self.write_json(f"orderbooks/{ticker}.json", payload)
        except Exception as exc:
            self.warn(f"orderbook fetch failed for {ticker}: {exc}")

    # ---------------------------------------------------------------- history
    def fetch_history(self, ticker: str, market: dict) -> None:
        series = (market.get("event_ticker") or ticker).rsplit("-", 1)[0]
        now = int(time.time())
        out: dict = {"ticker": ticker, "series_ticker": series,
                     "fetched_at": utc_now_iso(),
                     "source_url": f"{self.client.root}/series/{series}/markets/{ticker}/candlesticks"}
        for interval in (1, 60, 1440):
            _, span_minutes = CANDLE_RANGES[interval]
            start = now - span_minutes * 60
            try:
                data = self.client.request(
                    "GET", f"/series/{series}/markets/{ticker}/candlesticks",
                    params={"start_ts": start, "end_ts": now,
                            "period_interval": interval})
                candles = []
                for c in (data.get("candlesticks") or []):
                    price = c.get("price") or {}
                    close = fp(price.get("close_dollars"))
                    if close is None:
                        close = fp((c.get("yes_bid") or {}).get("close_dollars"))
                    if close is None:
                        continue
                    candles.append([
                        c.get("end_period_ts"),
                        fp(price.get("open_dollars")), close,
                        fp(price.get("high_dollars")), fp(price.get("low_dollars")),
                        fp(c.get("volume_fp")),
                    ])
                out[{1: "1m", 60: "60m", 1440: "1440m"}[interval]] = candles
            except Exception as exc:
                self.warn(f"candlesticks {interval}m failed for {ticker}: {exc}")
        self.write_json(f"history/{ticker}.json", out)

    # --------------------------------------------------------------- tracking
    def update_tracking(self, events_json: dict) -> None:
        tracked = self.read_json("tracked.json", {"events": {}})
        events = tracked.setdefault("events", {})
        now_iso = utc_now_iso()
        for topic, evs in (events_json.get("topics") or {}).items():
            for ev in evs:
                t = ev["event_ticker"]
                rec = events.get(t) or {
                    "first_seen": now_iso, "title": ev.get("title"),
                    "series_ticker": ev.get("series_ticker"), "topic": topic,
                }
                rec["last_seen"] = now_iso
                rec["title"] = ev.get("title")
                rec["topic"] = topic
                rec["resolved"] = rec.get("resolved")
                events[t] = rec
        # prune: resolved entries older than the lookback window are dropped
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RESOLUTION_LOOKBACK_DAYS)
                  ).strftime("%Y-%m-%dT%H:%M:%SZ")
        for t in list(events.keys()):
            rec = events[t]
            resolved = rec.get("resolved") or {}
            if resolved.get("resolved_at") and resolved["resolved_at"] < cutoff:
                del events[t]
        if len(events) > TRACKED_CAP:
            keep = sorted(events.items(),
                          key=lambda kv: kv[1].get("last_seen", ""), reverse=True)
            events.clear()
            events.update(dict(keep[:TRACKED_CAP]))
        tracked["updated_at"] = now_iso
        self.write_json("tracked.json", tracked)

    # ------------------------------------------------------------ resolutions
    def sweep_resolutions(self) -> None:
        """Re-fetch every stale tracked event; record how each resolved (yes/no).

        Market settlement semantics: settled markets carry `result` = "yes" | "no"
        (https://docs.kalshi.com/getting_started/market_settlement.md). For multi-market
        events the winning market(s) are those with result "yes".
        """
        tracked = self.read_json("tracked.json", {"events": {}})
        resolutions = self.read_json("resolutions.json", {"resolved": {}})
        resolved_map = resolutions.setdefault("resolved", {})
        events = tracked.get("events") or {}
        checked = 0
        skipped = 0
        sweep_cap = 30
        run_start_epoch = time.time()
        # Oldest-last-seen first; skip events seen in this run (they are live-open);
        # cap per run to respect API rate budgets on scheduled runs.
        def _last_seen(item):
            return item[1].get("last_seen") or ""
        for ticker, rec in sorted(list(events.items()), key=_last_seen):
            if rec.get("resolved"):
                continue
            if sweep_cap <= 0:
                skipped += 1
                continue
            try:
                seen_epoch = time.mktime(time.strptime(
                    rec["last_seen"], "%Y-%m-%dT%H:%M:%SZ"))
            except (ValueError, KeyError):
                seen_epoch = 0
            if run_start_epoch - seen_epoch < 15 * 60:
                skipped += 1
                continue
            try:
                data = self.client.request(
                    "GET", f"/events/{ticker}", params={"with_nested_markets": "true"})
            except Exception as exc:
                self.warn(f"resolution check failed for {ticker}: {exc}")
                continue
            sweep_cap -= 1
            checked += 1
            event = data.get("event") or {}
            markets = event.get("markets") or []
            if not markets:
                continue
            statuses = {classify_market_status(m.get("status")) for m in markets}
            if "open" in statuses or "closed" in statuses:
                continue  # still live
            settled = [m for m in markets if classify_market_status(m.get("status")) == "settled"]
            if not settled:
                continue
            winners = [m for m in settled if (m.get("result") or "").lower() == "yes"]
            settled_ts = max((m.get("settled_time") or m.get("close_time") or
                              m.get("latest_expiration_time") or "") for m in settled)
            resolution = {
                "resolved_at": settled_ts or utc_now_iso(),
                "outcome_side": "yes" if winners else "no",
                "winners": [
                    {"ticker": m.get("ticker"), "title": m.get("title") or m.get("yes_sub_title"),
                     "result": (m.get("result") or "").lower(),
                     "source_url": f"{self.client.root}/markets/{m.get('ticker')}"}
                    for m in (winners or settled)
                ],
                "market_count": len(settled),
                "event_source_url": f"{self.client.root}/events/{ticker}",
                "settlement_sources": [
                    {"name": s.get("name"), "url": s.get("url")}
                    for s in (event.get("settlement_sources") or [])[:4]
                ],
            }
            rec["resolved"] = resolution
            resolved_map[ticker] = {
                "title": rec.get("title"), "topic": rec.get("topic"),
                "series_ticker": rec.get("series_ticker"), **resolution,
            }
        resolutions["updated_at"] = utc_now_iso()
        # keep the newest 300 resolutions
        items = sorted(resolved_map.items(),
                       key=lambda kv: (kv[1].get("resolved_at") or ""), reverse=True)
        resolutions["resolved"] = dict(items[:300])
        self.write_json("resolutions.json", resolutions)
        self.write_json("tracked.json", tracked)
        self.warn(f"resolution sweep: checked {checked}, deferred {skipped} to later runs")

    def sweep_series_resolutions(self) -> None:
        """Capture settled (resolved) markets for seed series + all tracked series.

        Covers topics whose markets are currently all settled on the demo exchange
        (e.g. gas prices at collection time): the requirement is to track how events
        resolved (yes/no) even when nothing live remains in that topic.
        Series tickers: officially documented seeds (SERIES_SWEEP_SEEDS) plus every
        series observed live in tracked.json — no guessed tickers.
        """
        tracked = self.read_json("tracked.json", {"events": {}})
        resolutions = self.read_json("resolutions.json", {"resolved": {}, "by_market": {}})
        by_market = resolutions.setdefault("by_market", {})
        series_to_check = set(SERIES_SWEEP_SEEDS.get("gas", ()))
        series_to_check |= set(SERIES_SWEEP_SEEDS.get("golf", ()))
        for rec in (tracked.get("events") or {}).values():
            if rec.get("series_ticker"):
                series_to_check.add(rec["series_ticker"])
        checked_series = 0
        for series in sorted(series_to_check)[:25]:
            markets: list[dict] = []
            used_status = None
            for status in ("settled", "all"):
                try:
                    data = self.client.request(
                        "GET", "/markets",
                        params={"series_ticker": series, "status": status, "limit": 200})
                    markets = data.get("markets") or []
                    used_status = status
                except KalshiError as exc:
                    self.warn(f"series sweep {series} status={status}: {exc}")
                    continue
                if status == "settled" or markets:
                    break  # settled worked (possibly empty), or fall back to all
            if used_status is None:
                continue
            checked_series += 1
            for m in markets:
                if used_status == "all" and classify_market_status(m.get("status")) != "settled":
                    continue
                ticker = m.get("ticker")
                if not ticker or ticker in by_market:
                    continue
                by_market[ticker] = {
                    "series_ticker": series,
                    "title": m.get("title") or m.get("yes_sub_title"),
                    "result": (m.get("result") or "").lower() or None,
                    "status": m.get("status"),
                    "settled_time": m.get("settled_time") or m.get("close_time") or None,
                    "last_price_dollars": fp(m.get("last_price_dollars")),
                    "volume": fp(m.get("volume_fp")),
                    "source_url": f"{self.client.root}/markets/{ticker}",
                }
            if used_status == "all":
                # 'all' pages only 200 markets; keep it best-effort and note truncation
                self.warn(f"series sweep {series}: used status=all (status=settled unavailable); "
                          "results limited to the first page")
        # keep the newest 400 by-market resolutions
        items = sorted(by_market.items(),
                       key=lambda kv: (kv[1].get("settled_time") or ""), reverse=True)
        resolutions["by_market"] = dict(items[:400])
        resolutions["updated_at"] = utc_now_iso()
        self.write_json("resolutions.json", resolutions)
        self.warn(f"series resolution sweep: checked {checked_series} series, "
                  f"{len(by_market)} settled markets recorded")


def main() -> int:
    collector = Collector()
    failures = 0
    try:
        collector.collect()
    except Exception as exc:
        collector.warn(f"FATAL during collect: {type(exc).__name__}: {exc}")
        failures += 1
        # still write meta so the site can show collector health
        collector.meta["warnings"] = collector.warnings[-50:]
        try:
            collector.write_json("meta.json", collector.meta)
        except Exception:
            pass
    # Partial success is fine; total failure is not.
    return 1 if failures and collector.client.request_count == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
