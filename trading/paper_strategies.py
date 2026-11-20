"""Deterministic strategy rules + trade categorization for the paper-trading desk.

Every rule reads ONLY fields the Kalshi demo API publishes; every threshold is a
literal in this file so a run can be reproduced by hand. No rule predicts or
promises a return — the desk exists to MEASURE what each rule type did on demo
prices (project brief: "Automate simulated trades to test different strategies" and
"categorize trades and create strategies based on the type of trade").

Official field semantics used here (fetched from the docs on 2026-11-20, register in
`paper-desk/SOURCES.md`):
- `yes_bid_dollars`  — "Price for the highest YES buy offer on this market in dollars"
- `yes_ask_dollars`  — "Price for the lowest YES sell offer on this market in dollars"
- `yes_bid_size_fp`  — "Total contract size of orders to buy YES at the best bid price"
- `yes_ask_size_fp`  — "Total contract size of orders to sell YES at the best ask price"
- `no_bid_dollars` / `no_ask_dollars` — same for the NO side
- `last_price_dollars` — "Price for the last traded YES contract on this market in dollars"
- `previous_price_dollars` / `previous_yes_bid_dollars` / `previous_yes_ask_dollars` —
  the same three quantities "a day ago" (the docs state the one-day reference)
- `volume_24h_fp`, `volume_fp`, `open_interest_fp` — contract counts
- `result` — enum 'yes' | 'no' | 'scalar' | ''
- `price_ranges` — "Valid price ranges for orders on this market" (start/end/step)
Sources: https://docs.kalshi.com/api-reference/market/get-markets.md (Market schema),
https://docs.kalshi.com/getting_started/orderbook_responses.md (reciprocal YES/NO book).
"""

from __future__ import annotations

SWING_THRESHOLD_DOLLARS = 0.10  # project brief: alert/act on moves >= $0.10 either way

# --------------------------------------------------------------------- primitives
STRATEGY_LIST = [
    {
        "id": "swing_fade",
        "label": "Swing fade (buy after a >= $0.10 drop)",
        "family": "reversion",
        "entry": "best ask available with size, after last->ask fell by >= 0.10 vs the "
                 "previous desk sample and price stays inside [0.10, 0.90]",
        "exit": "take-profit +0.20, stop -0.20, else hold to settlement",
        "fields": ["yes_bid_dollars", "yes_ask_dollars", "volume_24h_fp", "status"],
    },
    {
        "id": "swing_momentum",
        "label": "Swing momentum (buy after a >= $0.10 rise)",
        "family": "momentum",
        "entry": "best ask available with size, after last->ask rose by >= 0.10 vs the "
                 "previous desk sample, price inside [0.10, 0.90] and 24h volume > 0",
        "exit": "take-profit +0.20, stop -0.20, else hold to settlement",
        "fields": ["yes_bid_dollars", "yes_ask_dollars", "volume_24h_fp", "status"],
    },
    {
        "id": "favorite_carry",
        "label": "Favorite carry (buy >= 0.90 quotes closing within 14 days)",
        "family": "carry",
        "entry": "best ask in [0.90, 0.99] with size, close_time within 14 days",
        "exit": "take-profit +0.20, stop -0.20, else hold to settlement",
        "fields": ["yes_ask_dollars", "yes_ask_size_fp", "close_time", "status"],
    },
    {
        "id": "longshot_fade_no",
        "label": "Longshot fade (buy NO when YES quotes <= 0.10)",
        "family": "reversion",
        "entry": "best NO ask in [0.90, 0.99] with size, YES last <= 0.10, 24h volume > 0",
        "exit": "take-profit +0.20, stop -0.20, else hold to settlement",
        "fields": ["no_ask_dollars", "yes_bid_size_fp", "last_price_dollars",
                   "volume_24h_fp", "close_time"],
    },
    {
        "id": "maker_midquote",
        "label": "Maker mid-quote (resting bid one tick inside the spread)",
        "family": "liquidity",
        "entry": "resting limit buy at yes_bid + one grid step (never crosses); fills only "
                 "when a later demo sample shows the best ask at or below the limit",
        "exit": "take-profit +0.20, stop -0.20, else hold to settlement",
        "fields": ["yes_bid_dollars", "yes_ask_dollars", "price_ranges", "status"],
    },
]

STRATEGIES = {s["id"]: s for s in STRATEGY_LIST}

# Exit rules (identical for every strategy so results are comparable across families).
TAKE_PROFIT_DOLLARS = 0.20
STOP_LOSS_DOLLARS = 0.20
MAX_HOLD_RUNS = 96  # 96 desk samples; after that the position is closed at the bid


def price_band(price: float | None) -> str:
    """Coarse band label for grouping trades (documented in Methodology on the site)."""
    if price is None:
        return "unknown"
    if price <= 0.10:
        return "0-10c (longshot)"
    if price < 0.30:
        return "10-30c"
    if price <= 0.70:
        return "30-70c (middle)"
    if price < 0.90:
        return "70-90c"
    return "90-100c (near-certain)"


def structure_label(action: str, side: str, price: float | None) -> str:
    """Trade-type label derived only from exchange-reported price/side."""
    if price is None:
        return f"{action} {side} (price unknown)"
    band = price_band(price)
    return f"{action} {side} @ {band}"


def categorize(quote: dict, action: str, side: str, price: float | None,
               topic: str | None) -> dict:
    """Return the categorization record stored with every simulated trade."""
    return {
        "topic": topic or "unknown",
        "action": action,
        "side": side,
        "price_dollars": price,
        "price_band": price_band(price),
        "structure": structure_label(action, side, price),
        "spread_dollars": spread_dollars(quote),
        "quote_context": {
            "yes_bid_dollars": quote.get("yes_bid"),
            "yes_ask_dollars": quote.get("yes_ask"),
            "no_bid_dollars": quote.get("no_bid"),
            "no_ask_dollars": quote.get("no_ask"),
            "last_price_dollars": quote.get("last"),
            "yes_bid_size_fp": quote.get("yes_bid_size"),
            "yes_ask_size_fp": quote.get("yes_ask_size"),
            "volume_24h_fp": quote.get("volume_24h"),
            "open_interest_fp": quote.get("open_interest"),
        },
        "note": "classification uses only fields the demo API reported at decision time",
    }


def spread_dollars(quote: dict) -> float | None:
    """Best YES bid -> ask spread; asks may be quoted at 1.00 when nobody sells."""
    bid, ask = quote.get("yes_bid"), quote.get("yes_ask")
    if bid is None or ask is None:
        return None
    return round(max(0.0, ask - bid), 4)


def grid_step(market: dict) -> float | None:
    """Smallest documented tick for this market (`price_ranges[].step`).

    https://docs.kalshi.com/api-reference/market/get-markets.md: `price_ranges` =
    "Valid price ranges for orders on this market".
    """
    steps = []
    for rng in market.get("price_ranges") or []:
        try:
            steps.append(float(rng["step"]))
        except (KeyError, TypeError, ValueError):
            continue
    return min(steps) if steps else None


def snap_to_grid(price: float, market: dict, direction: str = "down") -> float | None:
    """Round `price` onto the market's own price grid, keeping it order-legal.

    Returns None when no grid price exists in [step, 1 - step] (defensive: never
    simulate an order the exchange would reject with `invalid_price`).
    """
    step = grid_step(market)
    if step is None or step <= 0:
        step = 0.01
    lo, hi = step, round(1.0 - step, 6)
    scaled = price / step
    cand = int(scaled // 1) if direction == "down" else int(-((-scaled) // 1))
    cand = round(cand * step, 6)
    if cand < lo or cand > hi:
        cand = min(max(cand, lo), hi)
    if cand < lo or cand > hi:
        return None
    return round(cand, 4)


def price_on_grid(price: float, market: dict) -> bool:
    """True when `price` is a legal order price for this market (grid + range check)."""
    ranges = market.get("price_ranges") or []
    if not ranges:
        return 0.0 <= price <= 1.0
    for rng in ranges:
        try:
            start, end, step = float(rng["start"]), float(rng["end"]), float(rng["step"])
        except (KeyError, TypeError, ValueError):
            continue
        if price < start - 1e-9 or price > end + 1e-9:
            continue
        if step <= 0:
            return True
        k = (price - start) / step
        return abs(k - round(k)) < 1e-6
    return False


# ------------------------------------------------------------------ entry rules
def evaluate_entries(ctx: dict) -> list[dict]:
    """Return intents for one market. Pure function of `ctx` (deterministic).

    `ctx` keys: quote (parsed), prior (previous desk sample or {}), market (raw API
    object), topic, ticker, event_ticker, title, hours_to_close, config.
    """
    q = ctx["quote"]
    prior = ctx.get("prior") or {}
    cfg = ctx.get("config") or {}
    hours = ctx.get("hours_to_close")
    if ctx.get("status") != "active":
        return []

    yes_bid = q.get("yes_bid")
    yes_ask = q.get("yes_ask")
    no_ask = q.get("no_ask")
    last = q.get("last")
    vol24 = q.get("volume_24h") or 0.0
    intents: list[dict] = []

    # --- move measures (each is arithmetic on published fields) -----------------
    # desk-to-desk move: this sample's ask vs the previous sample's ask
    delta_desk = None
    if yes_ask is not None and prior.get("yes_ask") is not None:
        delta_desk = round(yes_ask - prior["yes_ask"], 4)
    # one-day move: docs define previous_yes_ask_dollars as the lowest YES sell offer
    # "a day ago", so this is a 24h reference, not a tick-to-tick change.
    delta_day = None
    prev_ask = q.get("previous_yes_ask")
    if yes_ask is not None and prev_ask is not None:
        delta_day = round(yes_ask - prev_ask, 4)

    signal = {
        "delta_desk_dollars": delta_desk,
        "delta_day_dollars": delta_day,
        "swing_threshold_dollars": SWING_THRESHOLD_DOLLARS,
        "prior_yes_ask_dollars": prior.get("yes_ask"),
        "previous_yes_ask_dollars_day_ago": prev_ask,
        "last_price_dollars": last,
    }
    tradeable_band = yes_ask is not None and 0.10 <= yes_ask <= 0.90

    # 1) swing fade: >= $0.10 drop since the last desk sample -> buy the dip
    if (delta_desk is not None and delta_desk <= -SWING_THRESHOLD_DOLLARS
            and tradeable_band):
        intents.append(_intent("swing_fade", ctx, "taker", "yes", yes_ask,
                               "best available ask after a "
                               f"{abs(delta_desk):.4f} USD drop since the previous desk sample",
                               signal))

    # 2) swing momentum: >= $0.10 rise since the last desk sample with 24h volume
    if (delta_desk is not None and delta_desk >= SWING_THRESHOLD_DOLLARS
            and tradeable_band and vol24 > 0):
        intents.append(_intent("swing_momentum", ctx, "taker", "yes", yes_ask,
                               "best available ask after a "
                               f"{delta_desk:.4f} USD rise since the previous desk sample "
                               "with 24h volume > 0", signal))

    # 3) favorite carry: near-certain YES closing soon
    if (yes_ask is not None and 0.90 <= yes_ask <= 0.99
            and hours is not None and 0 < hours <= 14 * 24):
        intents.append(_intent("favorite_carry", ctx, "taker", "yes", yes_ask,
                               "ask inside [0.90, 0.99] "
                               f"with {hours:.0f}h to close", signal))

    # 4) longshot fade: YES <= 0.10 with 24h volume -> buy NO at its best ask
    if (last is not None and last <= 0.10 and no_ask is not None
            and 0.90 <= no_ask <= 0.99 and vol24 > 0):
        intents.append(_intent("longshot_fade_no", ctx, "taker", "no", no_ask,
                               f"YES last {last:.4f} <= 0.10 and NO ask {no_ask:.4f} "
                               "inside [0.90, 0.99] with 24h volume > 0", signal))

    # 5) maker: rest one grid step above the best bid, never crossing the ask
    if yes_bid is not None and yes_ask is not None and yes_ask - yes_bid >= 2 * (
            grid_step(ctx["market"]) or 0.01):
        step = grid_step(ctx["market"]) or 0.01
        limit = snap_to_grid(round(yes_bid + step, 4), ctx["market"], "down")
        if limit is not None and limit < yes_ask:
            intents.append(_intent("maker_midquote", ctx, "maker", "yes", limit,
                                   f"resting bid {limit:.4f} one grid step above the best "
                                   f"bid {yes_bid:.4f} (spread {yes_ask - yes_bid:.4f})",
                                   signal, resting=True))
    return [i for i in intents if i]


def _intent(strategy_id: str, ctx: dict, role: str, side: str, price: float | None,
            reason: str, signal: dict, resting: bool = False) -> dict:
    return {
        "strategy": strategy_id,
        "strategy_label": STRATEGIES[strategy_id]["label"],
        "family": STRATEGIES[strategy_id]["family"],
        "role": role,
        "action": "open",
        "side": side,
        "price_dollars": None if price is None else round(float(price), 4),
        "ticker": ctx["ticker"],
        "event_ticker": ctx["event_ticker"],
        "topic": ctx.get("topic"),
        "title": ctx.get("title"),
        "reason": reason,
        "signal": dict(signal),
        "resting": resting,
        "classification": categorize(ctx["quote"], "open", side, price, ctx.get("topic")),
    }


# -------------------------------------------------------------------- exit rules
def evaluate_exits(position: dict, quote: dict, runs_held: int) -> dict | None:
    """Return a close intent, or None to keep holding.

    Uses the position's own bid (the price at which the held side can be sold now),
    which is what the exchange would give a taker.
    """
    entry = position.get("avg_price_dollars")
    exit_price = quote.get("yes_bid") if position.get("side") == "yes" else quote.get("no_bid")
    if entry is None or exit_price is None:
        return None
    move = round(exit_price - entry, 4)
    why = None
    if move >= TAKE_PROFIT_DOLLARS:
        why = f"take-profit: bid moved {move:+.4f} USD vs entry (rule +{TAKE_PROFIT_DOLLARS:.2f})"
    elif move <= -STOP_LOSS_DOLLARS:
        why = f"stop-loss: bid moved {move:+.4f} USD vs entry (rule -{STOP_LOSS_DOLLARS:.2f})"
    elif runs_held >= MAX_HOLD_RUNS:
        why = f"time-stop: held {runs_held} desk samples (rule {MAX_HOLD_RUNS})"
    if not why:
        return None
    return {
        "action": "close",
        "price_dollars": round(exit_price, 4),
        "exit_bid_dollars": round(exit_price, 4),
        "move_vs_entry_dollars": move,
        "reason": why,
    }
