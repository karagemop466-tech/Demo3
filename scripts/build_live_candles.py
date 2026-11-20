#!/usr/bin/env python3
"""Assemble the Live Alert Desk's candlestick store from committed official data.

Why this exists
---------------
The dev sandbox this session runs in has no HTTPS egress to the Kalshi API
(the TLS handshake to external-api.demo.kalshi.co is dropped), while GitHub
Actions runners do. So the desk is fed from candlestick payloads that earlier
collector runs already committed to this repository, and every value in the
store is copied field-for-field from those payloads:

  data/latest/candles.json   raw `/series/{s}/markets/{t}/candlesticks` responses
                             with the exact `source_url` for each window
  data/history/*.json        per-contract arrays [ts, open, high, low, close, volume]
                             (numbers and None), plus `source_url`
  analysis/data/live/candles.json
                             hourly/daily candlesticks for gas, crypto and golf
                             contracts collected from the PRODUCTION endpoint
                             (https://api.elections.kalshi.com/trade-api/v2). Those
                             contracts are labelled environment="production" in the
                             index and on every page, because the brief's target is
                             the demo exchange and mixing the two silently would be
                             misleading (flag L-11).

Field mapping was spot-checked against the live API response documented at
https://docs.kalshi.com/api-reference/market/get-market-candlesticks :

  price.open_dollars / high_dollars / low_dollars / close_dollars  -> OHLC
  volume_fp (contracts)                                            -> volume

Nothing is interpolated, smoothed, or invented: gaps stay gaps and candles
flagged as placeholders by the exchange (candles that repeat `previous_dollars`
without a `close_dollars`, plus their `yes_ask`/`yes_bid` quotes, which the API
uses for carries-forward periods) are recorded with close = None rather than
reusing an older price as if it traded.

Coverage is stated on the page: 26 contracts with hourly history, 7 with
per-minute history, from the committed snapshots.
"""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE = ROOT / "live" / "data"
OUT = LIVE / "candles"

API_DOC = "https://docs.kalshi.com/api-reference/market/get-market-candlesticks"

LATEST = ROOT / "data" / "latest" / "candles.json"
HISTORY = ROOT / "data" / "history"
PROD_ARCHIVE = ROOT / "analysis" / "data" / "live" / "candles.json"


def production_candles():
    """{ticker: {interval: {ts: [o,h,l,c,v]}, '_src': url, '_topic': t}} from the
    archived production-API candlestick payload."""
    if not PROD_ARCHIVE.exists():
        return {}
    try:
        d = json.loads(PROD_ARCHIVE.read_text())
    except Exception:
        return {}
    out = {}
    for ticker, entry in (d.get("series") or {}).items():
        got = {"_src": "", "_topic": entry.get("topic") or ""}
        for key, payload in entry.items():
            if key not in ("60", "1440"):
                continue
            interval = int(key)
            src = payload.get("source_url") or ""
            if src and not got["_src"]:
                got["_src"] = src
            for row in payload.get("candles") or []:
                ts = row.get("end_period_ts")
                if not ts:
                    continue
                close = row.get("price_close")
                got.setdefault(interval, {})[int(ts)] = [
                    row.get("price_open"), row.get("price_high"), row.get("price_low"),
                    close, row.get("volume_contracts")]
        if any(isinstance(k, int) for k in got):
            out[ticker] = got
    return out


def safe(ticker):
    return re.sub(r"[^A-Za-z0-9._-]", "_", ticker)


def history_candles(ticker):
    """Return {interval: {ts: [o,h,l,c,v]}} from data/history/<ticker>.json."""
    p = HISTORY / f"{ticker}.json"
    if not p.exists():
        return None, None
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None, None
    out = {}
    for key, interval in (("1m", 1), ("60m", 60), ("1440m", 1440)):
        rows = d.get(key) or []
        m = {}
        for r in rows:
            if not isinstance(r, list) or len(r) < 6 or not r[0]:
                continue
            ts, o, h, l, c, v = r[0], r[1], r[2], r[3], r[4], r[5]
            # the collector writes JSON nulls for missing OHLC fields; keep them
            m[int(ts)] = [o, h, l, c, v]
        if m:
            out[interval] = m
    return out, (d.get("source_url") or "")


def latest_candles():
    """Return {ticker: {interval: {ts: [o,h,l,c,v]}, '_src': {...}}} from
    data/latest/candles.json (raw official payloads)."""
    if not LATEST.exists():
        return {}
    d = json.loads(LATEST.read_text())
    out = {}
    for ticker, entry in (d.get("by_market") or {}).items():
        got = {"_src": {}, "_meta": entry}
        for label, payload in (entry.get("windows") or {}).items():
            interval = int(payload.get("period_interval_minutes") or
                           (1 if label.startswith("1m") else 60))
            src = payload.get("source_url") or ""
            for c in payload.get("candlesticks") or []:
                ts = c.get("end_period_ts")
                if not ts:
                    continue
                price = c.get("price") or {}
                close = price.get("close_dollars")
                if close is None:
                    # placeholder candle: the exchange carried the last price
                    # forward (documented `include_latest_before_start` and
                    # no-trade behaviour) -> record close = None, not a price
                    close = None
                o = price.get("open_dollars")
                row = [o, price.get("high_dollars"), price.get("low_dollars"),
                       close, c.get("volume_fp")]
                # only non-placeholder prices are usable; keep placeholders with
                # close None so the chart shows a gap instead of a fake fill
                got.setdefault(interval, {})[int(ts)] = row
                got["_src"][int(ts)] = src
        if any(k for k in got if isinstance(k, int)):
            out[ticker] = got
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    latest = latest_candles()
    hist_files = sorted(p.stem for p in HISTORY.glob("*.json")
                        if p.stem not in ("prices", "resolutions"))
    index = {"doc": API_DOC, "generated_from": [], "markets": {}}
    written = 0
    for ticker in hist_files:
        series = ticker.split("-")[0]
        merged, hsrc = history_candles(ticker)
        if not merged:
            continue
        srcs = {str(k): hsrc for k in merged}
        # overlay the newer raw payload when it covers the same ticker
        l = latest.get(ticker) or {}
        for interval, rows in merged.items():
            for ts in list(l.get(interval, {})):
                if ts in rows and l[interval][ts][3] is None:
                    continue          # official payload says "no trade": keep gap
            merged[interval].update({ts: r for ts, r in (l.get(interval) or {}).items()
                                     if r[3] is not None or ts not in rows})
            if l.get("_src"):
                srcs[str(interval)] = (sorted(set(l["_src"].values())) or [hsrc])[0]
        payload = {"ticker": ticker, "series_ticker": series,
                   "source_url": hsrc or API_DOC,
                   "field_map": "row = [open, high, low, close, volume_contracts] (dollars, contracts)",
                   "series": {str(k): [[ts, *rows[ts]] for ts in sorted(rows)]
                              for k, rows in sorted(merged.items())}}
        (OUT / f"{safe(ticker)}.json").write_text(json.dumps(payload))
        index["markets"][ticker] = {
            "series_ticker": series,
            "path": f"data/candles/{safe(ticker)}.json",
            "source_url": payload["source_url"],
            "environment": "demo",
            "intervals": {str(k): len(v) for k, v in sorted(merged.items())},
            "first_ts": min(min(v) for v in merged.values()),
            "last_ts": max(max(v) for v in merged.values()),
        }
        written += 1
    # also index latest-only contracts (no history file) so the browser can
    # render them straight from the raw payloads
    for ticker, l in latest.items():
        if ticker in index["markets"]:
            continue
        series = ticker.split("-")[0]
        series_map = {str(k): [[ts, *l[k][ts]] for ts in sorted(l[k])]
                      for k in l if isinstance(k, int)}
        payload = {"ticker": ticker, "series_ticker": series,
                   "source_url": (sorted(set(l["_src"].values())) or [API_DOC])[0],
                   "field_map": "row = [open, high, low, close, volume_contracts]",
                   "series": series_map}
        (OUT / f"{safe(ticker)}.json").write_text(json.dumps(payload))
        index["markets"][ticker] = {
            "series_ticker": series,
            "path": f"data/candles/{safe(ticker)}.json",
            "source_url": payload["source_url"],
            "environment": "demo",
            "intervals": {k: len(v) for k, v in series_map.items()},
            "first_ts": min((r[0] for v in series_map.values() for r in v), default=0),
            "last_ts": max((r[0] for v in series_map.values() for r in v), default=0),
        }
        written += 1
    # archived production-API candlesticks (labelled; see module docstring)
    prod = production_candles()
    for ticker, entry in prod.items():
        path = OUT / f"{safe(ticker)}.json"
        existing = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text()).get("series") or {}
            except Exception:
                existing = {}
        series_map = {str(k): [[ts, *entry[k][ts]] for ts in sorted(entry[k])]
                      for k in entry if isinstance(k, int)}
        for k, v in existing.items():
            series_map.setdefault(k, v)
        payload = {"ticker": ticker, "series_ticker": ticker.split("-")[0],
                   "source_url": entry["_src"],
                   "environment": "production",
                   "field_map": "row = [open, high, low, close, volume_contracts]",
                   "series": series_map}
        path.write_text(json.dumps(payload))
        index["markets"][ticker] = {
            "series_ticker": ticker.split("-")[0],
            "path": f"data/candles/{safe(ticker)}.json",
            "source_url": entry["_src"],
            "environment": "production",
            "topic_hint": entry.get("_topic") or "",
            "intervals": {k: len(v) for k, v in sorted(series_map.items())},
            "first_ts": min((r[0] for v in series_map.values() for r in v), default=0),
            "last_ts": max((r[0] for v in series_map.values() for r in v), default=0),
        }
        written += 1
    index["count"] = written
    index["environments"] = {
        "demo": "https://external-api.demo.kalshi.co/trade-api/v2",
        "production": "https://api.elections.kalshi.com/trade-api/v2",
    }
    index["generated_from"] = ["data/latest/candles.json",
                              "data/history/<ticker>.json"]
    (LIVE / "candles_index.json").write_text(json.dumps(index, indent=1,
                                                         sort_keys=True))
    print(f"candles: {written} contracts written to live/data/candles/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
