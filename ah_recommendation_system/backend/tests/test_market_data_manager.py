import unittest
from unittest.mock import patch

import pandas as pd
import time


class TestMarketDataManager(unittest.TestCase):
    def setUp(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        MarketDataManager._shared_cache_rows = None
        MarketDataManager._shared_cache_timestamp = None
        MarketDataManager._shared_cache_source = "none"

    def test_primary_quote_is_kept_and_missing_fields_are_supplemented(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import (
            MarketDataManager,
        )

        manager = MarketDataManager()
        primary = [{"code": "600519", "name": "Moutai", "price": 1500.0, "change_pct": 1.0}]
        supplement = [{
            "code": "600519", "price": 1501.0, "change_pct": 2.0, "pe": 22.0,
            "pb": 8.0, "market_cap": 1.8e12, "float_cap": 1.8e12,
            "turnover_pct": 0.4, "amount": 8e8, "volume": 5_000,
        }]
        with patch.object(manager, "_snapshot", side_effect=[primary, supplement]):
            result = manager.fetch_snapshot(limit=10)

        self.assertEqual(result.rows[0]["price"], 1500.0)
        self.assertEqual(result.rows[0]["source"], "hithink_financial_api")
        self.assertEqual(result.rows[0]["change_pct"], 1.0)
        self.assertEqual(result.rows[0]["pe"], 22.0)
        self.assertEqual(result.rows[0]["turnover_pct"], 0.4)
        self.assertEqual(set(result.supplemented_fields), {"pe", "pb", "market_cap", "float_cap", "turnover_pct", "amount", "volume"})
        self.assertEqual(result.attempted, ["hithink_financial_api", "akshare:supplement"])

    def test_snapshot_is_served_from_fresh_cache(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager(cache_ttl_seconds=60)
        manager._shared_cache = False
        rows = [{
            "code": "600519", "price": 1500.0, "change_pct": 1.0, "pe": 22.0,
            "pb": 8.0, "market_cap": 1.8e12, "float_cap": 1.8e12,
            "turnover_pct": 0.4, "amount": 8e8, "volume": 5_000,
        }]
        with patch.object(manager, "_snapshot", return_value=rows) as snapshot:
            first = manager.fetch_snapshot(limit=10)
            second = manager.fetch_snapshot(limit=10)

        self.assertEqual(snapshot.call_count, 1)
        self.assertEqual(first.source, "hithink_financial_api")
        self.assertEqual(second.source, "cache:hithink_financial_api")
        self.assertEqual(second.rows, first.rows)
        self.assertLessEqual(second.health()["cache_age_seconds"], 60)

    def test_stale_cache_is_refreshed(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager(cache_ttl_seconds=60)
        manager._shared_cache = True
        manager.__class__._shared_cache_rows = None
        manager.__class__._shared_cache_timestamp = None
        manager.__class__._shared_cache_source = "none"
        rows = [{
            "code": "600519", "price": 1500.0, "change_pct": 1.0, "pe": 22.0,
            "pb": 8.0, "market_cap": 1.8e12, "float_cap": 1.8e12,
            "turnover_pct": 0.4, "amount": 8e8, "volume": 5_000,
        }]
        with patch.object(manager, "_snapshot", return_value=rows) as snapshot:
            manager.fetch_snapshot(limit=10)
            manager._shared_cache_timestamp = (manager._shared_cache_timestamp or 0) - 61
            manager.fetch_snapshot(limit=10)

        self.assertEqual(snapshot.call_count, 2)

    def test_efinance_snapshot_falls_back_from_akshare(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager(
            order=["hithink_financial_api", "akshare", "efinance"],
            efinance_module=object(),
        )
        broken = [{"code": "600519", "price": None}]
        backup = [{"code": "600519", "price": 1500.0, "change_pct": 1.0, "amount": 8e8}]
        with patch.object(manager, "_snapshot", side_effect=[broken, broken, backup]):
            result = manager.fetch_snapshot(limit=10)

        self.assertEqual(result.source, "efinance")
        self.assertEqual(result.attempted, ["hithink_financial_api", "akshare", "efinance"])

    def test_efinance_supplements_missing_fields_from_fallback(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager(
            order=["hithink_financial_api", "akshare", "efinance"],
            efinance_module=object(),
        )
        primary = [{"code": "600519", "name": "Moutai", "price": 1500.0, "change_pct": 1.0}]
        akshare = [{"code": "600519", "price": 1501.0, "pe": 22.0, "turnover_pct": 0.4}]
        efinance = [{"code": "600519", "price": 1502.0, "pb": 8.0, "amount": 8e8}]
        with patch.object(manager, "_snapshot", side_effect=[primary, akshare, efinance]):
            result = manager.fetch_snapshot(limit=10)

        self.assertEqual(result.attempted, [
            "hithink_financial_api", "akshare:supplement", "efinance:supplement",
        ])
        self.assertEqual(result.rows[0]["price"], 1500.0)
        self.assertEqual(result.rows[0]["pe"], 22.0)
        self.assertEqual(result.rows[0]["pb"], 8.0)

    def test_primary_without_missing_fields_skips_supplement_calls(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager()
        rows = [{
            "code": "600519", "price": 1500.0, "change_pct": 1.0, "pe": 22.0,
            "pb": 8.0, "market_cap": 1.8e12, "float_cap": 1.8e12,
            "turnover_pct": 0.4, "amount": 8e8, "volume": 5_000,
        }]
        with patch.object(manager, "_snapshot", return_value=rows) as snapshot:
            manager.fetch_snapshot(limit=10)

        self.assertEqual(snapshot.call_count, 1)

    def test_unusable_primary_snapshot_falls_back_to_akshare(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager()
        incomplete = [{"code": "600519", "price": None, "change_pct": None, "amount": 0}]
        backup = [{"code": "600519", "price": 1500.0, "change_pct": 1.0, "amount": 8e8}]
        with patch.object(manager, "_snapshot", side_effect=[incomplete, backup]):
            result = manager.fetch_snapshot(limit=10)

        self.assertEqual(result.source, "akshare")
        self.assertEqual(result.rows[0]["code"], "600519")
        self.assertEqual(result.rows[0]["price"], 1500.0)
        self.assertEqual(result.rows[0]["source"], "akshare")
        self.assertEqual(result.attempted[:2], ["hithink_financial_api", "akshare"])
        self.assertTrue(all(item.endswith(":supplement") or item in {"hithink_financial_api", "akshare"} for item in result.attempted))
        self.assertEqual(result.fallback_level, 1)

    def test_open_circuit_breaker_is_reported_as_skipped(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager()
        def snapshot(name, limit):
            if name == "hithink_financial_api":
                raise AssertionError("must skip")
            return [{"code": "600519", "price": 1}]

        with patch.object(manager, "_snapshot", side_effect=snapshot):
            manager.breakers["hithink_financial_api"].record_failure()
            manager.breakers["hithink_financial_api"].record_failure()
            result = manager.fetch_snapshot(limit=10)

        self.assertEqual(result.source, "akshare")
        self.assertEqual(result.skipped, ["hithink_financial_api"])
        self.assertEqual(result.attempted[0], "akshare")
        self.assertNotIn("hithink_financial_api", result.attempted)

    def test_market_stats_are_derived_from_rows(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager()
        manager._rows = [
            {"code": "1", "change_pct": 2.0, "amount": 10},
            {"code": "2", "change_pct": -2.0, "amount": 20},
            {"code": "3", "change_pct": 0.0, "amount": 0},
        ]
        stats = manager.market_stats()
        self.assertEqual(stats["up_count"], 1)
        self.assertEqual(stats["down_count"], 1)
        self.assertEqual(stats["flat_count"], 1)
        self.assertEqual(stats["limit_up_count"], 0)
        self.assertEqual(stats["total_amount"], 30)

    def test_akshare_snapshot_normalizes_spot_rows(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import AkshareSnapshotProvider

        akshare = AkshareSnapshotProvider()
        frame = pd.DataFrame([{
            "代码": "600519", "名称": "Moutai", "最新价": 1500.0, "涨跌幅": 1.0,
            "成交额": 8e8, "成交量": 5000, "换手率": 0.4, "市盈率-动态": 22,
            "市净率": 8, "总市值": 1.8e12, "流通市值": 1.8e12,
        }])
        class FakeAkshare:
            @staticmethod
            def stock_zh_a_spot_em():
                return frame

        with patch("ah_recommendation_system.backend.stock_recommend.market_data.ak", FakeAkshare):
            rows = akshare.snapshot(limit=10)
        self.assertEqual(rows[0]["code"], "600519")
        self.assertEqual(rows[0]["price"], 1500.0)
        self.assertEqual(rows[0]["pe"], 22)

    def test_numeric_placeholders_are_coerced_to_none(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import normalize_numeric_fields

        rows = [{"amount": "-", "turnover_pct": "--", "pe": " ", "price": "-"}]
        normalize_numeric_fields(rows)

        self.assertIsNone(rows[0]["amount"])
        self.assertIsNone(rows[0]["turnover_pct"])
        self.assertIsNone(rows[0]["pe"])
        self.assertIsNone(rows[0]["price"])

    def test_akshare_and_efinance_snapshots_are_rate_limited(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import (
            AkshareSnapshotProvider,
            EfinanceSnapshotProvider,
            RateLimiter,
        )

        limiter = RateLimiter(min_interval_seconds=0.05)
        calls = []

        class FakeAkshare:
            @staticmethod
            def stock_zh_a_spot_em():
                calls.append("ak")
                return pd.DataFrame([{"代码": "600519", "名称": "Moutai", "最新价": 1500.0, "涨跌幅": 1.0}])

        class FakeStock:
            @staticmethod
            def get_realtime_quotes():
                calls.append("ef")
                return pd.DataFrame([{"代码": "600519", "名称": "Moutai", "最新价": 1500.0, "涨跌幅": 1.0}])

        class FakeEfinance:
            stock = FakeStock()

        akshare = AkshareSnapshotProvider(akshare_module=FakeAkshare(), rate_limiter=limiter)
        efinance = EfinanceSnapshotProvider(efinance_module=FakeEfinance(), rate_limiter=limiter)
        started = time.perf_counter()
        akshare.snapshot(limit=1)
        efinance.snapshot(limit=1)
        elapsed = time.perf_counter() - started

        self.assertEqual(calls, ["ak", "ef"])
        self.assertGreaterEqual(elapsed, 0.05)

    def test_provider_snapshot_retries_transient_failures(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import AkshareSnapshotProvider

        attempts = {"count": 0}

        class FlakyAkshare:
            @staticmethod
            def stock_zh_a_spot_em():
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise ConnectionError("aborted")
                return pd.DataFrame([{"代码": "600519", "名称": "Moutai", "最新价": 1500.0, "涨跌幅": 1.0}])

        rows = AkshareSnapshotProvider(akshare_module=FlakyAkshare()).snapshot(limit=1)
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(rows[0]["code"], "600519")
