import unittest
from unittest.mock import patch

import pandas as pd


class TestMarketDataManager(unittest.TestCase):
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

    def test_unusable_primary_snapshot_falls_back_to_akshare(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager

        manager = MarketDataManager()
        incomplete = [{"code": "600519", "price": None, "change_pct": None, "amount": 0}]
        backup = [{"code": "600519", "price": 1500.0, "change_pct": 1.0, "amount": 8e8}]
        with patch.object(manager, "_snapshot", side_effect=[incomplete, backup]):
            result = manager.fetch_snapshot(limit=10)

        self.assertEqual(result.source, "akshare")
        self.assertEqual(result.rows, backup)
        self.assertEqual(result.attempted, ["hithink_financial_api", "akshare"])
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
        self.assertEqual(result.attempted, ["akshare"])

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
