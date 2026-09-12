import json
import tempfile
import unittest
from pathlib import Path

from stock_recommend.recommendation_verification import (
    build_verification_plan,
    evaluate_record,
    persist_verification_plan,
    summarize_verification,
)


class RecommendationVerificationTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [{
            "candidate_id": "c1", "symbol": "600000", "market": "CN",
            "instrument_type": "stock", "theme": "bank", "price": 10,
            "benchmark": {"symbol": "000300", "market": "CN", "price": 4},
            "source_modules": ["scanner"], "evidence": ["volume"],
        }, {
            "candidate_id": "c2", "symbol": "00700", "market": "HK",
            "instrument_type": "stock", "theme": "tech", "price": 20,
            "benchmark": {"symbol": "HSI", "market": "HK", "price": 5},
            "source_modules": ["scanner"], "evidence": [],
        }]
        self.decisions = [{"candidate_id": "c1", "state": "selected", "selected": True,
                           "confidence": 0.8, "horizon_scores": {"short": 0.7},
                           "trigger": "breakout", "invalidation": "close below 9",
                           "verification_window": {"short": 5}, "model_version": "m1"},
                          {"candidate_id": "c2", "state": "excluded", "selected": False,
                           "confidence": 0.2, "horizon_scores": {}, "trigger": "",
                           "invalidation": "", "verification_window": {}, "model_version": "m1"}]

    def test_plan_contains_all_candidates_and_exchange_session_windows(self):
        records = build_verification_plan(self.candidates, self.decisions,
                                          as_of="2026-09-12", model_version="m1")
        self.assertEqual(len(records), 6)
        self.assertEqual({r["horizon"] for r in records}, {"short", "swing", "medium"})
        self.assertEqual(records[0]["status"], "pending")
        self.assertTrue(records[0]["recommendation_id"])
        self.assertEqual(records[3]["excluded_reason"], "decision_excluded")
        self.assertEqual(records[0]["window_sessions"], 5)

    def test_persistence_is_idempotent_and_conflicts_are_not_overwritten(self):
        records = build_verification_plan(self.candidates[:1], self.decisions[:1],
                                          as_of="2026-09-12", model_version="m1")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = persist_verification_plan(records, root)
            second = persist_verification_plan(records, root)
            altered = dict(records[0]); altered["theme"] = "changed"
            third = persist_verification_plan([altered], root)
            self.assertEqual(first["saved"], 3)
            self.assertEqual(second["duplicates"], 3)
            self.assertEqual(third["conflicts"], 1)
            files = list(root.glob("*.json"))
            self.assertEqual(len(files), 3)
            self.assertEqual(json.loads(files[0].read_text())["status"], "pending")

    def test_evaluation_requires_valid_observed_sessions_trigger_and_cost(self):
        record = build_verification_plan(self.candidates[:1], self.decisions[:1],
                                         as_of="2026-09-12", model_version="m1")[0]
        obs = {"entry_at": "2026-09-14", "exit_at": "2026-09-20", "observed_at": "2026-09-21",
               "entry_price": 10, "exit_price": 11, "benchmark_entry_price": 4,
               "benchmark_exit_price": 4.2, "session_count": 5, "trigger_occurred": True,
               "tradable": True, "round_trip_cost_pct": 0.1}
        result = evaluate_record(record, obs)
        self.assertAlmostEqual(result["gross_return_pct"], 10.0)
        self.assertAlmostEqual(result["net_return_pct"], 9.9)
        self.assertAlmostEqual(result["excess_return_pct"], 4.9)
        self.assertEqual(result["status"], "matured")
        self.assertTrue(result["price_hit"])
        bad = dict(obs, trigger_occurred=None)
        self.assertEqual(evaluate_record(record, bad)["status"], "not_triggered")
        self.assertIsNone(evaluate_record(record, dict(obs, round_trip_cost_pct=None))["net_return_pct"])
        self.assertEqual(evaluate_record(record, dict(obs, entry_at="2026-09-10"))["status"], "invalid")

    def test_summary_excludes_unmatured_and_reports_bins_and_coverage(self):
        records = build_verification_plan(self.candidates[:1], self.decisions[:1],
                                          as_of="2026-09-12", model_version="m1")
        evaluated = [evaluate_record(r, {"entry_at": "2026-09-14", "exit_at": "2026-09-20",
            "observed_at": "2026-09-21", "entry_price": 10, "exit_price": 11,
            "benchmark_entry_price": 4, "benchmark_exit_price": 4.2,
            "session_count": r["window_sessions"], "trigger_occurred": True,
            "tradable": True, "round_trip_cost_pct": 0.1}) for r in records]
        summary = summarize_verification(evaluated)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["matured_valid"], 3)
        self.assertIn("confidence_bins", summary)
        self.assertEqual(summary["drawdown"], "unavailable")


if __name__ == "__main__":
    unittest.main()
