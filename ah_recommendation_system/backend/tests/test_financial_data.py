import unittest

from ah_recommendation_system.backend.stock_recommend.financial_data import merge_statements
from ah_recommendation_system.backend.stock_recommend.quality_factors import assess_quality


class TestFinancialData(unittest.TestCase):
    def statements(self):
        common = {"pubDate": "2026-04-20", "statDate": "2025-12-31"}
        return {
            "profit": [dict(common, roeAvg="0.15", netProfit="100000000")],
            "growth": [dict(common, YOYNI="0.2")],
            "balance": [dict(common, liabilityToAsset="0.4")],
            "cash_flow": [dict(common, CFOToNP="1.2")],
        }

    def test_explicit_fraction_mapping_and_direct_cash_ratio(self):
        rows = merge_statements(self.statements(), as_of="2026-09-01")
        self.assertEqual(rows[0]["roe_pct"], 15)
        self.assertEqual(rows[0]["profit_growth_pct"], 20)
        self.assertEqual(rows[0]["debt_to_assets_pct"], 40)
        result = assess_quality(rows, as_of="2026-09-01")
        self.assertEqual(result["metric_count"], 4)
        self.assertEqual(result["cash_conversion"], 1.2)

    def test_later_revision_and_other_period_cannot_leak(self):
        data = self.statements()
        data["profit"].append(dict(data["profit"][0], pubDate="2026-10-01", roeAvg="0.9"))
        data["cash_flow"][0]["statDate"] = "2024-12-31"
        rows = merge_statements(data, as_of="2026-09-01")
        result = assess_quality(rows, as_of="2026-09-01")
        self.assertEqual(result["metrics"]["roe_pct"], 15)
        self.assertIsNone(result["cash_conversion"])

    def test_each_component_publication_must_precede_cutoff(self):
        data = self.statements()
        data["growth"][0]["pubDate"] = "2026-09-01"
        rows = merge_statements(data, as_of="2026-09-01")
        self.assertNotIn("profit_growth_pct", rows[0])

    def test_negative_profit_does_not_earn_cash_quality(self):
        data = self.statements()
        data["profit"][0]["netProfit"] = "-100"
        result = assess_quality(merge_statements(data, as_of="2026-09-01"), as_of="2026-09-01")
        self.assertIsNone(result["cash_conversion"])
