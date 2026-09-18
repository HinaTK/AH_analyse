import unittest
from unittest.mock import patch

import pandas as pd


def _base_row(code="600150", name="ship"):
    return {
        "code": code, "name": name, "price": 36.5, "change_pct": 1.2,
        "change_60d_pct": 7.7, "return_20d_pct": 13.9,
        "drawdown_from_60d_high_pct": -7.3, "amount": 4_680_000_000,
        "market_cap": 287_000_000_000, "pe": 20.5, "history_days": 120,
        "benchmark_excess_60d_pct": 19.13, "benchmark_source": "baostock:sh.000300",
        "benchmark_end": "2026-09-15", "above_ma20": True, "above_ma60": True,
    }


class TestCapitalRecoveryAndEventSwing(unittest.TestCase):
    def test_fund_history_fills_latest_day_net_when_rank_missing(self):
        from ah_recommendation_system.backend.stock_recommend import data_collector

        frame = pd.DataFrame([
            {"日期": "2026-09-11", "主力净流入-净额": 10_000_000},
            {"日期": "2026-09-12", "主力净流入-净额": 20_000_000},
            {"日期": "2026-09-13", "主力净流入-净额": -5_000_000},
            {"日期": "2026-09-14", "主力净流入-净额": 15_000_000},
            {"日期": "2026-09-15", "主力净流入-净额": 25_000_000},
        ])

        class FakeAk:
            def stock_individual_fund_flow(self, stock, market):
                return frame

        with patch.object(data_collector, "_is_mock_mode", return_value=False), patch.object(
            data_collector, "ak", FakeAk()
        ):
            rows = data_collector.collect_candidate_fund_history(["600150"], days=5)

        self.assertEqual(rows[0]["code"], "600150")
        self.assertEqual(rows[0]["main_net"], 25_000_000)
        self.assertEqual(rows[0]["main_net_5d"], 65_000_000)
        self.assertEqual(rows[0]["positive_days_5d"], 4)
        self.assertEqual(rows[0]["capital_days"], 5)

    def test_history_only_capital_is_scored_instead_of_missing(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-16",
            fundamental={"rows": [_base_row()]},
            capital={"rows": [{
                "code": "600150", "main_net": 25_000_000,
                "main_net_5d": 65_000_000, "positive_days_5d": 4, "capital_days": 5,
            }]},
        )
        candidate = build_candidates(snapshot)[0]
        self.assertGreater(candidate.factor_scores["capital"], 0)
        capital = next(item for item in candidate.evidence if item["factor"] == "capital")
        self.assertIsNotNone(capital["value"])
        self.assertNotEqual(capital.get("source"), "capital_unavailable")

    def test_missing_capital_cannot_become_formal_pick(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="600150", name="ship", price=36.5, composite=0.64,
            quality_grade="A",
            valid_dimensions={"trend", "price_volume", "value", "relative_strength", "quality"},
            evidence=[
                {"factor": "trend", "statement": "trend ok", "supports": True},
                {"factor": "price_volume", "statement": "volume ok", "supports": True},
                {"factor": "value", "statement": "PE 20.5", "supports": True},
                {"factor": "relative_strength", "statement": "excess ok", "supports": True},
                {"factor": "quality", "statement": "quality 0.58", "supports": True},
                {"factor": "capital", "statement": "资金数据缺失", "value": None, "source": "capital_unavailable", "supports": False},
            ],
            factor_scores={"trend": 0.83, "price_volume": 0.71, "value_quality": 0.66, "capital": 0.0, "relative_strength": 0.98, "event": 0.5},
        )
        result = select_by_rules(
            [candidate],
            coverage_mode="full_market",
            market_regime={"regime": "defense", "status": "available"},
        )
        self.assertEqual(result["picks"], [])
        self.assertTrue(any("capital" in reason for reason in candidate.rejection_reasons))

    def test_major_positive_news_swings_score_harder_than_no_news(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        quiet = CollectedSnapshot(
            date="2026-09-16",
            fundamental={"rows": [_base_row("000001", "quiet")]},
            capital={"rows": [{"code": "000001", "main_net": 80_000_000}]},
        )
        hot = CollectedSnapshot(
            date="2026-09-16",
            fundamental={"rows": [_base_row("000001", "quiet")]},
            capital={"rows": [{"code": "000001", "main_net": 80_000_000}]},
            events={"stock_news": [{"title": "公司签署重大合同", "code": "000001", "source": "news", "published_at": "2026-09-16"}]},
        )
        quiet_score = build_candidates(quiet)[0]
        hot_score = build_candidates(hot)[0]
        self.assertGreaterEqual(hot_score.event_score, 0.95)
        self.assertGreaterEqual(hot_score.composite - quiet_score.composite, 0.08)

    def test_major_negative_news_swings_score_down_hard(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-16",
            fundamental={"rows": [_base_row("000002", "risk")]},
            capital={"rows": [{"code": "000002", "main_net": 80_000_000}]},
            events={"stock_news": [{"title": "公司证监会立案调查", "code": "000002", "source": "csrc", "published_at": "2026-09-16"}]},
        )
        candidate = build_candidates(snapshot)[0]
        self.assertLessEqual(candidate.event_score, 0.05)
        self.assertTrue(candidate.observation_only)



    def test_fund_history_falls_back_to_sina_when_akshare_fails(self):
        from ah_recommendation_system.backend.stock_recommend import data_collector

        class FakeAk:
            def stock_individual_fund_flow(self, stock, market):
                raise ConnectionError("eastmoney down")

        sina_payload = [
            {"opendate": "2026-09-11", "r0_net": "10000000"},
            {"opendate": "2026-09-12", "r0_net": "20000000"},
            {"opendate": "2026-09-13", "r0_net": "-5000000"},
            {"opendate": "2026-09-14", "r0_net": "15000000"},
            {"opendate": "2026-09-15", "r0_net": "25000000"},
        ]

        class FakeResp:
            def json(self):
                return sina_payload
            def raise_for_status(self):
                return None

        with patch.object(data_collector, "_is_mock_mode", return_value=False), patch.object(
            data_collector, "ak", FakeAk()
        ), patch.object(data_collector.requests, "get", return_value=FakeResp()):
            rows = data_collector.collect_candidate_fund_history(["600150"], days=5)

        self.assertEqual(rows[0]["code"], "600150")
        self.assertEqual(rows[0]["main_net"], 25_000_000)
        self.assertEqual(rows[0]["main_net_5d"], 65_000_000)
        self.assertIn("sina", rows[0]["source"])


if __name__ == "__main__":
    unittest.main()
