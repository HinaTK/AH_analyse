import unittest

from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality


class TestQualityCoverageRegression(unittest.TestCase):
    def check(self, coverage, name):
        result = evaluate_report_quality({"coverage": coverage})
        return next(item["passed"] for item in result["checks"] if item["name"] == name)

    def test_history_counts_require_matching_valid_denominator(self):
        invalid = [
            {"candidate_count": 10, "history_count": 10},
            {"history_target_count": 10},
            *({"history_target_count": target, "history_count": count}
              for target, count in [(0, 0), (-1, 0), (10, -1), (10, 11),
                                    (10, 7), (True, 1), (10, True),
                                    (10.5, 10), (10, 8.5), ("bad", 8), (10, float("nan"))]),
        ]
        for coverage in invalid:
            with self.subTest(coverage=coverage):
                self.assertFalse(self.check(coverage, "candidate_history_completeness"))
        self.assertTrue(self.check({"history_target_count": 10, "history_count": 8},
                                   "candidate_history_completeness"))
        self.assertTrue(self.check({"source": "mock"}, "candidate_history_completeness"))
        self.assertFalse(self.check({"source": "mock", "history_target_count": 10, "history_count": 2},
                                    "candidate_history_completeness"))

    def test_live_freshness_requires_explicit_true(self):
        for value in (None, False, 1, "true"):
            with self.subTest(value=value):
                self.assertFalse(self.check(
                    {"source": "previous_close", "fresh_data_available": value},
                    "fresh_market_data",
                ))
        self.assertTrue(self.check({"fresh_data_available": True}, "fresh_market_data"))
        self.assertTrue(self.check({"source": "mock"}, "fresh_market_data"))
        self.assertFalse(self.check({"source": "mock", "fresh_data_available": False}, "fresh_market_data"))
