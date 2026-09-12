import unittest

import pandas as pd

from ah_recommendation_system.backend.stock_recommend.rolling_calibration import rolling_calibrate


def panel():
    rows = []
    dates = pd.bdate_range("2023-01-02", periods=160)
    for day in dates:
        for i in range(6):
            rows.append({"date": str(day.date()), "label_end": str((day + pd.offsets.BDay(6)).date()),
                         "code": str(i), "factors": {"good": i / 5, "bad": 1 - i / 5},
                         "net_return_pct": i - 2, "excess_return_pct": i - 2,
                         "benchmark_return_pct": 0, "regime": "offense", "eligible": True,
                         "status": "filled", "source": "synthetic_test"})
    return rows


class TestRollingCalibration(unittest.TestCase):
    def run_calibration(self, rows):
        return rolling_calibrate(rows, baseline={"good": .5, "bad": .5}, as_of="2025-01-01",
                                 train_days=40, validation_days=20, test_days=20, minimum_folds=2)

    def test_ranker_rejects_shortlist_and_mock_panels(self):
        from ah_recommendation_system.backend.stock_recommend.rolling_calibration import rolling_calibrate_ranker

        rows = []
        dates = pd.bdate_range("2023-01-02", periods=200)
        for day in dates:
            for i in range(6):
                rows.append({
                    "date": str(day.date()), "label_end": str((day + pd.offsets.BDay(6)).date()),
                    "code": str(i),
                    "factors": {"trend": i / 5, "price_volume": i / 5, "value_quality": .5,
                                "capital": .5, "relative_strength": i / 5, "event": .5},
                    "excess_return_pct": i - 2, "status": "filled",
                    "source": "mock", "point_in_time_snapshot": True, "panel_scope": "all_tradable",
                })
        result = rolling_calibrate_ranker(rows, as_of="2025-01-01",
                                          train_days=40, validation_days=20, test_days=20, minimum_folds=2)
        self.assertIn("non_live_evidence", result["reasons"])
        self.assertEqual(result["ranking_key"], "composite")

    def test_ranker_rejects_tagged_shortlist_scope(self):
        from ah_recommendation_system.backend.stock_recommend.rolling_calibration import rolling_calibrate_ranker

        rows = []
        dates = pd.bdate_range("2023-01-02", periods=200)
        for day in dates:
            for i in range(6):
                rows.append({
                    "date": str(day.date()), "label_end": str((day + pd.offsets.BDay(6)).date()),
                    "code": str(i),
                    "factors": {"trend": i / 5, "price_volume": i / 5, "value_quality": .5,
                                "capital": .5, "relative_strength": i / 5, "event": .5},
                    "excess_return_pct": i - 2, "status": "filled",
                    "source": "live_execution", "point_in_time_snapshot": True, "panel_scope": "all_saved_candidates",
                })
        result = rolling_calibrate_ranker(rows, as_of="2025-01-01",
                                          train_days=40, validation_days=20, test_days=20, minimum_folds=2)
        self.assertIn("selected_pick_bias", result["reasons"])
        self.assertEqual(result["ranking_key"], "composite")

    def test_actual_folds_purge_overlapping_outcomes(self):
        result = self.run_calibration(panel())
        self.assertGreaterEqual(len(result["folds"]), 2)
        fold = result["folds"][0]
        self.assertLess(fold["train_label_end"], fold["validation_start"])
        self.assertLess(fold["validation_label_end"], fold["test_start"])
        self.assertGreater(fold["fitted_weights"]["good"], .5)

    def test_test_labels_cannot_change_fit_or_parameter_selection(self):
        rows = panel()
        before = self.run_calibration(rows)["folds"][0]
        for row in rows:
            if before["test_start"] <= row["date"] <= before["test_end"]:
                row["net_return_pct"] *= -100
                row["excess_return_pct"] *= -100
        after = self.run_calibration(rows)["folds"][0]
        self.assertEqual(before["fitted_weights"], after["fitted_weights"])
        self.assertEqual(before["selected_weights"], after["selected_weights"])
        self.assertEqual(before["selected_threshold"], after["selected_threshold"])
        self.assertNotEqual(before["test_metrics"], after["test_metrics"])

    def test_synthetic_data_can_never_promote_live_weights(self):
        result = self.run_calibration(panel())
        self.assertFalse(result["applied"])
        self.assertIn("non_live_evidence", result["reasons"])

    def test_insufficient_and_duplicate_data_rejected(self):
        self.assertFalse(self.run_calibration(panel()[:10])["applied"])
        with self.assertRaises(ValueError):
            self.run_calibration(panel() + panel()[:1])

    def test_future_unmatured_labels_excluded(self):
        rows = panel()
        rows[-1]["label_end"] = "2030-01-01"
        result = self.run_calibration(rows)
        self.assertEqual(result["sample_count"], len(rows) - 1)

    def test_delayed_test_exit_cannot_remove_losing_candidate(self):
        rows = panel()
        first = self.run_calibration(rows)["folds"][0]
        for row in rows:
            if first["test_start"] <= row["date"] <= first["test_end"]:
                row["label_end"] = "2024-12-01"
                row["net_return_pct"] = -30
                row["excess_return_pct"] = -30
        result = self.run_calibration(rows)["folds"][0]
        self.assertEqual(first["test_count"], result["test_count"])
        self.assertLess(result["test_metrics"]["net_return_pct"], 0)

    def test_deferred_latest_validation_fold_cannot_disappear_from_promotion(self):
        rows = panel()
        before = self.run_calibration(rows)
        last = before["folds"][-1]
        for row in rows:
            if row["date"] == last["validation_start"] and row["code"] == "0":
                row["label_end"] = last["test_start"]
        result = self.run_calibration(rows)
        self.assertFalse(result["applied"])
        self.assertIn("deferred_validation_fold_cannot_promote", result["reasons"])

    def test_complete_dated_evidence_has_real_promotion_path(self):
        rows = panel()
        for row in rows:
            dates = pd.bdate_range(pd.Timestamp(row["date"]) + pd.offsets.BDay(), row["label_end"])
            row.update(source="live_execution", point_in_time_snapshot=True, panel_scope="all_saved_candidates",
                       market_calendar={str(day.date()): {"open": 100, "close": 100} for day in dates},
                       daily_equity={str(day.date()): 1 + row["net_return_pct"] / 100 * (i + 1) / len(dates)
                                     for i, day in enumerate(dates)},
                       daily_benchmark={str(day.date()): 1 for day in dates})
        # Baseline .55 selects nothing in this fixture. Use .5 so daily risk
        # comparison has an actual unchanged-baseline portfolio.
        result = rolling_calibrate(rows, baseline={"good": .5, "bad": .5}, as_of="2025-01-01",
                                   train_days=40, validation_days=20, test_days=30,
                                   minimum_folds=2, baseline_threshold=.5)
        self.assertTrue(result["applied"], result["reasons"])
        self.assertGreater(result["weights"]["good"], .5)
        self.assertLessEqual(result["weights"]["good"] - .5, .050001)
