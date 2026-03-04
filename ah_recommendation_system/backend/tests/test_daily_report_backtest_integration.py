import unittest


class TestDailyReportBacktestIntegration(unittest.TestCase):
    def test_generate_report_includes_pair_trading_backtest(self):
        from ah_recommendation_system.backend.data.price_fetcher import (
            get_price_fetcher,
        )
        from ah_recommendation_system.backend.run_daily_job import generate_report

        # Ensure deterministic, offline run.
        get_price_fetcher().enable_mock_data()
        report = generate_report()

        self.assertIn("pair_trading", report)
        pair = report.get("pair_trading") or {}
        self.assertIn("backtest", pair)

        bt = pair.get("backtest")
        self.assertIsInstance(bt, dict)
        summary = bt.get("summary") if isinstance(bt, dict) else None
        self.assertIsInstance(summary, dict)
        if isinstance(summary, dict):
            self.assertIn("pairs_tested", summary)
            self.assertIn("trades_total", summary)


if __name__ == "__main__":
    unittest.main()
