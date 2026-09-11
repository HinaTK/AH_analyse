import unittest


class TestQualityFactors(unittest.TestCase):
    def record(self, **changes):
        return dict({"published_at": "2026-08-20", "period_end": "2026-06-30", "source": "company_statement",
                     "roe_pct": 15, "profit_growth_pct": 20, "operating_cash_flow": 120,
                     "net_profit": 100, "cash_currency": "CNY", "profit_currency": "CNY",
                     "cash_unit": "yuan", "profit_unit": "yuan", "debt_to_assets_pct": 40}, **changes)

    def test_future_announcements_and_missing_quality_not_imputed(self):
        from ah_recommendation_system.backend.stock_recommend.quality_factors import assess_quality
        result = assess_quality([self.record()], as_of="2026-08-19")
        self.assertIsNone(result["score"])
        self.assertEqual(result["status"], "unavailable")

    def test_quality_is_audited_with_actual_fields(self):
        from ah_recommendation_system.backend.stock_recommend.quality_factors import assess_quality
        result = assess_quality([self.record()], as_of="2026-09-01")
        self.assertGreater(result["score"], .5)
        self.assertEqual(result["metric_count"], 4)
        self.assertEqual(result["cash_conversion"], 1.2)
        self.assertEqual(result["published_at"], "2026-08-20")

    def test_same_day_announcement_is_not_available_for_premarket(self):
        from ah_recommendation_system.backend.stock_recommend.quality_factors import assess_quality
        self.assertIsNone(assess_quality([self.record()], as_of="2026-08-20")["score"])

    def test_currency_and_unit_mismatch_does_not_form_cash_ratio(self):
        from ah_recommendation_system.backend.stock_recommend.quality_factors import assess_quality
        for changes in ({"cash_currency": "HKD"}, {"cash_unit": "million_yuan"}):
            result = assess_quality([self.record(**changes)], as_of="2026-09-01")
            self.assertIsNone(result["cash_conversion"])
            self.assertIn("cash_unit_or_currency_mismatch", result["missing"])

    def test_bank_excludes_nonfinancial_leverage_cash_scoring(self):
        from ah_recommendation_system.backend.stock_recommend.quality_factors import assess_quality
        result = assess_quality([self.record(debt_to_assets_pct=95)], as_of="2026-09-01", industry="银行")
        self.assertEqual(result["metric_count"], 2)
        self.assertEqual(result["status"], "partial")

    def test_candidate_uses_quality_and_does_not_award_fake_relative_strength(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot
        row = {"code": "600001", "name": "Example", "price": 10, "pe": 20, "market_cap": 1e10,
               "change_pct": 2, "change_60d_pct": 20, "amount": 3e8, "history_days": 120}
        snap = CollectedSnapshot(date="2026-09-01", fundamental={"rows": [row]}, capital={"rows": []})
        before = build_candidates(snap)[0]
        self.assertEqual(before.factor_scores["relative_strength"], 0)
        row["financial_records"] = [self.record()]
        after = build_candidates(snap)[0]
        self.assertNotEqual(after.factor_scores["value_quality"], before.factor_scores["value_quality"])
        self.assertTrue(any(e.get("factor") == "quality" for e in after.evidence))
