"""Automated simulated-trade engine ("paper" strategy tester).

Why simulation instead of live orders: the demo portfolio endpoints require a demo
API key (https://docs.kalshi.com/getting_started/api_keys) and this repository stores no
credentials. Rather than publishing invented balances, the pipeline runs a *fully
specified, deterministic* simulation over real observed prices and settlements, and
labels every row SIMULATED. When repo secrets exist, the same rule set drives real demo
orders (see demo_orders.py) and the two blotters are shown side by side.

Fairness rules baked in (so results are not rigged toward success):
  * A trade can only open on a market that was still open when the alert fired.
  * The fill price is the observed price at alert time, plus a fixed SIM_SLIPPAGE of
    $0.01 per contract (worse for the trader) and a fixed $0.01 fee per contract
    (Kalshi trading fees are variable; this is a conservative placeholder and is
    labelled as such on the page, never presented as the official fee).
  * A trade only settles when the market itself reports status settled with a result
    of exactly "yes" or "no"; otherwise it stays OPEN and is flagged, never assumed.
  * Every trade row carries the observation URL and the settlement URL it used.
"""

from __future__ import annotations

from typing import Iterable, Optional

MAX_CONTRACTS = 100.0       # per simulated trade, keeps any single market from dominating
SIM_SLIPPAGE = 0.01         # dollars per contract, always applied against the trader
SIM_FEE_PER_CONTRACT = 0.01  # conservative placeholder, labelled on the page
STARTING_CASH = 1000.0      # simulated starting balance (labelled SIMULATED)


def strategy_from_alert(alert: dict) -> Optional[dict]:
    """Map one >= $0.10 alert to an automatically simulated trade.

    Documented rule (strategy id `momentum_fade_v1`):
      buy the side that just became cheaper -- NO after an upward swing, YES after a
      downward swing -- because a >= $0.10 move in the demo book leaves that side at a
      lower price than before and the ROI screen must pass.
    Returns None when nothing should be traded (screen fails / price not tradable).
    """
    screen = alert.get("roi_screen") or {}
    if not screen.get("passes"):
        return None
    side = screen.get("side")
    price_now = alert.get("new_price")
    if side not in ("yes", "no") or price_now is None:
        return None
    entry = round(min(0.99, max(0.01, price_now + SIM_SLIPPAGE)), 2)
    contracts = MAX_CONTRACTS
    cost = round(entry * contracts, 2)
    return {
        "trade_id": "SIM-" + str(alert.get("alert_id", ""))[-12:],
        "strategy": "momentum_fade_v1",
        "strategy_label": "Momentum fade (buy the side the swing made cheaper)",
        "category": _category(alert),
        "mode": "SIMULATED",
        "market_ticker": alert.get("market_ticker"),
        "event_ticker": alert.get("event_ticker"),
        "title": alert.get("title"),
        "yes_sub_title": alert.get("yes_sub_title"),
        "topic": alert.get("topic"),
        "topic_label": alert.get("topic_label"),
        "side": side,
        "contracts": contracts,
        "quoted_price": price_now,
        "entry_price": entry,
        "slippage": SIM_SLIPPAGE,
        "fee": round(SIM_FEE_PER_CONTRACT * contracts, 2),
        "cost": round(cost + SIM_FEE_PER_CONTRACT * contracts, 2),
        "opened_at": alert.get("observed_at"),
        "status": "OPEN",
        "result": None,
        "pnl": None,
        "roi": None,
        "swing_alert": alert.get("alert_id"),
        "source_url": alert.get("source_url"),
        "settlement_url": None,
        "note": ("SIMULATED fill at the observed price +/- $0.01 slippage; settles only "
                 "when the market reports result yes/no"),
    }


def _category(alert: dict) -> str:
    d = alert.get("direction")
    swing = alert.get("delta_dollars")
    if d == "up":
        return "swing_up_buy_no"
    if d == "down":
        return "swing_down_buy_yes"
    return f"swing_{d}_{swing}"


def settle(trade: dict, resolution: dict) -> dict:
    """Settle a simulated trade from an official resolution row (never inferred)."""
    result = (resolution or {}).get("result")
    if result not in ("yes", "no"):
        return trade
    won = trade["side"] == result
    payout_contracts = trade["contracts"] if won else 0.0
    gross = round(payout_contracts * 1.0, 2)  # winning contracts pay $1 each (official)
    cost = trade["cost"]
    pnl = round(gross - cost, 2)
    out = dict(trade)
    out.update({
        "status": "SETTLED",
        "result": result,
        "won": won,
        "payout": gross,
        "pnl": pnl,
        "roi": (round(pnl / cost, 4) if cost else None),
        "settled_at": resolution.get("settlement_ts"),
        "settlement_url": resolution.get("source_url"),
        "resolved_yes_no": result.upper(),
    })
    return out


def run(prev_state: dict, alerts: Iterable[dict], resolutions: dict,
        observed_at: str) -> dict:
    """Advance the simulated portfolio by one pipeline run.

    `prev_state` is the persisted simulator state (trades list + meta). Trades are
    de-duplicated by trade_id so re-running against the same alerts is idempotent.
    """
    trades = list(prev_state.get("trades") or [])
    known = {t.get("trade_id") for t in trades}
    opened = 0
    for alert in alerts:
        trade = strategy_from_alert(alert)
        if not trade or trade["trade_id"] in known:
            continue
        known.add(trade["trade_id"])
        trades.append(trade)
        opened += 1
    settled_now = 0
    by_ticker = resolutions.get("by_market") or {}
    for i, t in enumerate(trades):
        if t.get("status") == "SETTLED":
            continue
        res = by_ticker.get(t.get("market_ticker"))
        if not res:
            continue
        before = t.get("status")
        trades[i] = settle(t, res)
        if before != "SETTLED":
            settled_now += 1
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    closed = [t for t in trades if t.get("status") == "SETTLED"]
    realised = round(sum(t.get("pnl") or 0.0 for t in closed), 2)
    staked_open = round(sum(t.get("cost") or 0.0 for t in open_trades), 2)
    wins = [t for t in closed if t.get("won")]
    return {
        "updated_at": observed_at,
        "mode": "SIMULATED",
        "starting_cash": STARTING_CASH,
        "cash_available": round(STARTING_CASH - staked_open + realised, 2),
        "realised_pnl": realised,
        "open_cost": staked_open,
        "counts": {
            "opened_this_run": opened,
            "settled_this_run": settled_now,
            "open": len(open_trades),
            "settled": len(closed),
            "wins": len(wins),
            "losses": len(closed) - len(wins),
        },
        "hit_rate": (round(len(wins) / len(closed), 4) if closed else None),
        "avg_roi": (round(sum(t.get("roi") or 0.0 for t in closed) / len(closed), 4)
                    if closed else None),
        "trades": sorted(trades, key=lambda t: t.get("opened_at") or "", reverse=True)[:600],
        "fee_note": ("Fee is a fixed $0.01/contract placeholder, not Kalshi's schedule "
                     "(https://docs.kalshi.com/getting_started/fees); flagged on the page."),
        "settlement_rule": "https://docs.kalshi.com/getting_started/market_settlement",
    }


def by_category(state: dict) -> list[dict]:
    """Performance grouped by trade category (the brief's 'categorize trades')."""
    groups: dict[str, dict] = {}
    for t in state.get("trades") or []:
        key = t.get("category") or "uncategorised"
        g = groups.setdefault(key, {
            "category": key, "trades": 0, "open": 0, "settled": 0,
            "wins": 0, "losses": 0, "staked": 0.0, "pnl": 0.0,
        })
        g["trades"] += 1
        if t.get("status") == "OPEN":
            g["open"] += 1
        else:
            g["settled"] += 1
            g["pnl"] = round(g["pnl"] + (t.get("pnl") or 0.0), 2)
            g["staked"] = round(g["staked"] + (t.get("cost") or 0.0), 2)
            if t.get("won"):
                g["wins"] += 1
            else:
                g["losses"] += 1
    rows = list(groups.values())
    for r in rows:
        r["hit_rate"] = (round(r["wins"] / r["settled"], 4) if r["settled"] else None)
        r["roi"] = (round(r["pnl"] / r["staked"], 4) if r["staked"] else None)
    rows.sort(key=lambda r: (-(r["settled"]), r["category"]))
    return rows
