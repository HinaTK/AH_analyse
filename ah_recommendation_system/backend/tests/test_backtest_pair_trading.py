import unittest

import pandas as pd


class TestPairTradingBacktest(unittest.TestCase):
    def test_backtest_generates_trades_and_metrics(self):
        # Synthetic premium series with a mean-reversion opportunity.
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=30, freq="B"),
                "premium_pct": [
                    0,
                    0,
                    0,
                    0,
                    0,
                    -5,
                    -6,
                    -7,
                    -3,
                    -1,
                    0,
                    1,
                    0,
                    0,
                    0,
                    4,
                    6,
                    7,
                    2,
                    0,
                    0,
                    0,
                    0,
                    -4,
                    -6,
                    -2,
                    0,
                    0,
                    0,
                    0,
                ],
            }
        )

        from ah_recommendation_system.backend.backtest.pair_trading_backtest import (
            run_backtest_from_premium_df,
        )

        result = run_backtest_from_premium_df(
            df=df,
            lookback=5,
            entry_z=1.0,
            exit_z=0.2,
            round_trip_cost_pct=0.5,
        )

        self.assertIn("metrics", result)
        self.assertIn("equity_curve", result)
        self.assertIn("trades", result)
        self.assertGreater(len(result["equity_curve"]), 0)
        self.assertGreaterEqual(result["metrics"]["trades"], 1)

    def test_backtest_from_prices_produces_result(self):
        # Synthetic prices with known premium movement. Use hkd_cny=1.0 for simplicity.
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        a_close = [100] * 30
        # H close moves to create premium swings: low -> high -> mean.
        h_close = [
            100,
            100,
            100,
            100,
            100,
            120,
            130,
            140,
            115,
            105,
            100,
            98,
            100,
            100,
            100,
            90,
            80,
            75,
            90,
            100,
            100,
            100,
            100,
            110,
            130,
            105,
            100,
            100,
            100,
            100,
        ]

        a_df = pd.DataFrame({"date": dates, "close": a_close})
        h_df = pd.DataFrame({"date": dates, "close": h_close})

        from ah_recommendation_system.backend.backtest.pair_trading_backtest import (
            run_backtest_from_price_dfs,
        )

        result = run_backtest_from_price_dfs(
            a_df=a_df,
            h_df=h_df,
            hkd_cny=1.0,
            lookback=5,
            entry_z=1.0,
            exit_z=0.2,
            round_trip_cost_pct=0.5,
        )

        self.assertIn("metrics", result)
        self.assertGreater(len(result["equity_curve"]), 0)
        self.assertIn("trades", result)
        self.assertGreaterEqual(result["metrics"]["trades"], 1)


if __name__ == "__main__":
    unittest.main()
