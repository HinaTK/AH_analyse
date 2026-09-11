import unittest
from unittest.mock import patch


class TestDataSourceRouter(unittest.TestCase):
    def test_circuit_opens_after_consecutive_failures_and_skips_calls(self):
        from ah_recommendation_system.backend.stock_recommend.data_source_router import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        self.assertTrue(breaker.allow_request(now=0))
        breaker.record_failure(now=0)
        self.assertTrue(breaker.allow_request(now=1))
        breaker.record_failure(now=1)
        self.assertFalse(breaker.allow_request(now=2))
        self.assertEqual(breaker.state(now=2), "open")

    def test_history_router_falls_back_after_primary_error(self):
        from ah_recommendation_system.backend.stock_recommend.data_source_router import (
            DataSourceRouter,
        )

        router = DataSourceRouter(
            providers={
                "primary": lambda code, start, end: (_ for _ in ()).throw(RuntimeError("down")),
                "backup": lambda code, start, end: [{"date": "2026-09-08", "close": 10}],
            },
            order={"history": ["primary", "backup"]},
        )
        result = router.fetch_history("000001", "20260101", "20260908")
        self.assertEqual(result.rows[0]["close"], 10)
        self.assertEqual(result.source, "backup")
        self.assertEqual(result.fallback_level, 1)

    def test_sina_quote_parser_normalizes_gbk_payload(self):
        from ah_recommendation_system.backend.stock_recommend.data_source_router import parse_sina_quotes

        fields = ["贵州茅台", "1490.00", "1480.00", "1500.00", "1510.00", "1470.00", "", "", "", "800000000"]
        fields += [""] * 20 + ["2026-09-08", "10:15:00"]
        payload = f'var hq_str_sh600519="{",".join(fields)}";'
        rows = parse_sina_quotes(payload.encode("gbk"))
        self.assertEqual(rows[0]["code"], "600519")
        self.assertEqual(rows[0]["price"], 1500.0)
        self.assertAlmostEqual(rows[0]["change_pct"], (1500 / 1480 - 1) * 100)

    def test_health_snapshot_does_not_expose_api_key(self):
        from ah_recommendation_system.backend.stock_recommend.data_source_router import DataSourceRouter

        router = DataSourceRouter(providers={})
        status = router.health()
        self.assertNotIn("api_key", str(status).lower())

    def test_report_exposes_provider_health_and_fallback_chain(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"picks": [], "as_of": "2026-09-08"},
            candidates=[],
            coverage={
                "universe_size": 10,
                "scanned_count": 10,
                "provider_health": {"hithink_financial_api": "healthy"},
                "fallback_chain": ["hithink_financial_api"],
                "circuit_breakers": [],
            },
        )
        self.assertEqual(report["provider_health"]["hithink_financial_api"], "healthy")
        self.assertEqual(report["fallback_chain"], ["hithink_financial_api"])

    def test_pipeline_reports_actual_market_data_attempted_chain(self):
        from ah_recommendation_system.backend.stock_recommend import data_collector, run

        snapshot = data_collector.CollectedSnapshot(date="2026-09-10")
        snapshot.fundamental = {
            "source": "hithink_financial_api",
            "rows": [{"code": "600519", "price": 1500, "provider_health": {"attempted_sources": ["hithink_financial_api", "akshare:supplement"]}}],
            "count": 1,
            "universe_size": 1,
            "provider_health": {"attempted_sources": ["hithink_financial_api", "akshare:supplement"]},
        }
        self.assertEqual(run.market_data_attempted_chain(snapshot), ["hithink_financial_api", "akshare:supplement"])
        snapshot.fundamental.pop("provider_health")
        self.assertEqual(run.market_data_attempted_chain(snapshot), ["hithink_financial_api"])

    def test_live_pipeline_prefetches_market_snapshot_before_collect(self):
        from unittest.mock import patch
        from ah_recommendation_system.backend.stock_recommend import data_collector, run

        snapshot = data_collector.CollectedSnapshot(date="2026-09-10")
        snapshot.fundamental = {"source": "hithink_financial_api", "rows": [{"code": "600519", "price": 1500}]}
        order = []

        def prefetch(*args, **kwargs):
            order.append("prefetch")
            return data_collector.SnapshotResult(rows=[{"code": "600519", "price": 1500}], source="hithink_financial_api")

        def collect(*args, **kwargs):
            order.append("collect")
            return snapshot

        with patch("ah_recommendation_system.backend.stock_recommend.run.prefetch_market_snapshot", side_effect=prefetch), patch(
            "ah_recommendation_system.backend.stock_recommend.run.collect_all", side_effect=collect
        ), patch("ah_recommendation_system.backend.stock_recommend.run.collect_focused_market"), patch(
            "ah_recommendation_system.backend.stock_recommend.run._enrich_with_daily_features", return_value=0
        ), patch("ah_recommendation_system.backend.stock_recommend.run.persist_snapshot"), patch(
            "ah_recommendation_system.backend.stock_recommend.run.save_report", return_value={}
        ), patch("ah_recommendation_system.backend.etf_sector.etf_sector_report.generate_etf_sector_block", return_value={}), patch(
            "ah_recommendation_system.backend.stock_recommend.run.analyze_hotspots", return_value={"status": "disabled", "hotspots": []}
        ), patch("ah_recommendation_system.backend.stock_recommend.run.review_candidate_events", return_value={"status": "disabled", "reviews": {}}), patch(
            "ah_recommendation_system.backend.stock_recommend.run.HithinkClient"
        ) as hithink:
            hithink.return_value.enabled = False
            hithink.return_value.probe.return_value = {"available": True, "capabilities": {"snapshot": True}}
            run.run_pipeline(mock=False, push=False)

        self.assertEqual(order[:2], ["prefetch", "collect"])

    def test_candidate_daily_features_are_prefetched_in_parallel(self):
        import threading
        import pandas as pd
        from ah_recommendation_system.backend.stock_recommend.run import _enrich_with_daily_features

        barrier = threading.Barrier(3, timeout=1)

        class FakeFetcher:
            def get_a_share_price(self, code, start, end):
                barrier.wait()
                bars = [
                    {
                        "date": "2026-06-%02d" % ((index % 28) + 1),
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10 + index * 0.01,
                        "volume": 1000,
                        "amount": 200_000_000,
                    }
                    for index in range(70)
                ]
                return pd.DataFrame(bars)

        rows = [{"code": "000001"}, {"code": "000002"}, {"code": "000003"}]
        enriched = _enrich_with_daily_features(rows, FakeFetcher(), as_of="2026-09-10", limit=3)

        self.assertEqual(enriched, 3)
        self.assertTrue(all(int(row.get("history_days") or 0) >= 60 for row in rows))
