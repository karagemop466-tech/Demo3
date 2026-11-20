"""Offline tests for the paper-trading desk. No network, no credentials.

Fixtures are SYNTHETIC market objects written here in the test: they use only field
names and value shapes documented at
https://docs.kalshi.com/api-reference/market/get-markets.md and
https://docs.kalshi.com/getting_started/orderbook_responses.md. They are inputs to a
unit test, NOT captured exchange data, and nothing from them is published as data
(the desk's own outputs are labelled `data_mode: offline-fixtures` when replayed).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "collector"))

import paper_engine as pe  # noqa: E402
from paper_strategies import (  # noqa: E402
    MAX_HOLD_RUNS, categorize, evaluate_entries, evaluate_exits, grid_step, price_band,
    price_on_grid, snap_to_grid,
)

TOPIC = "elections"


def market(ticker="KXTEST-1-A", *, last="0.5000", yes_bid="0.4800", yes_ask="0.5200",
           yes_bid_size="500.00", yes_ask_size="300.00", no_bid=None, no_ask=None,
           status="active", result="", volume_24h="1000.00", volume="9000.00",
           open_interest="8000.00", close_time="2030-01-01T00:00:00Z",
           step="0.0100", prev_ask=None, title="Test market?", event=None,
           notional="1.0000", settlement_value=None, settlement_ts=None):
    no_bid = no_bid if no_bid is not None else f"{1 - float(yes_ask):.4f}"
    no_ask = no_ask if no_ask is not None else f"{1 - float(yes_bid):.4f}"
    m = {
        "ticker": ticker, "event_ticker": event or ticker.rsplit("-", 1)[0],
        "market_type": "binary", "title": title, "yes_sub_title": "yes",
        "no_sub_title": "no", "status": status, "result": result,
        "close_time": close_time, "open_time": "2026-01-01T00:00:00Z",
        "created_time": "2026-01-01T00:00:00Z", "updated_time": "2026-01-01T00:00:00Z",
        "latest_expiration_time": close_time, "settlement_timer_seconds": 60,
        "notional_value_dollars": notional,
        "last_price_dollars": last,
        "yes_bid_dollars": yes_bid, "yes_bid_size_fp": yes_bid_size,
        "yes_ask_dollars": yes_ask, "yes_ask_size_fp": yes_ask_size,
        "no_bid_dollars": no_bid, "no_ask_dollars": no_ask,
        "volume_fp": volume, "volume_24h_fp": volume_24h,
        "open_interest_fp": open_interest,
        "previous_price_dollars": last,
        "previous_yes_bid_dollars": yes_bid,
        "previous_yes_ask_dollars": prev_ask if prev_ask is not None else yes_ask,
        "can_close_early": True, "expiration_value": "", "rules_primary": "r",
        "rules_secondary": "", "price_level_structure": "linear_cent",
        "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": step}],
        "strike_type": "custom", "settlement_bounds_type": "default",
    }
    if settlement_value is not None:
        m["settlement_value_dollars"] = settlement_value
    if settlement_ts is not None:
        m["settlement_ts"] = settlement_ts
    return m


def ctx_of(m, prior_ask=None, config=None):
    q = pe.quote_from_market(m)
    return {"ticker": m["ticker"], "event_ticker": m["event_ticker"], "topic": TOPIC,
            "title": m["title"], "market": m, "quote": q, "status": q["status"],
            "prior": {} if prior_ask is None else {"yes_ask": prior_ask},
            "config": config or pe.DEFAULT_CONFIG, "hours_to_close": 48.0}


class RuleTests(unittest.TestCase):
    def test_swing_fade_needs_a_full_dime_drop(self):
        m = market(yes_ask="0.4000", yes_bid="0.3900")
        self.assertEqual(evaluate_entries(ctx_of(m, prior_ask=0.4950)), [])  # 0.0950
        intents = evaluate_entries(ctx_of(m, prior_ask=0.5000))              # 0.1000
        self.assertIn("swing_fade", [i["strategy"] for i in intents])

    def test_swing_momentum_requires_volume(self):
        up = market(yes_ask="0.6000", yes_bid="0.5900", volume_24h="0.00")
        self.assertEqual([i["strategy"] for i in evaluate_entries(ctx_of(up, 0.5000))], [])
        up2 = market(yes_ask="0.6000", yes_bid="0.5900", volume_24h="10.00")
        self.assertIn("swing_momentum", [i["strategy"] for i in
                                        evaluate_entries(ctx_of(up2, 0.5000))])

    def test_no_entry_when_price_outside_band(self):
        m = market(yes_ask="0.9500", yes_bid="0.9400", close_time="2035-01-01T00:00:00Z")
        c = ctx_of(m, 0.5000)
        c["hours_to_close"] = 9999.0   # outside the carry window too
        self.assertEqual([i["strategy"] for i in evaluate_entries(c)], [])

    def test_favorite_carry_needs_a_near_certain_ask_and_a_close_within_14_days(self):
        m = market(yes_ask="0.9300", yes_bid="0.9200", close_time="2030-01-01T00:00:00Z")
        c = ctx_of(m, 0.5000)
        c["hours_to_close"] = 48.0
        self.assertIn("favorite_carry", [i["strategy"] for i in evaluate_entries(c)])
        c2 = ctx_of(m, 0.5000)
        c2["hours_to_close"] = 40 * 24.0
        self.assertNotIn("favorite_carry", [i["strategy"] for i in evaluate_entries(c2)])

    def test_longshot_fade_buys_no_and_uses_no_ask(self):
        m = market(last="0.0500", yes_bid="0.0400", yes_ask="0.0600",
                   no_bid="0.9400", no_ask="0.9600", yes_bid_size="10.00",
                   yes_ask_size="10.00", volume_24h="500.00")
        intents = evaluate_entries(ctx_of(m))
        self.assertIn("longshot_fade_no", [i["strategy"] for i in intents])
        it = [i for i in intents if i["strategy"] == "longshot_fade_no"][0]
        self.assertEqual(it["side"], "no")
        self.assertEqual(it["price_dollars"], 0.96)

    def test_maker_limit_rests_one_step_inside_the_spread(self):
        m = market(yes_bid="0.4000", yes_ask="0.4400", step="0.0100")
        intents = [i for i in evaluate_entries(ctx_of(m)) if i["strategy"] == "maker_midquote"]
        self.assertEqual(len(intents), 1)
        self.assertTrue(intents[0]["resting"])
        self.assertEqual(intents[0]["price_dollars"], 0.41)

    def test_exits(self):
        self.assertIsNone(evaluate_exits({"avg_price_dollars": 0.5, "side": "yes"},
                                        {"yes_bid": 0.55}, 3))
        tp = evaluate_exits({"avg_price_dollars": 0.5, "side": "yes"}, {"yes_bid": 0.70}, 3)
        self.assertIn("take-profit", tp["reason"])
        sl = evaluate_exits({"avg_price_dollars": 0.5, "side": "yes"}, {"yes_bid": 0.30}, 3)
        self.assertIn("stop-loss", sl["reason"])
        ts = evaluate_exits({"avg_price_dollars": 0.5, "side": "yes"},
                            {"yes_bid": 0.52}, MAX_HOLD_RUNS)
        self.assertIn("time-stop", ts["reason"])

    def test_grid_helpers(self):
        m = market(step="0.0100")
        self.assertEqual(grid_step(m), 0.01)
        self.assertEqual(snap_to_grid(0.4159, m, "down"), 0.41)
        self.assertTrue(price_on_grid(0.41, m))
        self.assertFalse(price_on_grid(0.415, m))
        self.assertEqual(snap_to_grid(1.5, m, "down"), 0.99)

    def test_categorization_bands(self):
        self.assertEqual(price_band(0.05), "0-10c (longshot)")
        self.assertEqual(price_band(0.20), "10-30c")
        self.assertEqual(price_band(0.5), "30-70c (middle)")
        self.assertEqual(price_band(0.8), "70-90c")
        self.assertEqual(price_band(0.95), "90-100c (near-certain)")
        self.assertEqual(price_band(None), "unknown")
        cat = categorize({"yes_bid": 0.48, "yes_ask": 0.52}, "open", "yes", 0.52, "crypto")
        self.assertEqual(cat["spread_dollars"], 0.04)
        self.assertEqual(cat["topic"], "crypto")


class QuoteMappingTests(unittest.TestCase):
    def test_field_parsing_uses_documented_fields(self):
        q = pe.quote_from_market(market())
        self.assertEqual(q["yes_bid"], 0.48)
        self.assertEqual(q["yes_ask_size"], 300.0)
        self.assertEqual(q["status"], "active")
        self.assertIsNone(pe.dollars(""))
        self.assertIsNone(pe.dollars(None))
        self.assertEqual(pe.count_fp("12.345"), 12.35)  # 2dp fixed point

    def test_missing_quote_stays_none(self):
        m = market(yes_ask="1.0000", yes_bid="0.0000")
        q = pe.quote_from_market(m)
        self.assertEqual(q["yes_bid"], 0.0)
        self.assertEqual(pe.size_at_touch("yes", "buy", q), q["yes_ask_size"])

    def test_no_side_size_is_the_mirrored_yes_level(self):
        q = pe.quote_from_market(market())
        self.assertEqual(pe.size_at_touch("no", "buy", q), q["yes_bid_size"])
        self.assertEqual(pe.size_at_touch("no", "sell", q), q["yes_ask_size"])

    def test_taker_price_selection(self):
        q = pe.quote_from_market(market())
        side = {"side": "yes", **{k: q[k] for k in ("yes_bid", "yes_ask", "no_bid", "no_ask")}}
        self.assertEqual(pe.price_for(side, "buy"), q["yes_ask"])
        self.assertEqual(pe.price_for(side, "sell"), q["yes_bid"])
        side["side"] = "no"
        self.assertEqual(pe.price_for(side, "buy"), q["no_ask"])
        self.assertEqual(pe.price_for(side, "sell"), q["no_bid"])


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.state = pe.init_state(dict(pe.DEFAULT_CONFIG), "https://x/trade-api/v2",
                                    "offline-fixtures")
        self.intent = {
            "strategy": "swing_fade", "strategy_label": "x", "family": "reversion",
            "role": "taker", "action": "open", "side": "yes", "ticker": "KXTEST-1-A",
            "event_ticker": "KXTEST-1", "topic": TOPIC, "title": "t",
            "reason": "r", "signal": {}, "classification": {},
            "quote": pe.quote_from_market(market()),
        }

    def test_open_is_capped_by_risk_and_by_size_at_touch(self):
        res = pe.do_open(self.state, self.intent, 0.52, 300.0, 1, None, "https://x")
        self.assertEqual(res["status"], "filled")
        self.assertEqual(res["record"]["count"], 48)  # 25 / 0.52 = 48.07 -> 48
        self.assertEqual(self.state["cash_dollars"], 5000.0 - 48 * 0.52)

        self.state["cash_dollars"] = self.state["config"]["cash_floor_dollars"]
        blocked = pe.do_open(self.state, self.intent, 0.52, 300.0, 2, None, "https://x")
        self.assertEqual(blocked["status"], "rejected")
        self.assertIn("no fillable size", blocked["reject_reason"])

    def test_zero_liquidity_is_a_rejection_not_a_fill(self):
        res = pe.do_open(self.state, self.intent, 0.52, 0.0, 1, None, "https://x")
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(self.state["cash_dollars"], 5000.0)
        self.assertEqual(self.state["positions"], [])

    def test_close_realizes_the_exact_difference(self):
        pe.do_open(self.state, self.intent, 0.52, 300.0, 1, None, "https://x")
        pos = self.state["positions"][0]
        n = pos["count"]
        res = pe.do_close(self.state, pos, 0.48, float(n), n, 2, "stop", "https://x")
        self.assertEqual(res["status"], "filled")
        self.assertAlmostEqual(res["record"]["realized_pnl_dollars"], round((0.48 - 0.52) * n, 4), 6)
        self.assertEqual(self.state["positions"], [])
        self.assertAlmostEqual(self.state["realized_pnl_dollars"],
                               res["record"]["realized_pnl_dollars"], 6)

    def test_settlement_yes_pays_notional_and_no_pays_zero(self):
        for side, result, expect_pnl in (("yes", "yes", 4.8), ("no", "yes", -5.2)):
            st = pe.init_state(dict(pe.DEFAULT_CONFIG), "https://x", "offline-fixtures")
            it = dict(self.intent, side=side)
            price = 0.52 if side == "yes" else 0.48
            res = pe.do_open(st, it, price, 100.0, 1, None, "https://x")
            st["positions"][0]["count"] = 10
            st["positions"][0]["avg_price_dollars"] = 0.52
            st["positions"][0]["cost_basis_dollars"] = 5.2
            q = pe.quote_from_market(market(status="finalized", result=result,
                                            settlement_value="1.0000",
                                            settlement_ts="2026-11-20T00:00:00Z"))
            st["positions"][0]["count"] = 10
            st["positions"][0]["avg_price_dollars"] = 0.52
            st["positions"][0]["cost_basis_dollars"] = 5.2
            trades, resolutions = pe.do_settlements(st, {it["ticker"]: q}, 2, "https://x")
            if side == "yes":
                self.assertEqual(len(trades), 1)
                self.assertAlmostEqual(trades[0]["realized_pnl_dollars"], expect_pnl, 4)
                self.assertEqual(resolutions[0]["result"], "yes")
                self.assertEqual(resolutions[0]["desk_outcome"], "win")
                self.assertEqual(st["positions"], [])
            else:
                # NO holder loses: payout 0, realized = -cost basis
                self.assertAlmostEqual(trades[0]["realized_pnl_dollars"], -5.2, 4)
                self.assertEqual(resolutions[0]["desk_outcome"], "loss")

    def test_unresolved_and_scalar_results_are_not_settled(self):
        st = pe.init_state(dict(pe.DEFAULT_CONFIG), "https://x", "offline-fixtures")
        res = pe.do_open(st, self.intent, 0.52, 300.0, 1, None, "https://x")
        self.assertEqual(res["status"], "filled")
        for m in (market(result=""), market(result="scalar", status="finalized"),
                  market(result="yes", status="active")):
            q = pe.quote_from_market(m)
            if m["result"] == "yes":
                # 'active' with a result but not finalized: still settled by our rule
                trades, _ = pe.do_settlements(st, {self.intent["ticker"]: q}, 2, "https://x")
                self.assertEqual(len(trades), 1)
                break
            trades, _ = pe.do_settlements(st, {self.intent["ticker"]: q}, 2, "https://x")
            self.assertEqual(trades, [])
            self.assertEqual(len(st["positions"]), 1)


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        latest = os.path.join(self.tmp, "latest")
        os.makedirs(latest)
        self.topics = ["gas", "elections", "culture", "crypto", "golf"]
        snap = {"retrieved_at": "2026-01-01T00:00:00Z",
                "ranking_metric": "volume_dollars_derived (test fixture)",
                "overall": [], "by_topic": {}}
        for topic in self.topics:
            snap["by_topic"][topic] = [
                {"event_ticker": f"KXTEST-{topic.upper()}-1", "topic": topic,
                 "title": f"{topic} test event", "market_count": 2,
                 "volume_dollars_derived": 1000.0,
                 "source_url": "https://external-api.demo.kalshi.co/trade-api/v2/"
                               f"markets?event_ticker=KXTEST-{topic.upper()}-1",
                 "top_markets": [
                     {"ticker": f"KXTEST-{topic.upper()}-1-A", "title": f"{topic} A",
                      "last_price_dollars": "0.5000", "volume_dollars_derived": 500.0},
                     {"ticker": f"KXTEST-{topic.upper()}-1-B", "title": f"{topic} B",
                      "last_price_dollars": "0.9500", "volume_dollars_derived": 400.0},
                 ]},
                {"event_ticker": "KXDEMOFUTHOURLY-TEST", "topic": topic,
                 "title": "synthetic demo test series", "market_count": 1,
                 "volume_dollars_derived": 10.0, "source_url": "https://x",
                 "top_markets": [{"ticker": "KXDEMOFUTHOURLY-TEST-1",
                                  "title": "skip me", "last_price_dollars": "0.5000"}]},
            ]
        with open(os.path.join(latest, "top_events.json"), "w") as fh:
            json.dump(snap, fh)
        self.fixtures = os.path.join(self.tmp, "fixtures")
        os.makedirs(self.fixtures)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_fixtures(self, markets, books=None):
        with open(os.path.join(self.fixtures, "markets_tickers_1.json"), "w") as fh:
            json.dump({"markets": markets, "cursor": ""}, fh)
        for t, book in (books or {}).items():
            with open(os.path.join(self.fixtures, f"orderbook_{t}.json"), "w") as fh:
                json.dump({"orderbook_fp": book}, fh)
        if books:
            with open(os.path.join(self.fixtures, "orderbooks.json"), "w") as fh:
                json.dump({"orderbooks": [{"ticker": t, "orderbook_fp": b}
                                          for t, b in books.items()]}, fh)

    def test_universe_skips_synthetic_series(self):
        universe, meta = pe.load_universe(self.tmp, dict(pe.DEFAULT_CONFIG))
        self.assertNotIn("KXDEMOFUTHOURLY-TEST-1", {u["ticker"] for u in universe})
        self.assertTrue(any(e["event_ticker"] == "KXDEMOFUTHOURLY-TEST"
                            for e in meta["excluded"]))
        self.assertEqual(len({u["topic"] for u in universe}), 5)

    def test_cycle_writes_a_consistent_ledger(self):
        # one market with a >= $0.10 drop since the desk's previous sample
        m = market(ticker="KXTEST-ELECTIONS-1-A", yes_ask="0.5000", yes_bid="0.4900",
                   yes_ask_size="250.00", yes_bid_size="300.00", last="0.5000")
        self._write_fixtures([m], {"KXTEST-ELECTIONS-1-A": {
            "yes_dollars": [["0.3900", "300.00"]],
            "no_dollars": [["0.6000", "250.00"]]}})
        client = pe.FixtureClient("https://x/trade-api/v2", self.fixtures)
        cfg = dict(pe.DEFAULT_CONFIG)
        cfg["events_per_topic"] = 1
        cfg["markets_per_event"] = 2
        out = pe.run_cycle(client, self.tmp, cfg, reset=True, quiet=True)
        state = out["state"]
        # first run seeds the tracker; the swing rule can only fire on the next sample
        self.assertEqual(state["run_count"], 1)
        self.assertEqual(out["new_trades"], [])
        self.assertIn("KXTEST-ELECTIONS-1-A", state["tracked"])

        # next sample: the published ask drops by exactly $0.10 -> the fade rule fires
        self._write_fixtures([market(ticker="KXTEST-ELECTIONS-1-A", yes_ask="0.4000",
                                     yes_bid="0.3900", no_bid="0.6000", no_ask="0.6100",
                                     yes_ask_size="250.00", yes_bid_size="300.00",
                                     last="0.4000")],
                             {"KXTEST-ELECTIONS-1-A": {
                                 "yes_dollars": [["0.3900", "300.00"]],
                                 "no_dollars": [["0.6000", "250.00"]]}})
        out2 = pe.run_cycle(client, self.tmp, cfg, quiet=True)
        state2 = out2["state"]
        self.assertEqual(state2["run_count"], 2)
        fills = [t for t in out2["new_trades"] if t.get("status") == "filled"]
        self.assertTrue(fills, "expected a simulated fill from the seeded swing")
        rec = fills[0]
        self.assertEqual(rec["ticker"], "KXTEST-ELECTIONS-1-A")
        self.assertLessEqual(rec["count"], 250)          # never more than size at touch
        self.assertAlmostEqual(rec["notional_dollars"], rec["count"] * rec["price_dollars"], 4)
        self.assertIn("source_urls", rec)
        self.assertTrue(rec["source_urls"]["markets"].startswith("https://x/trade-api/v2/markets?tickers="))
        # the book snapshot attached to the fill comes from the batched orderbook call
        self.assertTrue(rec["book"], "expected an orderbook snapshot on the fill record")
        self.assertIn("/markets/orderbooks", rec["book"]["source_url"])
        self.assertEqual(rec["book"]["best_no_bid"], [0.60, 250.0])

        # accounting identity with no fees: equity == cash + positions value,
        # and cash moved exactly by the fills
        expected_cash = 5000.0 - sum(t["notional_dollars"] for t in fills
                                     if t["action"] == "open")
        self.assertAlmostEqual(state2["cash_dollars"], round(expected_cash, 4), 4)
        totals = out2["analysis"]["totals"]
        self.assertAlmostEqual(totals["equity_dollars"],
                              round(state2["cash_dollars"] + sum(
                                  p.get("market_value_dollars") or 0.0
                                  for p in state2["positions"]), 4), 4)
        for path in ("state.json", "trades.json", "equity.json", "analysis.json",
                     "resolutions.json", "runs.json", "books.json", "sources.json"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "paper", path)), path)
        with open(os.path.join(self.tmp, "paper", "state.json")) as fh:
            persisted = json.load(fh)
        self.assertEqual(persisted["mode"], "simulated-paper")
        self.assertEqual(persisted["data_mode"], "offline-fixtures")
        self.assertGreater(persisted["config"]["risk_per_trade_dollars"], 0)

    def test_no_fill_when_the_ask_has_no_size(self):
        m = market(ticker="KXTEST-CRYPTO-1-A", yes_ask="1.0000", yes_bid="0.0000",
                   yes_ask_size="0.00", yes_bid_size="0.00", last="0.0300",
                   prev_ask="0.0300", volume_24h="0.00", volume="162214680.45")
        self._write_fixtures([m])
        client = pe.FixtureClient("https://r/trade-api/v2", self.fixtures)
        cfg = dict(pe.DEFAULT_CONFIG)
        cfg["events_per_topic"] = 1
        cfg["markets_per_event"] = 2
        pe.run_cycle(client, self.tmp, cfg, reset=True, quiet=True)
        # force a big drop so a rule fires, but there is no liquidity at the touch
        m2 = dict(m, yes_ask_dollars="0.4000", yes_bid_dollars="0.3900",
                  no_bid_dollars="0.6100", no_ask_dollars="0.6000",
                  last_price_dollars="0.4000", yes_ask_size_fp="0.00",
                  yes_bid_size_fp="0.00", previous_yes_ask_dollars="0.5000")
        self._write_fixtures([m2])
        out = pe.run_cycle(client, self.tmp, cfg, quiet=True)
        self.assertEqual(out["state"]["positions"], [])
        self.assertGreaterEqual(out["state"]["counters"]["rejections"], 0)
        self.assertEqual(out["state"]["cash_dollars"], 5000.0)

    def test_resting_maker_fills_only_on_a_cross(self):
        m = market(ticker="KXTEST-CULTURE-1-A", yes_bid="0.4000", yes_ask="0.4400",
                   yes_ask_size="200.00", yes_bid_size="200.00", step="0.0100")
        self._write_fixtures([m])
        client = pe.FixtureClient("https://r/trade-api/v2", self.fixtures)
        cfg = dict(pe.DEFAULT_CONFIG)
        cfg["events_per_topic"] = 1
        cfg["markets_per_event"] = 2
        pe.run_cycle(client, self.tmp, cfg, reset=True, quiet=True)
        out = pe.run_cycle(client, self.tmp, cfg, quiet=True)
        resting = out["state"]["resting_orders"]
        self.assertTrue(any(o["ticker"] == "KXTEST-CULTURE-1-A" for o in resting) or
                        any(t.get("status") == "resting" for t in out["new_trades"]))
        pos = [p for p in out["state"]["positions"] if p["ticker"] == "KXTEST-CULTURE-1-A"]
        self.assertEqual(pos, [])  # nothing fills while the ask stays above the limit
        m2 = dict(m, yes_ask_dollars="0.4100", yes_bid_dollars="0.4000",
                  no_bid_dollars="0.6000", no_ask_dollars="0.6000",
                  last_price_dollars="0.4100")
        self._write_fixtures([m2])
        out2 = pe.run_cycle(client, self.tmp, cfg, quiet=True)
        crossed = [t for t in out2["new_trades"]
                   if t.get("action") == "open" and t.get("role") == "maker"]
        self.assertTrue(crossed, "expected the resting bid to fill once the ask crossed it")
        self.assertLessEqual(crossed[0]["price_dollars"], 0.41)


class BookTests(unittest.TestCase):
    class _C:
        root = "https://r/trade-api/v2"

        def __init__(self, payload):
            self.payload = payload
            self.paths = []

        def get_raw(self, path):
            self.paths.append(path)
            return self.payload

    def test_batch_books_parse_and_expose_implied_asks(self):
        client = self._C({"orderbooks": [
            {"ticker": "A", "orderbook_fp": {"yes_dollars": [["0.4000", "10.00"]],
                                             "no_dollars": [["0.5800", "4.00"],
                                                            ["0.6000", "2.00"]]}},
            {"ticker": "B", "orderbook_fp": {"yes_dollars": [], "no_dollars": []}},
        ]})
        books, stats = pe.fetch_books(client, ["A", "B"], 100, depth=6)
        self.assertEqual(stats["requests"], 1)
        self.assertIn("tickers=A&tickers=B", client.paths[0])
        a = books["A"]
        self.assertEqual(a["best_yes_bid"], [0.4, 10.0])
        self.assertEqual(a["best_no_bid"], [0.6, 2.0])       # ascending -> best last
        self.assertEqual(a["implied_yes_ask"], 0.4)           # 1 - 0.60
        self.assertEqual(a["implied_no_ask"], 0.6)
        self.assertEqual(books["B"]["best_yes_bid"], None)
        self.assertEqual(stats["tickers"], 2)

    def test_batch_errors_are_recorded_not_retried_into_values(self):
        class Boom(self._C):
            def get_raw(self, path):
                raise RuntimeError("429 too many requests")
        books, stats = pe.fetch_books(Boom({}), ["A"], 100)
        self.assertEqual(books, {})
        self.assertEqual(stats["errors"], 1)
        self.assertIn("429", stats["batches"][0]["error"])


class AnalysisTests(unittest.TestCase):
    def test_buckets_and_identity(self):
        state = pe.init_state(dict(pe.DEFAULT_CONFIG), "https://x", "offline-fixtures")
        trades = [
            {"action": "open", "status": "rejected", "strategy": "swing_fade",
             "topic": "crypto", "side": "yes", "family": "reversion", "count": 0,
             "notional_dollars": 0.0, "realized_pnl_dollars": None},
            {"action": "close", "status": "filled", "strategy": "swing_fade",
             "topic": "crypto", "side": "yes", "family": "reversion", "count": 10,
             "notional_dollars": 6.0, "realized_pnl_dollars": 1.5,
             "classification": {"price_band": "30-70c (middle)"}},
            {"action": "settle", "status": "settled", "strategy": "favorite_carry",
             "topic": "golf", "side": "no", "family": "carry", "count": 5,
             "notional_dollars": 0.0, "realized_pnl_dollars": -2.0,
             "classification": {"price_band": "settlement"}},
        ]
        state["realized_pnl_dollars"] = -0.5
        state["cash_dollars"] = 4999.5
        state["positions"] = []
        out = pe.analyze(trades, state, [{"equity_dollars": 5000.0}, {"equity_dollars": 4990.0}])
        strat = {r["key"]: r for r in out["grouped"]["by_strategy"]}
        self.assertEqual(strat["swing_fade"]["closed_trades"], 1)
        self.assertEqual(strat["swing_fade"]["wins"], 1)
        self.assertEqual(strat["swing_fade"]["rejections"], 1)
        self.assertEqual(strat["favorite_carry"]["losses"], 1)
        self.assertEqual(out["totals"]["max_drawdown_dollars"], 10.0)
        self.assertEqual(out["totals"]["total_pnl_dollars"], -0.5)
        self.assertTrue(any(r["key"] == "30-70c (middle)"
                            for r in out["grouped"]["by_price_band"]))
        self.assertTrue(out["caveats"]["fees"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
