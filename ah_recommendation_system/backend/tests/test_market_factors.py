import unittest
import pandas as pd


def prices(values):
    return pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=len(values)), "close": values})


class TestMarketFactors(unittest.TestCase):
    def test_stale_benchmark_cannot_be_an_available_regime(self):
        from ah_recommendation_system.backend.stock_recommend.market_factors import classify_regime
        result = classify_regime(prices([100 + i for i in range(65)]), as_of="2026-09-01")
        self.assertEqual(result["regime"], "unknown")
        self.assertEqual(result["reason"], "stale_benchmark")

    def test_excess_uses_identical_session_endpoints(self):
        from ah_recommendation_system.backend.stock_recommend.market_factors import relative_strength
        stock = prices([10 + i for i in range(65)])
        benchmark = prices([100 + 2 * i for i in range(65)])
        result = relative_strength(stock, benchmark, as_of="2026-04-10", period=60)
        expected = ((74 / 14) / (228 / 108) - 1) * 100
        self.assertAlmostEqual(result["excess_pct"], expected)

    def test_future_prices_cannot_change_regime_or_relative_strength(self):
        from ah_recommendation_system.backend.stock_recommend.market_factors import relative_strength, classify_regime
        frame = prices([100 + i for i in range(85)])
        cutoff = frame.iloc[70]["date"].strftime("%Y-%m-%d")
        before = relative_strength(frame, frame, as_of=cutoff)
        regime = classify_regime(frame, as_of=cutoff)
        frame.loc[71:, "close"] = 1
        self.assertEqual(before, relative_strength(frame, frame, as_of=cutoff))
        self.assertEqual(regime, classify_regime(frame, as_of=cutoff))
        self.assertEqual(regime["regime"], "offense")

    def test_missing_endpoint_never_shortens_period(self):
        from ah_recommendation_system.backend.stock_recommend.market_factors import relative_strength
        frame = prices([100 + i for i in range(65)])
        self.assertIsNone(relative_strength(frame.iloc[:-1], frame, as_of="2026-04-10")["excess_pct"])

    def test_defense_regime_filters_formal_picks(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules
        candidate = Candidate(code="600001", name="Example", quality_grade="A", composite=.9,
                              valid_dimensions={"trend", "value", "price_volume"}, evidence=[{"statement": "confirmed"}])
        result = select_by_rules([candidate], market_regime={"regime": "defense", "status": "available"})
        self.assertEqual(result["picks"], [])
        self.assertTrue(any(r.startswith("market:") for r in candidate.rejection_reasons))
