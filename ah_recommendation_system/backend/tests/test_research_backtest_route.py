import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestResearchBacktestRoute(unittest.TestCase):
    def _build_app(self):
        import ah_recommendation_system.backend.api.research_routes as research_routes

        app = FastAPI()
        app.include_router(research_routes.router)
        return app

    def test_get_research_backtest_returns_payload(self):
        app = self._build_app()
        client = TestClient(app)
        payload = {
            "metrics": {"trades": 2, "total_return_pct": 4.5, "win_rate": 0.5},
            "equity_curve": [{"date": "2024-01-02", "equity": 1.0}],
            "trades": [
                {
                    "direction": "buy_ah",
                    "entry_date": "2024-01-02",
                    "exit_date": "2024-01-05",
                    "entry_premium_pct": -3.2,
                    "exit_premium_pct": -0.4,
                    "pnl_pct": 1.9,
                    "holding_days": 3,
                }
            ],
        }

        try:
            with mock.patch(
                "ah_recommendation_system.backend.api.research_routes.build_pair_backtest",
                return_value=payload,
                create=True,
            ) as build_pair_backtest:
                response = client.get("/api/v1/research/601398.SH/backtest")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        build_pair_backtest.assert_called_once_with("601398.SH")

    def test_get_research_backtest_returns_404_for_missing_mapping_error(self):
        import ah_recommendation_system.backend.api.research_routes as research_routes

        app = self._build_app()
        client = TestClient(app)

        try:
            with mock.patch(
                "ah_recommendation_system.backend.api.research_routes.build_pair_backtest",
                side_effect=research_routes.MissingAHMappingError("000001.SZ"),
                create=True,
            ):
                response = client.get("/api/v1/research/000001.SZ/backtest")
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "No AH pair mapping found for 000001.SZ"},
        )

    def test_get_research_backtest_returns_500_for_generic_value_error(self):
        app = self._build_app()
        client = TestClient(app)

        try:
            with mock.patch(
                "ah_recommendation_system.backend.api.research_routes.build_pair_backtest",
                side_effect=ValueError("premium calculation failed"),
                create=True,
            ):
                response = client.get("/api/v1/research/601398.SH/backtest")
        finally:
            client.close()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"detail": "premium calculation failed"},
        )

    def test_get_research_backtest_treats_missing_mapping_message_as_generic_value_error(
        self,
    ):
        app = self._build_app()
        client = TestClient(app)

        try:
            with mock.patch(
                "ah_recommendation_system.backend.api.research_routes.build_pair_backtest",
                side_effect=ValueError("No AH pair mapping found for 000001.SZ"),
                create=True,
            ):
                response = client.get("/api/v1/research/000001.SZ/backtest")
        finally:
            client.close()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"detail": "No AH pair mapping found for 000001.SZ"},
        )


if __name__ == "__main__":
    unittest.main()
