#!/usr/bin/env python3
"""
Builds the compact, self-citing artifacts the dashboard consumes, plus an analysis report.

Inputs (written by collector/collect.py):
  data/live.json        demo snapshot (large, git-ignored, regenerable)
  data/live-prod.json   production snapshot (large, git-ignored, regenerable)
  data/resolutions.json accumulated settled markets
  data/meta.json        run metadata + request log

Outputs (committed):
  data/dashboard.json   compact: series, top markets per topic, ladders, downsampled candles
  data/resolutions-compact.json  settled markets (trimmed fields) for the Resolutions page
  data/history/*.jsonl  append-only observations for tracked chart markets
  analysis/report.json  computed aggregates (each with an explicit formula + input source)
  analysis/REPORT.md    human-readable version of the same aggregates

Rules:
  * No invented numbers. Every aggregate is computed from API fields and carries the formula
    and the input file it used.
  * Aggregates that need data we do not have (portfolio, fills, P&L) are emitted as
    `unavailable` with the reason, not as zero.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ANALYSIS = ROOT / "analysis"

TOP_MARKETS_PER_TOPIC = 12
CANDLE_KEEP = {1: 240, 60: 168, 1440: 90}
RESOLUTION_KEEP_DAYS = 45


def load(path: Path, default):
    """Load JSON, treating missing/empty/corrupt files as `default`."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return default
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compact_candles(sets: dict, ticker: str) -> dict:
    """Downsample the API candlesticks into [t, close, bid, ask, volume, oi] tuples.

    Kalshi returns OHLC distributions per period (price, yes_bid, yes_ask) plus volume_fp and
    open_interest_fp. For charting we keep the CLOSE of each distribution and the point's
    timestamp, and we keep the API's own numbers untouched (no smoothing, no interpolation).
    """
    out = {}
    for period, block in (sets or {}).items():
        keep = CANDLE_KEEP.get(int(period), 200) if str(period).isdigit() else 200
        candles = (block or {}).get("candlesticks") or []
        points = []
        for c in candles[-keep:]:
            price = c.get("price") or {}
            yb = c.get("yes_bid") or {}
            ya = c.get("yes_ask") or {}
            points.append({
                "t": c.get("end_period_ts"),
                "close": _f(price.get("close_dollars")),
                "open": _f(price.get("open_dollars")),
                "high": _f(price.get("high_dollars")),
                "low": _f(price.get("low_dollars")),
                "bid": _f(yb.get("close_dollars")),
                "ask": _f(ya.get("close_dollars")),
                "vol": _f(c.get("volume_fp")),
                "oi": _f(c.get("open_interest_fp")),
            })
        out[period] = {
            "source": (block or {}).get("source"),
            "http": (block or {}).get("http"),
            "total_points_returned": (block or {}).get("count"),
            "points": points,
            "fields": "t=end_period_ts, close/open/high/low=price OHLC, bid/ask=yes bid/ask close, "
                      "vol=volume_fp, oi=open_interest_fp (all copied from the API)",
        }
    return out


def _f(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pick_top(markets: list, topic: str, key: str, n: int = TOP_MARKETS_PER_TOPIC) -> list:
    rows = [m for m in markets if topic in (m.get("topics") or [])]
    rows.sort(key=lambda m: (m.get("metrics", {}).get(key) or -1), reverse=True)
    return rows[:n]


def main() -> int:
    demo = load(DATA / "live.json", {})
    prod = load(DATA / "live-prod.json", {})
    resolutions = load(DATA / "resolutions.json", {"rows": []})

    # Guard: an empty input set must never overwrite good committed artifacts.
    if not demo.get("markets") and not prod.get("markets"):
        print("SKIP: data/live.json and data/live-prod.json are missing or empty (they are "
              "git-ignored and only exist on a runner that just collected them). Refusing to "
              "overwrite the committed artifacts with empty output.")
        return 0
    meta_demo = demo.get("meta", {})
    meta_prod = prod.get("meta", {})

    topics_cfg = (meta_demo.get("topics") or meta_prod.get("topics") or {})

    # ---------------------------------------------------------------- markets
    demo_markets = demo.get("markets") or []
    prod_markets = prod.get("markets") or []

    def compact_row(m, env):
        return {
            "ticker": m["ticker"],
            "event_ticker": m.get("event_ticker"),
            "series_ticker": m.get("series_ticker"),
            "title": m.get("title"),
            "yes_sub_title": m.get("yes_sub_title"),
            "topics": m.get("topics"),
            "status": m.get("status"),
            "price_level_structure": m.get("price_level_structure"),
            "price_ranges": m.get("price_ranges"),
            "close_time": m.get("close_time"),
            "expected_expiration_time": m.get("expected_expiration_time"),
            "yes_bid_dollars": m.get("yes_bid_dollars"),
            "yes_ask_dollars": m.get("yes_ask_dollars"),
            "last_price_dollars": m.get("last_price_dollars"),
            "volume_fp": m.get("volume_fp"),
            "volume_24h_fp": m.get("volume_24h_fp"),
            "open_interest_fp": m.get("open_interest_fp"),
            "metrics": m.get("metrics"),
            "rules_primary": (m.get("rules_primary") or "")[:240],
            "source": m.get("source"),
            "orderbook_source": m.get("orderbook_source"),
            "candles_source": m.get("candles_source"),
            "env": env,
            "_missing": m.get("_missing"),
        }

    tables = {}
    for topic in topics_cfg:
        tables[topic] = {
            "by_contracts_traded": [compact_row(m, "demo") for m in
                                    pick_top(demo_markets, topic, "contracts_traded")],
            "by_open_interest_dollars_derived": [compact_row(m, "demo") for m in
                                                 pick_top(demo_markets, topic, "open_interest_dollars_derived")],
            "by_resting_liquidity_dollars": [compact_row(m, "demo") for m in
                                             pick_top(demo_markets, topic, "resting_liquidity_dollars")],
            "production_top_by_contracts": [compact_row(m, "prod") for m in
                                            pick_top(prod_markets, topic, "contracts_traded", 6)],
        }

    # ---------------------------------------------------------------- ladders/candles
    ladders = {}
    candles = {}
    for source in (demo, prod):
        for ticker, book in (source.get("orderbooks") or {}).items():
            if book.get("http") == 200:
                ladders[ticker] = {
                    "env": source.get("meta", {}).get("environment"),
                    "best_yes_bid": book.get("best_yes_bid"),
                    "best_yes_ask_derived": book.get("best_yes_ask_derived"),
                    "best_no_bid": book.get("best_no_bid"),
                    "best_no_ask_derived": book.get("best_no_ask_derived"),
                    "spread_yes_derived": book.get("spread_yes_derived"),
                    "yes_resting_dollars": book.get("yes_resting_dollars"),
                    "no_resting_dollars": book.get("no_resting_dollars"),
                    "total_resting_dollars": book.get("total_resting_dollars"),
                    "yes_levels": book.get("yes_levels"),
                    "no_levels": book.get("no_levels"),
                    "ladder": (book.get("ladder") or [])[:60],
                    "source": book.get("source"),
                    "note": "Kalshi returns bids only. best_yes_ask is derived as 1 - best_no_bid "
                            "(docs: /getting_started/orderbook_responses).",
                }
        for ticker, sets in (source.get("candles") or {}).items():
            candles[ticker] = {"env": source.get("meta", {}).get("environment"),
                               **compact_candles(sets, ticker)}

    # ------------------------------------------------------------------ series
    series_rows = []
    for s in (demo.get("series") or []):
        series_rows.append({
            "series_ticker": s.get("series_ticker"),
            "title": s.get("title"),
            "category": s.get("category"),
            "tags": s.get("tags"),
            "frequency": s.get("frequency"),
            "volume_fp": s.get("volume_fp"),
            "topics": s.get("topics"),
            "settlement_sources": s.get("settlement_sources"),
            "contract_terms_url": s.get("contract_terms_url"),
            "source": s.get("source"),
            "env": "demo",
        })

    # ------------------------------------------------------------- resolutions
    rows = []
    cutoff = None
    if resolutions.get("rows"):
        try:
            stamps = sorted(r.get("settlement_ts") or "" for r in resolutions["rows"] if r.get("settlement_ts"))
            if stamps:
                cutoff = stamps[-1]
        except (TypeError, ValueError):
            cutoff = None
    for r in resolutions.get("rows", []):
        rows.append({
            "ticker": r.get("ticker"),
            "series_ticker": r.get("series_ticker"),
            "topics": r.get("topics"),
            "title": (r.get("title") or "")[:200],
            "result": r.get("result"),
            "settlement_value_dollars": r.get("settlement_value_dollars"),
            "settlement_ts": r.get("settlement_ts"),
            "close_time": r.get("close_time"),
            "expiration_value": (r.get("expiration_value") or "")[:80],
            "last_price_dollars": r.get("last_price_dollars"),
            "volume_fp": r.get("volume_fp"),
            "open_interest_fp": r.get("open_interest_fp"),
            "env": r.get("environment"),
            "source": r.get("source"),
        })
    rows.sort(key=lambda r: (r.get("settlement_ts") or ""), reverse=True)

    # ------------------------------------------------------------------ analysis
    report = build_report(demo, prod, rows, ladders, tables, topics_cfg)

    # ---------------------------------------------------------------- write out
    dashboard = {
        "meta": {
            "built_at_utc": now_iso(),
            "demo_run": {k: meta_demo.get(k) for k in
                         ("run_id", "environment", "started_at_utc", "finished_at_utc",
                          "counts", "request_count", "duration_seconds", "parameters")},
            "prod_run": {k: meta_prod.get(k) for k in
                         ("run_id", "environment", "started_at_utc", "finished_at_utc",
                          "counts", "request_count", "duration_seconds", "parameters")},
            "notes": [
                "All prices are Kalshi contract prices in dollars: 1.00 = certain YES, 0.00 = certain NO.",
                "Demo market data comes from https://external-api.demo.kalshi.co/trade-api/v2 (the endpoint in the brief).",
                "Production market data comes from https://external-api.kalshi.com/trade-api/v2 and is labelled where shown.",
                "Kalshi's demo environment prices may not reflect real markets (docs: /getting_started/demo_env).",
                "Every row keeps the request URL it came from; blank values were absent from the API response.",
            ],
            "auth_status": demo.get("auth_probes") or [],
            "cors_probe": demo.get("cors_probe") or [],
        },
        "topics": {t: {"label": v["label"], "rule": v.get("rule"),
                       "series_matched_total": v.get("series_matched_total"),
                       "series_selected": v.get("selected", [])}
                   for t, v in (demo.get("topics") or {}).items()},
        "series": series_rows,
        "tables": tables,
        "ladders": ladders,
        "candles": candles,
        "analysis": report,
    }
    (DATA / "dashboard.json").write_text(json.dumps(dashboard, separators=(",", ":")),
                                         encoding="utf-8")
    (DATA / "resolutions-compact.json").write_text(json.dumps({
        "meta": {
            "built_at_utc": now_iso(),
            "rows": len(rows),
            "note": resources_note(),
        },
        "rows": rows,
    }, separators=(",", ":")), encoding="utf-8")
    ANALYSIS.mkdir(exist_ok=True)
    (ANALYSIS / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (ANALYSIS / "REPORT.md").write_text(render_md(report), encoding="utf-8")
    (DATA / "meta.json").write_text(json.dumps(trim_meta(meta_demo, meta_prod), indent=1),
                                    encoding="utf-8")
    print(json.dumps({"dashboard_bytes": (DATA / "dashboard.json").stat().st_size,
                      "resolutions_rows": len(rows),
                      "resolutions_bytes": (DATA / "resolutions-compact.json").stat().st_size},
                     indent=1))
    return 0


def resources_note() -> str:
    return ("Settled markets collected with GET /markets?series_ticker=...&status=settled"
            "&mve_filter=exclude. `result` is Kalshi's own field (yes | no | scalar | '')."
            " Rows accumulate in data/resolutions.json across runs; this file is the trimmed"
            " projection used by the site. Docs:"
            " https://docs.kalshi.com/getting_started/market_settlement.md")


def trim_meta(meta_demo: dict, meta_prod: dict) -> dict:
    """Keep the request log compact: dedupe URLs, keep statuses, keep errors in full."""
    def slim(meta):
        reqs = meta.get("requests") or []
        seen = {}
        for r in reqs:
            key = r.get("url", "")
            path_key = key.split("?")[0]
            entry = seen.setdefault(path_key, {"url_sample": key, "status": r.get("status"),
                                               "calls": 0, "errors": []})
            entry["calls"] += 1
            if r.get("error"):
                entry["errors"].append(r["error"][:160])
        return {
            "run_id": meta.get("run_id"),
            "environment": meta.get("environment"),
            "base_url": meta.get("base_url"),
            "started_at_utc": meta.get("started_at_utc"),
            "finished_at_utc": meta.get("finished_at_utc"),
            "duration_seconds": meta.get("duration_seconds"),
            "counts": meta.get("counts"),
            "topics": meta.get("topics"),
            "parameters": meta.get("parameters"),
            "docs": meta.get("docs"),
            "request_total": meta.get("request_count"),
            "endpoints_called": list(seen.values()),
        }
    return {"demo": slim(meta_demo), "prod": slim(meta_prod), "built_at_utc": now_iso()}


def build_report(demo, prod, rows, ladders, tables, topics_cfg) -> dict:
    """Aggregates only. Each entry states its formula and its input."""
    out: dict = {"generated_at_utc": now_iso(),
                 "inputs": {"demo_run_id": demo.get("meta", {}).get("run_id"),
                            "prod_run_id": prod.get("meta", {}).get("run_id")},
                 "definitions": {}}

    out["definitions"] = {
        "contracts_traded": "Kalshi `volume_fp` — contracts exchanged on the market. Source: GET /markets.",
        "contracts_traded_24h": "Kalshi `volume_24h_fp`. Source: GET /markets.",
        "open_interest_contracts": "Kalshi `open_interest_fp` — contracts currently held. Source: GET /markets.",
        "traded_notional_dollars_derived": "volume_fp x price_used, where price_used is last_price_dollars "
                                           "if present else the mid of yes bid/ask. Derived, not returned by Kalshi.",
        "open_interest_dollars_derived": "open_interest_fp x price_used (same price basis). Derived.",
        "resting_liquidity_dollars": "sum over orderbook levels of price x contracts, for both YES and NO bids. "
                                     "Computed from GET /markets/{ticker}/orderbook.",
        "implied_asks": "Kalshi returns bids only; a YES bid at X is a NO ask at 1-X, so asks are derived. "
                        "Source: https://docs.kalshi.com/getting_started/orderbook_responses.md",
    }

    # market-level aggregates per topic
    per_topic = {}
    demo_markets = demo.get("markets") or []
    for topic in topics_cfg:
        sub = [m for m in demo_markets if topic in (m.get("topics") or [])]
        metrics = [m.get("metrics") or {} for m in sub]
        vals = {
            "open_markets": len(sub),
            "sum_contracts_traded": _sum(x.get("contracts_traded") for x in metrics),
            "sum_open_interest_contracts": _sum(x.get("open_interest_contracts") for x in metrics),
            "sum_traded_notional_dollars_derived": _sum(x.get("traded_notional_dollars_derived") for x in metrics),
            "sum_open_interest_dollars_derived": _sum(x.get("open_interest_dollars_derived") for x in metrics),
            "sum_resting_liquidity_dollars": _sum(x.get("resting_liquidity_dollars") for x in metrics),
            "median_last_price": _median(x.get("price_used") for x in metrics),
            "markets_with_missing_price": sum(1 for m in sub if m.get("_missing")),
        }
        per_topic[topic] = vals
    out["per_topic_demo"] = per_topic

    # resolution aggregates
    res_by_topic = defaultdict(lambda: Counter())
    for r in rows:
        for t in (r.get("topics") or []):
            res_by_topic[t][r.get("result") or "blank"] += 1
    out["resolutions"] = {
        "formula": "Count of settled markets per topic by Kalshi `result` (yes/no/scalar/blank). "
                   "Input: data/resolutions.json (GET /markets?status=settled).",
        "total_rows": len(rows),
        "by_topic": {t: dict(c) for t, c in res_by_topic.items()},
        "by_environment": dict(Counter(r.get("env") or "?" for r in rows)),
    }

    # settlement lag: settlement_ts - close_time, only where both parse
    lags = []
    for r in rows:
        try:
            c = datetime.fromisoformat((r.get("close_time") or "").replace("Z", "+00:00"))
            s = datetime.fromisoformat((r.get("settlement_ts") or "").replace("Z", "+00:00"))
            lags.append((s - c).total_seconds() / 3600)
        except ValueError:
            continue
    out["settlement_lag_hours"] = {
        "formula": "(settlement_ts - close_time) in hours, for rows where both timestamps exist.",
        "n": len(lags),
        "median": round(statistics.median(lags), 2) if lags else None,
        "mean": round(statistics.fmean(lags), 2) if lags else None,
        "p90": round(sorted(lags)[int(len(lags) * 0.9)], 2) if lags else None,
        "negative_count": sum(1 for x in lags if x < 0),
        "note": "Negative values mean the market settled before its scheduled close, which the API "
                "permits via early close (can_close_early).",
    }

    # liquidity snapshot stats
    liq = [l.get("total_resting_dollars") for l in ladders.values() if l.get("total_resting_dollars") is not None]
    spreads = [l.get("spread_yes_derived") for l in ladders.values() if l.get("spread_yes_derived") is not None]
    out["liquidity_snapshot"] = {
        "formula": "Per tracked market: total resting dollars and derived YES spread from the orderbook.",
        "markets_sampled": len(liq),
        "median_resting_dollars": round(statistics.median(liq), 2) if liq else None,
        "max_resting_dollars": max(liq) if liq else None,
        "min_resting_dollars": min(liq) if liq else None,
        "median_yes_spread": round(statistics.median(spreads), 4) if spreads else None,
    }

    # measured expectancy study (computed by analysis/expectancy.py)
    exp_path = DATA / "expectancy.json"
    exp = load(exp_path, None)
    if isinstance(exp, dict) and exp.get("buckets"):
        out["resolution_study"] = {k: exp.get(k) for k in
                                   ("formula", "input", "rows_usable", "rows_excluded", "buckets",
                                    "favourite_band_0_80_to_0_99", "longshot_band_0_01_to_0_20",
                                    "all_rows", "caveats")}

    # strategy candidates generated from the current book (analysis/strategies.py)
    rules = load(DATA / "order-rules.json", None)
    if isinstance(rules, dict):
        out["strategy_candidates"] = {
            "policy": rules.get("policy"),
            "count": len(rules.get("candidates") or []),
            "simulation": (rules.get("simulation") or {}).get("summary"),
            "skipped": len(rules.get("skipped") or []),
            "measured_skips": sum(1 for s in (rules.get("skipped") or []) if s.get("measured")),
            "disclaimer": (rules.get("simulation") or {}).get("disclaimer"),
        }

    # data quality
    out["data_quality"] = {
        "markets_with_missing_fields": sum(1 for m in demo_markets if m.get("_missing")),
        "markets_sampled": len(demo_markets),
        "auth_probe_statuses": [{"url": p.get("url"), "status": p.get("status")}
                                for p in (demo.get("auth_probes") or [])],
        "note": "Blank cells in the site mean the API did not return that field, or the data "
                "requires an API key this repo does not have.",
    }

    out["not_available"] = {
        "portfolio": {
            "reason": "GET /portfolio/* requires the signed headers KALSHI-ACCESS-KEY, "
                      "KALSHI-ACCESS-TIMESTAMP and KALSHI-ACCESS-SIGNATURE (Ed25519 or RSA-PSS). "
                      "No demo API key is configured for this repository, so no balance, position, "
                      "fill or P&L figure is published. Observed 401 responses are recorded in the "
                      "Auth status panel.",
            "to_enable": "Add repository secrets KALSHI_DEMO_KEY_ID and KALSHI_DEMO_PRIVATE_KEY "
                         "(Settings > Secrets and variables > Actions). The workflow "
                         "portfolio.yml then writes data/portfolio.json and the Portfolio page "
                         "lights up with real numbers.",
            "source": "https://docs.kalshi.com/getting_started/api_keys.md",
        },
        "trade_execution": {
            "reason": "POST /portfolio/orders is a signed, authenticated write. Without a key the "
                      "dashboard cannot place demo orders, and it must not fabricate fills.",
            "to_enable": "Same secrets as above, plus ALLOW_LIVE_DEMO_TRADING=true on the workflow "
                         "so a human consciously enables write access.",
            "source": "https://docs.kalshi.com/api-reference/orders/create-order.md",
        },
        "websocket": {
            "reason": "The WebSocket API requires the same signed handshake even for public market-data "
                      "channels, so it cannot be opened from an unauthenticated static page. The site "
                      "therefore polls committed REST snapshots (hourly, plus manual dispatch).",
            "source": "https://docs.kalshi.com/getting_started/quick_start_websockets.md",
            "to_enable": "Add the same demo key secrets; collector/ws_stream.py can then keep a "
                         "signed socket open and append tick-by-tick observations to "
                         "data/history/. Until then the chart uses REST candlesticks and the "
                         "hourly snapshot log, both of which are real API data.",
        },
    }

    return out


def _sum(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(sum(vals), 2) if vals else None


def _median(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(vals), 4) if vals else None


def render_md(report: dict) -> str:
    lines = ["# Analysis report", "",
             f"Generated {report['generated_at_utc']} from demo run "
             f"`{report['inputs']['demo_run_id']}` and production run `{report['inputs']['prod_run_id']}`.",
             "", "Every figure below is an aggregation of API fields listed in *Definitions*;",
             "nothing is estimated. Where data is unavailable it says so instead of showing zero.", "",
             "## Definitions", ""]
    for k, v in report["definitions"].items():
        lines.append(f"- **{k}** — {v}")
    lines += ["", "## Per-topic aggregates (demo environment)", "",
              "| Topic | Open markets | Contracts traded | Open interest (contracts) | Traded notional $ (derived) | Open-interest $ (derived) | Resting liquidity $ | Median price |",
              "|---|---|---|---|---|---|---|---|"]
    for t, v in report["per_topic_demo"].items():
        lines.append("| {t} | {om} | {ct} | {oi} | {tn} | {oiv} | {liq} | {mp} |".format(
            t=t, om=v["open_markets"], ct=_fmt(v["sum_contracts_traded"]),
            oi=_fmt(v["sum_open_interest_contracts"]),
            tn=_fmt(v["sum_traded_notional_dollars_derived"]),
            oiv=_fmt(v["sum_open_interest_dollars_derived"]),
            liq=_fmt(v["sum_resting_liquidity_dollars"]),
            mp=v["median_last_price"] if v["median_last_price"] is not None else "—"))
    lines += ["", "## Resolution outcomes", "", f"_{report['resolutions']['formula']}_", "",
              "| Topic | yes | no | scalar | blank |", "|---|---|---|---|---|"]
    for t, c in report["resolutions"]["by_topic"].items():
        lines.append(f"| {t} | {c.get('yes', 0)} | {c.get('no', 0)} | {c.get('scalar', 0)} | {c.get('blank', 0)} |")
    lag = report["settlement_lag_hours"]
    rs = report.get("resolution_study") or {}
    if rs.get("buckets"):
        lines += ["", "## Resolution study: realised outcome vs. price", "",
                  f"_{rs['formula']}_", "",
                  f"Input: {rs['input']} — usable rows {rs['rows_usable']:,}, excluded "
                  f"{rs['rows_excluded']}.", "",
                  "| YES price band | n | resolved yes | win rate | avg YES price | YES expectancy / contract | NO expectancy / contract |",
                  "|---|---|---|---|---|---|---|"]
        for b in rs["buckets"]:
            if not b.get("n"):
                lines.append(f"| {b['bucket']} | 0 | — | — | — | — | — |")
                continue
            lines.append(f"| {b['bucket']} | {b['n']:,} | {b['yes']:,} | {b['win_rate_yes']:.2%} | "
                         f"{b['avg_yes_price']:.4f} | {b['yes_expectancy_per_contract']:+.4f} | "
                         f"{b['no_expectancy_per_contract']:+.4f} |")
        for key, label in (("favourite_band_0_80_to_0_99", "0.80-0.99 favourite band"),
                           ("longshot_band_0_01_to_0_20", "0.01-0.20 longshot band"),
                           ("all_rows", "all settled rows")):
            band = rs.get(key)
            if band:
                lines += ["", f"**{label}**: n={band['n']:,}, win rate {band['win_rate_yes']:.2%}, "
                              f"avg price {band['avg_yes_price']:.4f}, YES expectancy "
                              f"{band['yes_expectancy_per_contract']:+.4f}/contract, NO expectancy "
                              f"{band['no_expectancy_per_contract']:+.4f}/contract."]
        lines += ["", "Caveats:"] + [f"- {c}" for c in rs.get("caveats", [])]

    sc = report.get("strategy_candidates") or {}
    if sc.get("policy"):
        lines += ["", "## Strategy candidates from the current order book", "",
                  f"Policy: `{json.dumps(sc['policy'])}`", "",
                  f"- candidates that survived the rules: **{sc.get('count')}**",
                  f"- markets skipped, including {sc.get('measured_skips')} rejected because they "
                  f"sit in the measured negative-expectancy favourite band",
                  f"- simulation: `{json.dumps(sc.get('simulation'))}`", "",
                  sc.get("disclaimer") or ""]

    lines += ["", "## Settlement timing", "", f"_{lag['formula']}_", "",
              f"- observations: {lag['n']}", f"- median: {lag['median']} h",
              f"- mean: {lag['mean']} h", f"- p90: {lag['p90']} h",
              f"- settled before scheduled close: {lag['negative_count']}",
              "", "## Liquidity snapshot", "", f"_{report['liquidity_snapshot']['formula']}_", "",
              f"- markets sampled: {report['liquidity_snapshot']['markets_sampled']}",
              f"- median resting dollars: {report['liquidity_snapshot']['median_resting_dollars']}",
              f"- median derived YES spread: {report['liquidity_snapshot']['median_yes_spread']}",
              "", "## Data quality", "",
              f"- markets sampled: {report['data_quality']['markets_sampled']}",
              f"- markets with at least one missing field: {report['data_quality']['markets_with_missing_fields']}",
              "", "## Not available (and why)", ""]
    for k, v in report["not_available"].items():
        lines += [f"### {k}", "", v["reason"], "", f"To enable: {v.get('to_enable', 'n/a')}", "",
                  f"Source: {v['source']}", ""]
    return "\n".join(lines) + "\n"


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


if __name__ == "__main__":
    raise SystemExit(main())
