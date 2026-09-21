import unittest
from unittest.mock import patch

from ah_recommendation_system.backend import run_daily_job as job


class TestMockReportOffline(unittest.TestCase):
    def test_mock_report_never_calls_live_etf_collector(self):
        fetcher = job.get_price_fetcher()
        previous_mode = fetcher.use_mock_data
        fetcher.enable_mock_data()
        try:
            with patch.object(job, "generate_etf_sector_block", return_value={}) as collector:
                report = job.generate_report()
            collector.assert_not_called()
            self.assertEqual(report["data_mode"], "mock")
            self.assertEqual(report["etf_sector"]["data_status"], "unavailable")
            self.assertEqual(report["etf_sector"]["reason"], "disabled_in_mock_mode")
        finally:
            fetcher.use_mock_data = previous_mode


if __name__ == "__main__":
    unittest.main()
