import unittest

from ah_recommendation_system.backend.stock_recommend.portfolio_validation import evaluate_cohorts


class TestPortfolioValidation(unittest.TestCase):
    def trade(self, code="1", **changes):
        return dict({"code": code, "date": "2026-07-01", "label_end": "2026-07-06",
                     "status": "filled", "regime": "offense", "entry_date": "2026-07-02",
                     "daily_equity": {"2026-07-02": 1, "2026-07-03": .8, "2026-07-06": 1.1},
                     "daily_benchmark": {"2026-07-02": 1, "2026-07-03": 1.01, "2026-07-06": 1.02},
                     "invested_amount": 10000, "exit_amount": 11000}, **changes)

    def test_daily_drawdown_catches_loss_hidden_by_winning_exit(self):
        result = evaluate_cohorts([[self.trade()]], slots=1)
        self.assertAlmostEqual(result["net_return_pct"], 10)
        self.assertAlmostEqual(result["max_drawdown_pct"], -20)
        self.assertAlmostEqual(result["net_excess_pct"], 8)
        self.assertAlmostEqual(result["turnover"], 2.1)

    def test_unfilled_allocation_stays_cash_and_benchmark_keeps_full_exposure(self):
        result = evaluate_cohorts([[self.trade(), self.trade("2", status="unfilled")]], slots=2)
        self.assertAlmostEqual(result["net_return_pct"], 5)
        self.assertAlmostEqual(result["net_excess_pct"], 3)
        self.assertAlmostEqual(result["max_drawdown_pct"], -10)

    def test_overlapping_cohorts_rejected_instead_of_double_spending_capital(self):
        with self.assertRaises(ValueError):
            evaluate_cohorts([[self.trade()], [self.trade(date="2026-07-03")]], slots=1)

    def test_missing_mark_or_mismatched_benchmark_rejects_risk_validation(self):
        trade = self.trade()
        trade["daily_equity"].pop("2026-07-03")
        result = evaluate_cohorts([[trade]], slots=1)
        self.assertFalse(result["risk_validated"])
        self.assertIn("incomplete_daily_marks", result["reasons"])

    def test_delayed_exit_uses_common_benchmark_calendar(self):
        first, second = self.trade("1"), self.trade("2", label_end="2026-07-07")
        second["daily_equity"]["2026-07-07"] = 1.12
        second["daily_benchmark"]["2026-07-07"] = 1.03
        result = evaluate_cohorts([[first, second]], slots=2)
        self.assertTrue(result["risk_validated"])
        self.assertEqual(result["daily_curve"][-1]["date"], "2026-07-07")

    def test_common_calendar_includes_idle_benchmark_exposure(self):
        calendar = {"2026-07-02": {"open": 100, "close": 100},
                    "2026-07-03": {"open": 100, "close": 101},
                    "2026-07-06": {"open": 101, "close": 102},
                    "2026-07-07": {"open": 102, "close": 120}}
        result = evaluate_cohorts([[self.trade()]], slots=1, benchmark_calendar=calendar)
        self.assertAlmostEqual(result["net_return_pct"], 10)
        self.assertAlmostEqual(result["net_excess_pct"], -10)
        cash = evaluate_cohorts([], slots=1, benchmark_calendar=calendar)
        self.assertAlmostEqual(cash["net_excess_pct"], -20)
