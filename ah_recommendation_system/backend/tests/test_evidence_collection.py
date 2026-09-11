import unittest

import pandas as pd

from ah_recommendation_system.backend.stock_recommend.evidence_collection import enrich_evidence


class Market:
    def get_benchmark_bars(self, start, end):
        return pd.DataFrame({"date": pd.bdate_range(end="2026-08-31", periods=140),
                             "close": [100 + i for i in range(140)]})

    def get_stock_bars(self, code, start, end):
        return self.get_benchmark_bars(start, end)


class Finance:
    def get_records(self, code, as_of):
        return [{"source": "test", "published_at": "2026-04-20", "period_end": "2025-12-31"}]


class TestEvidenceCollection(unittest.TestCase):
    def test_bounded_coverage_and_past_benchmark_are_explicit(self):
        rows = [{"code": "600001"}, {"code": "600002"}]
        result = enrich_evidence(rows, as_of="2026-09-01", limit=1, market_provider=Market(), financial_provider=Finance())
        self.assertEqual(result["attempted_count"], 1)
        self.assertEqual(result["financial_count"], 1)
        self.assertEqual(result["relative_strength_count"], 1)
        self.assertNotIn("financial_records", rows[1])
        self.assertEqual(result["market_regime"]["regime"], "offense")
        self.assertLess(rows[0]["benchmark_end"], "2026-09-01")

    def test_future_corporate_action_cannot_change_current_evidence(self):
        market = Market()
        frame = market.get_stock_bars("600001", "", "")
        frame["prev_close"] = frame["close"].shift(1)
        future = pd.DataFrame([{"date": pd.Timestamp("2027-01-01"), "close": 120, "prev_close": 120}])
        market.get_stock_bars = lambda *args: pd.concat([frame, future], ignore_index=True)
        rows = [{"code": "600001"}]
        result = enrich_evidence(rows, as_of="2026-09-01", market_provider=market, financial_provider=Finance())
        self.assertEqual(result["relative_strength_count"], 1)

    def test_missing_regime_prevents_formal_recommendations(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules
        candidate = Candidate(code="600001", name="test", composite=.9)
        result = select_by_rules([candidate], market_regime={"regime": "unknown", "status": "unavailable"})
        self.assertEqual(result["picks"], [])
        self.assertTrue(any(r.startswith("market:") for r in candidate.rejection_reasons))
