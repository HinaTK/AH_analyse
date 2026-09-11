import tempfile
import json
import unittest
from pathlib import Path

from ah_recommendation_system.backend.stock_recommend.reweight import aggregate_factor_stats, build_event_calibration_records, run_weekly_reweight


class TestCalibrationEvidence(unittest.TestCase):
    def row(self, **changes):
        row = {"as_of": "2026-07-01", "verified_at": "2026-08-01", "verification_version": "execution-v1",
               "verification_status": "complete", "calibration_eligible": False,
               "per_pick": [{"code": "600001", "return_T5_pct": 10, "excess_return_T5_pct": -1,
                             "execution": {"5": {"status": "filled", "excess_return_pct": -1}},
                             "factors": {"trend": .8, "event_score_rule": .8, "event_score_llm": .9}}]}
        return dict(row, **changes)

    def test_new_records_use_net_excess_not_preview_return(self):
        rows = [self.row()]
        self.assertEqual(aggregate_factor_stats(rows)["trend"]["hit_rate"], 0)
        self.assertEqual(build_event_calibration_records(rows)[0]["outcome"], 0)

    def test_excluded_and_unfilled_never_contribute(self):
        row = self.row(verification_status="excluded")
        self.assertEqual(aggregate_factor_stats([row])["trend"]["sample_count"], 0)
        self.assertEqual(build_event_calibration_records([row]), [])
        row = self.row()
        row["per_pick"][0]["execution"]["5"]["status"] = "unfilled"
        self.assertEqual(aggregate_factor_stats([row])["trend"]["sample_count"], 0)

    def test_repeated_verifications_count_once_and_latest_wins(self):
        older = self.row(verified_at="2026-08-01")
        newer = self.row(verified_at="2026-08-02")
        newer["per_pick"][0]["excess_return_T5_pct"] = 2
        newer["per_pick"][0]["execution"]["5"]["excess_return_pct"] = 2
        stats = aggregate_factor_stats([newer, older, newer])
        self.assertEqual(stats["trend"]["sample_count"], 1)
        self.assertEqual(stats["trend"]["hit_rate"], 1)

    def test_weekly_job_does_not_promote_legacy_preview_statistics(self):
        from ah_recommendation_system.backend.stock_recommend.reweight import DEFAULT_WEIGHTS

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = {"per_pick": [{"return_T5_pct": 10, "factors": dict.fromkeys(DEFAULT_WEIGHTS, .9)}]}
            (root / "stock-recommend-ledger.jsonl").write_text("\n".join(json.dumps(legacy) for _ in range(100)), encoding="utf-8")
            result = run_weekly_reweight(ledgers_dir=root, weights_path=root / "weights.json")
            saved = json.loads((root / "weights.json").read_text(encoding="utf-8"))
            self.assertFalse(saved["applied"])
            self.assertEqual(result["weights"], DEFAULT_WEIGHTS)
