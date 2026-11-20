#!/usr/bin/env python3
"""One run of the Kalshi demo alerting pipeline.

What it does on each run (all documented, all source-linked):

  1. Discover in-scope open events for the five topics with ONE paged call per topic:
       GET /events?status=open&with_nested_markets=true&series_ticker=...
     (docs.kalshi.com/api-reference/events/get-events). Nested markets carry the price
     fields, so no per-market calls are needed for price monitoring.
  2. For every tracked market, compare the current last_price_dollars with the previous
     observation persisted in data/alerts/state.json. A change of >= $0.10 in either
     direction becomes an alert with BOTH observation URLs and timestamps.
  3. Persist every observation (prices.json, trimmed) so the live chart can be drawn
     from real recorded points as well as from the browser's own polls.
  4. Track resolutions: fetch settled markets per tracked series, record result
     yes/no + settlement timestamp + settlement value + the exact market URL.
  5. Record orderbook liquidity ladders (contracts available at each price) for the
     highest-dollar in-scope markets.
  6. Run the paper strategy simulator over new alerts and settle open simulated trades
     with the official results.
  7. Write data/alerts/*.json, every row carrying its source_url.

Nothing is inferred: a missing price, result or level stays null and the site renders
it blank with an "unverified" flag.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import traceback
from datetime import datetime, timezone

from . import kalshi_http as kh
from . import strategies, swings
from .topics import TOPICS, classify

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "alerts"
ROOT_DOC = "https://karagemop466-tech.github.io/Demo3/"

# Seed series per topic. These are *observed* on the demo exchange and only used to
# widen discovery; the classification rules decide what actually lands in a topic.
SEED_SERIES = {
    "gas": ["KXAAAGASW", "KXAAAGASM"],
    "golf": ["KXPGATOUR", "KXPGARYDER"],
    "crypto": ["KXBTCY", "KXBTC", "KXETHY"],
    "elections": ["KXPRESNOMD", "KXHOUSE", "KXSENATE", "KXGOVCA"],
    "culture": ["KXRT", "KXSHOWENDSIMPSONS"],
}

MAX_MARKETS_PER_TOPIC = 40     # keeps the live poll + the data files small
MAX_ALERTS = 400               # rolling window shown in the two chat feeds
MAX_PRICE_POINTS = 120         # observations kept per market for the chart
MAX_ORDERBOOKS = 12


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=False, ensure_ascii=False) + "\n")


def market_value(m: dict) -> float:
    """Estimated dollar volume = contracts traded x price. Estimate, labelled as such.

    The public market object reports contracts (`volume_fp`) and a per-contract price,
    not dollars (docs: get-markets), so any dollar figure is derived and marked.
    """
    v = kh.num(m.get("volume_fp")) or 0.0
    p = kh.num(m.get("last_price_dollars")) or 0.0
    return v * p


class Pipeline:
    def __init__(self, client: kh.Client, log=print):
        self.client = client
        self.log = log
        self.warnings: list[str] = []
        self.state = read_json(DATA / "state.json", {"markets": {}})
        self.resolutions = read_json(DATA / "resolutions.json", {"by_market": {}})
        self.alerts = read_json(DATA / "alerts.json", {"alerts": []})
        self.sim = read_json(DATA / "sim_portfolio.json", {"trades": []})
        self.series_cache = read_json(DATA / "series_cache.json", {"series": {}})
        self.updated = utc_now()

    # -- 0. series metadata (official tags) --------------------------------
    def series_meta(self, ticker: str) -> dict:
        """GET /series/{ticker} -> {tags, category, title}; cached across runs.

        Source: https://docs.kalshi.com/api-reference/market/get-series
        The API's own `tags` are the strongest official evidence of what a series is
        about (e.g. KXUSOPEN carries tags=["Golf"] even though its category says
        Sports), so they are checked before any keyword rule.
        """
        cache = self.series_cache.setdefault("series", {})
        if ticker in cache:
            return cache[ticker]
        path = f"/series/{ticker}"
        try:
            j = self.client.get(path, {})
            s = j.get("series") or {}
            rec = {"tags": s.get("tags") or [], "category": s.get("category") or "",
                   "title": s.get("title") or "",
                   "settlement_sources": s.get("settlement_sources") or [],
                   "source_url": self.client.url(path, {})}
        except (kh.KalshiHTTPError, OSError, ValueError) as exc:
            self.warnings.append(f"series {ticker}: {exc}")
            rec = {"tags": [], "category": "", "title": "",
                   "settlement_sources": [],
                   "source_url": self.client.url(path, {})}
        cache[ticker] = rec
        return rec

    # -- 1. discovery -------------------------------------------------------
    def discover(self) -> dict[str, list[dict]]:
        """Return topic -> list of {event, markets} for open, in-scope events."""
        by_topic: dict[str, list[dict]] = {t: [] for t in TOPICS}
        seen: set[str] = set()
        for topic, series_list in SEED_SERIES.items():
            for series in series_list:
                path = "/events"
                params = {"status": "open", "series_ticker": series,
                          "with_nested_markets": "true", "limit": 200}
                url = self.client.url(path, params)
                try:
                    j = self.client.get(path, params)
                except (kh.KalshiHTTPError, OSError, ValueError) as exc:
                    self.warnings.append(f"discovery {series}: {exc}")
                    continue
                for ev in j.get("events") or []:
                    et = ev.get("event_ticker")
                    if not et or et in seen:
                        continue
                    markets = ev.get("markets") or []
                    if not markets:
                        continue
                    st = ev.get("series_ticker") or series
                    sm = self.series_meta(st) if st else {"tags": [], "category": "",
                                                          "settlement_sources": []}
                    t, rule = classify(st, ev.get("title") or "",
                                       ev.get("category") or sm.get("category") or "",
                                       sm.get("tags") or [])
                    if not t:
                        continue
                    if len(by_topic[t]) >= 6:
                        continue
                    seen.add(et)
                    markets = sorted(markets, key=market_value, reverse=True)
                    by_topic[t].append({
                        "event": ev,
                        "markets": markets[:MAX_MARKETS_PER_TOPIC],
                        "rule": rule,
                        "source_url": url,
                    })
        return by_topic

    # -- 2. price observations + swing detection ----------------------------
    def observe(self, by_topic: dict[str, list[dict]]) -> list[dict]:
        prev_markets = self.state.get("markets") or {}
        new_markets: dict[str, dict] = {}
        new_alerts: list[dict] = []
        for topic, groups in by_topic.items():
            for g in groups:
                ev = g["event"]
                meta = {
                    "topic": topic,
                    "topic_label": TOPICS[topic],
                    "title": ev.get("title") or "",
                    "rule": g["rule"],
                    "settlement_sources": (ev.get("settlement_sources")
                                           or sm.get("settlement_sources") or []),
                }
                for m in g["markets"]:
                    ticker = m.get("ticker")
                    if not ticker:
                        continue
                    price_now = kh.num(m.get("last_price_dollars"))
                    if price_now is None:
                        continue
                    prev = prev_markets.get(ticker)
                    market_url = self.client.url(
                        "/markets", {"tickers": ticker})
                    if prev and prev.get("price") is not None:
                        alert = swings.detect_swing(
                            m, prev["price"], prev.get("observed_at") or "",
                            prev.get("source_url") or market_url,
                            self.updated, market_url, meta)
                        if alert:
                            new_alerts.append(alert)
                    points = (prev or {}).get("points") or []
                    points.append({"t": self.updated, "price": price_now,
                                   "source_url": market_url})
                    new_markets[ticker] = {
                        "ticker": ticker,
                        "event_ticker": m.get("event_ticker"),
                        "series_ticker": m.get("series_ticker") or ev.get("series_ticker"),
                        "title": meta["title"],
                        "yes_sub_title": m.get("yes_sub_title") or "",
                        "topic": topic,
                        "topic_label": TOPICS[topic],
                        "price": price_now,
                        "yes_bid": kh.num(m.get("yes_bid_dollars")),
                        "yes_ask": kh.num(m.get("yes_ask_dollars")),
                        "previous_price": kh.num(m.get("previous_price_dollars")),
                        "volume": kh.num(m.get("volume_fp")),
                        "volume_24h": kh.num(m.get("volume_24h_fp")),
                        "open_interest": kh.num(m.get("open_interest_fp")),
                        "close_time": m.get("close_time"),
                        "status": m.get("status"),
                        "est_dollar_volume": round(market_value(m), 2),
                        "observed_at": self.updated,
                        "source_url": market_url,
                        "classification_rule": g["rule"],
                        "settlement_sources": meta["settlement_sources"],
                        "points": points[-MAX_PRICE_POINTS:],
                    }
        self.state["markets"] = new_markets
        self.state["updated_at"] = self.updated

        merged = new_alerts + list(self.alerts.get("alerts") or [])
        seen = set()
        deduped = []
        for a in merged:
            if a.get("alert_id") in seen:
                continue
            seen.add(a.get("alert_id"))
            deduped.append(a)
        self.alerts = {
            "updated_at": self.updated,
            "threshold_dollars": swings.SWING_THRESHOLD,
            "definition": ("an alert is raised when the last_price_dollars of a tracked "
                           "market changes by >= $0.10 between two recorded observations; "
                           "both observations are linked on the row"),
            "count_this_run": len(new_alerts),
            "alerts": deduped[:MAX_ALERTS],
        }
        return new_alerts

    # -- 3. candle-based swings (recent 1-minute history) -------------------
    def candle_swings(self) -> list[dict]:
        """Scan 1-minute candlesticks of the tracked markets with the deepest history.

        Guarded: candlesticks need start_ts/end_ts/period_interval (docs), and only a
        handful of markets are queried per run to stay well inside the unauthenticated
        rate limits (docs.kalshi.com/getting_started/rate_limits).
        """
        rows: list[dict] = []
        markets = sorted((self.state.get("markets") or {}).values(),
                         key=lambda m: -(m.get("est_dollar_volume") or 0.0))[:6]
        end_ts = int(datetime.now(timezone.utc).timestamp())
        start_ts = end_ts - 3600
        for m in markets:
            series, ticker = m.get("series_ticker"), m.get("ticker")
            if not series or not ticker:
                continue
            path = f"/series/{series}/markets/{ticker}/candlesticks"
            params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": 1}
            url = self.client.url(path, params)
            try:
                j = self.client.get(path, params)
            except (kh.KalshiHTTPError, OSError, ValueError) as exc:
                self.warnings.append(f"candles {ticker}: {exc}")
                continue
            meta = {"topic": m.get("topic"), "topic_label": m.get("topic_label"),
                    "title": m.get("title"), "rule": m.get("classification_rule"),
                    "settlement_sources": m.get("settlement_sources")}
            rows.extend(swings.detect_candle_swings(
                j.get("candlesticks") or [], m, meta, url))
        return rows

    # -- 4. resolutions -----------------------------------------------------
    def track_resolutions(self, by_topic: dict[str, list[dict]]) -> None:
        by_market = self.resolutions.setdefault("by_market", {})
        series_seen: dict[str, dict] = {}
        for topic, groups in by_topic.items():
            for g in groups:
                ev = g["event"]
                for m in g["markets"]:
                    series_seen[m.get("series_ticker") or ev.get("series_ticker")] = {
                        "topic": topic, "title": ev.get("title"),
                        "settlement_sources": ev.get("settlement_sources") or []}
        for series, meta in sorted(series_seen.items()):
            if not series:
                continue
            params = {"series_ticker": series, "status": "settled", "limit": 200}
            path = "/markets"
            url = self.client.url(path, params)
            try:
                j = self.client.get(path, params)
            except (kh.KalshiHTTPError, OSError, ValueError) as exc:
                self.warnings.append(f"resolutions {series}: {exc}")
                continue
            for m in j.get("markets") or []:
                ticker = m.get("ticker")
                if not ticker or ticker in by_market:
                    continue
                row = swings.resolution_row(
                    m, {"topic": meta["topic"], "topic_label": TOPICS[meta["topic"]],
                        "title": m.get("title") or meta.get("title")},
                    self.updated,
                    self.client.url("/markets", {"tickers": ticker}))
                if row:
                    row["topic_rule"] = f"series_ticker={series}"
                    row["resolution_gap_seconds"] = swings.resolution_timing(row)
                    by_market[ticker] = row
        # Keep the newest 1,500 by settlement timestamp, but never let one topic
        # (crypto ladders settle thousands of markets) crowd out the other four.
        ordered = sorted(by_market.values(),
                         key=lambda r: r.get("settlement_ts") or "", reverse=True)
        kept, per_topic = {}, {t: 0 for t in TOPICS}
        for r in ordered:
            t = r.get("topic")
            if per_topic.get(t, 0) >= 300:
                continue
            per_topic[t] = per_topic.get(t, 0) + 1
            kept[r["market_ticker"]] = r
            if len(kept) >= 1500:
                break
        self.resolutions = {
            "updated_at": self.updated,
            "count": len(kept),
            "counts_by_topic": per_topic,
            "result_counts": {
                "yes": sum(1 for r in kept.values() if r["result"] == "yes"),
                "no": sum(1 for r in kept.values() if r["result"] == "no"),
            },
            "rule": "market.result (yes|no) after status settled; settlement value from "
                    "settlement_value_dollars",
            "settlement_doc": kh.SOURCES["market_settlement"],
            "by_market": kept,
        }

    # -- 5. liquidity -------------------------------------------------------
    def orderbooks(self) -> dict:
        top = sorted((self.state.get("markets") or {}).values(),
                     key=lambda m: -(m.get("est_dollar_volume") or 0.0))[:MAX_ORDERBOOKS]
        out = {}
        for m in top:
            ticker = m.get("ticker")
            params = {"depth": 25}
            path = f"/markets/{ticker}/orderbook"
            url = self.client.url(path, params)
            try:
                j = self.client.get(path, params)
            except (kh.KalshiHTTPError, OSError, ValueError) as exc:
                self.warnings.append(f"orderbook {ticker}: {exc}")
                continue
            levels = swings.orderbook_levels(j)
            out[ticker] = {
                "market_ticker": ticker,
                "title": m.get("title"),
                "yes_sub_title": m.get("yes_sub_title"),
                "topic": m.get("topic"),
                "topic_label": m.get("topic_label"),
                "yes": levels["yes"],
                "no": levels["no"],
                "summary": levels["summary"],
                "observed_at": self.updated,
                "source_url": url,
                "doc": kh.SOURCES["get_orderbook"],
            }
        return {"updated_at": self.updated, "count": len(out),
                "definition": ("contracts available at each price, from orderbook_fp: "
                               "each level is [price_dollars, contracts]"),
                "orderbooks": out}

    # -- 6. simulation ------------------------------------------------------
    def simulate(self, new_alerts: list[dict], candle_rows: list[dict]) -> None:
        self.sim = strategies.run(self.sim, new_alerts + candle_rows,
                                  self.resolutions, self.updated)
        self.sim["by_category"] = strategies.by_category(self.sim)

    # -- run ----------------------------------------------------------------
    def run(self) -> dict:
        by_topic = self.discover()
        new_alerts = self.observe(by_topic)
        candle_rows = []
        try:
            candle_rows = self.candle_swings()
        except Exception as exc:  # candle scan is best-effort, never fatal
            self.warnings.append(f"candle scan failed: {type(exc).__name__}: {exc}")
        try:
            self.track_resolutions(by_topic)
        except Exception as exc:
            self.warnings.append(f"resolution tracking failed: {type(exc).__name__}: {exc}")
        books = {"updated_at": self.updated, "count": 0, "orderbooks": {}}
        try:
            books = self.orderbooks()
        except Exception as exc:
            self.warnings.append(f"orderbooks failed: {type(exc).__name__}: {exc}")
        try:
            if self.alerts.get("alerts"):
                self.simulate(new_alerts, candle_rows)
        except Exception as exc:
            self.warnings.append(f"simulation failed: {type(exc).__name__}: {exc}")

        markets = self.state.get("markets") or {}
        ranked = sorted(markets.values(), key=lambda m: -(m.get("est_dollar_volume") or 0.0))
        write_json(DATA / "alerts.json", self.alerts)
        write_json(DATA / "resolutions.json", self.resolutions)
        write_json(DATA / "orderbooks.json", books)
        write_json(DATA / "sim_portfolio.json", self.sim)
        write_json(DATA / "prices.json", {
            "updated_at": self.updated,
            "points_note": "recorded observations per market (last %d kept)" % MAX_PRICE_POINTS,
            "markets": {t: {"topic": m["topic"], "points": m.get("points") or []}
                        for t, m in markets.items()},
        })
        write_json(DATA / "state.json", self.state)
        write_json(DATA / "series_cache.json", self.series_cache)
        write_json(DATA / "markets.json", {
            "updated_at": self.updated,
            "api_root": self.client.root,
            "ranking_method": ("estimated dollar volume = volume_fp x last_price_dollars "
                               "(the public market object has no dollar-volume field)"),
            "topics": TOPICS,
            "count": len(ranked),
            "by_topic": {t: [m for m in ranked if m.get("topic") == t] for t in TOPICS},
        })
        counts = {t: len([m for m in markets.values() if m.get("topic") == t])
                  for t in TOPICS}
        status = {
            "updated_at": self.updated,
            "api_root": self.client.root,
            "requests": self.client.requests,
            "client_errors": self.client.errors[-20:],
            "markets_tracked": len(markets),
            "markets_by_topic": counts,
            "alerts_this_run": len(new_alerts),
            "alerts_total": len(self.alerts.get("alerts") or []),
            "candle_swings": len(candle_rows),
            "resolutions": self.resolutions.get("count", 0),
            "orderbooks": books.get("count", 0),
            "sim_open": (self.sim.get("counts") or {}).get("open", 0),
            "sim_settled": (self.sim.get("counts") or {}).get("settled", 0),
            "warnings": self.warnings[-30:],
            "threshold_dollars": swings.SWING_THRESHOLD,
        }
        write_json(DATA / "status.json", status)
        return status


def main() -> int:
    root = os.environ.get("KALSHI_API_ROOT", kh.DEMO_ROOT)
    client = kh.Client(root=root)
    p = Pipeline(client)
    try:
        status = p.run()
    except Exception:
        traceback.print_exc()
        write_json(DATA / "status.json", {
            "updated_at": utc_now(), "api_root": root, "fatal": traceback.format_exc()[-2000:],
            "warnings": p.warnings[-30:], "markets_tracked": 0,
        })
        return 1
    print(json.dumps({k: v for k, v in status.items() if k != "warnings"}, indent=1))
    for w in status["warnings"]:
        print("warn:", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
