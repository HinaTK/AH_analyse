import unittest
from unittest.mock import patch

from fastapi import HTTPException
from requests import ConnectionError

from ah_recommendation_system.backend.api import etf_sector_routes as routes


class TestEtfOutageFallback(unittest.IsolatedAsyncioTestCase):
    async def test_selection_outage_returns_explicitly_degraded_stored_report(self):
        stored = {"generated_at": "2026-09-18 15:00:00", "recommendations": [{"code": "510300"}]}
        with patch.object(routes, "select_hot_etf_candidates", side_effect=ConnectionError("upstream offline")), patch.object(
            routes, "_load_latest_stored_etf_trend", return_value=stored
        ):
            try:
                result = await routes.get_etf_trend_block(source="live")
            except HTTPException as exc:
                self.fail(f"Expected labelled stored fallback, got HTTP {exc.status_code}")
        self.assertEqual(result["generated_at"], stored["generated_at"])
        self.assertEqual(result["fallback_source"], "stored")
        self.assertEqual(result["fallback_reason"], "live_fetch_exception")
        self.assertEqual(result["data_status"], "degraded")
        self.assertIs(result["fresh_data_available"], False)
        self.assertIn("非实时", result["data_warning"])
        self.assertNotIn("fallback_source", stored)

    async def test_generation_outage_also_falls_back_without_refreshing_timestamp(self):
        stored = {"generated_at": "2026-09-18 15:00:00"}
        with patch.object(routes, "generate_etf_trend_recommendation_block", side_effect=ConnectionError("offline")), patch.object(
            routes, "_load_latest_stored_etf_trend", return_value=stored
        ):
            result = await routes.get_etf_trend_block(source="live", codes="510300")
        self.assertEqual(result["generated_at"], stored["generated_at"])
        self.assertEqual(result["fallback_reason"], "live_fetch_exception")

    async def test_no_stored_report_keeps_failure_instead_of_fabricating_data(self):
        with patch.object(routes, "select_hot_etf_candidates", side_effect=ConnectionError("offline")), patch.object(
            routes, "_load_latest_stored_etf_trend", return_value=None
        ):
            with self.assertRaises(HTTPException) as caught:
                await routes.get_etf_trend_block(source="live")
        self.assertEqual(caught.exception.status_code, 500)

    async def test_stored_missing_stays_404_and_never_calls_live(self):
        with patch.object(routes, "select_hot_etf_candidates") as live, patch.object(
            routes, "_load_latest_stored_etf_trend", return_value=None
        ):
            with self.assertRaises(HTTPException) as caught:
                await routes.get_etf_trend_block(source="stored")
        self.assertEqual(caught.exception.status_code, 404)
        live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
