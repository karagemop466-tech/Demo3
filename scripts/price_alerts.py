#!/usr/bin/env python3
"""Detect contract-price swings of >= $0.10 from committed Kalshi demo snapshots.

Session 6d201d19 (branch arena/6d201d19-demo3). Brief item: "alert system ... sudden swings
in contract prices greater than or equal to $0.10 in either direction".

Inputs (all committed by the collectors, nothing fetched here):
  data/history/prices.jsonl   one row per (ticker, collector run): last_price_dollars, volume_fp, ts
  data/latest/markets_open.json  titles / event tickers / source_url per open market (title lookup)
  data/latest/top_events.json    live top-dollar markets per topic (watchlist for the live browser poller)

Outputs:
  data/latest/alerts.json     alerts (chronological), watchlist, rule text, counts, sources

Rules (published in the output file and on alerts.html):
  * SWING: two consecutive snapshots of the SAME ticker whose last_price_dollars differ by
    >= 0.10 (exact decimal arithmetic; 0.10 counts, 0.0999 does not).
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


def detect_swings(rows, titles=None):
    """rows: iterable of dicts with ticker, topic, ts, last_price_dollars, volume_fp.

    Returns chronological list of alert dicts (no cause fields filled; those stay empty).
    """
    titles = titles or {}
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
            # Quote check: does the bid/ask midpoint at the swing reading support the printed last price?
            bid = dec(r.get("yes_bid_dollars"))
            ask = dec(r.get("yes_ask_dollars"))
            if bid is not None and ask is not None and bid > 0 and ask > 0:
                mid = ((bid + ask) / 2).quantize(Q4, rounding=ROUND_HALF_UP)
                supported = bool(abs(mid - p) <= THRESHOLD / 2)
                mid_s = f"{mid:.4f}"
            else:
                supported, mid_s = None, ""
            meta = titles.get(ticker, {})
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
                "quote_mid_dollars": mid_s,
                "last_supported_by_quote": supported,
                "volume_fp": str(vol) if vol is not None else "",
                "source_url": f"{DEMO}/markets?tickers={ticker}",
                "synthetic": is_synthetic(ticker),
                "high_roi": passes,
                "roi_side": side or "",
                "roi_bought_price_dollars": f"{bought:.4f}" if bought is not None else "",
                "roi_multiple": f"{mult:.4f}" if mult is not None else "",
                "cause_link": "",
                "cause_status": "unverified - not inferred",
            })
    alerts.sort(key=lambda a: (a["ts"], a["ticker"]))
    return alerts


def load_titles():
    """Title lookup from the committed open-market snapshot (official API fields)."""
    out = {}
    p = ROOT / "data/latest/markets_open.json"
    if not p.exists():
        return out
    for m in json.loads(p.read_text()).get("markets", []):
        out[m["ticker"]] = {
            "title": m.get("title", ""),
            "event_ticker": m.get("event_ticker", ""),
            "topic": m.get("topic", ""),
        }
    return out


def build_watchlist(titles):
    """Top markets per topic from the committed ranking (live poller watchlist)."""
    p = ROOT / "data/latest/top_events.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    out, seen = [], set()
    for topic, events in sorted(data.get("by_topic", {}).items()):
        n = 0
        for ev in events:
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
                    "event_ticker": ev.get("event_ticker", ""),
                    "source_url": f"{DEMO}/markets?tickers={t}",
                    "synthetic": is_synthetic(t),
                })
    return out


def main():
    rows = []
    for line in (ROOT / "data/history/prices.jsonl").read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    titles = load_titles()
    alerts = detect_swings(rows, titles)
    watch = build_watchlist(titles)
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_root": DEMO,
        "rule": {
            "threshold_dollars": "0.10",
            "comparison": "consecutive snapshots of the same ticker; |last_price_dollars change| >= 0.10",
            "input": "data/history/prices.jsonl",
            "either_direction": True,
            "quote_check": "the bid/ask midpoint at the swing reading must be within $0.05 of the printed last price; otherwise last_supported_by_quote is false",
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
            "last_not_supported_by_quote": sum(1 for a in alerts if a["last_supported_by_quote"] is False),
            "synthetic": sum(1 for a in alerts if a["synthetic"]),
            "watchlist": len(watch),
        },
        "alerts": alerts,
        "watchlist": watch,
        "sources": [
            DOCS_MARKETS,
            f"{DEMO}/markets?tickers=<ticker>",
            "https://docs.kalshi.com/getting_started/demo_env",
        ],
    }
    (ROOT / "data/latest/alerts.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"alerts={len(alerts)} high_roi={out['counts']['high_roi']} watchlist={len(watch)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
