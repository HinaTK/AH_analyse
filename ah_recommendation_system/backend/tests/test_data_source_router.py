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
