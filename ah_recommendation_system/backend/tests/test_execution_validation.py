import unittest

import pandas as pd


def bars(prices=(10, 10, 11, 12, 13)):
    return pd.DataFrame([
        {"date": date.strftime("%Y-%m-%d"), "open": float(price), "close": float(price),
         "high": price + .05, "low": price - .05, "volume": 1000000,
         "prev_close": prices[max(0, index - 1)]}
        for index, (date, price) in enumerate(zip(pd.bdate_range("2026-09-01", periods=len(prices)), prices))
    ])


class TestExecutionValidation(unittest.TestCase):
    def simulate(self, frame=None, **kwargs):
        from ah_recommendation_system.backend.stock_recommend.execution_validation import simulate_forward_trade

        return simulate_forward_trade(
            bars=bars() if frame is None else frame,
            benchmark=bars((100, 100, 102, 103, 104)),
            code=kwargs.pop("code", "600001"), signal_date="2026-09-01",
            horizon=kwargs.pop("horizon", 1), **kwargs,
        )

    def test_next_open_costs_and_benchmark_are_aligned(self):
        from ah_recommendation_system.backend.stock_recommend.execution_validation import ExecutionCosts

        result = self.simulate(costs=ExecutionCosts(buy_fee=.001, sell_fee=.002, slippage=.001, minimum_fee=0, sell_tax=0))
        self.assertEqual(result["status"], "filled")
        self.assertEqual(result["entry_date"], "2026-09-02")
        self.assertEqual(result["exit_date"], "2026-09-03")
        expected = ((11 * .999 * .998) / (10 * 1.001 * 1.001) - 1) * 100
        self.assertAlmostEqual(result["net_return_pct"], expected, places=5)
        self.assertAlmostEqual(result["excess_return_pct"], expected - 2, places=5)

    def test_checks_suspension_on_execution_day(self):
        frame = bars()
        frame.loc[1, "volume"] = 0
        result = self.simulate(frame)
        self.assertEqual(result["status"], "unfilled")
        self.assertEqual(result["reason"], "entry_suspended")

    def test_checks_open_limit_even_if_close_recovered(self):
        frame = bars()
        frame.loc[1, ["open", "high"]] = [11, 11]
        result = self.simulate(frame)
        self.assertEqual(result["status"], "unfilled")
        self.assertEqual(result["reason"], "entry_limit_up")

    def test_chinext_uses_twenty_percent_limit(self):
        frame = bars()
        frame.loc[1, ["open", "high"]] = [11, 11]
        self.assertEqual(self.simulate(frame, code="301001")["status"], "filled")

    def test_limit_down_exit_is_delayed_not_fabricated(self):
        frame = bars((10, 10, 9, 9.2, 9.3))
        result = self.simulate(frame)
        self.assertEqual(result["status"], "filled")
        self.assertEqual(result["exit_date"], "2026-09-04")
        self.assertEqual(result["exit_delay_sessions"], 1)
        self.assertAlmostEqual(result["benchmark_return_pct"], 3)

    def test_missing_entry_bar_does_not_shift_entry(self):
        result = self.simulate(bars().drop(index=1))
        self.assertEqual(result["status"], "unfilled")
        self.assertEqual(result["reason"], "entry_data_missing")

    def test_unmatured_horizon_remains_pending(self):
        self.assertEqual(self.simulate(horizon=5)["status"], "pending")

    def test_rejects_same_day_horizon_and_invalid_costs(self):
        from ah_recommendation_system.backend.stock_recommend.execution_validation import ExecutionCosts

        with self.assertRaises(ValueError):
            self.simulate(horizon=0)
        with self.assertRaises(ValueError):
            ExecutionCosts(slippage=float("nan"))

    def test_missing_previous_close_or_nonfinite_price_is_not_filled(self):
        for column in ("prev_close", "open"):
            frame = bars()
            frame.loc[1, column] = float("nan")
            self.assertEqual(self.simulate(frame)["status"], "unfilled")

    def test_missing_benchmark_has_no_strategy_result(self):
        from ah_recommendation_system.backend.stock_recommend.execution_validation import simulate_forward_trade

        result = simulate_forward_trade(bars=bars(), benchmark=pd.DataFrame(), code="600001", signal_date="2026-09-01", horizon=1)
        self.assertEqual(result["status"], "unavailable")

    def test_minimum_commission_applies_per_order_not_per_share(self):
        from ah_recommendation_system.backend.stock_recommend.execution_validation import ExecutionCosts

        result = self.simulate(quantity=1000, costs=ExecutionCosts(buy_fee=.0003, sell_fee=.0003, sell_tax=.0005, slippage=0))
        self.assertEqual(result["entry_cost"], 5)
        self.assertEqual(result["exit_cost"], 10.5)
        self.assertAlmostEqual(result["net_return_pct"], ((11000 - 10.5) / 10005 - 1) * 100)

    def test_benchmark_entry_is_open_not_close(self):
        from ah_recommendation_system.backend.stock_recommend.execution_validation import simulate_forward_trade

        benchmark = bars((100, 100, 102, 103, 104))
        benchmark.loc[1, "open"] = 98
        result = simulate_forward_trade(bars=bars(), benchmark=benchmark, code="600001", signal_date="2026-09-01", horizon=1)
        self.assertAlmostEqual(result["benchmark_return_pct"], (102 / 98 - 1) * 100)

    def test_known_entry_failure_is_not_hidden_by_unmatured_exit(self):
        frame = bars()
        frame.loc[1, "volume"] = 0
        self.assertEqual(self.simulate(frame, horizon=20)["status"], "unfilled")

    def test_zero_prices_duplicate_dates_and_invalid_horizon_rejected(self):
        frame = bars()
        frame.loc[1, "prev_close"] = 0
        self.assertEqual(self.simulate(frame)["status"], "unfilled")
        self.assertEqual(self.simulate(pd.concat([bars(), bars().iloc[[1]]]))["status"], "unavailable")
        with self.assertRaises(ValueError):
            self.simulate(horizon=1.5)

    def test_actual_exchange_limit_prices_override_generic_board_rule(self):
        frame = bars()
        frame.loc[1, ["open", "high"]] = [10.5, 10.5]
        frame["limit_up"] = 11.0
        frame.loc[1, "limit_up"] = 10.5
        self.assertEqual(self.simulate(frame)["reason"], "entry_limit_up")

    def test_open_position_with_missing_exit_data_is_unavailable_not_unfilled(self):
        frame = bars().drop(index=2)
        self.assertEqual(self.simulate(frame)["status"], "unavailable")

    def test_unlimited_listing_session_requires_explicit_exchange_flag(self):
        frame = bars()
        frame.loc[1, ["open", "high"]] = [12, 12]
        frame["no_price_limit"] = False
        frame.loc[1, "no_price_limit"] = True
        self.assertEqual(self.simulate(frame)["status"], "filled")
