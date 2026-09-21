import unittest

import pandas as pd

from ah_recommendation_system.backend.backtest.pair_trading_backtest import (
    run_backtest_from_premium_df,
    run_backtest_from_price_dfs,
)


class TestPairBacktestTiming(unittest.TestCase):
    def run_series(self, premiums, mode="premium", cost=0.0, exit_z=0.2):
        dates = pd.date_range("2024-01-01", periods=len(premiums))
        params = dict(lookback=3, entry_z=1.0, exit_z=exit_z,
                      round_trip_cost_pct=cost)
        if mode == "premium":
            return run_backtest_from_premium_df(
                pd.DataFrame({"date": dates, "premium_pct": premiums}), **params)
        return run_backtest_from_price_dfs(
            pd.DataFrame({"date": dates, "close": [100 + p for p in premiums]}),
            pd.DataFrame({"date": dates, "close": [100.0] * len(premiums)}),
            hkd_cny=1.0, **params)

    def test_close_signal_only_changes_next_interval_position(self):
        for mode in ("premium", "prices"):
            for sign in (-1, 1):
                with self.subTest(mode=mode, sign=sign):
                    result = self.run_series([0, 0, sign * 10, sign * 5], mode)
                    curve = result["equity_curve"]
                    self.assertAlmostEqual(curve[2]["equity"], 1.0)
                    gain = 0.05 if mode == "premium" else 5 / (100 + sign * 10)
                    self.assertAlmostEqual(curve[3]["equity"], 1 + gain)
                    self.assertEqual(result["trades"][0]["exit_date"], "2024-01-04")
                    self.assertAlmostEqual(result["trades"][0]["pnl_pct"], gain * 100)

    def test_round_trip_cost_is_counted_in_trade_pnl(self):
        result = self.run_series([0, 0, -10, -5], cost=2.0)
        trade = result["trades"][0]
        self.assertLess(trade["pnl_pct"], 5.0)
        self.assertGreater(trade["pnl_pct"], 0.0)
        # 5% premium move minus 1% entry and 1% exit: 0.99*1.05*0.99 - 1 = 2.9105%
        self.assertAlmostEqual(trade["pnl_pct"], 2.9105, places=3)

    def test_missing_z_does_not_skip_observable_held_return(self):
        # Missing premium invalidates the rolling signal, not later known returns.
        result = self.run_series([0, 0, -10, float("nan"), -5, -4], exit_z=-1)
        self.assertAlmostEqual(result["equity_curve"][3]["equity"], 1.0)
        self.assertAlmostEqual(result["equity_curve"][4]["equity"], 1.0)
        self.assertAlmostEqual(result["equity_curve"][5]["equity"], 1.01)
        self.assertAlmostEqual(result["metrics"]["total_return_pct"], 1.0)

    def test_missing_price_return_does_not_count_as_zero(self):
        dates = pd.date_range("2024-01-01", periods=5)
        a_df = pd.DataFrame({"date": dates, "close": [100.0, 100.0, 90.0, float("nan"), 85.0]})
        h_df = pd.DataFrame({"date": dates, "close": [100.0, 100.0, 100.0, 105.0, 105.0]})
        result = run_backtest_from_price_dfs(
            a_df, h_df, hkd_cny=1.0, lookback=3, entry_z=1.0, exit_z=-1, round_trip_cost_pct=0.0
        )
        curve = result["equity_curve"]
        self.assertAlmostEqual(curve[2]["equity"], 1.0)
        # Missing A return must not be treated as 0 while H moved +5%.
        self.assertAlmostEqual(curve[3]["equity"], curve[2]["equity"])


if __name__ == "__main__":
    unittest.main()
