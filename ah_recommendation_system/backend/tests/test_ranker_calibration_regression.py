"""Deterministic research fixtures, never production market evidence."""
import unittest

import pandas as pd

from ah_recommendation_system.backend.stock_recommend.rolling_calibration import rolling_calibrate_ranker


FEATURES = ("trend", "price_volume", "value_quality", "capital", "relative_strength", "event")


def panel():
    rows = []
    for day in pd.bdate_range("2023-01-02", periods=120):
        end = day + pd.offsets.BDay(1)
        date, exit_date = str(day.date()), str(end.date())
        for i in range(6):
            net = i - 2
            rows.append({"date": date, "label_end": exit_date, "code": str(i),
                         "factors": dict.fromkeys(FEATURES, i / 5),
                         "composite": .9 - i * .02,
                         "net_return_pct": net, "excess_return_pct": net,
                         "benchmark_return_pct": 0, "status": "filled",
                         "regime": "offense", "eligible": True,
                         "source": "live_execution", "point_in_time_snapshot": True,
                         "panel_scope": "all_tradable",
                         "daily_equity": {exit_date: 1 + net / 100},
                         "daily_benchmark": {exit_date: 1.0},
                         "market_calendar": {exit_date: {"open": 100, "close": 100}}})
    return rows


def calibrate(rows, **kwargs):
    return rolling_calibrate_ranker(rows, as_of="2025-01-01", train_days=20,
                                    validation_days=20, test_days=20, minimum_folds=2, **kwargs)


class TestRankerCalibrationRegression(unittest.TestCase):
    def test_test_portfolio_uses_dated_top_five_and_measured_drawdown(self):
        rows = panel()
        first = calibrate(rows)["folds"][0]
        for row in rows:
            if first["test_start"] <= row["date"] <= first["test_end"]:
                row["net_return_pct"] = row["excess_return_pct"] = -10
                row["daily_equity"] = dict.fromkeys(row["daily_equity"], .9)
        metrics = calibrate(rows)["folds"][0]["test_metrics"]
        self.assertEqual(metrics["cohort_count"], 10)
        self.assertLess(metrics["cohort_drawdown_pct"], -1)
        self.assertLess(metrics["portfolio"]["max_drawdown_pct"], -1)
        self.assertTrue(metrics["portfolio"]["risk_validated"])
        for cohort in metrics["cohorts"]:
            self.assertLessEqual(len(cohort["codes"]), 5)

    def test_baseline_is_independent_saved_composite(self):
        result = calibrate(panel())
        self.assertTrue(result["folds"])
        fold = result["folds"][0]
        self.assertGreater(fold["test_metrics"]["mean_net_excess_pct"],
                           fold["baseline_metrics"]["mean_net_excess_pct"])
        self.assertEqual(fold["baseline_ranking_key"], "composite")
        for cohort in fold["baseline_metrics"]["cohorts"]:
            self.assertEqual(cohort["codes"], ["0", "1", "2", "3", "4"])


if __name__ == "__main__":
    unittest.main()
