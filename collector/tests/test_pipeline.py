#!/usr/bin/env python3
"""
Offline tests for the collector/analysis pipeline. No network, no credentials.

Run:  python3 -m unittest discover -s collector/tests -v
They run in .github/workflows/checks.yml on every push, so a regression that would publish a
wrong number or a wrong citation breaks the build instead of the site.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "collector"))

import collect  # noqa: E402


class TestOrderbookMaths(unittest.TestCase):
    """T2: orderbook normalisation must reproduce Kalshi's own documented worked example.

    Source: https://docs.kalshi.com/getting_started/orderbook_responses.md
    (response structure, ascending arrays, best bid last, YES ask = 1 - best NO bid,
     spread = best ask - best bid; the page computes 0.44 - 0.42 = 0.02).
    """

    DOC_EXAMPLE = {"orderbook_fp": {
        "yes_dollars": [["0.0100", "200.00"], ["0.1500", "100.00"], ["0.2000", "50.00"],
                        ["0.2500", "20.00"], ["0.3000", "11.00"], ["0.3100", "10.00"],
                        ["0.3200", "10.00"], ["0.3300", "11.00"], ["0.3400", "9.00"],
                        ["0.3500", "11.00"], ["0.4100", "10.00"], ["0.4200", "13.00"]],
        "no_dollars": [["0.0100", "100.00"], ["0.1600", "3.00"], ["0.2500", "50.00"],
                       ["0.2800", "19.00"], ["0.3600", "5.00"], ["0.3700", "50.00"],
                       ["0.3800", "300.00"], ["0.4400", "29.00"], ["0.4500", "20.00"],
                       ["0.5600", "17.00"]],
    }}

    def setUp(self):
        self.book = collect.book_from(self.DOC_EXAMPLE)

    def test_best_bids_are_last_ascending_element(self):
        self.assertAlmostEqual(self.book["best_yes_bid"], 0.42, places=6)
        self.assertAlmostEqual(self.book["best_no_bid"], 0.56, places=6)

    def test_implied_asks_and_spread_match_docs(self):
        self.assertAlmostEqual(self.book["best_yes_ask_derived"], 0.44, places=6)
        self.assertAlmostEqual(self.book["best_no_ask_derived"], 0.58, places=6)
        self.assertAlmostEqual(self.book["spread_yes_derived"], 0.02, places=6)

    def test_depth_is_price_times_contracts(self):
        expected = sum(float(p) * float(c) for p, c in self.DOC_EXAMPLE["orderbook_fp"]["yes_dollars"])
        self.assertAlmostEqual(self.book["yes_resting_dollars"], expected, places=2)
        self.assertAlmostEqual(self.book["total_resting_dollars"],
                               self.book["yes_resting_dollars"] + self.book["no_resting_dollars"],
                               places=2)

    def test_ladder_is_best_price_first_and_side_labelled(self):
        ladder = self.book["ladder"]
        yes = [l for l in ladder if l["side"] == "yes"]
        self.assertEqual([l["price"] for l in yes], sorted((l["price"] for l in yes), reverse=True))
        self.assertEqual({l["side"] for l in ladder}, {"yes", "no"})

    def test_empty_book_does_not_crash(self):
        empty = collect.book_from({})
        self.assertIsNone(empty["best_yes_bid"])
        self.assertIsNone(empty["spread_yes_derived"])
        self.assertEqual(empty["total_resting_dollars"], 0.0)


class TestTopicMapping(unittest.TestCase):
    """T1: classification must be exact-match and must not quietly widen topic scope.

    Fixture tickers/categories are real values observed from
    GET https://demo-api.kalshi.co/trade-api/v2/series on 2026-11-20.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads((ROOT / "collector" / "topics.json").read_text())
        cls.fx = json.loads((ROOT / "collector" / "fixtures" / "t1_series.json").read_text())

    def topics(self, ticker):
        series = next(s for s in self.fx["series"] if s["ticker"] == ticker)
        return [h["topic"] for h in collect.classify(series, self.cfg)]

    def test_gas_series_matched_by_prefix_not_by_economics_category(self):
        # KXAAAGASW is category=Economics, but ~900 unrelated series share that category,
        # so a category rule would mislabel them; the gas topic must have no categories rule.
        self.assertEqual(self.topics("KXAAAGASW"), ["gas"])
        self.assertEqual(self.cfg["topics"]["gas"]["categories"], [])

    def test_crypto_elections_culture_golf(self):
        self.assertEqual(self.topics("KXBTCD"), ["crypto"])
        self.assertEqual(self.topics("KXSENATENJ"), ["elections"])
        self.assertEqual(self.topics("KX1SONGSABRINACARPENTER"), ["culture"])
        self.assertEqual(self.topics("KXPGARYDER"), ["golf"])

    def test_unmatched_series_is_excluded_not_guessed(self):
        unrelated = {"ticker": "KXUNRELATED", "title": "Weather in NYC", "category": "Weather",
                     "tags": ["Weather"]}
        self.assertEqual(collect.classify(unrelated, self.cfg), [])

    def test_every_topic_rule_records_a_reason(self):
        for name, rule in self.cfg["topics"].items():
            self.assertTrue(rule.get("why"), f"{name} is missing its justification")


class TestHonestyRules(unittest.TestCase):
    """Guard rails that keep the site from publishing invented values."""

    def test_missing_fields_become_none_not_zero(self):
        self.assertIsNone(collect.fnum(None))
        self.assertIsNone(collect.fnum(""))
        self.assertIsNone(collect.money(""))
        self.assertEqual(collect.fnum("0.0000"), 0.0)

    def test_size_metrics_marks_derived_values_and_price_basis(self):
        market = {"volume_fp": "100.00", "open_interest_fp": "40.00",
                  "last_price_dollars": "0.25", "yes_bid_dollars": "0.20",
                  "yes_ask_dollars": "0.30", "volume_24h_fp": "10.00"}
        metrics = collect.size_metrics(market, None)
        self.assertEqual(metrics["contracts_traded"], 100.0)
        self.assertEqual(metrics["traded_notional_dollars_derived"], 25.0)
        self.assertEqual(metrics["price_basis"], "last_trade")
        self.assertIn("_derived", "traded_notional_dollars_derived")

    def test_size_metrics_uses_mid_when_no_last_trade(self):
        market = {"volume_fp": "10.00", "open_interest_fp": "0", "last_price_dollars": None,
                  "yes_bid_dollars": "0.20", "yes_ask_dollars": "0.30"}
        metrics = collect.size_metrics(market, None)
        self.assertEqual(metrics["price_basis"], "mid")
        self.assertEqual(metrics["traded_notional_dollars_derived"], 2.5)

    def test_size_metrics_returns_none_without_any_price(self):
        metrics = collect.size_metrics({"volume_fp": "10.00"}, None)
        self.assertIsNone(metrics["traded_notional_dollars_derived"])
        self.assertIsNone(metrics["price_basis"])

    def test_documented_urls_are_all_https_kalshi(self):
        for key, url in collect.HOSTS.items():
            self.assertTrue(url.startswith("https://"), key)
            self.assertIn("kalshi", url, key)


class TestCommittedArtifacts(unittest.TestCase):
    """If artifacts exist in the working tree, they must be self-consistent and parseable."""

    def test_dashboard_artifact_shape(self):
        path = ROOT / "data" / "dashboard.json"
        if not path.exists():
            self.skipTest("dashboard.json not built in this workspace")
        dash = json.loads(path.read_text())
        self.assertIn("meta", dash)
        self.assertIn("tables", dash)
        for topic, groups in dash["tables"].items():
            self.assertEqual(set(groups) >= {"by_contracts_traded"}, True, topic)
            for row in groups["by_contracts_traded"]:
                self.assertTrue(row.get("source", "").startswith("https://"), row.get("ticker"))
                self.assertIn("metrics", row)

    def test_analysis_report_marks_na_items(self):
        path = ROOT / "analysis" / "report.json"
        if not path.exists():
            self.skipTest("report.json not built in this workspace")
        report = json.loads(path.read_text())
        for key, item in report.get("not_available", {}).items():
            self.assertTrue(item.get("reason"), key)
            self.assertTrue(item.get("source"), key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
