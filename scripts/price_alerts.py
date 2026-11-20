#!/usr/bin/env python3
"""Detect contract-price swings of >= $0.10 from committed Kalshi demo snapshots.

Session 6d201d19 (branch arena/6d201d19-demo3). Brief item: "alert system ... sudden swings
in contract prices greater than or equal to $0.10 in either direction".

Inputs (all committed by the collectors, nothing fetched here):
  data/history/prices.jsonl   one row per (ticker, collector run): last_price_dollars, volume_fp, ts
  data/latest/markets_open.json  titles / event tickers / source_url per open market (title lookup)
  data/latest/markets_settled.json  settled markets incl. result yes/no + settlement_ts (resolutions)
  data/latest/events.json     official event records incl. settlement_sources (cause / event links)
  data/latest/top_events.json    live top-dollar markets per topic (watchlist for the live browser poller)

Outputs:
  data/latest/alerts.json     alerts (chronological), resolutions, watchlist, rule text, counts, sources

Rules (published in the output file and on alerts.html):
  * SWING: two consecutive snapshots of the SAME ticker whose last_price_dollars differ by
    >= 0.10 (exact decimal arithmetic; 0.10 counts, 0.0999 does not).
  * RESOLUTION: a tracked market that has settled is recorded with its official result
    ("yes" or "no"), settlement_ts and settlement_value_dollars, so the trader can see how the
    event resolved (https://docs.kalshi.com/getting_started/market_settlement).
  * CAUSE LINKS: the official event record's settlement_sources (name + url) are attached to every
    alert. They are the websites Kalshi itself names as the settlement reference for the contract.
    They are reference links, NOT an attribution of what caused a move. When the event publishes no
    settlement source the field stays empty and is flagged as unverified - never inferred.
  * HIGH-ROI SCREEN (PLACEHOLDER, not a model): the side that a move makes cheaper is the
    side the screen "likes". Gross payout multiple if that side settles at $1.00 is
    (1 - p) / p where p is the bought price. The screen passes when multiple >= 1.00,
    volume_fp > 0, and the market is not in a synthetic exchange-test series. This is
    arithmetic on official prices, NOT a forecast and NOT the user's model (see F-6D-01).

Run: python3 scripts/price_alerts.py
"""
import json
import pathlib
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMO = "https://external-api.demo.kalshi.co/trade-api/v2"
DOCS_MARKETS = "https://docs.kalshi.com/api-reference/market/get-markets.md"
DOCS_EVENT = "https://docs.kalshi.com/api-reference/events/get-event"
DOCS_SETTLEMENT = "https://docs.kalshi.com/getting_started/market_settlement"

THRESHOLD = Decimal("0.10")
HIGH_ROI_MIN_MULTIPLE = Decimal("1.00")
# Exchange-test series seen in the committed snapshots (repo finding I-15, not an official
# Kalshi statement). Alerts from these are kept in the All chat but never pass the ROI screen.
SYNTHETIC_PREFIXES = ("KXDEMO", "KXQUICKSETTLE")
WATCH_PER_TOPIC = 8

Q4 = Decimal("0.0001")


def dec(v):
    """Parse an API dollar string exactly; empty/None -> None."""
    if v is None or v == "":
        return None
    return Decimal(str(v)).quantize(Q4, rounding=ROUND_HALF_UP)


def is_synthetic(ticker):
    return str(ticker).upper().startswith(SYNTHETIC_PREFIXES)


def roi_screen(price, volume_fp, ticker, direction):
    """Placeholder high-ROI screen. direction: +1 (YES got more expensive) or -1 (NO side).

    For an upward move the screen buys YES at `price`; for a downward move it buys NO at
    (1 - price). Returns (passes, side, bought_price, multiple) with Decimal multiple or None.
    """
    if price is None or not (Decimal("0") < price < Decimal("1")):
        return (False, None, None, None)
    if direction > 0:
        side, bought = "YES", price
    else:
        side, bought = "NO", Decimal("1") - price
    multiple = (Decimal("1") - bought) / bought
    passes = (
        multiple >= HIGH_ROI_MIN_MULTIPLE
        and volume_fp is not None and volume_fp > 0
        and not is_synthetic(ticker)
    )
    return (passes, side, bought.quantize(Q4), multiple.quantize(Decimal("0.0001")))


def detect_swings(rows, titles=None, events=None, resolutions=None):
    """rows: iterable of dicts with ticker, topic, ts, last_price_dollars, volume_fp.

    Returns chronological list of alert dicts. Each alert carries the official event
    record (title + API URL), the event's official settlement_sources (cause links) and
    the official resolution of the market if it has already settled.
    """
    titles = titles or {}
    events = events or {}
    resolutions = resolutions or {}
    by_ticker = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)
    alerts = []
    for ticker, rs in by_ticker.items():
        rs = sorted(rs, key=lambda r: r["ts"])
        prices = [dec(r.get("last_price_dollars")) for r in rs]
        for i in range(1, len(rs)):
            r, prev_r = rs[i], rs[i - 1]
            p, prev_p = prices[i], prices[i - 1]
            if p is None or prev_p is None or prev_r["ts"] == r["ts"]:
                continue
            delta = p - prev_p
            if abs(delta) < THRESHOLD:
                continue
            direction = 1 if delta > 0 else -1
            vol = dec(r.get("volume_fp"))
            passes, side, bought, mult = roi_screen(p, vol, ticker, direction)
            # Persistence: the NEXT reading. A last-trade print that snaps back toward the old
            # level is flagged, because a single print is not a sustained price move.
            nxt = prices[i + 1] if i + 1 < len(rs) else None
            reverted = nxt is not None and abs(nxt - prev_p) < THRESHOLD / 2
            meta = titles.get(ticker, {})
            ev = events.get(meta.get("event_ticker", ""), {})
            srcs = ev.get("settlement_sources") or []
            alerts.append({
                "ts": r["ts"],
                "prev_ts": prev_r["ts"],
                "ticker": ticker,
                "event_ticker": meta.get("event_ticker", ""),
                "title": meta.get("title", ""),
                "topic": r.get("topic", meta.get("topic", "")),
                "from_dollars": f"{prev_p:.4f}",
                "to_dollars": f"{p:.4f}",
                "delta_dollars": f"{delta:+.4f}",
                "direction": "up" if direction > 0 else "down",
                "to_bid_dollars": str(dec(r.get("yes_bid_dollars")) or ""),
                "to_ask_dollars": str(dec(r.get("yes_ask_dollars")) or ""),
                "next_reading_dollars": f"{nxt:.4f}" if nxt is not None else "",
                "next_reading_ts": rs[i + 1]["ts"] if nxt is not None else "",
                "reverted_next_reading": bool(reverted),
                "volume_fp": str(vol) if vol is not None else "",
                "source_url": f"{DEMO}/markets?tickers={ticker}",
                "synthetic": is_synthetic(ticker),
                "high_roi": passes,
                "roi_side": side or "",
                "roi_bought_price_dollars": f"{bought:.4f}" if bought is not None else "",
                "roi_multiple": f"{mult:.4f}" if mult is not None else "",
                "event_title": ev.get("title", ""),
                "event_url": ev.get("event_url", ""),
                "settlement_sources": srcs,
                "cause_link": srcs[0]["url"] if srcs else "",
                "cause_status": ("official settlement source (reference link, not an attribution of the move)"
                                 if srcs else "unverified - not inferred"),
                "resolution": resolutions.get(ticker),
            })
    alerts.sort(key=lambda a: (a["ts"], a["ticker"]))
    return alerts


def load_titles():
    """Title lookup from the committed open- and settled-market snapshots (official API fields)."""
    out = {}
    for name in ("markets_open.json", "markets_settled.json"):
        p = ROOT / "data/latest" / name
        if not p.exists():
            continue
        for m in json.loads(p.read_text()).get("markets", []):
            row = out.setdefault(m["ticker"], {})
            row["title"] = m.get("title") or row.get("title", "")
            row["event_ticker"] = m.get("event_ticker") or row.get("event_ticker", "")
            row["topic"] = m.get("topic") or row.get("topic", "")
    for ticker, m in load_verified_meta().items():
        row = out.setdefault(ticker, {})
        row["title"] = m.get("title") or row.get("title", "")
        row["event_ticker"] = m.get("event_ticker") or row.get("event_ticker", "")
        row["topic"] = row.get("topic", "")
    return out


def load_verified_meta():
    """Official records for markets the collector snapshots do not cover.

    data/latest/verified_market_meta.json holds rows read directly from the demo API
    (each row carries its source_url). Used for titles and resolutions only.
    """
    out = {}
    p = ROOT / "data/latest/verified_market_meta.json"
    if not p.exists():
        return out
    for m in json.loads(p.read_text()).get("markets", []):
        out[m["ticker"]] = m
    return out


def load_recent_resolutions(per_topic=4):
    """Most recent official resolutions per tracked topic (how events resolved: yes/no).

    Source: data/latest/resolutions.json, written by the collector from market.result
    (https://docs.kalshi.com/getting_started/market_settlement).
    """
    p = ROOT / "data/latest/resolutions.json"
    if not p.exists():
        return []
    rows = json.loads(p.read_text()).get("resolutions", [])
    rows = sorted(rows, key=lambda r: (r.get("settlement_ts") or "", r.get("ticker") or ""),
                  reverse=True)
    out, per = [], {}
    for r in rows:
        t = r.get("topic", "")
        if per.get(t, 0) >= per_topic:
            continue
        per[t] = per.get(t, 0) + 1
        out.append({
            "ticker": r.get("ticker", ""),
            "title": r.get("title", ""),
            "topic": t,
            "event_ticker": r.get("event_ticker", ""),
            "result": r.get("result", ""),
            "settlement_ts": r.get("settlement_ts", ""),
            "settlement_value_dollars": r.get("settlement_value_dollars", ""),
            "close_time": r.get("close_time", ""),
            "source_url": r.get("source_url", ""),
            "synthetic": is_synthetic(r.get("ticker", "")),
        })
    return out


def load_events():
    """Official event records: title, event API URL and settlement_sources (cause links).

    GET /events returns event.settlement_sources = [{"name": ..., "url": ...}] - the sites
    Kalshi itself names as the settlement reference for the contract.
    """
    out = {}
    p = ROOT / "data/latest/events.json"
    if not p.exists():
        return out
    rows = json.loads(p.read_text()).get("events", [])
    vp = ROOT / "data/latest/verified_market_meta.json"
    if vp.exists():
        rows = rows + json.loads(vp.read_text()).get("events", [])
    for e in rows:
        et = e.get("event_ticker")
        if not et:
            continue
        srcs = []
        for s in e.get("settlement_sources") or []:
            url = str(s.get("url") or "")
            if not url.startswith("http"):
                continue
            srcs.append({"name": str(s.get("name") or url), "url": url})
        out[et] = {
            "title": e.get("title", ""),
            "event_url": e.get("source_url") or f"{DEMO}/events/{et}",
            "settlement_sources": srcs,
            "topic": e.get("topic", ""),
        }
    return out


def load_resolutions():
    """Ticker -> official resolution of a settled market (result yes/no + settlement fields)."""
    out = {}
    p = ROOT / "data/latest/markets_settled.json"
    if not p.exists():
        return out
    for m in json.loads(p.read_text()).get("markets", []):
        result = str(m.get("result") or "").lower()
        if result not in ("yes", "no"):
            continue
        out[m["ticker"]] = {
            "result": result,
            "status": m.get("status", ""),
            "settlement_ts": m.get("settlement_ts", ""),
            "settlement_value_dollars": m.get("settlement_value_dollars", ""),
            "source_url": m.get("source_url") or f"{DEMO}/markets?tickers={m['ticker']}",
            "title": m.get("title", ""),
            "topic": m.get("topic", ""),
            "event_ticker": m.get("event_ticker", ""),
        }
    for ticker, m in load_verified_meta().items():
        if ticker in out:
            continue
        result = str(m.get("result") or "").lower()
        if result not in ("yes", "no"):
            continue
        out[ticker] = {
            "result": result,
            "status": m.get("status", ""),
            "settlement_ts": m.get("settlement_ts", ""),
            "settlement_value_dollars": m.get("settlement_value_dollars", ""),
            "source_url": m.get("source_url", ""),
            "title": m.get("title", ""),
            "topic": "",
            "event_ticker": m.get("event_ticker", ""),
        }
    return out


def build_watchlist(titles, events=None):
    """Top markets per topic from the committed ranking (live poller watchlist)."""
    events = events or {}
    p = ROOT / "data/latest/top_events.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    out, seen = [], set()
    for topic, evs in sorted(data.get("by_topic", {}).items()):
        n = 0
        for ev in evs:
            et = ev.get("event_ticker", "")
            evmeta = events.get(et, {})
            for m in ev.get("top_markets", []):
                t = m.get("ticker")
                if not t or t in seen or n >= WATCH_PER_TOPIC:
                    continue
                seen.add(t)
                n += 1
                meta = titles.get(t, {})
                out.append({
                    "ticker": t,
                    "topic": topic,
                    "title": meta.get("title") or ev.get("title", ""),
                    "event_ticker": et,
                    "event_title": evmeta.get("title", ""),
                    "event_url": evmeta.get("event_url", ""),
                    "settlement_sources": evmeta.get("settlement_sources") or [],
                    "source_url": f"{DEMO}/markets?tickers={t}",
                    "synthetic": is_synthetic(t),
                })
    return out


def build_resolutions(resolutions, watch, alerts=None, events=None):
    """Resolution rows for tracked markets: how each event resolved (yes / no).

    Only markets the site actually tracks (alert tickers + watchlist) are listed, and
    only those the exchange has settled. Unresolved markets are not listed at all -
    nothing is inferred.
    """
    events = events or {}
    tracked = {}
    for w in watch:
        tracked[w["ticker"]] = w
    for a in (alerts or []):
        tracked.setdefault(a["ticker"], {"ticker": a["ticker"]})
    out = []
    for ticker, r in resolutions.items():
        if ticker not in tracked:
            continue
        w = tracked.get(ticker, {})
        ev = events.get(r.get("event_ticker", "") or w.get("event_ticker", ""), {})
        out.append({
            "ticker": ticker,
            "title": r.get("title") or w.get("title", ""),
            "topic": r.get("topic") or w.get("topic", ""),
            "result": r["result"],
            "status": r.get("status", ""),
            "settlement_ts": r.get("settlement_ts", ""),
            "settlement_value_dollars": r.get("settlement_value_dollars", ""),
            "source_url": r.get("source_url", ""),
            "event_ticker": r.get("event_ticker", "") or w.get("event_ticker", ""),
            "event_title": ev.get("title", ""),
            "event_url": ev.get("event_url", ""),
            "settlement_sources": ev.get("settlement_sources") or [],
            "synthetic": is_synthetic(ticker),
        })
    out.sort(key=lambda r: (r.get("settlement_ts") or "", r["ticker"]))
    return out


def main():
    rows = []
    for line in (ROOT / "data/history/prices.jsonl").read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    titles = load_titles()
    events = load_events()
    resolutions = load_resolutions()
    alerts = detect_swings(rows, titles, events, resolutions)
    watch = build_watchlist(titles, events)
    res_rows = build_resolutions(resolutions, watch, alerts, events)
    recent = load_recent_resolutions()
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_root": DEMO,
        "rule": {
            "threshold_dollars": "0.10",
            "comparison": "consecutive snapshots of the same ticker; |last_price_dollars change| >= 0.10",
            "input": "data/history/prices.jsonl",
            "either_direction": True,
            "persistence_check": "a swing whose next reading moves back to within $0.05 of the old price is flagged reverted_next_reading (single print, not sustained)",
        },
        "high_roi_rule": {
            "status": "PLACEHOLDER - not the user's model; arithmetic on official prices, not a forecast",
            "formula": "gross payout multiple of the side made cheaper by the move = (1 - p) / p",
            "min_multiple": "1.00",
            "requires": "volume_fp > 0 and not a synthetic exchange-test series",
            "synthetic_prefixes": list(SYNTHETIC_PREFIXES),
        },
        "snapshot_samples": len(rows),
        "snapshot_tickers": len({r["ticker"] for r in rows}),
        "counts": {
            "alerts": len(alerts),
            "up": sum(1 for a in alerts if a["direction"] == "up"),
            "down": sum(1 for a in alerts if a["direction"] == "down"),
            "high_roi": sum(1 for a in alerts if a["high_roi"]),
            "reverted_next_reading": sum(1 for a in alerts if a["reverted_next_reading"]),
            "synthetic": sum(1 for a in alerts if a["synthetic"]),
            "watchlist": len(watch),
            "resolved": len(res_rows),
            "resolved_yes": sum(1 for r in res_rows if r["result"] == "yes"),
            "resolved_no": sum(1 for r in res_rows if r["result"] == "no"),
            "recent_resolutions": len(recent),
        },
        "alerts": alerts,
        "resolutions": res_rows,
        "recent_resolutions": recent,
        "watchlist": watch,
        "cause_rule": {
            "what_it_is": "the official event record's settlement_sources (name + url) - the websites Kalshi names as the settlement reference for the contract",
            "not_a_claim": "these are reference links for the trader to check; this repo makes no claim about which page caused a move",
            "source": DOCS_EVENT,
        },
        "sources": [
            DOCS_MARKETS,
            DOCS_EVENT,
            DOCS_SETTLEMENT,
            f"{DEMO}/markets?tickers=<ticker>",
            f"{DEMO}/events/<event_ticker>",
            "https://docs.kalshi.com/getting_started/demo_env",
        ],
    }
    (ROOT / "data/latest/alerts.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"alerts={len(alerts)} high_roi={out['counts']['high_roi']} watchlist={len(watch)} "
          f"resolved={len(res_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
