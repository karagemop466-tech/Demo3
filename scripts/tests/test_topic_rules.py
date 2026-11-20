#!/usr/bin/env python3
"""Offline tests for the topic classifier in scripts/collect_kalshi_data.py (CR-d7d7a733-1, claim 764c370e).

Fixture rows are copied verbatim from data/latest/series.json (the committed Kalshi demo catalogue,
retrieved 2026-11-20). Expected topics for gas-price markets are stated by hand from each title.
Run:  python3 -m unittest scripts/tests/test_topic_rules.py
"""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("collect_kalshi_data", ROOT / "scripts" / "collect_kalshi_data.py")
collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collect)

# (ticker, title, category, tags) — gas-price markets; must classify as "gas"
GAS_PRICE_MARKETS = [
    ('KXAAAGASDIL', 'Illinois gas price', 'Economics', ['Oil and energy', 'Econ Daily']),
    ('AAAGASM', 'US gas price', 'Economics', ['Oil and energy']),
    ('GAS', 'Gas weekly', 'Economics', []),
    ('KXGAS', 'Gas weekly', 'Economics', []),
    ('DIESELM', 'Diesel price this month', 'Economics', ['Gas']),
    ('KXDIESELELECT', 'Diesel prices on Election Day', 'Economics', ['Oil and energy']),
    ('NGASW', 'Natural gas price max and min weekly', 'Economics', ['Oil and energy']),
    ('KXNATGAS15M', 'Natural Gas 15-minute', 'Commodities', ['15 min']),
    ('KXTRUFGAS', 'Truflation US CPI Gasoline Price Index', 'Economics', ['Inflation']),
    ('KXGASMAX', 'EIA Gas highest price yearly', 'Economics', []),
    ('KXUSGASCPI', 'US gasoline CPI in [month]', 'Economics', ['Inflation']),
    ('KXHOILW', 'Heating Oil Weekly', 'Commodities', ['Oil & Gas']),
    ('KXNGASMIN', 'Natural gas yearly low', 'Economics', ['Oil & Gas', 'Oil and energy']),
    ('KXAAAGASMAXTX', 'Texas highest gas price yearly', 'Economics', ['Oil & Gas', 'Oil and energy']),
    ('KXAAAGASED', 'US gas price on Election Day', 'Economics', ['Oil & Gas', 'Oil and energy']),
    ('KXCPIGAS', 'CPI on gas', 'Economics', ['Inflation']),
]

# (ticker, title, category, tags) — all classified "gas" by the old rules; must NOT be "gas" now
NOT_GAS_MARKETS = [
    ('KXGASTATELEG', 'Georgia State Legislature control', 'Elections', ['State legislatures', 'US Elections']),
    ('KXGASENGOVCOMBO', 'Georgia Senate-Governor Combo', 'Elections', ['Senate', 'Mixed Combos', 'US Elections', 'Governor', 'Election Combos']),
    ('KXLALIGASCORE', 'Correct Score', 'Sports', ['Soccer']),
    ('KXBUNDESLIGASCORE', 'Correct Score', 'Sports', ['Soccer']),
    ('KXDENSUPERLIGASPREAD', 'Spread', 'Sports', ['Soccer']),
    ('KXMEGASPEEDCHARGE', 'Will the U.S. or Singapore criminally charge Megaspeed?', 'Politics', ['AI', 'International', 'Prosecutions', 'SCOTUS & courts', 'Asia & Pacific']),
    ('KXQUICKSETTLE', 'Quick Settle', 'Science and Technology', ['Energy']),
    ('SUPERCON', 'Room-temp superconductor validated', 'Science and Technology', ['Energy', 'Papers']),
    ('KXNEWTEST', 'HI', 'Science and Technology', ['Energy', 'AI']),
    ('KXH100GPUTEST', 'Hourly Directional NYC Temperature', 'Science and Technology', ['AI', 'Energy']),
    ('KXIJ', 'WE', 'Science and Technology', ['Energy', 'AI']),
    ('KXDIESELEXPORTBAN', 'US Diesel Export Ban', 'Politics', ['Oil and energy']),
    ('KXRUSDIESELGL', 'Will OFAC end its Russian diesel import license?', 'Politics', ['Trump', 'Oil and energy']),
    ('KXRUSDIESELIMPORT', 'Will Russian diesel be imported into the United States?', 'Politics', ['Trump', 'Oil and energy']),
    ('KXGASTAX', 'Gasoline tax holiday bill', 'Politics', []),
    ('KXMARCELLUSGAS', 'Marcellus natural gas production', 'Economics', ['Oil and energy']),
    ('KXEIAGASINVM', 'U.S. gasoline inventories', 'Economics', ['Oil and energy']),
    ('KXWTI', 'WTI oil election day', 'Commodities', ['Oil & Gas']),
    ('KXBRENTW', 'Brent Oil', 'Commodities', ['Oil & Gas']),
    ('KXEIACRUDEW', 'U.S. crude oil inventories', 'Economics', ['Econ Weekly', 'Oil and energy']),
    ('KXTXERCOTPEAK', 'Texas ERCOT peak electricity demand', 'Economics', ['Oil and energy']),
    ('KXPOWERKWH', 'Average US electricity price this month', 'Economics', ['Oil and energy']),
    ('KXKEYSTONEFID', 'Keystone XL final investment decision', 'Financials', ['Oil and energy']),
    ('KXSPRMAX', 'SPRMAX', 'Economics', ['Oil and energy']),
    ('KXMAGASTAX', 'Massachusetts gas tax suspension', 'Politics', ['Local']),
    ('KXSUSPENDGASTAX', 'Will the federal gas tax be suspended?', 'Politics', ['Congress']),
    ('KXGASBAN', 'Gas stove ban', 'Politics', []),
    ('KXPAGAS', 'Pennsylvania natural gas production', 'Economics', ['Oil and energy']),
]


class GasTopicTests(unittest.TestCase):
    def test_gas_price_markets_are_gas(self):
        for ticker, title, category, tags in GAS_PRICE_MARKETS:
            with self.subTest(ticker=ticker):
                topic, _rule = collect.classify(ticker, title, category, tags)
                self.assertEqual(topic, "gas")

    def test_false_positives_leave_gas(self):
        for ticker, title, category, tags in NOT_GAS_MARKETS:
            with self.subTest(ticker=ticker):
                topic, _rule = collect.classify(ticker, title, category, tags)
                self.assertNotEqual(topic, "gas")

    def test_pga_and_solheim_are_golf(self):
        for ticker, title, category, tags in [("KXPGASTROKEMARGIN", "PGA Stroke Margin", "Sports", []),
                                               ("KXPGASOLHEIM", "Solheim Cup", "Sports", ["Golf"])]:
            with self.subTest(ticker=ticker):
                topic, _rule = collect.classify(ticker, title, category, tags)
                self.assertEqual(topic, "golf")

    def test_georgia_legislature_is_elections_by_category(self):
        topic, _rule = collect.classify("KXGASTATELEG", "Georgia State Legislature control", "Elections",
                                        ["State legislatures", "US Elections"])
        self.assertEqual(topic, "elections")

    def test_energy_and_oil_tags_alone_do_not_make_gas(self):
        for tag in ["Energy", "Oil & Gas", "Oil and energy", "energy"]:
            with self.subTest(tag=tag):
                topic, _rule = collect.classify("KXTESTX", "Unrelated title", "Economics", [tag])
                self.assertNotEqual(topic, "gas")

    def test_exact_fuel_tag_is_gas(self):
        topic, rule = collect.classify("KXTESTX", "Unrelated title", "Economics", ["Gas"])
        self.assertEqual((topic, rule), ("gas", "tag=Gas"))

    def test_policy_and_production_titles_are_not_gas(self):
        for title in ["Gasoline tax holiday bill", "US gasoline inventories this week",
                      "Marcellus natural gas production", "Will OFAC end its Russian diesel import license?"]:
            with self.subTest(title=title):
                topic, _rule = collect.classify("KXTESTX", title, "Politics", [])
                self.assertNotEqual(topic, "gas")

    def test_crude_oil_is_not_gas(self):
        for ticker, title in [("KXWTIMONTHLY", "WTI oil monthly"), ("KXBRENTW", "Brent Oil"), ("OILW", "Price of oil weekly")]:
            with self.subTest(ticker=ticker):
                topic, _rule = collect.classify(ticker, title, "Commodities", ["Oil & Gas"])
                self.assertNotEqual(topic, "gas")


if __name__ == "__main__":
    unittest.main()
