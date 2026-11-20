"""Trade categorization + strategy framework for the demo dashboard.

Every classification is derived only from fields the exchange reports (entry price,
side, last traded price, volume) — nothing is inferred about future performance.
Strategy tags group trades so the dashboard can answer: "what kind of trade is this,
and which kinds have performed how?" (project brief: categorize trades and create
strategies based on the type of trade).
"""

from __future__ import annotations

STRUCTURE_RULES = [
    # (structure id, human label, predicate)  — evaluated in order, first match wins
    ("directional_lock", "Lock (>=90c)", lambda a, p: a == "buy" and p >= 0.90),
    ("directional_favorite", "Favorite (55-90c)", lambda a, p: a == "buy" and p > 0.55),
    ("directional_coinflip", "Coin-flip (45-55c)", lambda a, p: a == "buy" and 0.45 <= p <= 0.55),
    ("directional_value", "Value (10-45c)", lambda a, p: a == "buy" and p > 0.10),
    ("directional_longshot", "Longshot (<=10c)", lambda a, p: a == "buy" and p <= 0.10),
    ("fade_lock", "Fade lock (sell >=90c)", lambda a, p: a == "sell" and p >= 0.90),
    ("fade_longshot", "Fade longshot (sell <=10c)", lambda a, p: a == "sell" and p <= 0.10),
    ("fade", "Fade (sell)", lambda a, p: a == "sell"),
]


def classify_trade(action: str, side: str, price: float,
                   market_last: float | None = None,
                   market_volume: float | None = None) -> dict:
    """Return a classification record for one order."""
    structure, label = "directional", "Directional"
    for sid, lbl, pred in STRUCTURE_RULES:
        try:
            if pred(action, price):
                structure, label = sid, lbl
                break
        except Exception:
            continue
    drift = None
    if market_last is not None:
        drift = round(price - market_last, 4)  # +ve = paying over last, -ve = under
    return {
        "structure": structure,
        "structure_label": label,
        "side": side,
        "action": action,
        "entry_vs_last": drift,
        "liquidity_context": {
            "market_last_dollars": market_last,
            "market_volume": market_volume,
        },
        "note": "classification uses only exchange-reported fields (price, last, volume)",
    }


# --------------------------------------------------------------------------
# Framework strategies (documented defaults; performance is measured, never assumed)
# --------------------------------------------------------------------------
STRATEGY_LIBRARY = [
    {
        "id": "favorite-confirmation",
        "name": "Favorite confirmation",
        "applies_to": ["elections", "crypto"],
        "rule": "Buy YES in a trending favorite only when best yes_bid_size >= 50 "
                "contracts and yes_ask spread <= 2c; exit on category-specific stop.",
        "risk": "mean-reversion of long favorites after news spikes",
        "status": "framework default - no live performance record yet",
    },
    {
        "id": "gas-mean-revert",
        "name": "Gas-price mean reversion",
        "applies_to": ["gas"],
        "rule": "Daily gas-price markets: when price deviates >15c from the 60-minute "
                "candle VWAP band, trade toward the band; stand down within 2h of close.",
        "risk": "settlement-time whipsaw; thin books near expiry",
        "status": "framework default - no live performance record yet",
    },
    {
        "id": "crypto-momentum",
        "name": "Crypto momentum continuation",
        "applies_to": ["crypto"],
        "rule": "On 1-minute candles, ride 3 consecutive higher highs for BTC/ETH "
                "above/below markets; reverse on volume climax > 3x 20-bar average.",
        "risk": "24/7 series with fast mean reversion; fees compound on churn",
        "status": "framework default - no live performance record yet",
    },
    {
        "id": "golf-leaderboard-value",
        "name": "Golf leaderboard value",
        "applies_to": ["golf"],
        "rule": "Mid-tournament: buy co-leaders priced below 25c when weather delay "
                "compresses finishing variance; hedge with the field on Sunday.",
        "risk": "single-outcome variance is extreme in small fields",
        "status": "framework default - no live performance record yet",
    },
    {
        "id": "culture-crossover",
        "name": "Culture crossover",
        "applies_to": ["culture"],
        "rule": "Multi-outcome award shows: back the 2nd-odds nominee if combined top-2 "
                "prices < $0.95 (longshot basket), avoid markets with open interest < $1k.",
        "risk": "mutually-exclusive event legs settle one winner only",
        "status": "framework default - no live performance record yet",
    },
    {
        "id": "arb-cross-book",
        "name": "Cross-book arb guard",
        "applies_to": ["*"],
        "rule": "Monitor yes_bid + no_bid > $1.00 on the same market; buy both sides "
                "when net > 1c after fees; report, never chase < 1c.",
        "risk": "fee schedule (kalshi.com/docs/kalshi-fee-schedule.pdf) erodes thin edges",
        "status": "framework default - no live performance record yet",
    },
]


def strategy_suggestions(topic: str | None) -> list[dict]:
    """Strategies that apply to a topic, or all when topic is None."""
    if topic is None:
        return STRATEGY_LIBRARY
    return [s for s in STRATEGY_LIBRARY
            if topic in s["applies_to"] or "*" in s["applies_to"]]
