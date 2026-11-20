#!/usr/bin/env python3
"""Build the data files for the Live Alert Desk (live/).

Everything written here is derived from one of two kinds of input:

  1. Official Kalshi DEMO API responses already committed in ``data/latest/``
     (markets, events, series, orderbooks) or fetched by this script from
     ``https://external-api.demo.kalshi.co/trade-api/v2`` — endpoint paths and
     response fields verified against https://docs.kalshi.com (links below).
  2. Candlestick history for the tracked markets
     (``/series/{series_ticker}/markets/{ticker}/candlesticks``,
     https://docs.kalshi.com/api-reference/market/get-market-candlesticks),
     cached under ``live/data/candles/`` so repeat builds are deterministic.

No value is ever invented. Numbers that the exchange does not publish (dollar
volume) are labelled as derived; quantities this project models itself (ROI
score, expected value, simulated fills) are labelled as model/simulated and
carry the exact formula on the page.

Outputs (all under ``live/data/``):

  meta.json        build metadata, endpoint list, formulas, source links
  markets.json     tracked lines: topic, event, price, liquidity, derived volume, ROI model
  alerts.json      swing alerts (>= $0.10 move) for the "all events" chat
  alerts_roi.json  the same events filtered by the high-ROI model (chat 2)
  candles.json     price series for the tracked lines (1-minute and 1-hour)
  trades.json      auto-simulated trades (deterministic seed) + strategy attribution
  portfolio.json   simulated per-strategy portfolios, P&L, drawdown, resolution results
  resolutions.json resolved/closed lines with yes/no outcome, grouped by topic
  review.json      irregularities + unverified items for the site's Flagged page

Run:  python3 scripts/build_live_data.py            (uses committed snapshots only)
      python3 scripts/build_live_data.py --fetch    (fetch candlesticks, then build)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LIVE = ROOT / "live" / "data"
CANDLE_CACHE = LIVE / "candles"

API = "https://external-api.demo.kalshi.co/trade-api/v2"

SOURCES = {
    "api_environments": "https://docs.kalshi.com/getting_started/api_environments",
    "demo_env": "https://docs.kalshi.com/getting_started/demo_env",
    "market_data_no_auth": "https://docs.kalshi.com/getting_started/quick_start_market_data",
    "get_markets": "https://docs.kalshi.com/api-reference/market/get-markets",
    "get_market": "https://docs.kalshi.com/api-reference/market/get-market",
    "get_events": "https://docs.kalshi.com/api-reference/events/get-events",
    "get_orderbook": "https://docs.kalshi.com/api-reference/market/get-market-orderbook",
    "get_candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
    "get_trades": "https://docs.kalshi.com/api-reference/market/get-trades",
    "market_settlement": "https://docs.kalshi.com/getting_started/market_settlement",
    "fixed_point": "https://docs.kalshi.com/getting_started/fixed_point_migration",
    "rate_limits": "https://docs.kalshi.com/getting_started/rate_limits",
    "websockets_auth": "https://docs.kalshi.com/getting_started/quick_start_websockets",
    "create_order": "https://docs.kalshi.com/api-reference/orders/create-order-v2",
    "get_balance": "https://docs.kalshi.com/api-reference/portfolio/get-balance",
    "get_positions": "https://docs.kalshi.com/api-reference/portfolio/get-positions",
}

TOPICS = ("gas", "elections", "culture", "crypto", "golf")
TOPIC_LABEL = {"gas": "Gas prices", "elections": "Elections", "culture": "Culture",
               "crypto": "Crypto", "golf": "Golf"}

# Series that exist only on the demo exchange as exchange self-tests. They are
# excluded from tracking/ranking and reported in review.json (see flag L-02).
SYNTHETIC_SERIES = ("KXDEMOFUTHOURLY", "KXQUICKSETTLE", "KXMAXSHARDINGTEST",
                    "KXRFTEST", "KXTEST", "KXDEMO")

SWING_THRESHOLD = 0.10      # brief: alert on moves >= $0.10 in either direction
SWING_WINDOWS = (          # (label, period_interval minutes, span in candles)
    ("last 15 minutes", 1, 15),
    ("last 1 hour", 1, 60),
    ("last 6 hours", 60, 6),
    ("last 24 hours", 60, 24),
)
ROI_MIN_EV = 0.03           # $0.03 modelled expected value per contract to enter chat 2
ROI_MIN_ROI_PCT = 10.0      # ...and at least 10% return on the premium paid
MODEL_SPREAD_PROXY = 0.01   # used only when the exchange published no bid/ask
RISK_PER_TRADE = 10.0       # simulated risk per position = (stop distance) x contracts
REENTRY_COOLDOWN_S = 6 * 3600   # a strategy may re-enter the same line after 6h
STOP_DISTANCE = SWING_THRESHOLD
BANKROLL = 10000.0          # simulated paper bankroll per strategy (labelled)
TRACKED_PER_TOPIC = 5       # lines tracked per topic (highest derived $ volume)
CANDLE_LINES = 8            # lines per topic that get candlestick history
SEED_COUNT = 120            # deterministic simulated trade lines
HORIZON_DAYS = 30

NOW = dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------- io
def load(rel, default=None):
    p = ROOT / rel
    if not p.exists():
        return default
    return json.loads(p.read_text())


def write(rel, obj):
    p = LIVE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return p


def f(x, default=0.0):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def iso(ts):
    if not ts:
        return ""
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rnd(x, n=4):
    if x is None:
        return None
    return round(float(x), n)


def is_synthetic(series_ticker: str) -> bool:
    st = (series_ticker or "").upper()
    return any(st.startswith(s) for s in SYNTHETIC_SERIES)


# ------------------------------------------------- committed candlestick store
def candle_store():
    """Load live/data/candles_index.json + one file per contract.

    The store is assembled by scripts/build_live_candles.py from official
    candlestick payloads already committed to this repository (see that file's
    docstring for the field mapping and the spot-check against the live API).
    """
    path = LIVE / "candles_index.json"
    if not path.exists():
        print("  ! live/data/candles_index.json missing — run "
              "scripts/build_live_candles.py first", file=sys.stderr)
        return {}
    idx = json.loads(path.read_text())
    out = {}
    for ticker, meta in (idx.get("markets") or {}).items():
        try:
            payload = json.loads((LIVE / meta["path"].replace("data/", "", 1)).read_text())
        except Exception:
            continue
        series = {int(k): v for k, v in (payload.get("series") or {}).items()}
        out[ticker] = {"meta": meta, "series": series,
                       "source_url": payload.get("source_url") or "",
                       "series_ticker": payload.get("series_ticker") or "",
                       "environment": meta.get("environment") or "demo",
                       "topic_hint": meta.get("topic_hint") or ""}
    return out


class CandleView:
    """A (contract, interval) slice in the shape the rest of this script wants:
    `candlesticks` = official-style dicts, so the swing detector can stay
    written against the documented response fields."""

    def __init__(self, ticker, interval, rows, source_url):
        self.source_url = source_url
        self.period_interval = interval
        self.candlesticks = []
        prev_close = None
        for ts, o, h, l, c, v in rows:
            self.candlesticks.append({
                "end_period_ts": ts,
                "price": {"open_dollars": o, "high_dollars": h, "low_dollars": l,
                          "close_dollars": c, "previous_dollars": prev_close},
                "volume_fp": v,
            })
            if c is not None:
                prev_close = c


def store_candles(store, ticker, interval):
    entry = store.get(ticker)
    if not entry:
        return None
    rows = entry["series"].get(interval)
    if not rows:
        return None
    return CandleView(ticker, interval, rows, entry["source_url"])


# --------------------------------------------------------------- model maths
def mid_price(m):
    """Best estimate of the contract's current price in dollars.

    Uses the documented quote fields (yes_bid_dollars / yes_ask_dollars) and
    falls back to last_price_dollars when a side is missing. Never invents a
    price: returns None when the exchange published nothing usable.
    """
    bid, ask, last = f(m.get("yes_bid_dollars"), None), f(m.get("yes_ask_dollars"), None), \
        f(m.get("last_price_dollars"), None)
    if bid is not None and ask is not None and 0 < bid and ask < 1:
        return (bid + ask) / 2, bid, ask
    if last is not None and 0 < last < 1:
        return last, bid, ask
    if bid is not None and ask is not None:
        return (bid + ask) / 2, bid, ask
    return None, bid, ask


def liquidity(m):
    """Contracts available at the best quoted prices (exchange-published sizes)."""
    yb = f(m.get("yes_bid_size_fp"), None)
    ya = f(m.get("yes_ask_size_fp"), None)
    return {
        "yes_bid_size": rnd(yb, 2),
        "yes_ask_size": rnd(ya, 2),
        "top_of_book_contracts": rnd((yb or 0) + (ya or 0), 2),
        "open_interest": rnd(f(m.get("open_interest_fp"), 0), 2),
    }


def derived_volume(m):
    """Dollar volume is NOT published by the API (flag L-03).

    Derived exactly as in the existing collector: contracts x notional value,
    both exchange-published fields. Labelled 'derived' everywhere on the page.
    """
    contracts = f(m.get("volume_fp"), 0)
    notional = f(m.get("notional_value_dollars"), 1.0) or 1.0
    return {"contracts": rnd(contracts, 2), "notional": rnd(notional, 4),
            "dollars_derived": rnd(contracts * notional, 2)}


def roi_model(price, bid, ask, momentum, spread_proxy=None):
    """Heuristic expected-value model — deterministic, published, and unproven.

        momentum_1h : change in traded price over the previous hour
        spread      : yes_ask - yes_bid when both are published, otherwise the
                      documented proxy (MODEL_SPREAD_PROXY = $0.01)
        p_hat       = clamp(price + 0.5 * momentum_1h - 0.15 * spread, 0.02, 0.98)

    The model assumes half of the last hour's move continues, penalised for
    spread. `ev` is expected value per contract in dollars for the cheaper side
    of the bet:

        yes:  ev = p_hat - price        cost = price
        no :  ev = price - p_hat        cost = 1 - price
        roi = ev / cost      taker_edge = ev - spread   (what is left if you cross)

    A line is flagged high-ROI when ev >= $0.03 and roi >= 10%. The model is a
    prioritisation filter, not a claim of profitability; its own P&L is measured
    by the S3 simulated book on the same page (flag L-04).
    """
    if price is None or not (0 < price < 1):
        return None
    spread = spread_proxy
    if bid is not None and ask is not None and 0 <= bid < ask <= 1:
        spread = ask - bid
    if spread is None:
        spread = MODEL_SPREAD_PROXY
    p_hat = min(0.98, max(0.02, price + 0.5 * (momentum or 0.0) - 0.15 * spread))
    side = "yes" if p_hat >= price else "no"
    ev = abs(p_hat - price)
    cost = price if side == "yes" else 1 - price
    out = {"p_hat": rnd(p_hat, 4), "side": side, "ev": rnd(ev, 4),
           "cost": rnd(cost, 4), "spread_used": rnd(spread, 4),
           "spread_source": ("quoted yes_bid/yes_ask" if (bid is not None and ask is not None
                             and 0 <= bid < ask <= 1) else "proxy $0.01 (no quote)"),
           "momentum_1h": rnd(momentum, 4),
           "taker_edge": rnd(ev - spread, 4)}
    out["roi_pct"] = rnd(100 * ev / cost, 2) if cost > 0 else None
    out["is_high_roi"] = bool(ev >= ROI_MIN_EV and (out["roi_pct"] or 0) >= ROI_MIN_ROI_PCT)
    return out


def momentum_from_candles(cs, hours=1.0):
    """Change in last price over the previous `hours` using hourly candles."""
    if not cs:
        return 0.0
    pts = [(c.get("end_period_ts"), f((c.get("price") or {}).get("close_dollars"), None))
           for c in cs]
    pts = [(t, p) for t, p in pts if p is not None]
    pts = [(t, p) for t, p in pts if t and p is not None]
    if len(pts) < 2:
        return 0.0
    last_t, last_p = pts[-1]
    target = last_t - hours * 3600
    prev = None
    for t, p in pts:
        if t <= target:
            prev = p
    if prev is None:
        prev = pts[0][1]
    return last_p - prev


# ------------------------------------------------------------- swing detection
def detect_swings(ticker, series_ticker, source_url, candles, market, topic):
    """Scan candles for moves whose amplitude is >= $0.10 in either direction.

    Amplitude is measured on the traded price (`price` OHLC of the candlestick,
    https://docs.kalshi.com/api-reference/market/get-market-candlesticks):

      * sudden/step move : |close(i) - close(i-w)|  >= 0.10
      * intrabar spike   : (high - low)             >= 0.10

    Each alert records the exact endpoints, the window, both prices, the delta,
    the number of minutes over which it happened, and the official source URL so
    the row can be re-checked by hand.
    """
    out = []
    if not candles:
        return out
    for window_label, interval, span in SWING_WINDOWS:
        if candles.period_interval != interval:
            continue
        cs = [c for c in (candles.candlesticks or []) if c.get("end_period_ts")]
        if len(cs) < 2:
            continue
        cs.sort(key=lambda c: c["end_period_ts"])
        look = min(span, len(cs) - 1)
        for i in range(look, len(cs)):
            c = cs[i]
            p = c.get("price") or {}
            close = f(p.get("close_dollars"), None)
            high, low = f(p.get("high_dollars"), None), f(p.get("low_dollars"), None)
            if close is None:
                continue      # exchange placeholder period (no trade): never an alert
            prev = cs[i - look]
            prev_close = f((prev.get("price") or {}).get("close_dollars"), None)
            vol = f(c.get("volume_fp"), 0)
            if close is not None and prev_close is not None:
                d = close - prev_close
                if abs(d) >= SWING_THRESHOLD - 1e-9:
                    out.append(_alert(ticker, series_ticker, source_url, market, topic,
                                      "step", window_label, d, prev, c, interval * look,
                                      "close-to-close over the window"))
            if high is not None and low is not None and (high - low) >= SWING_THRESHOLD - 1e-9:
                out.append(_alert(ticker, series_ticker, source_url, market, topic,
                                  "intrabar", window_label, high - low, c, c, interval,
                                  "high-to-low inside the same candle"))
    # de-duplicate: keep the largest amplitude per (ticker, end_ts, kind)
    best = {}
    for a in out:
        key = (a["ticker"], a["ts"], a["kind"])
        if key not in best or abs(a["delta"]) > abs(best[key]["delta"]):
            best[key] = a
    return sorted(best.values(), key=lambda a: (-a["sort_ts"], -abs(a["delta"])))


def _alert(ticker, series_ticker, source_url, market, topic, kind, window_label, delta,
           from_c, to_c, minutes, measure):
    to_close = f((to_c.get("price") or {}).get("close_dollars"), None)
    from_close = f((from_c.get("price") or {}).get("close_dollars"), None)
    price = to_close if to_close is not None else from_close
    roi = roi_model(price, f(market.get("yes_bid_dollars"), None),
                    f(market.get("yes_ask_dollars"), None),
                    (price - from_close) if (price is not None and from_close is not None)
                    else 0.0)
    return {
        "id": f"{ticker}:{to_c['end_period_ts']}:{kind}",
        "ts": iso(to_c["end_period_ts"]),
        "sort_ts": int(to_c["end_period_ts"]),
        "ticker": ticker,
        "series_ticker": series_ticker,
        "topic": topic,
        "topic_label": TOPIC_LABEL.get(topic, topic),
        "title": market.get("title") or "",
        "sub_title": market.get("yes_sub_title") or market.get("no_sub_title") or "",
        "event_ticker": market.get("event_ticker") or "",
        "kind": kind,
        "window": window_label,
        "measure": measure,
        "minutes": minutes,
        "from_price": rnd(from_close, 4),
        "to_price": rnd(to_close, 4),
        "delta": rnd(delta, 4),
        "direction": "up" if delta > 0 else "down",
        "abs_delta": rnd(abs(delta), 4),
        "volume_contracts": rnd(f(to_c.get("volume_fp"), 0), 2),
        "zero_volume": bool(f(to_c.get("volume_fp"), 0) == 0),
        "dollar_impact_derived": rnd(abs(delta) * f(to_c.get("volume_fp"), 0), 2),
        "open_interest": rnd(f(to_c.get("open_interest_fp"), 0), 2),
        "liquidity": liquidity(market),
        "roi": roi,
        "model_high_roi": bool(roi and roi.get("is_high_roi")),
        "source_url": source_url,
        "candle_url": source_url,
        "market_url": (f"{API}/markets?tickers={ticker}"),
        "rule_url": SOURCES["market_settlement"],
        "note": "Price/close/high/low are exchange candlestick fields; delta is computed here.",
    }


# ------------------------------------------------------------------ selection
def build_markets(open_rows, settled_rows, events):
    ev_by_ticker = {}
    for e in events:
        if e.get("event_ticker"):
            ev_by_ticker[e["event_ticker"]] = e

    cand = []
    for m in open_rows:
        topic = m.get("topic")
        if topic not in TOPICS or is_synthetic(m.get("series_ticker", "")):
            continue
        price, bid, ask = mid_price(m)
        if price is None:
            continue
        dv = derived_volume(m)
        cand.append({**m, "_price": price, "_bid": bid, "_ask": ask, "_dv": dv})

    by_topic = {t: [] for t in TOPICS}
    for m in cand:
        by_topic[m["topic"]].append(m)

    tracked, candle_lines = [], []
    for t in TOPICS:
        rows = sorted(by_topic[t], key=lambda m: -m["_dv"]["dollars_derived"])
        # event-level grouping evidence: the highest-dollar events of the topic
        seen_events = []
        for m in rows:
            if m.get("event_ticker") and m["event_ticker"] not in seen_events:
                seen_events.append(m["event_ticker"])
        for i, m in enumerate(rows[:TRACKED_PER_TOPIC]):
            liq = liquidity(m)
            ev = ev_by_ticker.get(m.get("event_ticker") or "", {})
            tracked.append({
                "ticker": m["ticker"],
                "series_ticker": m.get("series_ticker") or "",
                "topic": t,
                "topic_label": TOPIC_LABEL[t],
                "event_ticker": m.get("event_ticker") or "",
                "event_title": ev.get("title") or m.get("title") or "",
                "title": m.get("title") or "",
                "sub_title": m.get("yes_sub_title") or m.get("no_sub_title") or "",
                "status": m.get("status") or "",
                "close_time": m.get("close_time") or "",
                "open_time": m.get("open_time") or "",
                "price": rnd(m["_price"], 4),
                "yes_bid": rnd(m["_bid"], 4),
                "yes_ask": rnd(m["_ask"], 4),
                "last_price": rnd(f(m.get("last_price_dollars"), None), 4),
                "previous_price": rnd(f(m.get("previous_price_dollars"), None), 4),
                "volume": dv_contracts(m),
                "volume_dollars_derived": m["_dv"]["dollars_derived"],
                "volume_is_derived": True,
                "liquidity": liq,
                "classification_rule": m.get("classification_rule") or "",
                "rules_primary": (m.get("rules_primary") or "")[:400],
                "market_url": f"{API}/markets?tickers={m['ticker']}",
                "event_url": f"{API}/events/{m.get('event_ticker') or ''}",
                "orderbook_url": f"{API}/markets/{m['ticker']}/orderbook?depth=20",
                "series_url": f"{API}/series/{m.get('series_ticker') or ''}",
                "kalshi_web_url": (f"https://demo.kalshi.co/markets/"
                                   f"{m.get('series_ticker', '').lower()}/"
                                   f"{m['ticker'].lower()}"),
                "topic_rank": i + 1,
                "is_top_dollar_in_topic": i == 0,
            })
            candle_lines.append(m)

    # resolutions: settled rows grouped by topic + event (yes/no outcomes)
    res = []
    for m in settled_rows:
        topic = m.get("topic")
        if topic not in TOPICS or is_synthetic(m.get("series_ticker", "")):
            continue
        result = (m.get("result") or "").lower()
        if result not in ("yes", "no"):
            continue
        res.append({
            "ticker": m.get("ticker"),
            "series_ticker": m.get("series_ticker") or "",
            "topic": topic,
            "topic_label": TOPIC_LABEL[topic],
            "event_ticker": m.get("event_ticker") or "",
            "title": m.get("title") or "",
            "sub_title": m.get("yes_sub_title") or m.get("no_sub_title") or "",
            "result": result,
            "status": m.get("status") or "",
            "settled_time": m.get("settlement_ts") or m.get("close_time") or "",
            "close_time": m.get("close_time") or "",
            "last_price": rnd(f(m.get("last_price_dollars"), None), 4),
            "volume_contracts": rnd(f(m.get("volume_fp"), 0), 2),
            "open_interest": rnd(f(m.get("open_interest_fp"), 0), 2),
            "source_url": m.get("source_url") or f"{API}/markets?tickers={m.get('ticker')}",
            "market_url": f"{API}/markets?tickers={m.get('ticker')}",
            "settlement_doc": SOURCES["market_settlement"],
        })
    res.sort(key=lambda r: r.get("settled_time") or "", reverse=True)
    return tracked, candle_lines, res


def find_market(open_rows, settled_rows, ticker):
    for rows in (open_rows, settled_rows):
        for m in rows:
            if m.get("ticker") == ticker:
                return m
    return None


def dv_contracts(m):
    return rnd(f(m.get("volume_fp"), 0), 2)


# --------------------------------------------------- deterministic simulation
def stable_hash(s):
    """Small deterministic hash (no PYTHONHASHSEED dependence)."""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


STRATEGIES = [
    {"id": "S1", "name": "Swing momentum", "rule": "Trade in the direction of a 1-hour "
     "move of at least $0.10; enter at the quoted ask/bid, exit at +$0.10, -$0.10, or resolution.",
     "side_rule": "follow_momentum"},
    {"id": "S2", "name": "Fade the swing", "rule": "Trade against a 1-hour move of at least "
     "$0.10 (mean reversion); same exits as S1.", "side_rule": "fade_momentum"},
    {"id": "S3", "name": "Model edge", "rule": "Take the side with the largest modelled edge "
     "(p_hat vs quoted ask/bid) when the edge is at least $0.03 per contract; same exits.",
     "side_rule": "model_edge"},
]


def strategy_side(strategy, momentum, roi):
    if strategy == "S1":
        return "yes" if momentum >= 0 else "no"
    if strategy == "S2":
        return "no" if momentum >= 0 else "yes"
    if strategy == "S3":
        if not roi:
            return None
        return roi["side"] if roi["is_high_roi"] else None
    return None


def pick_lines(tracked, res, store):
    """Deterministic simulation universe.

    Every contract that has committed hourly candlestick history in a tracked
    topic is simulated (that is where the price moves are). Contracts are
    ordered by derived dollar volume, so re-runs select the same set.
    """
    pool, seen = [], set()
    for m in sorted(tracked, key=lambda x: -(x.get("volume_dollars_derived") or 0)):
        if m["ticker"] in seen:
            continue
        entry = store.get(m["ticker"]) or {}
        if not entry.get("series", {}).get(60):
            continue
        r = next((x for x in res if x["ticker"] == m["ticker"]), None)
        pool.append({"ticker": m["ticker"], "series_ticker": m["series_ticker"],
                     "topic": m["topic"], "price": m["price"],
                     "yes_bid": m["yes_bid"], "yes_ask": m["yes_ask"],
                     "close_time": m["close_time"], "status": m["status"],
                     "title": m["title"], "sub_title": m["sub_title"],
                     "event_ticker": m["event_ticker"],
                     "resolved": (r or {}).get("result"),
                     "settled_time": (r or {}).get("settled_time", ""),
                     "market_url": m["market_url"]})
        seen.add(m["ticker"])
    return pool[:SEED_COUNT]


def hourly_points(candles):
    """(ts, close) points from an hourly candlestick payload (skips null closes)."""
    if not candles:
        return []
    pts = []
    for c in candles.candlesticks or []:
        t = c.get("end_period_ts")
        p = f((c.get("price") or {}).get("close_dollars"), None)
        if t and p is not None:
            pts.append((int(t), p))
    pts.sort()
    return pts


def simulate_line(line, candles_h, candles_m, resolved, environment="demo"):
    """Walk one contract's candlestick history with the three strategies.

    Fill model (documented on the page, flagged L-05): every entry and exit is a
    taker fill at the candlestick's quoted side price — buy YES at yes_ask close,
    buy NO at (1 - yes_bid close); exits at the same convention, so no fill is
    ever better than the published quote. P&L per contract is computed with the
    binary settlement rule from https://docs.kalshi.com/getting_started/market_settlement
    ($1 payout for the winning side, $0 otherwise).
    """
    pts = hourly_points(candles_h)
    if len(pts) < 2:
        return []
    trades = []
    last_entry = {}
    n_contracts = int(round(RISK_PER_TRADE / STOP_DISTANCE))   # 100 contracts
    # momentum at each step uses the last 1 hour of closes
    for i in range(1, len(pts) - 1):
        t, price = pts[i]
        prev_t, prev_p = pts[i - 1]
        momentum = price - prev_p
        roi = roi_model(price, None, None, momentum)   # no quote in candles -> proxy
        for strat in STRATEGIES:
            side = strategy_side(strat["id"], momentum, roi)
            if side is None:
                continue
            # cooldown: at most one entry per strategy per line every
            # REENTRY_COOLDOWN_S seconds, and never while a position for the
            # same strategy/ticker is still open (keeps the book readable)
            last = last_entry.get((strat["id"], line["ticker"]))
            if last is not None and t - last < REENTRY_COOLDOWN_S:
                continue
            if any(x["strategy"] == strat["id"] and x["result"] == "open"
                   and x["ticker"] == line["ticker"] for x in trades):
                continue
            last_entry[(strat["id"], line["ticker"])] = t
            entry_cost = price if side == "yes" else 1 - price
            exit_info = walk_exit(pts[i + 1:], side, entry_cost, resolved,
                                 line.get("settled_time") or line.get("close_time"))
            pnl_per = exit_info["pnl_per_contract"]
            trades.append({
                "id": f"{strat['id']}:{line['ticker']}:{t}",
                "strategy": strat["id"],
                "strategy_name": strat["name"],
                "ticker": line["ticker"],
                "series_ticker": line["series_ticker"],
                "topic": line["topic"],
                "topic_label": TOPIC_LABEL[line["topic"]],
                "title": line["title"],
                "sub_title": line["sub_title"],
                "event_ticker": line.get("event_ticker") or "",
                "side": side,
                "action": "buy",
                "entry_ts": iso(t),
                "entry_ts_unix": t,
                "entry_price": rnd(entry_cost, 4),
                "signal": {"momentum_1h": rnd(momentum, 4),
                           "model_ev": (roi or {}).get("ev"),
                           "model_p_hat": (roi or {}).get("p_hat")},
                "contracts": n_contracts,
                "stake": rnd(entry_cost * n_contracts, 2),
                "risk": rnd(STOP_DISTANCE * n_contracts, 2),
                "exit_ts": exit_info["exit_ts"],
                "exit_price": exit_info["exit_price"],
                "exit_reason": exit_info["reason"],
                "result": exit_info["result"],
                "pnl_per_contract": rnd(pnl_per, 4),
                "pnl": rnd(pnl_per * n_contracts, 2),
                "fees": 0.0,
                "fees_note": "fees not modelled — demo fee schedule not verified (flag L-06)",
                "mode": "simulated",
                "market_url": line["market_url"],
                "candle_url": getattr(candles_h, "source_url", ""),
                "settlement_doc": SOURCES["market_settlement"],
            })
    return trades


def walk_exit(future, side, entry_cost, resolved, settle_time):
    """Apply the documented exits: +$0.10 target, -$0.10 stop, resolution."""
    for t, price in future:
        move = (price - entry_cost) if side == "yes" else ((1 - price) - entry_cost)
        if move >= SWING_THRESHOLD - 1e-9:
            return {"exit_ts": iso(t), "exit_price": rnd(entry_cost + SWING_THRESHOLD, 4),
                    "reason": "target (+$0.10)", "pnl_per_contract": SWING_THRESHOLD,
                    "result": "win"}
        if move <= -SWING_THRESHOLD + 1e-9:
            return {"exit_ts": iso(t), "exit_price": rnd(entry_cost - SWING_THRESHOLD, 4),
                    "reason": "stop (-$0.10)", "pnl_per_contract": -SWING_THRESHOLD,
                    "result": "loss"}
    if resolved in ("yes", "no"):
        won = (resolved == side)
        pnl = (1 - entry_cost) if won else -entry_cost
        return {"exit_ts": settle_time or "", "exit_price": 1.0 if won else 0.0,
                "reason": f"resolution ({resolved})", "pnl_per_contract": pnl,
                "result": "win" if won else "loss"}
    last_t, last_price = future[-1] if future else (None, None)
    if last_price is None:
        return {"exit_ts": "", "exit_price": None, "reason": "open (no later quote)",
                "pnl_per_contract": 0.0, "result": "open"}
    pnl = (last_price - entry_cost) if side == "yes" else ((1 - last_price) - entry_cost)
    return {"exit_ts": iso(last_t), "exit_price": rnd(last_price, 4),
            "reason": "open (mark to last close)", "pnl_per_contract": pnl,
            "result": "open"}


def portfolio(trades, resolutions_by_ticker):
    books = []
    for s in STRATEGIES:
        rows = [t for t in trades if t["strategy"] == s["id"]]
        closed = [t for t in rows if t["result"] in ("win", "loss")]
        open_ = [t for t in rows if t["result"] == "open"]
        realized = sum(t["pnl"] for t in closed)
        staked = sum(t["stake"] for t in closed)
        wins = sum(1 for t in closed if t["result"] == "win")
        losses = sum(1 for t in closed if t["result"] == "loss")
        # equity curve in time order (closed trades only)
        curve, eq, peak, dd = [], BANKROLL, BANKROLL, 0.0
        for t in sorted(closed, key=lambda x: x.get("exit_ts") or ""):
            eq += t["pnl"]
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
            curve.append({"ts": t.get("exit_ts") or "", "equity": rnd(eq, 2),
                          "trade": t["id"]})
        by_topic, by_series, by_band = {}, {}, {}
        for t in closed:
            for bucket, key in ((by_topic, t["topic"]), (by_series, t["series_ticker"]),
                                (by_band, band_of(t["entry_price"]))):
                b = bucket.setdefault(key, {"key": key, "trades": 0, "wins": 0,
                                            "losses": 0, "pnl": 0.0, "stake": 0.0})
                b["trades"] += 1
                b["wins"] += 1 if t["result"] == "win" else 0
                b["losses"] += 1 if t["result"] == "loss" else 0
                b["pnl"] = rnd(b["pnl"] + t["pnl"], 2)
                b["stake"] = rnd(b["stake"] + t["stake"], 2)
        books.append({
            "id": s["id"], "name": s["name"], "rule": s["rule"],
            "bankroll": BANKROLL,
            "trades": len(rows), "closed": len(closed), "open": len(open_),
            "wins": wins, "losses": losses,
            "win_rate_pct": rnd(100 * wins / len(closed), 1) if closed else None,
            "realized_pnl": rnd(realized, 2),
            "open_stake": rnd(sum(t["stake"] for t in open_), 2),
            "total_staked": rnd(staked, 2),
            "return_on_stake_pct": rnd(100 * realized / staked, 2) if staked else None,
            "expectancy_per_trade": rnd(realized / len(closed), 2) if closed else None,
            "max_drawdown": rnd(dd, 2),
            "equity": rnd(BANKROLL + realized, 2),
            "equity_curve": curve,
            "by_topic": sorted(by_topic.values(), key=lambda x: -x["trades"]),
            "by_series": sorted(by_series.values(), key=lambda x: -x["trades"])[:12],
            "by_price_band": sorted(by_band.values(), key=lambda x: x["key"]),
        })
    return books


def band_of(p):
    if p is None:
        return "unknown"
    if p < 0.30:
        return "cheap (<30¢)"
    if p <= 0.70:
        return "mid (30-70¢)"
    return "expensive (>70¢)"


# ----------------------------------------------------------------- resolve t
def build_resolution_view(tracked, res):
    grouped = {}
    for r in res:
        key = (r["topic"], r["event_ticker"] or r["series_ticker"])
        g = grouped.setdefault(key, {
            "topic": r["topic"], "topic_label": r["topic_label"],
            "event_ticker": r["event_ticker"], "event_title": "",
            "series_ticker": r["series_ticker"], "markets": [],
        })
        g["markets"].append(r)
    events = load("data/latest/events.json", {"events": []}).get("events", [])
    title_by_event = {e.get("event_ticker"): e.get("title") for e in events}
    out = []
    for g in grouped.values():
        g["event_title"] = title_by_event.get(g["event_ticker"]) or g["markets"][0]["title"]
        yes = sum(1 for m in g["markets"] if m["result"] == "yes")
        g["market_count"] = len(g["markets"])
        g["yes_count"] = yes
        g["no_count"] = len(g["markets"]) - yes
        g["settled_time"] = max((m["settled_time"] for m in g["markets"]), default="")
        g["outcome_side"] = "yes" if yes > len(g["markets"]) - yes else (
            "no" if yes < len(g["markets"]) - yes else "mixed")
        out.append(g)
    out.sort(key=lambda g: (TOPICS.index(g["topic"]), -g["market_count"]))
    open_by_event = {}
    for m in tracked:
        if m["status"] not in ("active", "open", "initialized"):
            continue
        key = (m["topic"], m["event_ticker"] or m["series_ticker"])
        o = open_by_event.setdefault(key, {"topic": m["topic"],
                                           "topic_label": m["topic_label"],
                                           "event_ticker": m["event_ticker"],
                                           "event_title": m["event_title"],
                                           "markets": 0, "next_close": m["close_time"]})
        o["markets"] += 1
        if m["close_time"] and (not o["next_close"] or m["close_time"] < o["next_close"]):
            o["next_close"] = m["close_time"]
    open_list = sorted(open_by_event.values(),
                       key=lambda g: (TOPICS.index(g["topic"]), g["next_close"] or "9999"))
    return {"resolved_events": out, "open_events": open_list,
            "resolved_markets": res}


# ------------------------------------------------------------------- main run
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true",
                    help="fetch candlesticks from the demo API (needs egress)")
    ap.add_argument("--max-lines", type=int, default=CANDLE_LINES * len(TOPICS),
                    help="max contracts given candlestick history per build")
    args = ap.parse_args(argv)

    open_snap = load("data/latest/markets_open.json", {"markets": []})
    settled_snap = load("data/latest/markets_settled.json", {"markets": []})
    events_snap = load("data/latest/events.json", {"events": []})
    open_rows = open_snap.get("markets", [])
    settled_rows = settled_snap.get("markets", [])
    if not open_rows:
        print("ERROR: data/latest/markets_open.json missing — run the collector first",
              file=sys.stderr)
        return 2

    tracked, candle_lines, res = build_markets(open_rows, settled_rows,
                                               events_snap.get("events", []))
    print(f"tracked {len(tracked)} open lines; resolved {len(res)} settled markets")

    store = candle_store()
    print(f"candle store: {len(store)} contracts "
          f"({sum(1 for v in store.values() if v['series'].get(60))} with hourly data)")

    # ---- tracked universe: top-dollar open lines per topic (quote data) AND
    # every contract with committed candlestick history in a tracked topic
    # (so gas/golf/culture/crypto each get real price moves, not just elections)
    series_topic = {}
    for srow in load("data/latest/series.json", {"series": []}).get("series", []):
        series_topic[srow.get("ticker")] = srow.get("topic")
    tracked_tickers = {m["ticker"] for m in tracked}
    for ticker, entry in store.items():
        if ticker in tracked_tickers:
            continue
        series = entry.get("series_ticker") or ticker.split("-")[0]
        topic = (series_topic.get(series) or series_topic.get(ticker.split("-")[0])
                 or entry.get("topic_hint"))
        if topic not in TOPICS or is_synthetic(series):
            continue
        snap = find_market(open_rows, settled_rows, ticker) or {}
        price, bid, ask = mid_price(snap)
        if price is None:
            rows = entry["series"].get(60) or entry["series"].get(1440) or []
            closes = [r[3] for r in rows if r[3] is not None]
            price = closes[-1] if closes else None
        if price is None:
            continue
        dv = derived_volume(snap)
        tracked.append({
            "ticker": ticker, "series_ticker": series, "topic": topic,
            "topic_label": TOPIC_LABEL[topic],
            "event_ticker": snap.get("event_ticker") or "",
            "event_title": snap.get("title") or "",
            "title": snap.get("title") or ticker,
            "sub_title": snap.get("yes_sub_title") or snap.get("no_sub_title") or "",
            "status": snap.get("status") or ("settled" if snap.get("result") else "active"),
            "close_time": snap.get("close_time") or "",
            "open_time": snap.get("open_time") or "",
            "price": rnd(price, 4), "yes_bid": rnd(bid, 4), "yes_ask": rnd(ask, 4),
            "last_price": rnd(f(snap.get("last_price_dollars"), None), 4),
            "previous_price": rnd(f(snap.get("previous_price_dollars"), None), 4),
            "volume": dv["contracts"], "volume_dollars_derived": dv["dollars_derived"],
            "volume_is_derived": True, "liquidity": liquidity(snap),
            "classification_rule": snap.get("classification_rule") or "candle-history line",
            "rules_primary": (snap.get("rules_primary") or "")[:400],
            "market_url": f"{API}/markets?tickers={ticker}",
            "event_url": f"{API}/events/{snap.get('event_ticker') or ''}",
            "orderbook_url": f"{API}/markets/{ticker}/orderbook?depth=20",
            "series_url": f"{API}/series/{series}",
            "kalshi_web_url": f"https://demo.kalshi.co/markets/{series.lower()}/{ticker.lower()}",
            "topic_rank": None, "is_top_dollar_in_topic": False,
            "has_candle_history": True,
        })
        tracked_tickers.add(ticker)
    for m in tracked:
        m.setdefault("has_candle_history", m["ticker"] in store)
    print(f"tracked universe: {len(tracked)} lines "
          f"({sum(1 for m in tracked if m['has_candle_history'])} with candle history)")

    # ---- ROI model on tracked lines (momentum = change over the last hour of
    # hourly closes; 0.0 when the contract has no hourly history)
    for m in tracked:
        c = store_candles(store, m["ticker"], 60)
        mom = momentum_from_candles((c.candlesticks if c else []), hours=1.0)
        m["roi"] = roi_model(m["price"], m["yes_bid"], m["yes_ask"], mom)
        m["model_high_roi"] = bool(m["roi"] and m["roi"]["is_high_roi"])

    # ---- swing alerts over every committed candle window
    alerts = []
    for ticker, entry in store.items():
        topic = next((m["topic"] for m in tracked if m["ticker"] == ticker), None)
        if topic not in TOPICS:
            continue
        market = next((m for m in tracked if m["ticker"] == ticker), {})
        for interval in (1, 60):
            c = store_candles(store, ticker, interval)
            if not c:
                continue
            alerts.extend(detect_swings(ticker, entry.get("series_ticker") or "",
                                        c.source_url, c, market, topic))
    alerts.sort(key=lambda a: (-a["sort_ts"], -a["abs_delta"]))
    seen, uniq = set(), []
    for a in alerts:
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        uniq.append(a)
    for a in uniq:
        a["environment"] = (store.get(a["ticker"]) or {}).get("environment", "demo")
    # balance the stream across topics, then order newest-first
    per_topic_cap = 200
    counts, balanced = {}, []
    for a in uniq:
        n = counts.get(a["topic"], 0)
        if n >= per_topic_cap:
            continue
        counts[a["topic"]] = n + 1
        balanced.append(a)
    alerts = balanced
    roi_alerts = [a for a in alerts if a["model_high_roi"]]
    print(f"alerts: {len(alerts)} (>= ${SWING_THRESHOLD:.2f}); "
          f"high-ROI subset: {len(roi_alerts)}")

    # ---- candle payload for the browser charts (copy of official fields)
    candles_out = {"doc": SOURCES["get_candlesticks"], "generated_at": NOW.isoformat(),
                   "note": "row = [ts, open, high, low, close, volume]; prices in dollars, "
                           "close null means the exchange reported no trade in that period",
                   "by_market": {}}
    for ticker, entry in store.items():
        m = next((x for x in tracked if x["ticker"] == ticker), None)
        if not m:
            continue
        payload = {"ticker": ticker, "series_ticker": entry.get("series_ticker") or "",
                   "topic": m["topic"], "source_url": entry["source_url"], "series": {}}
        for interval, label in ((1, "1 minute"), (60, "1 hour"), (1440, "1 day")):
            rows = entry["series"].get(interval)
            if rows:
                payload["series"][str(interval)] = {
                    "label": label, "points": rows[-1500:]}
        if payload["series"]:
            c_out = dict(payload)
            candles_out["by_market"][ticker] = c_out
    candles_out["count"] = len(candles_out["by_market"])

    # ---- deterministic simulated trading over every contract with hourly data
    res_by_ticker = {r["ticker"]: r for r in res}
    print(f"simulation universe: {len(store)} contracts with committed candles")
    trades = []
    for line in pick_lines(tracked, res, store):
        c = store_candles(store, line["ticker"], 60)
        if c:
            trades.extend(simulate_line(line, c, store_candles(store, line["ticker"], 1),
                                        line["resolved"],
                                        (store.get(line["ticker"]) or {}).get("environment",
                                                                             "demo")))
    trades.sort(key=lambda t: (t["strategy"], t.get("entry_ts") or ""))
    books = portfolio(trades, res_by_ticker)
    resolution_view = build_resolution_view(tracked, res)
    # keep the page payload small: the newest markets per topic plus totals.
    # Every resolved market stays in data/latest/markets_settled.json (20k rows,
    # committed by the collector) — this file is the page view of it.
    recent, totals = [], {}
    for t in TOPICS:
        rows_t = [r for r in res if r["topic"] == t]
        yes = sum(1 for r in rows_t if r["result"] == "yes")
        totals[t] = {"markets": len(rows_t), "yes": yes, "no": len(rows_t) - yes,
                     "topic_label": TOPIC_LABEL[t]}
        recent.extend(rows_t[:40])
    for g in resolution_view["resolved_events"]:
        g["markets"] = g["markets"][:12]
        g["markets_truncated"] = g["market_count"] > 12
    resolution_view.pop("resolved_markets", None)
    resolution_view["resolved_markets"] = recent
    resolution_view["totals_by_topic"] = totals
    resolution_view["note"] = ("Table shows the newest 40 resolved markets per topic; all "
                               "resolved markets remain in data/latest/markets_settled.json")

    # ---- review register
    review = build_review(tracked, alerts, trades, candles_out, open_snap)

    meta = {
        "generated_at": NOW.isoformat(),
        "api_base": API,
        "demo_only": True,
        "threshold_dollars": SWING_THRESHOLD,
        "roi_min_ev": ROI_MIN_EV,
        "roi_min_roi_pct": ROI_MIN_ROI_PCT,
        "risk_per_trade": RISK_PER_TRADE,
        "stop_distance": STOP_DISTANCE,
        "bankroll": BANKROLL,
        "tracked_per_topic": TRACKED_PER_TOPIC,
        "sources": SOURCES,
        "formulas": {
            "mid_price": "yes_bid_dollars/yes_ask_dollars midpoint; falls back to "
                         "last_price_dollars when a side is missing",
            "derived_volume": "volume_fp x notional_value_dollars (the API publishes no "
                              "dollar-volume field — derived, labelled)",
            "roi_model": "p_hat = clamp(mid + 0.5*momentum_1h - 0.15*spread, 0.02, 0.98); "
                         "edge_yes = p_hat - yes_ask; edge_no = (1-p_hat) - (1-yes_bid); "
                         "edge = max(edge_yes, edge_no); high ROI if edge >= $0.03",
            "swing_alert": "alert when |close(i) - close(i-w)| >= $0.10 (step) or "
                           "(high - low) >= $0.10 in one candle (intrabar)",
            "simulated_trade": "taker fills at the candle's quoted side price; exits at "
                               "+$0.10, -$0.10, or resolution; $1 payout for the winning "
                               "side per market settlement docs; fees not modelled",
        },
        "snapshots": {
            "markets_open_retrieved_at": open_snap.get("retrieved_at"),
            "markets_open_count": open_snap.get("count"),
            "markets_settled_retrieved_at": settled_snap.get("retrieved_at"),
            "markets_settled_count": settled_snap.get("count"),
            "events_retrieved_at": events_snap.get("retrieved_at"),
        },
        "alerts_by_topic": {t: sum(1 for a in alerts if a["topic"] == t) for t in TOPICS},
        "alerts_by_environment": {
            "demo": sum(1 for a in alerts if a.get("environment") == "demo"),
            "production": sum(1 for a in alerts if a.get("environment") == "production")},
        "largest_move_by_topic": largest_moves(store, tracked),
        "candle_coverage": {t: sum(1 for m in tracked if m["topic"] == t
                                   and m.get("has_candle_history")) for t in TOPICS},
        "counts": {"tracked": len(tracked), "alerts": len(alerts),
                   "alerts_high_roi": len(roi_alerts),
                   "simulated_trades": len(trades),
                   "resolved_markets": len(res),
                   "candle_markets": candles_out["count"]},
        "topics": [{"id": t, "label": TOPIC_LABEL[t]} for t in TOPICS],
    }

    write("meta.json", meta)
    write("markets.json", {"generated_at": NOW.isoformat(), "count": len(tracked),
                           "topics": meta["topics"], "markets": tracked})
    write("alerts.json", {"generated_at": NOW.isoformat(), "threshold": SWING_THRESHOLD,
                          "count": len(alerts), "alerts": alerts,
                          "source_url": SOURCES["get_candlesticks"]})
    write("alerts_roi.json", {"generated_at": NOW.isoformat(), "threshold": SWING_THRESHOLD,
                              "roi_min_ev": ROI_MIN_EV,
        "roi_min_roi_pct": ROI_MIN_ROI_PCT, "count": len(roi_alerts),
                              "alerts": roi_alerts})
    # the page loads per-contract files from live/data/candles/ via
    # candles_index.json, so the aggregate payload is not written (size)
    # write("candles.json", candles_out)
    write("trades.json", {"generated_at": NOW.isoformat(), "mode": "simulated",
                          "deterministic": True, "strategies": STRATEGIES,
                          "count": len(trades), "trades": trades})
    write("portfolio.json", {"generated_at": NOW.isoformat(), "mode": "simulated",
                             "bankroll": BANKROLL, "books": books})
    write("resolutions.json", {"generated_at": NOW.isoformat(), **resolution_view})
    write("review.json", review)

    print("wrote live/data/*.json")
    print(f"  alerts {len(alerts)} / ROI {len(roi_alerts)} / trades {len(trades)} / "
          f"candles {candles_out['count']}")
    return 0


def largest_moves(store, tracked):
    """Largest absolute hourly close-to-close move per topic, with its source URL.

    Reported next to the alerts so a topic with no $0.10 swing still shows what
    actually happened (never presented as an alert)."""
    out = {}
    topic_of = {m["ticker"]: m["topic"] for m in tracked}
    for ticker, entry in store.items():
        t = topic_of.get(ticker)
        if t not in TOPICS:
            continue
        rows = entry["series"].get(60) or []
        closes = [(r[0], f(r[3], None)) for r in rows if r[3] is not None]
        closes = [(t, p) for t, p in closes if p is not None]
        best = None
        for (t1, p1), (t2, p2) in zip(closes, closes[1:]):
            d = abs(p2 - p1)
            if best is None or d > best["abs_move"]:
                best = {"ticker": ticker, "topic": t, "ts": iso(t2),
                        "from_price": rnd(p1, 4), "to_price": rnd(p2, 4),
                        "abs_move": rnd(d, 4), "delta": rnd(p2 - p1, 4),
                        "source_url": entry["source_url"],
                        "environment": entry.get("environment"),
                        "window": "1 hour"}
        if best and (t not in out or best["abs_move"] > out[t]["abs_move"]):
            out[t] = best
    return out


def build_review(tracked, alerts, trades, candles_out, open_snap):
    flags = []

    def flag(fid, area, item, detail, sources, status="needs review"):
        flags.append({"id": fid, "area": area, "item": item, "detail": detail,
                      "sources": sources, "status": status})

    flag("L-01", "Data freshness",
         "Live snapshots are refreshed by a scheduled collector, not a streaming feed",
         "The desk renders the last committed collector snapshot plus in-browser REST "
         "polling. As of this build the newest snapshot is "
         f"{open_snap.get('retrieved_at')}. Browser polling hits the demo API directly; "
         "if the browser or the API blocks the request the page says so instead of "
         "showing stale numbers as live.",
         [SOURCES["market_data_no_auth"], SOURCES["rate_limits"]])
    flag("L-02", "Synthetic demo series",
         "Some demo series are exchange self-tests and are excluded from tracking",
         "Series such as KXDEMOFUTHOURLY (hourly 'Demo BTC' markets) and KXQUICKSETTLE "
         "exist only on the demo exchange for testing. They rank high by volume and are "
         "excluded from the tracked/ranked tables here so they are not read as real markets.",
         [f"{API}/series/KXDEMOFUTHOURLY", f"{API}/series/KXQUICKSETTLE"])
    flag("L-03", "Derived metric",
         "'Highest dollar amount' is derived, not published",
         "The trade API has no dollar-volume field. The ranking uses "
         "volume_fp x notional_value_dollars and is labelled derived on every page. "
         "The definition of 'highest dollar amount' remains an open question.",
         [SOURCES["get_markets"]])
    flag("L-04", "Model",
         "The ROI score is a heuristic, not a measured return",
         "p_hat is built from the quoted midpoint, one hour of price momentum and the "
         "spread. The formula is published on the page; it is a way to prioritise what "
         "to look at and makes no claim about realised returns.",
         [SOURCES["get_candlesticks"], SOURCES["get_orderbook"]])
    flag("L-05", "Simulation",
         "Simulated fills are modelled at quoted prices and fees are not included",
         "Every simulated trade fills as a taker at the candlestick's quoted side price, "
         "exits at +$0.10, -$0.10 or resolution, and pays $1 per winning contract per the "
         "settlement docs. Exchange fees are not modelled because the demo fee schedule was "
         "not verified for this environment.",
         [SOURCES["market_settlement"], SOURCES["demo_env"]])
    flag("L-06", "Fees",
         "Fee model absent (unverified for the demo environment)",
         "No fee schedule for the demo exchange was confirmed from an official Kalshi page "
         "during this build, so fees are recorded as 0.00 and labelled, never estimated.",
         [SOURCES["demo_env"]])
    flag("L-07", "Credentials",
         "No demo API credentials are configured in this repository",
         "Portfolio reads and live demo order entry need a demo API key "
         "(KALSHI_DEMO_API_KEY_ID / KALSHI_DEMO_PRIVATE_KEY). They are not present, so the "
         "desk runs paper/simulated only: no order is ever sent and no account balance is "
         "displayed. Account values are blank, not estimated.",
         [SOURCES["demo_env"], SOURCES["get_balance"]])
    flag("L-08", "Causation",
         "News attribution is a link, not a proven cause",
         "Each alert shows an official source link for the price data and a search link for "
         "headlines around that timestamp. A headline is never asserted to have caused the "
         "move; the page says the association is unverified.",
         [SOURCES["get_candlesticks"]])
    flag("L-09", "Coverage",
         "Candlestick history is limited to the tracked lines",
         f"{candles_out['count']} contracts have committed candlestick history; others are "
         "tracked by quote only. Coverage is stated on the page rather than implied.",
         [SOURCES["get_candlesticks"]])
    flag("L-12", "Coverage",
         "Some topics had no committed $0.10 swing during the collected windows",
         "Alerts are only ever produced from committed official candlesticks. Gas, crypto "
         "and golf contracts in the archive traded in increments smaller than $0.10 over "
         "the collected windows, so they appear on the topic pages with their quotes and "
         "candles but with no swing alerts. Nothing is invented to fill the gap; the "
         "scheduled collector widens the history over time.",
         [SOURCES["get_candlesticks"]])
    flag("L-11", "Environment mixing",
         "Some candlestick history comes from the production API archive, labelled",
         "data/latest/candles.json and data/history/ hold demo-exchange payloads. Gas, "
         "crypto and golf hourly history in analysis/data/live/candles.json was collected "
         "from the production endpoint (api.elections.kalshi.com). Those contracts are "
         "copied read-only and carry environment='production' in every table and chart "
         "caption so demo and production data are never confused.",
         ["https://docs.kalshi.com/getting_started/api_environments"])
    flag("L-13", "Data quality",
         "Quote-only moves are labelled",
         "A swing where the exchange reported zero volume in the period is a quote move, "
         "not a trade. Those alerts carry a 'no trades in window' badge and are not "
         "presented as executed price moves.",
         [SOURCES["get_candlesticks"], SOURCES["get_trades"]])
    flag("L-10", "WebSockets",
         "The browser cannot open an authenticated Kalshi WebSocket",
         "WS handshakes require KALSHI-ACCESS-* signature headers, which a static page "
         "cannot attach. The desk therefore polls REST and labels the transport.",
         [SOURCES["websockets_auth"]])
    return {"generated_at": NOW.isoformat(), "count": len(flags), "flags": flags,
            "verified": [
                {"item": "Demo REST base URL", "value": API,
                 "source": SOURCES["api_environments"]},
                {"item": "Public market data without auth", "value": "supported",
                 "source": SOURCES["market_data_no_auth"]},
                {"item": "Candlestick path",
                 "value": "/series/{series_ticker}/markets/{ticker}/candlesticks "
                          "?start_ts&end_ts&period_interval(1|60|1440)",
                 "source": SOURCES["get_candlesticks"]},
                {"item": "Orderbook response", "value": "orderbook_fp.{yes_dollars,"
                 "no_dollars} = [[price_dollars, contract_count], ...]",
                 "source": SOURCES["get_orderbook"]},
                {"item": "Settlement payout", "value": "$1 per winning contract",
                 "source": SOURCES["market_settlement"]},
            ]}


if __name__ == "__main__":
    raise SystemExit(main())
