import unittest
import json


class TestFactorValidation(unittest.TestCase):
    def test_rejects_highly_correlated_factors(self):
        from ah_recommendation_system.backend.stock_recommend.factor_validation import validate_factor_set

        result = validate_factor_set({"trend": [1, 2, 3, 4], "relative_strength": [2, 4, 6, 8]})
        self.assertIn(("trend", "relative_strength"), result["redundant_pairs"])

    def test_reports_directional_ic_and_missing_values(self):
        from ah_recommendation_system.backend.stock_recommend.factor_validation import validate_factor_set

        result = validate_factor_set({"trend": [1, 2, 3, 4], "value": [None, 2, 1, 3]}, forward_returns=[.01, .02, .03, .04])
        self.assertGreater(result["factors"]["trend"]["ic"], 0.9)
        self.assertEqual(result["factors"]["value"]["sample_count"], 3)

    def test_constant_and_infinite_data_remain_unavailable(self):
        from ah_recommendation_system.backend.stock_recommend.factor_validation import validate_factor_set

        result = validate_factor_set({"constant": [1, 1, 1, float("inf")]}, forward_returns=[1, 2, 3, 4])
        self.assertIsNone(result["factors"]["constant"]["ic"])
        self.assertEqual(result["factors"]["constant"]["sample_count"], 3)
        json.dumps(result, allow_nan=False)

    def test_uses_daily_cross_sections_not_pooled_time_trends(self):
        from ah_recommendation_system.backend.stock_recommend.factor_validation import validate_factor_set

        # Across days both series rise; within EACH day higher factor loses.
        result = validate_factor_set(
            {"factor": [1, 2, 3, 100, 101, 102]},
            forward_returns=[3, 2, 1, 102, 101, 100],
            dates=["2026-01-01"] * 3 + ["2026-01-02"] * 3,
            symbols=["a", "b", "c"] * 2,
        )
        self.assertAlmostEqual(result["factors"]["factor"]["ic"], -1)
        self.assertEqual(result["factors"]["factor"]["period_count"], 2)
        self.assertFalse(result["calibration_eligible"])

    def test_rejects_misaligned_lengths_and_duplicate_observations(self):
        from ah_recommendation_system.backend.stock_recommend.factor_validation import validate_factor_set

        with self.assertRaises(ValueError):
            validate_factor_set({"x": [1, 2, 3]}, forward_returns=[1, 2])
        with self.assertRaises(ValueError):
            validate_factor_set({"x": [1, 2, 3]}, dates=["2026-01-01"] * 3, symbols=["a"] * 3)


if __name__ == "__main__":
    unittest.main()
