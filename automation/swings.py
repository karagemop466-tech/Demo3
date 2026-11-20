"""Pure detection logic for the live alerting dashboard.

Everything in this module is a deterministic function of explicitly-passed
observations, which is what makes the output verifiable: each alert records the two
exact API URLs (and timestamps) of the observations that produced it, so any reader can
re-fetch the URL and check the number instead of trusting it.

Definitions (published on alerts.html):
  * price      = `last_price_dollars` (dollars per contract, 0.00-1.00) with
                 `previous_price_dollars` as the fallback the API itself provides.
                 Source: https://docs.kalshi.com/api-reference/market/get-markets
  * swing      = |price_now - price_prev| >= $0.10, up (up) or down (down).
  * window     = the alert is raised when the change happens between the previous poll
                 and the current poll. The observation gap is stored on every alert.
  * resolution = `market.result` ("yes"/"no") once `status` is settled.
                 Source: https://docs.kalshi.com/getting_started/market_settlement
  * liquidity  = `orderbook_fp.yes_dollars` / `no_dollars` levels, each
                 [price_dollars, contracts]: exactly "how many contracts are available
                 at a given price".
                 Source: https://docs.kalshi.com/api-reference/market/get-market-orderbook
  * ROI screen = the documented, deterministic rule used to decide which alerts the
                 "high-ROI" feed shows. It is a screen, not a promise of return.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from .kalshi_http import num

SWING_THRESHOLD = 0.10  # US dollars per contract, per the project requirement

# ---------------------------------------------------------------- high-ROI screen
# Published rule (alerts.html + strategy.html show the same table):
#   expected ROI per $1 staked, at the observed post-swing price p:
#       buy  YES -> ROI = (1 - p) / p          (pays $1 if YES)
#       buy  NO  -> ROI = (1 - (1 - p)) / (1 - p) = p / (1 - p)
#   The feed keeps alerts whose *tradable* ROI >= MIN_ROI and whose swing is at least
#   the threshold. "Tradable" means the move is at least MIN_ROI_CUSHION beyond the
#   threshold, so a $0.10-move on a coin-flip does not masquerade as high ROI.
MIN_ROI = 0.25          # 25% gross return per $1 at the post-swing price
MIN_ROI_CUSHION = 0.10  # require a swing >= $0.20 for a "high ROI" label


def roi_buy(price_: Optional[float], side: str) -> Optional[float]:
    """Gross ROI per $1 staked for buying `side` at `price_` dollars (no fees)."""
    if price_ is None:
        return None
    if side == "yes":
        p = price_
    else:
        p = 1.0 - price_
    if p is None or p <= 0.0 or p >= 1.0:
        return None  # cannot buy at 0 or 1 dollar: no tradable edge
    return (1.0 - p) / p


def roi_screen(old: float, new: float) -> dict:
    """High-ROI screen for a swing from `old` to `new`.

    The move direction tells us which side got cheaper *after* the swing:
      * price jumped up   -> YES got expensive, NO is the value side
      * price dropped down-> NO got expensive, YES is the value side
    Returns a dict; `passes` is False whenever an input is missing so that nothing is
    ever inferred from a blank value.
    """
    out = {
        "rule": "high_roi_v1",
        "min_roi": MIN_ROI,
        "min_swing": MIN_ROI_CUSHION,
        "passes": False,
        "side": None,
        "entry_price": None,
        "roi": None,
        "reason": "",
    }
    if old is None or new is None:
        out["reason"] = "price missing"
        return out
    delta = new - old
    if abs(delta) < MIN_ROI_CUSHION:
        out["reason"] = (f"swing ${abs(delta):.2f} < ${MIN_ROI_CUSHION:.2f} cushion")
        return out
    side = "no" if delta > 0 else "yes"
    entry = (1.0 - new) if side == "no" else new
    roi = roi_buy(new, side)
    out.update({"side": side, "entry_price": entry, "roi": roi})
    if roi is None:
        out["reason"] = "post-swing price not tradable (0 or $1)"
        return out
    if roi < MIN_ROI:
        out["reason"] = f"ROI {roi:.2f} < {MIN_ROI:.2f}"
        return out
    out["passes"] = True
    out["reason"] = (f"buy {side.upper()} at ${entry:.2f} returns "
                     f"{roi * 100:.0f}% per $1 if it settles {side.upper()}")
    return out


# ---------------------------------------------------------------- swing detection
def alert_id(market_ticker: str, prev_ts: str, curr_ts: str, old: float, new: float) -> str:
    raw = f"{market_ticker}|{prev_ts}|{curr_ts}|{old:.4f}|{new:.4f}"
    return "SL-" + hashlib.sha1(raw.encode()).hexdigest()[:12]


def detect_swing(market: dict, prev_price: float, prev_ts: str, prev_url: str,
                 now_ts: str, now_url: str, meta: dict) -> Optional[dict]:
    """Build one alert row if the change between the two observations is >= $0.10."""
    new_price = num(market.get("last_price_dollars"))
    if new_price is None or prev_price is None:
        return None
    delta = round(new_price - prev_price, 4)
    if abs(delta) < SWING_THRESHOLD - 1e-9:
        return None
    screen = roi_screen(prev_price, new_price)
    return {
        "alert_id": alert_id(market.get("ticker", ""), prev_ts, now_ts, prev_price, new_price),
        "market_ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "title": meta.get("title") or market.get("title") or "",
        "yes_sub_title": market.get("yes_sub_title") or "",
        "topic": meta.get("topic"),
        "topic_label": meta.get("topic_label"),
        "direction": "up" if delta > 0 else "down",
        "delta_dollars": round(delta, 4),
        "old_price": round(prev_price, 4),
        "new_price": round(new_price, 4),
        "prev_observed_at": prev_ts,
        "observed_at": now_ts,
        "gap_seconds": _gap_seconds(prev_ts, now_ts),
        "prev_source_url": prev_url,
        "source_url": now_url,
        "volume_24h": num(market.get("volume_24h_fp")),
        "open_interest": num(market.get("open_interest_fp")),
        "yes_bid": num(market.get("yes_bid_dollars")),
        "yes_ask": num(market.get("yes_ask_dollars")),
        "high_roi": bool(screen["passes"]),
        "roi_screen": screen,
        "classification_rule": meta.get("rule"),
        "settlement_sources": meta.get("settlement_sources") or [],
        "kalshi_url": f"https://kalshi.com/markets/{market.get('series_ticker') or ''}",
        "note": ("swing = last_price_dollars change between the two linked API "
                 "observations; threshold $0.10"),
    }


def _gap_seconds(a: str, b: str) -> Optional[int]:
    try:
        ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
        tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return int(abs((tb - ta).total_seconds()))
    except (AttributeError, TypeError, ValueError):
        return None


def detect_candle_swings(candlesticks: Iterable[dict], market: dict, meta: dict,
                         source_url: str, max_keep: int = 8) -> list[dict]:
    """Detect >= $0.10 moves inside 1-minute candlesticks.

    Two independent, documented measures, both taken from official candlestick fields
    (https://docs.kalshi.com/api-reference/market/get-market-candlesticks):
      * close-to-close: price.close_dollars[t] - price.close_dollars[t-1]
      * intra-candle:   price.high_dollars - price.low_dollars
    Each row keeps the candle timestamps and the exact request URL.
    """
    rows: list[dict] = []
    candles = [c for c in candlesticks if isinstance(c, dict)]
    prev_close = None
    for c in candles:
        p = c.get("price") or {}
        close_ = num(p.get("close_dollars"))
        high = num(p.get("high_dollars"))
        low = num(p.get("low_dollars"))
        ts = c.get("end_period_ts")
        iso = (datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
               if isinstance(ts, (int, float)) else None)
        if close_ is not None and prev_close is not None:
            d = round(close_ - prev_close, 4)
            if abs(d) >= SWING_THRESHOLD - 1e-9:
                rows.append(_candle_row("close_to_close", d, prev_close, close_, iso,
                                        market, meta, source_url, c))
        if high is not None and low is not None:
            d = round(high - low, 4)
            if abs(d) >= SWING_THRESHOLD - 1e-9:
                rows.append(_candle_row("intra_candle_high_low", d, low, high, iso,
                                        market, meta, source_url, c))
        if close_ is not None:
            prev_close = close_
    rows.sort(key=lambda r: r.get("observed_at") or "", reverse=True)
    return rows[:max_keep]


def _candle_row(kind: str, delta: float, old: float, new: float, ts: Optional[str],
                market: dict, meta: dict, source_url: str, candle: dict) -> dict:
    screen = roi_screen(old, new)
    return {
        "alert_id": alert_id(market.get("ticker", "") + "|" + kind, "", ts or "", old, new),
        "kind": kind,
        "market_ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "title": meta.get("title") or "",
        "yes_sub_title": market.get("yes_sub_title") or "",
        "topic": meta.get("topic"),
        "topic_label": meta.get("topic_label"),
        "direction": "up" if delta > 0 else "down",
        "delta_dollars": delta,
        "old_price": round(old, 4),
        "new_price": round(new, 4),
        "observed_at": ts,
        "candle_end_period_ts": candle.get("end_period_ts"),
        "volume": num(candle.get("volume_fp")),
        "source_url": source_url,
        "high_roi": bool(screen["passes"]),
        "roi_screen": screen,
        "classification_rule": meta.get("rule"),
        "settlement_sources": meta.get("settlement_sources") or [],
        "note": ("detected inside 1-minute candlesticks: " + kind +
                 " (docs: get-market-candlesticks)"),
    }


# ---------------------------------------------------------------- resolutions
def resolution_row(market: dict, meta: dict, observed_at: str, source_url: str) -> Optional[dict]:
    """One resolved event row: result must be exactly "yes" or "no" per the API."""
    result = (market.get("result") or "").strip().lower()
    if result not in ("yes", "no"):
        return None
    return {
        "market_ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "title": meta.get("title") or market.get("title") or "",
        "yes_sub_title": market.get("yes_sub_title") or "",
        "topic": meta.get("topic"),
        "topic_label": meta.get("topic_label"),
        "result": result,
        "status": market.get("status"),
        "settlement_value_dollars": num(market.get("settlement_value_dollars")),
        "settlement_ts": market.get("settlement_ts"),
        "close_time": market.get("close_time"),
        "last_price_dollars": num(market.get("last_price_dollars")),
        "volume": num(market.get("volume_fp")),
        "open_interest": num(market.get("open_interest_fp")),
        "observed_at": observed_at,
        "source_url": source_url,
        "settlement_sources": meta.get("settlement_sources") or [],
        "settlement_doc": "https://docs.kalshi.com/getting_started/market_settlement",
    }


def resolution_timing(res: dict) -> Optional[int]:
    """Seconds between market close and the settlement timestamp the API reports."""
    close_, settled = res.get("close_time"), res.get("settlement_ts")
    if not close_ or not settled:
        return None
    try:
        a = datetime.fromisoformat(str(close_).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(settled).replace("Z", "+00:00"))
        return int((b - a).total_seconds())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- liquidity
def orderbook_levels(book: dict) -> dict:
    """Return {"yes": [{price, contracts}], "no": [...]} from orderbook_fp.

    Shape verified in https://docs.kalshi.com/api-reference/market/get-market-orderbook:
        {"orderbook_fp": {"yes_dollars": [["0.1500","100.00"], ...], "no_dollars": [...]}}
    """
    ob = (book or {}).get("orderbook_fp") or book or {}
    out = {"yes": [], "no": []}
    for side, key in (("yes", "yes_dollars"), ("no", "no_dollars")):
        for lvl in ob.get(key) or []:
            if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
                continue
            p, c = num(lvl[0]), num(lvl[1])
            if p is None or c is None:
                continue
            out[side].append({"price": p, "contracts": c})
        out[side].sort(key=lambda x: x["price"])
    yes = out["yes"]
    out["summary"] = {
        "best_yes_bid": max((l["price"] for l in yes), default=None),
        "best_yes_bid_contracts": (max(yes, key=lambda l: l["price"])["contracts"]
                                   if yes else None),
        "yes_contracts_total": round(sum(l["contracts"] for l in yes), 2) if yes else 0.0,
        "no_contracts_total": round(sum(l["contracts"] for l in out["no"]), 2),
        "yes_notional": round(sum(l["price"] * l["contracts"] for l in yes), 2),
        "no_notional": round(sum(l["price"] * l["contracts"] for l in out["no"]), 2),
    }
    return out


# ---------------------------------------------------------------- portfolio math
def simulate_outcome(entry_price: float, contracts: float, side: str, result: str) -> dict:
    """Settle one simulated position using the official settlement rule:
    the winning side receives $1 per contract
    (https://docs.kalshi.com/getting_started/market_settlement)."""
    cost = round(entry_price * contracts, 6)
    payout = round((1.0 if side == result else 0.0) * contracts, 6)
    return {
        "cost": round(cost, 2),
        "payout": round(payout, 2),
        "pnl": round(payout - cost, 2),
        "roi": (round((payout - cost) / cost, 4) if cost else None),
        "market_result": result,
        "side": side,
        "won": side == result,
    }


def to_json(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False)
