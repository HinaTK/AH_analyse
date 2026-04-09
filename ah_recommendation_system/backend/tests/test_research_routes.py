import importlib
import sys
import unittest
from types import ModuleType
from unittest import mock

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


class FakeWatchlistStore:
    def __init__(self, items=None, add_results=None, failures=None):
        self._items = [item.copy() for item in (items or [])]
        self._add_results = {
            a_code: item.copy() for a_code, item in (add_results or {}).items()
        }
        self._failures = failures or {}

    def list_symbols(self):
        failure = self._failures.get("list")
        if failure:
            raise failure

        return [item.copy() for item in self._items]

    def add_symbol(self, a_code: str):
        failure = self._failures.get("add")
        if failure:
            raise failure

        item = self._add_results.get(a_code)
        if item and not any(
            existing["a_code"] == item["a_code"] for existing in self._items
        ):
            self._items.append(item.copy())

    def remove_symbol(self, a_code: str):
        failure = self._failures.get("remove")
        if failure:
            raise failure

        self._items = [item for item in self._items if item["a_code"] != a_code]


class TestResearchRoutes(unittest.TestCase):
    def _build_router_module(self, module_name: str, router: APIRouter | None = None):
        module = ModuleType(module_name)
        module.router = router or APIRouter()
        return module

    def _import_main_module(self):
        import ah_recommendation_system.backend.api.research_routes as research_routes
        import ah_recommendation_system.backend.api.watchlist_routes as watchlist_routes

        stubbed_modules = {
            "ah_recommendation_system.backend.api.export_routes": self._build_router_module(
                "export_routes"
            ),
            "ah_recommendation_system.backend.api.backtest_routes": self._build_router_module(
                "backtest_routes"
            ),
            "ah_recommendation_system.backend.api.etf_sector_routes": self._build_router_module(
                "etf_sector_routes"
            ),
            "ah_recommendation_system.backend.api.data_health_routes": self._build_router_module(
                "data_health_routes"
            ),
            "ah_recommendation_system.backend.api.report_routes": self._build_router_module(
                "report_routes"
            ),
            "ah_recommendation_system.backend.api.stock_routes": self._build_router_module(
                "stock_routes"
            ),
            "ah_recommendation_system.backend.api.strategy_routes": self._build_router_module(
                "strategy_routes"
            ),
            "ah_recommendation_system.backend.api.research_routes": research_routes,
            "ah_recommendation_system.backend.api.watchlist_routes": watchlist_routes,
            "ah_recommendation_system.backend.config": SimpleConfigModule(),
            "ah_recommendation_system.backend.data.price_fetcher": SimplePriceFetcherModule(),
            "ah_recommendation_system.backend.reporting.report_store": SimpleReportStoreModule(),
            "ah_recommendation_system.backend.reporting.report_refresh": SimpleReportRefreshModule(),
        }

        sys.modules.pop("ah_recommendation_system.backend.main", None)
        with (
            mock.patch.dict(sys.modules, stubbed_modules),
            mock.patch("loguru.logger.add", return_value=1),
        ):
            return importlib.import_module("ah_recommendation_system.backend.main")

    def _build_route_app(self):
        import ah_recommendation_system.backend.api.research_routes as research_routes
        import ah_recommendation_system.backend.api.watchlist_routes as watchlist_routes

        app = FastAPI()
        app.include_router(research_routes.router)
        app.include_router(watchlist_routes.router)
        return app, research_routes, watchlist_routes

    def test_get_research_returns_payload(self):
        app, research_routes, _ = self._build_route_app()
        client = TestClient(app)
        payload = {
            "stock": {
                "a_code": "601398.SH",
                "h_code": "1398.HK",
                "name": "ICBC",
                "latest_premium_pct": 5.25,
            },
            "premium_series": [{"date": "2024-01-03", "premium_pct": 5.25}],
            "pair_trading": {"signal": "hold"},
            "multi_factor": {"total_score": 0.81},
            "ml_prediction": {"predicted_direction": "premium_increase"},
        }

        try:
            with mock.patch(
                "ah_recommendation_system.backend.api.research_routes.build_stock_research",
                return_value=payload,
            ) as build_stock_research:
                response = client.get("/api/v1/research/601398.SH")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        build_stock_research.assert_called_once_with("601398.SH")

    def test_get_research_returns_404_for_missing_mapping_error(self):
        import ah_recommendation_system.backend.api.research_routes as research_routes

        app, _, _ = self._build_route_app()
        client = TestClient(app)

        try:
            with mock.patch(
                "ah_recommendation_system.backend.api.research_routes.build_stock_research",
                side_effect=research_routes.MissingAHMappingError("000001.SZ"),
            ):
                response = client.get("/api/v1/research/000001.SZ")
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "No AH pair mapping found for 000001.SZ"},
        )

    def test_get_research_returns_500_for_generic_value_error(self):
        app, _, _ = self._build_route_app()
        client = TestClient(app)

        try:
            with mock.patch(
                "ah_recommendation_system.backend.api.research_routes.build_stock_research",
                side_effect=ValueError("premium calculation failed"),
            ):
                response = client.get("/api/v1/research/601398.SH")
        finally:
            client.close()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"detail": "premium calculation failed"},
        )

    def test_watchlist_add_list_delete_roundtrip_uses_fake_store(self):
        app, _, watchlist_routes = self._build_route_app()
        expected_item = {
            "a_code": "601398.SH",
            "h_code": "1398.HK",
            "name": "ICBC",
        }
        store = FakeWatchlistStore(add_results={"601398.SH": expected_item})
        app.dependency_overrides[watchlist_routes.get_watchlist_store] = lambda: store
        client = TestClient(app)

        try:
            add_response = client.post("/api/v1/watchlist/601398.SH")
            list_response = client.get("/api/v1/watchlist")
            delete_response = client.delete("/api/v1/watchlist/601398.SH")
            final_list_response = client.get("/api/v1/watchlist")
        finally:
            client.close()

        self.assertEqual(add_response.status_code, 200)
        self.assertEqual(add_response.json()["items"], [expected_item])
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json(), {"items": [expected_item]})
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json(), {"items": []})
        self.assertEqual(final_list_response.status_code, 200)
        self.assertEqual(final_list_response.json(), {"items": []})

    def test_watchlist_add_returns_500_when_store_raises_value_error(self):
        app, _, watchlist_routes = self._build_route_app()
        store = FakeWatchlistStore(
            failures={"add": ValueError("watchlist write failed")}
        )
        app.dependency_overrides[watchlist_routes.get_watchlist_store] = lambda: store
        client = TestClient(app)

        try:
            response = client.post("/api/v1/watchlist/601398.SH")
        finally:
            client.close()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "watchlist write failed"})

    def test_main_registers_watchlist_and_research_routes(self):
        app = self._import_main_module().app

        paths = {route.path for route in app.routes}

        self.assertIn("/api/v1/watchlist", paths)
        self.assertIn("/api/v1/watchlist/{a_code}", paths)
        self.assertIn("/api/v1/research/{a_code}", paths)


class SimpleConfigModule(ModuleType):
    def __init__(self):
        super().__init__("config")
        self.LOGGING_CONFIG = {
            "file": "NUL",
            "level": "INFO",
            "format": "{message}",
        }


class SimplePriceFetcherModule(ModuleType):
    def __init__(self):
        super().__init__("price_fetcher")

    @staticmethod
    def get_price_fetcher():
        class Fetcher:
            use_mock_data = True

            @staticmethod
            def enable_mock_data():
                return None

        return Fetcher()


class SimpleReportStoreModule(ModuleType):
    def __init__(self):
        super().__init__("report_store")

    @staticmethod
    def get_report_store():
        class Store:
            @staticmethod
            def load_latest():
                return True

        return Store()


class SimpleReportRefreshModule(ModuleType):
    def __init__(self):
        super().__init__("report_refresh")

    @staticmethod
    def refresh_latest_report(*args, **kwargs):
        return None


if __name__ == "__main__":
    unittest.main()
