#!/usr/bin/env python3
"""Swing scanner + strategy backtest for the Kalshi demo alert console (session 5ab18dc3).

What this produces (all committed under `data/swings/`, plus the model spec at
`alerts/model.json`):

  swings.json      every >= $0.10 contract-price swing found in the tracked universe,
                   with the exact API URL the candles came from, the bid/ask path around
                   the swing, and the measured post-swing outcome.
  strategies.json  per-strategy expectancy (mean net $/contract, hit rate, ROI on the
                   price paid, after the published Kalshi taker fee) plus the per-bucket
                   calibration table the browser ROI model uses.
  meta.json        run record: mode, params, request/error counts, source list, warnings.
  model.json       machine-readable alert + ROI spec shared by this script and
                   `assets/swing-core.js` (single source of truth for the thresholds).

Everything measured here is derived from the official Kalshi DEMO exchange
(https://external-api.demo.kalshi.co/trade-api/v2, per
https://docs.kalshi.com/getting_started/api_environments.md). No value is inferred: if a
field is not present in the API response it is written as null and the row is flagged.

Verified API shapes used (fetched 2026-11-20, see alerts/SPEC.md for the evidence table):
  * GET /series/{series_ticker}/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval
    -> {ticker, candlesticks:[{end_period_ts, yes_bid{open/low/high/close_dollars},
        yes_ask{...}, price{open/low/high/close/mean/previous/min/max_dollars},
        volume_fp, open_interest_fp}]}; period_interval is MINUTES, valid 1 | 60 | 1440.
    https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md
  * GET /markets?tickers= / ?event_ticker= -> market object with
    last_price_dollars, yes_bid_dollars, yes_ask_dollars, *_size_fp, volume_fp,
    volume_24h_fp, open_interest_fp, close_time, result, status.
    https://docs.kalshi.com/api-reference/market/get-markets.md
  * Binary-market mirror: a YES bid at X is a NO ask at (1 - X) and a YES ask at X is a
    NO bid at (1 - X), identical size -> https://docs.kalshi.com/getting_started/orderbook_responses.md
    (also stated on https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md)
  * Taker fee = round-up(0.07 x C x P x (1 - P)) dollars for a general market
    -> https://kalshi.com/docs/kalshi-fee-schedule.pdf ("General Trading Fees Table":
    P=$0.50, C=100 -> $1.75; reproduced by `tests/swing_scan.test.py::test_fee_table`).

Modes
  --offline  read the committed collector snapshot (`data/latest/candles.json`,
             `data/latest/markets_open.json`). No network. Used in CI pre-merge checks
             and in the dev sandbox (which has no route to kalshi hosts).
  (default)  live: pick the top-dollar open markets per topic from
             `data/latest/markets_open.json`, fetch fresh candlesticks from the demo API
             and scan them. Run from GitHub Actions (`.github/workflows/swing-scan.yml`),
             which has unrestricted egress.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collector"))

# ---------------------------------------------------------------- constants
# Alert rule (owner brief): "sudden swings in contract prices greater than or equal to
# $0.10 in either direction". Worked in integer units of $0.0001 ("bits") so that no
# binary-float error can decide an alert.
BIT = 10000
THRESHOLD_BITS = 1000      # $0.10
REARM_BAND_BITS = 500      # $0.05 -- price must retrace into this band before a new alert

# Demo-exchange synthetic test series that rank high on volume but are not real markets
# (see COORDINATION.md I-15: "KXDEMOFUTHOURLY hourly BTC demos, KXQUICKSETTLE '1+1=2'").
EXCLUDED_SERIES_PREFIX = ("KXDEMOFUTHOURLY", "KXQUICKSETTLE", "KXMVE")

FEE_RATE = 0.07            # general taker fee multiplier, published fee schedule
TOPIC_LABELS = {"gas": "Gas prices", "elections": "Elections", "culture": "Culture",
                "crypto": "Crypto", "golf": "Golf"}
EXIT_HORIZONS = {"15": 15, "60": 60}   # minutes after the alert candle

BUCKETS_PRICE = [(0.00, 0.05, "0-5c"), (0.05, 0.20, "5-20c"), (0.20, 0.50, "20-50c"),
                 (0.50, 0.80, "50-80c"), (0.80, 0.95, "80-95c"), (0.95, 1.01, "95-100c")]
BUCKETS_MOVE = [(1000, 2000, "10-20c"), (2000, 4000, "20-40c"), (4000, 10 ** 9, ">40c")]
BUCKETS_TTC = [(0, 2, "<2h"), (2, 24, "2-24h"), (24, 24 * 14, "1-14d"),
               (24 * 14, 10 ** 6, ">14d")]

SOURCES = [
    "https://docs.kalshi.com/getting_started/api_environments.md",
    "https://docs.kalshi.com/getting_started/demo_env.md",
    "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
    "https://docs.kalshi.com/api-reference/market/get-markets.md",
    "https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md",
    "https://docs.kalshi.com/getting_started/orderbook_responses.md",
    "https://docs.kalshi.com/getting_started/pagination.md",
    "https://docs.kalshi.com/getting_started/market_settlement.md",
    "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
]


# ------------------------------------------------------------------ helpers
def bits(dollars) -> int | None:
    """$ string/number -> integer units of $0.0001 (null when the field is absent)."""
    if dollars is None or dollars == "":
        return None
    try:
        return int(round(float(dollars) * BIT))
    except (TypeError, ValueError):
        return None


def dollars(b: int | None, dp: int = 4) -> float | None:
    return None if b is None else round(b / BIT, dp)


def fnum(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def band(value, table, default="unclassified"):
    if value is None:
        return default
    for lo, hi, name in table:
        if lo <= value < hi:
            return name
    return default


def iso(ts) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


CONTRACTS = 100   # block size the study trades; keeps cent-rounding realistic (see below)


# Exact integer fee arithmetic. With P = price_bits/1e4 and fee = 0.07*C*P*(1-P):
#   dollars * 1e10 = 7*C*price_bits*(1e4 - price_bits) + C*price_bits*1e6   (all integers)
# so cent alignment is a plain integer floor/ceil -- no binary-float drift in the numbers
# that decide a strategy's expectancy. Valid for |num| < 2**53 in JS (guarded) and
# unbounded in Python.
_FEE_SCALE = 10 ** 10
_CENT_SCALE = 10 ** 8      # dollars*1e10 -> cents*1e8


def _num_units(price_b: int, contracts: int, sign: int, multiplier: float = 1.0) -> int:
    """Numerator (over 1e10 dollars) of C*P + sign*0.07*mult*C*P*(1-P), exact integers.

    `multiplier` is the series' own `fee_multiplier` from GET /series/{ticker} (observed
    1 with `fee_type: quadratic` on KXWTIMAX); 0.07 x P x (1-P) is the general quadratic
    formula in the published schedule, so a non-default multiplier scales it.
    """
    base = contracts * price_b * (10 ** 4 - price_b)
    extra = round(7 * base * (multiplier - 1.0)) if multiplier != 1.0 else 0
    return contracts * price_b * 10 ** 6 + sign * (7 * base + extra)


def _model_fee(price_b: int, contracts: int, multiplier: float = 1.0) -> float:
    """0.07 x mult x C x P x (1-P) -- the published general taker formula (fee schedule PDF)."""
    return 7 * contracts * price_b * (10 ** 4 - price_b) / _FEE_SCALE * multiplier


def buy_cost_dollars(price_b: int, contracts: int = CONTRACTS, multiplier: float = 1.0) -> float:
    """Debit for a taker buy: the buyer's balance change is aligned DOWN, so the cost
    (a positive debit) is ceil_cent(C*P + model_fee) -- fee_rounding.md `aligned_change`."""
    num = _num_units(price_b, contracts, +1, multiplier)
    return -((-num) // _CENT_SCALE) / 100.0     # integer ceiling, then cents -> dollars


def sell_proceeds_dollars(price_b: int, contracts: int = CONTRACTS, multiplier: float = 1.0) -> float:
    """Credit for a taker sell: floor_cent(C*P - model_fee) (same doc, seller direction)."""
    num = _num_units(price_b, contracts, -1, multiplier)
    return (num // _CENT_SCALE) / 100.0


def round_trip_fees(buy_b: int, sell_b: int, contracts: int = CONTRACTS) -> float:
    """Effective fees on both legs, derived from the aligned cash flows (never a guess)."""
    paid = buy_cost_dollars(buy_b, contracts) - contracts * (buy_b / BIT)
    kept = contracts * (sell_b / BIT) - sell_proceeds_dollars(sell_b, contracts)
    return round(paid + kept, 6)


# ------------------------------------------------------------ swing detection
def candle_series(candles: list[dict]) -> list[dict]:
    """Normalise candlesticks into (ts, last close, yes bid/ask open+close) rows.

    Uses only documented fields. `close` is `price.close_dollars` (the trade price of the
    period); executable levels come from `yes_bid`/`yes_ask` in the same response.
    """
    rows = []
    for c in sorted(candles, key=lambda x: x.get("end_period_ts") or 0):
        ts = c.get("end_period_ts")
        price = c.get("price") or {}
        yb = c.get("yes_bid") or {}
        ya = c.get("yes_ask") or {}
        rows.append({
            "ts": ts,
            "close": bits(price.get("close_dollars")),
            "open": bits(price.get("open_dollars")),
            "high": bits(price.get("high_dollars")),
            "low": bits(price.get("low_dollars")),
            "yes_bid_close": bits(yb.get("close_dollars")),
            "yes_bid_open": bits(yb.get("open_dollars")),
            "yes_ask_close": bits(ya.get("close_dollars")),
            "yes_ask_open": bits(ya.get("open_dollars")),
            "volume_fp": fnum(c.get("volume_fp")),
            "open_interest_fp": fnum(c.get("open_interest_fp")),
        })
    return [r for r in rows if r["ts"] is not None and r["close"] is not None]


def window_candles_for(window_minutes: int, interval_minutes: int) -> int:
    """Candles that cover `window_minutes` at `interval_minutes` per candle (>= 1).

    Keeps the alert rule identical across 1-minute and 60-minute candles: the anchor is
    always 'the best/worst print of the previous N minutes', never 'the previous N candles'.
    """
    return max(1, int(round(window_minutes / max(1, interval_minutes))))


def detect_swings(rows: list[dict], window_seconds: int, threshold_bits: int = THRESHOLD_BITS,
                  rearm: int = REARM_BAND_BITS) -> list[dict]:
    """Deterministic >= threshold swing detector (shared rule with assets/swing-core.js).

    Exactly mirrored, candle-for-candle, by `KalshiSwingCore.detectSwings` / `.observe`, and
    pinned by the same reference vectors in tests/swing_core.test.js and
    scripts/tests/test_scan_swings.py.

    Rule:
      * anchor window = the candles whose end_period_ts falls in [ts_i - window_seconds, ts_i)
      * UP swing at i    when close[i] - min(close in window) >= threshold
        (a rise of at least the threshold measured off the window's LOW)
      * DOWN swing at i  when max(close in window) - close[i] >= threshold
        (a fall of at least the threshold measured off the window's HIGH)
      * re-arm: after firing, silence until |close[i] - anchor| <= rearm band. A one-way run
        is therefore ONE chat message, not one per candle -- which is what keeps a scrolling
        feed usable -- and the price must give back into the band before a new leg counts.
    """
    out = []
    armed = True
    last_anchor = None
    start = 0
    for i in range(len(rows)):
        ts = rows[i]["ts"]
        while start < i and rows[start]["ts"] < ts - window_seconds:
            start += 1
        if start >= i:                      # no prior print inside the window
            continue
        cur = rows[i]["close"]
        window = rows[start:i]
        hi_at = max(range(len(window)), key=lambda k: window[k]["close"])
        lo_at = min(range(len(window)), key=lambda k: window[k]["close"])
        window_hi = window[hi_at]["close"]
        window_lo = window[lo_at]["close"]
        if not armed:
            if last_anchor is not None and abs(cur - last_anchor) <= rearm:
                armed, last_anchor = True, None
            continue
        direction = None
        anchor = None
        anchor_idx = None
        delta = 0
        up_move, dn_move = cur - window_lo, window_hi - cur
        if up_move >= dn_move:                      # both legs possible: report the larger
            if up_move >= threshold_bits:
                direction, anchor, anchor_idx, delta = "up", window_lo, start + lo_at, up_move
        elif dn_move >= threshold_bits:
            direction, anchor, anchor_idx, delta = "down", window_hi, start + hi_at, dn_move
        if direction is None:
            continue
        out.append({"index": i, "anchor_index": anchor_idx, "direction": direction,
                    "anchor": anchor, "delta_bits": delta, "from": anchor, "to": cur})
        armed, last_anchor = False, anchor
    return out


# ------------------------------------------------------------------ outcomes
STRATEGY_NAMES = ("fade15", "fade60", "momo60", "fade_settle")


def _no_data(reason: str) -> dict:
    """Explicit 'we could not measure this' record -- never a silent 0."""
    return {"status": "not-measurable", "note": reason}


def measure(rows: list[dict], sw: dict, interval_min: int, horizon_min: int = 60,
            multiplier: float = 1.0) -> dict:
    """Post-swing outcome, measured inside a stated horizon (and 'ever' for reference).

    reversion_hit  = within `horizon_min` minutes of the alert, the price gave back at
                     least half the move (the classic mean-reversion test)
    continuation   = the extra distance beyond the swing print inside the same horizon
    Both are also computed over all remaining candles (`*_ever`) so the reader can see how
    much of the 'reversion' is simply the market drifting later. Nothing is extrapolated:
    when the series ends before the horizon, the row says so.
    """
    i = sw["index"]
    delta = sw["delta_bits"]
    end = len(rows) - 1
    k = max(1, int(round(horizon_min / max(1, interval_min))))
    fwd = rows[i + 1:min(i + 1 + k, end + 1)]
    ever = rows[i + 1:end + 1]
    res = {"retrace_dollars_horizon": None, "reversion_hit": None, "continuation_dollars": None,
           "retrace_dollars_ever": None, "reversion_hit_ever": None,
           "candles_in_horizon": len(fwd), "candles_after": len(ever),
           "horizon_minutes": horizon_min, "strategies": {n: _no_data("no forward candles")
                                                           for n in STRATEGY_NAMES}}
    if not ever:
        return res

    def _retrace(window, direction, peak_or_trough):
        if not window:
            return None, None
        if direction == "up":
            back = max(0, peak_or_trough - min(r["close"] for r in window))
            cont = max(0, max(r["close"] for r in window) - peak_or_trough)
        else:
            back = max(0, max(r["close"] for r in window) - peak_or_trough)
            cont = max(0, peak_or_trough - min(r["close"] for r in window))
        return back, cont

    hb, hc = _retrace(fwd or [rows[i]], sw["direction"], sw["to"])
    eb, ec = _retrace(ever, sw["direction"], sw["to"])
    res["retrace_dollars_horizon"] = dollars(hb)
    res["reversion_hit"] = (hb or 0) >= delta // 2 if fwd else None
    res["continuation_dollars"] = dollars(hc)
    res["retrace_dollars_ever"] = dollars(eb)
    res["reversion_hit_ever"] = (eb or 0) >= delta // 2
    if not fwd:
        res["strategies_note"] = "series ended before the 60-minute horizon"

    entry = rows[i + 1] if i + 1 <= end else None
    if entry is None:
        return res
    plan = {"fade15": ("fade", 15), "fade60": ("fade", 60), "momo60": ("momo", 60)}
    for name, (kind, minutes) in plan.items():
        kk = max(1, int(round(minutes / max(1, interval_min))))
        exit_row = rows[min(i + kk, end)]
        rec = simulate_fade(sw["direction"], entry, exit_row, multiplier) if kind == "fade" \
            else simulate_momo(sw["direction"], entry, exit_row, multiplier)
        rec["horizon_minutes_requested"] = minutes
        rec["horizon_minutes_actual"] = kk * interval_min
        res["strategies"][name] = rec
    rec = simulate_fade(sw["direction"], entry, rows[end])
    rec["horizon_minutes_actual"] = (end - i) * interval_min
    res["strategies"]["fade_settle"] = rec
    return res


def _fill_legs(direction: str, row_in: dict, row_out: dict, side: str) -> tuple | None:
    """Executable (price_in, price_out) for one contract, in bits, or None if unquotable.

    side='yes': buy YES at the YES ask, sell YES at the YES bid.
    side='no' : buy NO at (1 - YES bid), sell NO at (1 - YES ask)  [binary mirror].
    """
    ONE = BIT
    if side == "yes":
        pin, pout = row_in.get("yes_ask_open"), row_out.get("yes_bid_close")
    else:
        yb, ya = row_in.get("yes_bid_open"), row_out.get("yes_ask_close")
        pin, pout = (None if yb is None else ONE - yb), (None if ya is None else ONE - ya)
    if pin is None or pout is None or pin <= 0 or pout <= 0 or pin >= ONE or pout >= ONE:
        return None
    return pin, pout


def _net(pay_b: int, recv_b: int, contracts: int = CONTRACTS, multiplier: float = 1.0) -> dict:
    """Round trip on a `contracts`-contract block, priced from the aligned cash flows.

    net_dollars is PER CONTRACT (size-invariant, so the site can scale it); net_block_dollars
    is the cash result of the block actually modelled. Fees come from the published formula
    plus the documented cent alignment -- see buy_cost_dollars/sell_proceeds_dollars.
    """
    cost = buy_cost_dollars(pay_b, contracts, multiplier)
    proceeds = sell_proceeds_dollars(recv_b, contracts, multiplier)
    gross_block = contracts * (recv_b - pay_b) / BIT
    fees = round(cost - contracts * (pay_b / BIT) + contracts * (recv_b / BIT) - proceeds, 6)
    net_block = round(proceeds - cost, 6)
    return {"pay_dollars": round(pay_b / BIT, 4), "receive_dollars": round(recv_b / BIT, 4),
            "contracts": contracts, "cost_block_dollars": round(cost, 4),
            "proceeds_block_dollars": round(proceeds, 4),
            "gross_dollars": round(gross_block / contracts, 6),
            "gross_block_dollars": round(gross_block, 6),
            "contracts": contracts,
            "fees_dollars": round(fees / contracts, 6), "fees_block_dollars": fees,
            "fee_multiplier_used": multiplier,
            "net_dollars": round(net_block / contracts, 6),
            "net_block_dollars": net_block,
            "roi_on_paid": round(net_block / cost, 6) if cost > 0 else None,
            "status": "simulated-fill"}


def simulate_fade(direction: str, row_in: dict, row_out: dict, multiplier: float = 1.0) -> dict:
    """Fade = take the OTHER side of the move (buy NO after an up-swing, buy YES after a
    down-swing) and exit at the horizon. Returns a `not-quotable` record when the candle
    has no bid/ask on the needed side -- never a zeroed fake trade."""
    side = "no" if direction == "up" else "yes"
    legs = _fill_legs(direction, row_in, row_out, side)
    if legs is None:
        return {"status": "not-quotable", "note": "no bid/ask in candle data for that side"}
    out = _net(*legs, multiplier=multiplier)
    out["side"] = side
    return out


def simulate_momo(direction: str, row_in: dict, row_out: dict, multiplier: float = 1.0) -> dict:
    """Momentum = take the SAME side as the move."""
    side = "yes" if direction == "up" else "no"
    legs = _fill_legs(direction, row_in, row_out, side)
    if legs is None:
        return {"status": "not-quotable", "note": "no bid/ask in candle data for that side"}
    out = _net(*legs)
    out["side"] = side
    return out


# --------------------------------------------------------------- aggregates
def agg(rows: list[dict]) -> dict:
    """Aggregate a strategy's per-swing results. Units: dollars PER CONTRACT throughout."""
    ok = [r for r in rows if r.get("net_dollars") is not None]
    n = len(rows)
    if not ok:
        return {"n": n, "n_quotable": 0, "mean_net_dollars": None, "median_net_dollars": None,
                "mean_gross_dollars": None, "hit_rate": None, "hit_rate_gross": None,
                "mean_roi_on_paid": None, "mean_fees_dollars": None,
                "total_net_dollars": None, "unquotable": n, "not_measurable": n - len(ok)}
    if not any("gross_dollars" in r for r in ok):
        pass
    nets = sorted(r["net_dollars"] for r in ok)
    wins = [r for r in ok if r["net_dollars"] > 0]
    rois = [r["roi_on_paid"] for r in ok if r.get("roi_on_paid") is not None]
    mid = nets[len(nets) // 2] if len(nets) % 2 else (nets[len(nets) // 2 - 1] + nets[len(nets) // 2]) / 2
    gross = [r["gross_dollars"] for r in ok if r.get("gross_dollars") is not None]
    return {"n": n, "n_quotable": len(ok),
            "mean_net_dollars": round(sum(nets) / len(nets), 6),
            "median_net_dollars": round(mid, 6),
            "mean_gross_dollars": round(sum(gross) / len(gross), 6) if gross else None,
            "hit_rate": round(len(wins) / len(ok), 4),
            "hit_rate_gross": round(len([g for g in gross if g > 0]) / len(gross), 4) if gross else None,
            "mean_roi_on_paid": round(sum(rois) / len(rois), 6) if rois else None,
            "mean_fees_dollars": round(sum(r.get("fees_dollars") or 0 for r in ok) / len(ok), 6),
            "total_net_dollars": round(sum(nets), 4), "unquotable": n - len(ok),
            "not_measurable": 0}


def bucket_key(topic: str, from_d: float | None, move_bits: int, ttc_hours: float | None) -> str:
    return "|".join([topic or "unclassified", band(from_d, BUCKETS_PRICE),
                     band(move_bits, BUCKETS_MOVE),
                     band(ttc_hours if ttc_hours is not None else None, BUCKETS_TTC)])


def shrink(successes: int, total: int, prior_rate: float, k: int = 4) -> float:
    """Beta(1,1)-style shrinkage of a bucket rate toward the global rate (k pseudo-observes).

    Documented so the browser model and this script agree; prevents a 1-of-1 bucket from
    reading as a 100% edge.
    """
    return round((successes + k * prior_rate) / (total + k), 6)


# ------------------------------------------------------------------- sources
def candle_source_url(root: str, series_ticker: str | None, ticker: str) -> str:
    series = series_ticker or (ticker.split("-", 1)[0] if ticker else "")
    return f"{root}/series/{series}/markets/{ticker}/candlesticks"


# ------------------------------------------------------------- link / probe
NEWS_SEARCH = "https://news.google.com/search?q="


def quote_url(s: str) -> str:
    from urllib.parse import quote
    return quote(s[:120], safe="")


def build_links(api_root: str, market_ticker: str, event_ticker: str | None,
                title: str | None, probe: dict | None) -> list[dict]:
    """Links attached to every alert row.

    Only two kinds are ever marked verified: the API record that the row's numbers came
    from, and (when the CI probe confirmed it resolves) the Kalshi event page. The news
    link is a labelled search deep-link -- a lookup, never an assertion of cause.
    """
    links = [{"kind": "official-api", "label": "API record for this market (source of the row)",
              "url": f"{api_root}/markets?tickers={market_ticker}", "verified": True}]
    verified_root = (probe or {}).get("verified_root")
    if event_ticker:
        if verified_root:
            links.append({"kind": "official-site", "label": "Kalshi event page",
                          "url": f"{verified_root}/event/{event_ticker}", "verified": True,
                          "note": f"CI probe returned 200 with the ticker echoed at "
                                  f"{(probe or {}).get('checked_at')}"})
        else:
            detail = ", ".join(f"{a['site_root']} -> {a.get('status_code') or a.get('error')}"
                               for a in (probe or {}).get("attempts", [])) or "no probe"
            links.append({"kind": "unverified-site", "label": "Kalshi event page (not confirmed)",
                          "url": None, "verified": False,
                          "note": f"probe did not confirm the route ({detail}); "
                                  "see the Flagged register instead of guessing a URL"})
    if title:
        links.append({"kind": "candidate-news-search", "verified": False,
                      "label": "Candidate catalyst search (last 24h) - a lookup link, not a proven cause",
                      "url": NEWS_SEARCH + quote_url(title + " when:1d")})
    return links


SITE_ROOTS = ("https://kalshi.com", "https://demo.kalshi.co")


def _probe_one(site_root: str, event_ticker: str, timeout: float = 20.0) -> dict:
    import urllib.error
    import urllib.request
    out = {"site_root": site_root, "url": f"{site_root}/event/{event_ticker}",
           "status_code": None, "body_bytes": 0, "ticker_echoed": False, "title_echoed": False,
           "error": None}
    try:
        req = urllib.request.Request(out["url"], headers={
            "User-Agent": "Mozilla/5.0 (compatible; kalshi-demo-tracker/1.0 verification probe)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(600_000).decode("utf-8", "replace")
            out["status_code"] = resp.status
            out["body_bytes"] = len(body)
            out["ticker_echoed"] = event_ticker in body
    except urllib.error.HTTPError as exc:
        out["status_code"] = exc.code
        out["error"] = f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - a probe failure is recorded, never fatal
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    out["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def probe_event_page(event_ticker: str | None, timeout: float = 20.0) -> dict:
    """Does Kalshi's public event page actually resolve for a tracked event?

    Run from CI (the dev sandbox has no route to kalshi hosts). The console only renders an
    event-page link when a probe returned HTTP 200 AND echoed the ticker; anything else
    (404, 429, blocked, SPA with no server HTML) is recorded as unverified and the link is
    omitted rather than guessed. Each attempt is kept so the Flagged page can show why.
    """
    out = {"attempted": bool(event_ticker), "attempts": [], "verified_root": None}
    if not event_ticker:
        out["error"] = "no event ticker in the snapshot to probe"
        return out
    for root in SITE_ROOTS:
        att = _probe_one(root, event_ticker, timeout)
        out["attempts"].append(att)
        time.sleep(2.0)
        if att["status_code"] == 200 and att["ticker_echoed"] and not out["verified_root"]:
            out["verified_root"] = root
    out["status_code"] = out["attempts"][0]["status_code"]
    out["ticker_echoed"] = bool(out["verified_root"])
    out["checked_at"] = out["attempts"][-1]["checked_at"]
    return out


def poll_resolutions(client, api_root: str, tickers: list[str]) -> dict:
    """Re-poll /markets?tickers= for every swung market: status + yes/no result + settle time.

    Implements the brief's 'track live events until the events have resolved' for the scan
    universe. Batches of 50 tickers (the documented comma-list filter; the batch orderbook
    endpoint caps at 100 -- /markets limit max is 1000, see get-markets docs).
    """
    out: dict[str, dict] = {}
    for i in range(0, len(tickers), 50):
        chunk = tickers[i:i + 50]
        try:
            data = client.request("GET", "/markets", params={"tickers": ",".join(chunk), "limit": 200})
        except Exception as exc:  # noqa: BLE001
            for t in chunk:
                out[t] = {"resolution_poll_error": str(exc)[:160]}
            continue
        for m in data.get("markets", []):
            t = m.get("ticker")
            out[t] = {"status": m.get("status"), "result": m.get("result") or None,
                      "settlement_ts": m.get("settlement_ts") or None,
                      "settlement_value_dollars": m.get("settlement_value_dollars") or None,
                      "last_price_dollars": m.get("last_price_dollars"),
                      "resolution_source_url": f"{api_root}/markets?tickers={t}"}
    return out


def fetch_series_meta(client, root: str, series_list) -> dict:
    """GET /series/{series_ticker} for each series in the universe.

    The response carries the exchange's own answer to "what moves/ settles this market":
    `settlement_sources[].{name,url}`, `fee_type`, `fee_multiplier`, `contract_terms_url`,
    `categories`, `tags`. Shape verified live 2026-11-20 against
    https://external-api.demo.kalshi.co/trade-api/v2/series/KXWTIMAX (ICE, quadratic, 1)
    and documented on https://docs.kalshi.com/api-reference/market/get-series.md
    """
    meta = {}
    for series in sorted({s for s in series_list if s}):
        try:
            data = client.request("GET", f"/series/{series}")
            entry = data.get("series") or {}
            meta[series] = {
                "series_ticker": series,
                "title": entry.get("title"),
                "category": entry.get("category"),
                "categories": entry.get("categories"),
                "tags": entry.get("tags"),
                "frequency": entry.get("frequency"),
                "fee_type": entry.get("fee_type"),
                "fee_multiplier": entry.get("fee_multiplier"),
                "settlement_sources": entry.get("settlement_sources") or [],
                "contract_terms_url": entry.get("contract_terms_url"),
                "expected_volume_initial": entry.get("expected_volume_initial"),
                "source_url": f"{root}/series/{series}",
            }
        except Exception as exc:  # noqa: BLE001
            meta[series] = {"series_ticker": series, "error": str(exc)[:160],
                            "source_url": f"{root}/series/{series}"}
    return meta


def offline_series_meta() -> dict:
    """Series metadata committed by an earlier live run, if any."""
    path = os.path.join(ROOT, "data", "swings", "series_meta.json")
    if os.path.exists(path):
        try:
            return json.load(open(path)).get("by_series", {})
        except Exception:
            return {}
    return {}


# ------------------------------------------------------------------- offline
def load_offline():
    """Build scan inputs from the committed collector snapshot (no network)."""
    latest = os.path.join(ROOT, "data", "latest")
    candles = {}
    path = os.path.join(latest, "candles.json")
    if os.path.exists(path):
        candles = json.load(open(path)).get("by_market", {}) or {}
    markets = {}
    mpath = os.path.join(latest, "markets_open.json")
    if os.path.exists(mpath):
        for m in json.load(open(mpath)).get("markets", []):
            markets[m["ticker"]] = m
    spath = os.path.join(latest, "markets_settled.json")
    if os.path.exists(spath):
        try:
            for m in json.load(open(spath)).get("markets", []):
                markets.setdefault(m["ticker"], m)
        except Exception:
            pass
    units = []
    for ticker, entry in candles.items():
        meta = markets.get(ticker, {})
        windows = []
        for wname, w in (entry.get("windows") or {}).items():
            interval = 60 if wname.startswith("1h") else (1 if wname.startswith("1m") else 1440)
            windows.append({"label": wname, "interval_minutes": interval,
                            "candlesticks": w.get("candlesticks") or []})
        units.append({"ticker": ticker, "series_ticker": entry.get("series_ticker"),
                      "market": meta, "windows": windows,
                      "source_url": entry.get("source_url") or meta.get("source_url"),
                      "offline": True})
    return units


# --------------------------------------------------------------------- live
def pick_live_universe(markets: list[dict], per_topic: int) -> dict:
    """Top-dollar open markets per topic, excluding demo synthetic series and MVE combos.

    Ranking uses the collector's labelled estimate (volume_fp x notional), which is the
    same published ranking the dashboard uses (see COORDINATION.md I-16 / F4).
    """
    by_topic: dict[str, list[dict]] = {}
    for m in markets:
        topic = m.get("topic")
        if not topic:
            continue
        series = m.get("series_ticker") or ""
        if series.startswith(EXCLUDED_SERIES_PREFIX):
            continue
        if m.get("mve_collection_ticker"):
            continue
        by_topic.setdefault(topic, []).append(m)
    out = {}
    for topic, rows in by_topic.items():
        rows.sort(key=lambda r: -(r.get("volume_dollars_derived") or 0.0))
        out[topic] = rows[:per_topic]
    return out


def fetch_candles(client, root: str, series_ticker: str, ticker: str, hours: int,
                  interval: int) -> tuple[list[dict], str]:
    end = int(time.time())
    start = end - hours * 3600
    params = {"start_ts": start, "end_ts": end, "period_interval": interval}
    data = client.request("GET", f"/series/{series_ticker}/markets/{ticker}/candlesticks",
                          params=params)
    return (data.get("candlesticks") or []), (
        f"{root}/series/{series_ticker}/markets/{ticker}/candlesticks"
        f"?start_ts={start}&end_ts={end}&period_interval={interval}")


def live_units(args) -> tuple[list[dict], dict]:
    from kalshi_api import KalshiClient, DEMO_REST_ROOT  # noqa: PLC0415
    root = os.environ.get("KALSHI_API_ROOT", DEMO_REST_ROOT)
    client = KalshiClient(root=root, min_interval=args.interval_seconds)
    mpath = os.path.join(ROOT, "data", "latest", "markets_open.json")
    markets = json.load(open(mpath)).get("markets", []) if os.path.exists(mpath) else []
    universe = pick_live_universe(markets, args.per_topic)
    units, warnings = [], []
    now = datetime.now(timezone.utc)
    for topic, rows in sorted(universe.items()):
        for m in rows:
            ticker = m["ticker"]
            series = m.get("series_ticker") or ticker.split("-", 1)[0]
            windows = []
            for interval, hours in ((1, args.hours_1m), (60, args.hours_60m)):
                try:
                    candles, url = fetch_candles(client, root, series, ticker, hours, interval)
                    windows.append({"label": f"{interval}m_{hours}h",
                                    "interval_minutes": interval, "candlesticks": candles,
                                    "source_url": url,
                                    "window": {"start_ts": int((now - timedelta(hours=hours)).timestamp()),
                                               "end_ts": int(now.timestamp())}})
                except Exception as exc:  # a 404/429 on one market must not kill the scan
                    warnings.append(f"candles {ticker} @{interval}m: {exc}")
            if not windows:
                continue
            units.append({"ticker": ticker, "series_ticker": series, "market": m,
                          "windows": windows, "topic": topic, "offline": False})
            time.sleep(args.interval_seconds)
    res_poll = poll_resolutions(client, root, [u["ticker"] for u in units])
    for u in units:
        u["resolution"] = res_poll.get(u["ticker"]) or {}
    probe = probe_event_page(next((u["market"].get("event_ticker") for u in units
                                   if u["market"].get("event_ticker")), None))
    stats = {"requests": client.request_count, "errors": client.error_count,
             "event_page_probe": probe,
             "warnings": warnings[-40:], "api_root": root,
             "universe_counts": {t: len(v) for t, v in sorted(universe.items())}}
    return units, stats, client


# ------------------------------------------------------------------ main
def run(args) -> int:
    started = datetime.now(timezone.utc)
    client = None
    if args.offline and args.out == "data/swings" and not args.allow_offline_overwrite:
        # The published files are the workflow's job; the offline self-test is a code test.
        # Two sessions tripped over this in one hour, so the foot-gun is now a hard error.
        print("refusing to write synthetic offline data into the published data/swings/ and "
              "alerts/model.json - pass --out /tmp/yourdir (or --allow-offline-overwrite if you "
              "really mean it)", file=sys.stderr)
        return 4
    if args.offline:
        units, stats = load_offline(), {"mode": "offline", "requests": 0, "errors": 0,
                                       "warnings": [], "event_page_probe": {"attempted": False,
                                       "status_code": None, "ticker_echoed": False,
                                       "error": "offline mode does not probe (no route from the dev sandbox)"}}
        root = "https://external-api.demo.kalshi.co/trade-api/v2"
    else:
        units, stats, client = live_units(args)
        root = stats.pop("api_root")
        stats["mode"] = "live"
        reqs = stats.get("requests") or 0
        if not units or (reqs and stats.get("errors") == reqs):
            # A run that could not read the API must not blank the published calibration:
            # exit before any file is written (the dev sandbox has no direct route to the
            # demo host, so this also protects `python3 scripts/scan_swings.py` from here).
            print("FAIL: live scan produced no usable market data "
                  f"(units={len(units)}, requests={reqs}, errors={stats.get('errors')}) - "
                  "refusing to overwrite data/swings/*.json or alerts/model.json", file=sys.stderr)
            for w in (stats.get("warnings") or [])[:5]:
                print("   ", w, file=sys.stderr)
            return 2
    stats["universe_units"] = len(units)
    probe = stats.get("event_page_probe") or {}

    series_list = [u.get("series_ticker") or (u["ticker"].split("-", 1)[0] if u.get("ticker") else None)
                   for u in units]
    if args.offline:
        series_meta = offline_series_meta()
        stats["series_meta_source"] = "committed data/swings/series_meta.json (from a live run)"
    else:
        series_meta = fetch_series_meta(client, root, series_list)
        stats["series_meta_source"] = "fetched this run"
    write(os.path.join(ROOT, args.out, "series_meta.json"),
          {"meta": {"generated_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endpoint": f"{root}/series/{{series_ticker}}",
                    "doc": "https://docs.kalshi.com/api-reference/market/get-series.md"},
           "by_series": series_meta})

    swings_out, strat_rows = [], []
    for unit in units:
        m = unit.get("market") or {}
        topic = unit.get("topic") or m.get("topic")
        resolution = unit.get("resolution") or {}
        close_time = resolution.get("close_time") or m.get("close_time")
        ttc_hours = None
        if close_time:
            try:
                ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                ttc_hours = (ct - started).total_seconds() / 3600.0
            except ValueError:
                ttc_hours = None
        series_key = unit.get("series_ticker") or (unit["ticker"].split("-", 1)[0] if unit.get("ticker") else "")
        smeta = series_meta.get(series_key) or {}
        fee_mult = smeta.get("fee_multiplier")
        fee_mult = float(fee_mult) if isinstance(fee_mult, (int, float)) else 1.0
        for window in unit["windows"]:
            interval = int(window.get("interval_minutes") or 1)
            window_seconds = args.window_minutes * 60
            min_candles = window_candles_for(args.window_minutes, interval)
            rows = candle_series(window.get("candlesticks") or [])
            if len(rows) <= min_candles:
                continue
            src = window.get("source_url") or unit.get("source_url") or candle_source_url(
                root, unit.get("series_ticker"), unit["ticker"])
            for sw in detect_swings(rows, window_seconds, args.threshold_bits, args.rearm_bits):
                outcome = measure(rows, sw, interval, multiplier=fee_mult)
                from_d, to_d = dollars(sw["from"]), dollars(sw["to"])
                key = bucket_key(topic, from_d, sw["delta_bits"], ttc_hours)
                settle_ts = resolution.get("settlement_ts")
                resolved_after = None
                if settle_ts and rows[sw["index"]]["ts"]:
                    try:
                        resolved_after = datetime.fromisoformat(
                            settle_ts.replace("Z", "+00:00")).timestamp() > rows[sw["index"]]["ts"]
                    except ValueError:
                        resolved_after = None
                rec = {
                    "id": f"{unit['ticker']}@{sw['index']}:{window['label']}",
                    "topic": topic,
                    "topic_label": TOPIC_LABELS.get(topic or "", "unclassified"),
                    "market_ticker": unit["ticker"],
                    "series_ticker": unit.get("series_ticker"),
                    "event_ticker": m.get("event_ticker"),
                    "market_title": m.get("title") or m.get("yes_sub_title"),
                    "event_title": m.get("event_title"),
                    "direction": sw["direction"],
                    "window_minutes": args.window_minutes,
                    "window_candles_approx": min_candles,
                    "candle_interval_minutes": interval,
                    "window_label": window["label"],
                    "swing_start_ts": rows[sw["anchor_index"]]["ts"],
                    "swing_end_ts": rows[sw["index"]]["ts"],
                    "swing_start_iso": iso(rows[sw["anchor_index"]]["ts"]),
                    "swing_end_iso": iso(rows[sw["index"]]["ts"]),
                    "from_dollars": from_d,
                    "to_dollars": to_d,
                    "delta_dollars": round(sw["delta_bits"] / BIT, 4),
                    "delta_pct_of_from": round(sw["delta_bits"] / sw["from"], 6) if sw["from"] else None,
                    "volume_fp_at_swing": rows[sw["index"]]["volume_fp"],
                    "open_interest_fp_at_swing": rows[sw["index"]]["open_interest_fp"],
                    "yes_bid_dollars": dollars(rows[sw["index"]]["yes_bid_close"]),
                    "yes_ask_dollars": dollars(rows[sw["index"]]["yes_ask_close"]),
                    "spread_dollars": (round((rows[sw["index"]]["yes_ask_close"] - rows[sw["index"]]["yes_bid_close"]) / BIT, 4)
                                       if rows[sw["index"]]["yes_ask_close"] is not None
                                       and rows[sw["index"]]["yes_bid_close"] is not None else None),
                    "market_status": resolution.get("status") or m.get("status"),
                    "result": resolution.get("result") or (m.get("result") or None),
                    "settlement_ts": settle_ts,
                    "settlement_value_dollars": resolution.get("settlement_value_dollars"),
                    "resolved_after_swing": resolved_after,
                    "close_time": close_time,
                    "hours_to_close": round(ttc_hours, 3) if ttc_hours is not None else None,
                    "retrace_dollars": outcome["retrace_dollars_horizon"],
                    "reversion_hit": outcome["reversion_hit"],
                    "retrace_dollars_ever": outcome["reversion_hit_ever"],
                    "reversion_hit_ever": outcome["reversion_hit_ever"],
                    "continuation_dollars": outcome["continuation_dollars"],
                    "candles_in_horizon": outcome["candles_in_horizon"],
                    "candles_after": outcome["candles_after"],
                    "horizon_minutes": outcome["horizon_minutes"],
                    "strategies": outcome["strategies"],
                    "bucket": key,
                    "bucket_price_band": band(from_d, BUCKETS_PRICE),
                    "bucket_move_band": band(sw["delta_bits"], BUCKETS_MOVE),
                    "bucket_ttc_band": band(ttc_hours, BUCKETS_TTC),
                    "est_dollar_volume_market": round((fnum(m.get("volume_fp")) or 0.0) * (fnum(m.get("last_price_dollars")) or 0.0), 2) if m else None,
                    "source_url": src,
                    "resolution_source_url": resolution.get("resolution_source_url"),
                    "rules_primary": m.get("rules_primary"),
                    "settlement_sources": smeta.get("settlement_sources") or [],
                    "series_category": smeta.get("category"),
                    "series_tags": smeta.get("tags"),
                    "fee_type": smeta.get("fee_type"),
                    "fee_multiplier": smeta.get("fee_multiplier"),
                    "contract_terms_url": smeta.get("contract_terms_url"),
                    "links": build_links(root, unit["ticker"], m.get("event_ticker"),
                                         m.get("title") or m.get("yes_sub_title"), probe),
                    "flag": None if m.get("event_ticker") else "no-event-ticker-in-snapshot",
                }
                swings_out.append(rec)
                for sname, sdata in outcome["strategies"].items():
                    strat_rows.append({"strategy": sname, "topic": topic, "bucket": key,
                                       "direction": sw["direction"], **sdata})

    # -------- strategy aggregates + bucket calibration
    strategies = {}
    for sname in sorted({r["strategy"] for r in strat_rows}):
        rows = [r for r in strat_rows if r["strategy"] == sname]
        a = agg(rows)
        a["direction_split"] = {d: len([r for r in rows if r["direction"] == d])
                                for d in ("up", "down")}
        strategies[sname] = {"overall": a,
                             "by_topic": {t: agg([r for r in rows if r.get("topic") == t])
                                          for t in sorted({r.get("topic") for r in rows} if rows else [])}}
    global_rev = round(len([s for s in swings_out if s["reversion_hit"]]) / len(swings_out), 6) if swings_out else None
    _hit_cache = {}

    def global_hit_rate(name: str):
        """Global post-fee win rate for a strategy -- the shrinkage prior for its buckets."""
        if name not in _hit_cache:
            rows = [r for r in strat_rows if r["strategy"] == name and r.get("net_dollars") is not None]
            _hit_cache[name] = round(len([r for r in rows if r["net_dollars"] > 0]) / len(rows), 6) if rows else None
        return _hit_cache[name]

    global_fade_hit = global_hit_rate("fade60")

    buckets = {}
    for s in swings_out:
        b = buckets.setdefault(s["bucket"], {"n": 0, "reversion_hits": 0, "reversion_hits_ever": 0,
                                             "strat": {}, "markets": set(),
                                             "mean_delta_dollars": 0.0, "resolved_yes": 0,
                                             "resolved_no": 0, "unresolved": 0})
        b["n"] += 1
        b["markets"].add(s["market_ticker"])
        b["mean_delta_dollars"] += s["delta_dollars"]
        if s["reversion_hit"]:
            b["reversion_hits"] += 1
        if s.get("reversion_hit_ever"):
            b["reversion_hits_ever"] += 1
        if s.get("result") == "yes":
            b["resolved_yes"] += 1
        elif s.get("result") == "no":
            b["resolved_no"] += 1
        else:
            b["unresolved"] += 1
        for name, rec in (s["strategies"] or {}).items():
            if rec.get("net_dollars") is None:
                continue
            acc = b["strat"].setdefault(name, {"n": 0, "wins": 0, "net_sum": 0.0, "gross_sum": 0.0})
            acc["n"] += 1
            acc["net_sum"] += rec["net_dollars"]
            acc["gross_sum"] += rec.get("gross_dollars") or 0.0
            if rec["net_dollars"] > 0:
                acc["wins"] += 1
    calib = {}
    for key, b in sorted(buckets.items()):
        n_markets = len(b["markets"])
        b["mean_delta_dollars"] = round(b["mean_delta_dollars"] / b["n"], 6)
        b["n_markets"] = n_markets
        b.pop("markets")
        rev_rate = round(b["reversion_hits"] / b["n"], 6)
        enough = b["n"] >= args.min_bucket_n and n_markets >= args.min_bucket_markets
        per_strat = {}
        for name, acc in sorted(b["strat"].items()):
            per_strat[name] = {
                "n_quotable": acc["n"],
                "hit_rate": round(acc["wins"] / acc["n"], 6),
                "hit_rate_shrunk": shrink(acc["wins"], acc["n"], global_hit_rate(name) or 0.5),
                "mean_net_dollars": round(acc["net_sum"] / acc["n"], 6),
                "mean_gross_dollars": round(acc["gross_sum"] / acc["n"], 6),
            }
        best_name, best_net = None, None
        for name, v in per_strat.items():
            if best_net is None or v["mean_net_dollars"] > best_net:
                best_name, best_net = name, v["mean_net_dollars"]
        fade = per_strat.get("fade60") or per_strat.get("fade15")
        calib[key] = {
            "n_swings": b["n"], "n_markets": n_markets,
            "resolved_yes": b["resolved_yes"], "resolved_no": b["resolved_no"],
            "unresolved": b["unresolved"],
            "reversion_rate": rev_rate,
            "reversion_rate_within_horizon_minutes": 60,
            "reversion_rate_shrunk": shrink(b["reversion_hits"], b["n"], global_rev or 0.5),
            "reversion_rate_ever": round(b["reversion_hits_ever"] / b["n"], 6),
            "fade_n_quotable": (fade or {}).get("n_quotable"),
            "fade_hit_rate": (fade or {}).get("hit_rate"),
            "fade_hit_rate_shrunk": (fade or {}).get("hit_rate_shrunk"),
            "fade_mean_net_dollars": (fade or {}).get("mean_net_dollars"),
            "strategies": per_strat,
            "best_strategy": best_name, "best_mean_net_dollars": best_net,
            "evidence": "sufficient" if enough else "insufficient",
            "evidence_rule": f"n_swings >= {args.min_bucket_n} and n_markets >= {args.min_bucket_markets}",
        }

    # -------- per-event rollup for the site tables (organised by topic, events grouped)
    events: dict[str, dict] = {}
    for s in swings_out:
        e = events.setdefault(s["event_ticker"] or s["market_ticker"], {
            "event_ticker": s["event_ticker"], "topic": s["topic"],
            "topic_label": s["topic_label"], "title": s["event_title"] or s["market_title"],
            "n_swings": 0, "markets_flagged": set(), "max_abs_delta_dollars": 0.0,
            "last_swing_iso": None, "first_swing_iso": None, "results": set(),
            "reversion_hits": 0, "source_urls": set(), "close_time": s.get("close_time"),
            "status": s.get("market_status"), "series": set(),
        })
        e["n_swings"] += 1
        e["markets_flagged"].add(s["market_ticker"])
        e["series"].add(s["series_ticker"])
        e["source_urls"].add(s["source_url"])
        if s.get("resolution_source_url"):
            e["source_urls"].add(s["resolution_source_url"])
        e["max_abs_delta_dollars"] = max(e["max_abs_delta_dollars"], s["delta_dollars"])
        e["reversion_hits"] += 1 if s["reversion_hit"] else 0
        ts = s["swing_end_iso"]
        e["last_swing_iso"] = max(e["last_swing_iso"] or "", ts or "")
        e["first_swing_iso"] = min(e["first_swing_iso"] or "9999", ts or "9999")
        if s.get("result"):
            e["results"].add(s["result"])
    event_rows = []
    for e in sorted(events.values(), key=lambda x: (-x["n_swings"], -x["max_abs_delta_dollars"])):
        e["markets_flagged"] = sorted(e["markets_flagged"])
        e["series"] = sorted(x for x in e["series"] if x)
        e["source_urls"] = sorted(e["source_urls"])
        e["resolution_outcome"] = ("/".join(sorted(e["results"])) if e["results"] else None)
        e["reversion_rate"] = round(e["reversion_hits"] / e["n_swings"], 4)
        e.pop("results")
        event_rows.append(e)

    model = {
        "generated_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": stats["mode"],
        "api_root": root,
        "alert_rule": {
            "threshold_dollars": args.threshold_bits / BIT,
            "rearm_band_dollars": args.rearm_bits / BIT,
            "window_minutes_default": args.window_minutes,
            "window_minutes_options": [5, 10, 30, 60, 180, 360, 1440],
            "directions": ["up", "down"],
            "definition": "up_move = close[i] - min(close over the previous window) (the leg is "
                          "measured OFF THE WINDOW LOW); down_move = max(close over the previous "
                          "window) - close[i] (measured off the window HIGH). Fire 'up' when "
                          "up_move >= max(down_move, threshold); otherwise fire 'down' when "
                          "down_move >= max(up_move, threshold) - the stronger leg of the two wins, "
                          "so one run in one direction prints one alert. Re-arm once "
                          "|close[i] - anchor| <= the re-arm band. The window is measured in MINUTES "
                          "and converted to candles per candle interval, and windows that start at "
                          "or after index i are skipped. (An earlier copy of this string described a "
                          "breakout off the prior extreme, which is not what the code does; both "
                          "runtimes are pinned by the same reference vectors.)",
            "source_of_truth": "scripts/scan_swings.py::detect_swings mirrored by "
                               "assets/swing-core.js::detectSwings",
            "live_price_field": "last_price_dollars (with yes_bid_dollars/yes_ask_dollars for "
                                "the executable path)",
            "fields_doc": "https://docs.kalshi.com/api-reference/market/get-markets.md",
        },
        "link_rules": {
            "api_record": f"{root}/markets?tickers={{ticker}}",
            "event_page_probe": probe,
            "event_page_linked_only_if_probe_200_and_echoed": True,
            "news_link_policy": "search deep-link labelled as a candidate, never a proven cause",
        },
        "roi_model": {
            "weights": {"calibrated_edge": 0.35, "relative_move": 0.20, "executability": 0.20,
                        "liquidity_depth": 0.15, "time_to_resolution": 0.10},
            "pass_threshold_score": 0.60,
            "min_bucket_n": args.min_bucket_n,
            "min_bucket_markets": args.min_bucket_markets,
            "global_reversion_rate": global_rev,
            "global_fade_hit_rate": global_fade_hit,
            "shrinkage_pseudo_count": 4,
            "buckets": calib,
            "excluded_series_prefixes": list(EXCLUDED_SERIES_PREFIX),
            "excluded_reason": "demo synthetic exchange-test series and MVE combos "
                               "(COORDINATION.md I-15; /markets mve_filter docs)",
            "strategy_names": list(STRATEGY_NAMES),
            "reversion_horizon_minutes": 60,
            "edge_definition": "max over the measured strategies of the bucket's mean net "
                               "$/contract (best_strategy / best_mean_net_dollars); a bucket "
                               "with no positive strategy is not a pick",
            "fee_model": {"taker_rate_multiplier": FEE_RATE,
                          "formula": "ceil(0.07 * C * P * (1-P)) dollars per round-trip leg",
                          "source": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
                          "rounding_doc": "https://docs.kalshi.com/getting_started/fee_rounding.md"},
        },
        "sources": SOURCES,
    }

    outdir = os.path.join(ROOT, args.out)
    os.makedirs(outdir, exist_ok=True)
    payload_meta = {
        "generated_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_root": root,
        "threshold_dollars": args.threshold_bits / BIT,
        "window_minutes": args.window_minutes,
        "rearm_band_dollars": args.rearm_bits / BIT,
        "per_topic_markets": args.per_topic,
        "hours_1m": args.hours_1m, "hours_60m": args.hours_60m,
        "swings_found": len(swings_out),
        "events_with_swings": len(event_rows),
        "markets_scanned": len(units),
        "event_page_probe": probe,
        "stats": stats,
        "sources": SOURCES,
        "caveats": [
            "Demo exchange: prices, volumes and liquidity are simulated test data, not real "
            "markets (https://docs.kalshi.com/getting_started/demo_env.md).",
            "Candlestick OHLC is the per-period trade price plus the quoted YES bid/ask at the "
            "period open/close; fills assume the taker crosses that quote exactly and ignore "
            "book depth -- optimistic, see alerts/SPEC.md 'Fill model'.",
            "Reversion is measured within a stated 60-minute horizon; the '*_ever' fields show "
            "what happens over the rest of the available series. Reading the ever-variant as a "
            "tradeable edge would be wrong -- that is why both are published.",
            "Block size for fees and PnL is 100 contracts; net figures are per contract so they "
            "scale, and the fee alignment matches Kalshi's published schedule exactly.",
            "Strategies are simulated trades; no order was sent to Kalshi (no demo API "
            "credentials exist in this repo -- COORDINATION.md I-12).",
            "External news links are search deep-links offered as candidate catalysts; timing "
            "proximity is not evidence of causation.",
        ],
    }
    write(os.path.join(outdir, "swings.json"), {"meta": payload_meta, "swings": swings_out})
    write(os.path.join(outdir, "strategies.json"), {
        "meta": payload_meta, "strategies": strategies,
        "buckets": calib, "bucket_detail": buckets,
        "counts": {"swings": len(swings_out), "strategy_rows": len(strat_rows),
                   "events": len(event_rows)},
    })
    write(os.path.join(outdir, "events.json"), {"meta": payload_meta, "events": event_rows})
    write(os.path.join(outdir, "meta.json"), payload_meta)
    # the browser console reads alerts/model.json; a run pointed at another --out (the CI
    # offline self-test uses /tmp) must leave the committed file alone
    if args.out == "data/swings":
        write(os.path.join(ROOT, "alerts", "model.json"), model)

    print(f"[scan_swings] mode={stats['mode']} units={len(units)} swings={len(swings_out)} "
          f"events={len(event_rows)} rows={len(strat_rows)} requests={stats.get('requests')} "
          f"errors={stats.get('errors')}")
    for sname, s in strategies.items():
        o = s["overall"]
        print(f"  {sname:>13}: n={o['n']} quotable={o['n_quotable']} "
              f"mean_net=${o['mean_net_dollars']} hit={o['hit_rate']} roi={o['mean_roi_on_paid']}")
    print("  event-page probe:", json.dumps(probe)[:220])
    if stats.get("warnings"):
        print("  warnings:", *stats["warnings"][:5], sep="\n    ")
    if args.fail_on_empty and not swings_out and not args.offline:
        print("FAIL: live scan found zero swings", file=sys.stderr)
        return 3
    return 0


def write(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
    print("  wrote", os.path.relpath(path, ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--offline", action="store_true", help="use committed snapshot, no network")
    p.add_argument("--out", default="data/swings", help="output directory (repo-relative)")
    p.add_argument("--allow-offline-overwrite", action="store_true",
                   help="let --offline write into the published data/swings/ + alerts/model.json")
    p.add_argument("--per-topic", type=int, default=12, dest="per_topic",
                   help="top-dollar open markets per topic to scan (live mode)")
    p.add_argument("--hours-1m", type=int, default=48, dest="hours_1m")
    p.add_argument("--hours-60m", type=int, default=168, dest="hours_60m")
    p.add_argument("--interval-seconds", type=float, default=0.25, dest="interval_seconds")
    p.add_argument("--window-minutes", type=int, default=60, dest="window_minutes",
                   help="lookback used for the swing anchor, in minutes")
    p.add_argument("--threshold-bits", type=int, default=THRESHOLD_BITS, dest="threshold_bits")
    p.add_argument("--rearm-bits", type=int, default=REARM_BAND_BITS, dest="rearm_bits")
    p.add_argument("--min-bucket-n", type=int, default=8, dest="min_bucket_n")
    p.add_argument("--min-bucket-markets", type=int, default=3, dest="min_bucket_markets",
                   help="independent markets required before a bucket calls its evidence sufficient")
    p.add_argument("--fail-on-empty", action="store_true", dest="fail_on_empty")
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
