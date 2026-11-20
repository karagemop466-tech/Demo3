"""Tests for the measured strategy backtest (session 26973298).

Run: python3 -m unittest discover -s scripts/tests -p "test_backtest*.py" -v
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_strategies as bt  # noqa: E402


class FeeFormulaTest(unittest.TestCase):
    """The fee function must reproduce the official Kalshi fee table exactly."""

    OFFICIAL = [(0.01, 0.07), (0.05, 0.34), (0.10, 0.63), (0.15, 0.90), (0.20, 1.12),
                (0.25, 1.32), (0.30, 1.47), (0.35, 1.60), (0.40, 1.68), (0.45, 1.74),
                (0.50, 1.75), (0.55, 1.74), (0.60, 1.68), (0.65, 1.60), (0.70, 1.47),
                (0.75, 1.32), (0.80, 1.12), (0.85, 0.90), (0.90, 0.63), (0.95, 0.34),
                (0.99, 0.07)]

    def test_matches_official_table_for_100_contracts(self):
        # source: https://kalshi.com/docs/kalshi-fee-schedule.pdf (July 7, 2026 table)
        for price, expected in self.OFFICIAL:
            with self.subTest(price=price):
                self.assertAlmostEqual(bt.fee(price, 100), expected, places=6)

    def test_single_contract_is_a_rarer_rounding(self):
        # The PDF's 1-contract column is itself rounded to the cent; only the closed form
        # is exact. This test pins the documented formula at 1 contract.
        self.assertAlmostEqual(bt.fee(0.50, 1), 0.02, places=6)   # 0.0175 -> 0.02
        self.assertAlmostEqual(bt.fee(0.99, 1), 0.01, places=6)   # 0.000693 -> 0.01

    def test_zero_sized_or_degenerate_prices(self):
        self.assertEqual(bt.fee(0.0), 0.0)
        self.assertEqual(bt.fee(1.0), 0.0)


class FillModelTest(unittest.TestCase):
    def test_yes_fill_is_the_traded_close(self):
        pt = {"close": 0.37, "yes_bid": 0.10, "yes_ask": 0.90}
        self.assertAlmostEqual(bt.fill_prices("yes", pt), 0.37)

    def test_no_fill_is_the_complement(self):
        pt = {"close": 0.37, "yes_bid": 0.10, "yes_ask": 0.90}
        self.assertAlmostEqual(bt.fill_prices("no", pt), 0.63)

    def test_missing_price_is_never_invented(self):
        self.assertIsNone(bt.fill_prices("yes", {"close": None}))
        self.assertIsNone(bt.fill_prices("no", {"close": None}))

    def test_spread_reported_only_when_valid(self):
        self.assertAlmostEqual(bt.spread_cost({"yes_bid": 0.40, "yes_ask": 0.44}), 0.04)
        self.assertIsNone(bt.spread_cost({"yes_bid": 0.50, "yes_ask": 0.40}))
        self.assertIsNone(bt.spread_cost({"yes_bid": None, "yes_ask": 0.40}))


class MaxDrawdownTest(unittest.TestCase):
    def test_no_drawdown_when_monotonic(self):
        self.assertEqual(bt.max_drawdown([1.0, 2.0, 3.0]), 0.0)

    def test_drawdown_measures_peak_to_trough(self):
        self.assertAlmostEqual(bt.max_drawdown([1.0, -3.0, 0.5]), -3.0)

    def test_empty(self):
        self.assertEqual(bt.max_drawdown([]), 0.0)


class PublishedResultsTest(unittest.TestCase):
    """Guards the committed output: every number on the page must be reproducible."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "strategy" / "data" / "backtest.json"
        if not path.exists():
            raise unittest.SkipTest("strategy/data/backtest.json not built")
        cls.doc = json.loads(path.read_text())

    def test_fee_table_check_passed_in_output(self):
        self.assertTrue(self.doc["fee_verification"]["all_match"])

    def test_every_trade_carries_a_source_url(self):
        for name, ds in self.doc["datasets"].items():
            for t in ds["trades"]:
                with self.subTest(dataset=name, strategy=t["strategy"]):
                    self.assertTrue(t["source_url"].startswith("http"))
                    if t["exit_kind"] == "settlement":
                        self.assertTrue(t["settlement_source_url"].startswith("http"))
                        self.assertIn(t["settled_result"], ("yes", "no"))

    def test_metrics_match_trades(self):
        for name, ds in self.doc["datasets"].items():
            for s in ds["strategies"]:
                rows = [t for t in ds["trades"] if t["strategy"] == s["id"]]
                m = s["metrics"]
                with self.subTest(dataset=name, strategy=s["id"]):
                    self.assertEqual(m.get("trades", 0), len(rows))
                    if rows:
                        self.assertAlmostEqual(
                            m["net_pnl"], round(sum(r["net_pnl"] for r in rows), 2), places=2)

    def test_fills_are_inside_the_price_range(self):
        for ds in self.doc["datasets"].values():
            for t in ds["trades"]:
                self.assertGreater(t["entry_price"], 0.0)
                self.assertLess(t["entry_price"], 1.0)

    def test_resolved_dataset_only_contains_settled_exits(self):
        for t in self.doc["datasets"]["resolved"]["trades"]:
            self.assertEqual(t["exit_kind"], "settlement")

    def test_exploratory_dataset_never_claims_settlement(self):
        for t in self.doc["datasets"]["exploratory"]["trades"]:
            self.assertEqual(t["exit_kind"], "mark")
            self.assertIsNone(t["settled_result"])

    def test_resolution_rows_quote_a_settlement_source(self):
        for r in self.doc["datasets"]["resolved"]["resolutions"]:
            self.assertIn(r["settled_result"], ("yes", "no"))
            self.assertTrue(r["settlement_source_url"].startswith("http"))


if __name__ == "__main__":
    unittest.main()
