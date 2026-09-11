import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ah_recommendation_system.backend.stock_recommend.backtest_verify import verify_recommendation


def history(scale=1):
    days = pd.bdate_range("2026-07-01", periods=40)
    return pd.DataFrame([
        {"date": day, "open": (10 + i * .03) * scale, "close": (10 + i * .03) * scale,
         "high": (10.1 + i * .03) * scale, "low": (9.9 + i * .03) * scale,
         "prev_close": (10 + max(0, i - 1) * .03) * scale, "volume": 100000}
        for i, day in enumerate(days)
    ])


class FakeExecutionProvider:
    def __init__(self, frame=None):
        self.frame = history() if frame is None else frame
        self.calls = []

    def get_stock_bars(self, code, start, end):
        self.calls.append(code)
        return self.frame

    def get_benchmark_bars(self, start, end):
        return history(scale=100)


class PreviewProvider:
    use_mock_data = False

    def get_a_share_price(self, *args, **kwargs):
        return history()


class TestForwardVerification(unittest.TestCase):
    def test_invalid_unfilled_benchmark_stays_retryable_without_json_crash(self):
        for price in (0, float("nan")):
            report = self.report()
            report["candidate_panel"] = [{"code": "600001", "factor_scores": {"trend": .8}}]
            stock, benchmark = history(), history(scale=100)
            stock.loc[1, "volume"] = 0
            benchmark.loc[1, "open"] = price
            provider = FakeExecutionProvider(stock)
            provider.get_benchmark_bars = lambda *args: benchmark
            with tempfile.TemporaryDirectory() as tmp:
                result = verify_recommendation(report, ledgers_dir=Path(tmp), execution_provider=provider,
                                               price_fetcher=PreviewProvider(), evaluation_date="2026-09-01")
                self.assertFalse(result["candidate_panel_complete"])
                self.assertEqual(result["verification_status"], "pending")

    def test_saves_unselected_and_unfilled_candidates_without_selection_bias(self):
        report = self.report()
        report.update(candidate_panel_scope="all_saved_candidates", candidate_panel=[
            {"code": "600001", "factor_scores": {"trend": .8}, "quality_grade": "A"},
            {"code": "600002", "factor_scores": {"trend": .2}, "quality_grade": "B"}])
        frame = history()
        frame.loc[1, "volume"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recommendation(report, ledgers_dir=Path(tmp), price_fetcher=PreviewProvider(),
                                           execution_provider=FakeExecutionProvider(frame), evaluation_date="2026-09-01")
        self.assertEqual(len(result["per_pick"]), 1)
        self.assertEqual(len(result["candidate_outcomes"]), 2)
        self.assertTrue(result["candidate_panel_complete"])
        self.assertEqual(result["candidate_outcomes"][1]["status"], "unfilled")
        self.assertEqual(result["candidate_outcomes"][1]["net_return_pct"], 0)

    def report(self):
        return {"as_of": "2026-07-01", "generated_at": "2026-07-01 08:30:00",
                "coverage": {"mode": "full_market", "source": "live"},
                "factor_version": "test-v1", "market": {"regime": "neutral"},
                "picks": [{"code": "600001", "name": "Example", "action": "WATCH", "factors": {"trend": .8}}]}

    def test_persists_net_and_aligned_excess_outcomes_with_methodology(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recommendation(self.report(), ledgers_dir=Path(tmp), price_fetcher=PreviewProvider(), execution_provider=FakeExecutionProvider())
            pick = result["per_pick"][0]
            self.assertIn("return_T5_pct", pick)  # preview compatibility
            self.assertLess(pick["excess_return_T5_pct"], 0)  # identical benchmark gross return, costs hurt
            self.assertEqual(pick["execution"]["5"]["status"], "filled")
            self.assertEqual(result["verification_status"], "complete")
            self.assertEqual(result["execution_assumption"], "next_session_open_fixed_horizon_not_watch_trigger")
            self.assertEqual(result["factor_version"], "test-v1")
            stored = json.loads((Path(tmp) / "stock-recommend-ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(stored["per_pick"][0]["execution"]["5"]["entry_date"], "2026-07-02")

    def test_mock_report_excluded_before_network_or_calibration(self):
        report = self.report()
        report["coverage"]["mode"] = "mock_sample"
        provider = FakeExecutionProvider()
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recommendation(report, ledgers_dir=Path(tmp), price_fetcher=PreviewProvider(), execution_provider=provider)
        self.assertEqual(result["verification_status"], "excluded")
        self.assertFalse(result["calibration_eligible"])
        self.assertEqual(provider.calls, [])

    def test_missing_long_horizons_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recommendation(self.report(), ledgers_dir=Path(tmp), price_fetcher=PreviewProvider(), execution_provider=FakeExecutionProvider(history().iloc[:8]))
        self.assertEqual(result["verification_status"], "pending")
        self.assertIsNone(result["per_pick"][0]["net_return_T20_pct"])

    def test_future_frames_are_clipped_to_evaluation_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_recommendation(self.report(), ledgers_dir=Path(tmp), price_fetcher=PreviewProvider(), execution_provider=FakeExecutionProvider(), evaluation_date="2026-07-06")
        self.assertEqual(result["verification_status"], "pending")
        self.assertIsNone(result["per_pick"][0]["net_return_T5_pct"])

    def test_default_verification_instantiates_real_execution_provider(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ah_recommendation_system.backend.stock_recommend.backtest_verify.ExecutionDataProvider",
            return_value=FakeExecutionProvider(),
        ) as provider:
            result = verify_recommendation(self.report(), ledgers_dir=Path(tmp), price_fetcher=PreviewProvider())
        provider.assert_called_once()
        self.assertEqual(result["verification_status"], "complete")

    def test_pending_report_is_retried_then_complete_version_is_skipped(self):
        from ah_recommendation_system.backend.stock_recommend.backtest_verify import verify_all_pending

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports, ledgers = root / "reports", root / "ledgers"
            reports.mkdir()
            (reports / "recommend_20260701.json").write_text(json.dumps(self.report()), encoding="utf-8")
            args = dict(price_fetcher=PreviewProvider(), execution_provider=FakeExecutionProvider())
            first = verify_all_pending(reports, ledgers, evaluation_date="2026-07-06", **args)
            self.assertEqual(first[0]["verification_status"], "pending")
            second = verify_all_pending(reports, ledgers, evaluation_date="2026-09-01", **args)
            self.assertEqual(second[0]["verification_status"], "complete")
            third = verify_all_pending(reports, ledgers, evaluation_date="2026-09-01", **args)
            self.assertEqual(third, [])
            report = self.report()
            report["picks"][0]["code"] = "600002"
            (reports / "recommend_20260701.json").write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(len(verify_all_pending(reports, ledgers, evaluation_date="2026-09-01", **args)), 1)
