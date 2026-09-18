import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd


def _rising_then_falling_bars(days=90, peak_at=70):
    bars = []
    base = datetime(2026, 1, 1)
    price = 10.0
    for i in range(days):
        if i <= peak_at:
            price += 0.12
        else:
            price -= 0.18
        bars.append({
            "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": price - 0.05,
            "high": price + 0.15,
            "low": price - 0.15,
            "close": round(price, 4),
            "volume": 1000 + i,
            "amount": 200_000_000,
        })
    return bars


class TestPathCapitalTurnover(unittest.TestCase):
    def test_daily_features_expose_60d_high_drawdown_and_20d_return(self):
        from ah_recommendation_system.backend.stock_recommend.technical_features import calculate_features

        features = calculate_features(_rising_then_falling_bars())
        self.assertIsNotNone(features["return_20d_pct"])
        self.assertLess(features["return_20d_pct"], 0)
        self.assertGreater(features["return_60d_pct"], 0)
        self.assertLess(features["drawdown_from_60d_high_pct"], -8)
        self.assertIsNotNone(features["high_60d"])
        self.assertGreater(features["high_60d"], 0)

    def test_late_drawdown_caps_trend_and_relative_strength(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-15",
            fundamental={"rows": [{
                "code": "600989", "name": "path-test", "price": 24,
                "change_pct": 1.0, "change_60d_pct": 20.0, "return_20d_pct": -6.0,
                "drawdown_from_60d_high_pct": -12.0, "amount": 1_500_000_000,
                "market_cap": 180_000_000_000, "pe": 12, "history_days": 120,
                "benchmark_excess_60d_pct": 25.0, "benchmark_source": "baostock:sh.000300",
                "benchmark_end": "2026-09-14",
            }]},
            capital={"rows": [{"code": "600989", "main_net": 200_000_000}]},
        )
        candidate = build_candidates(snapshot)[0]
        self.assertLessEqual(candidate.factor_scores["trend"], 0.65)
        self.assertLessEqual(candidate.factor_scores["relative_strength"], 0.6)
        statements = " ".join(item["statement"] for item in candidate.evidence)
        self.assertIn("近20日", statements)
        self.assertIn("60日高点", statements)

    def test_large_cap_low_turnover_caps_liquidity_and_capital(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-15",
            fundamental={"rows": [{
                "code": "600989", "name": "baofeng", "price": 24.46,
                "change_pct": 2.0, "change_60d_pct": 13.8, "return_20d_pct": 5.8,
                "drawdown_from_60d_high_pct": -4.4, "amount": 1_575_000_000,
                "market_cap": 179_370_000_000, "pe": 11.7, "history_days": 120,
            }]},
            capital={"rows": [{"code": "600989", "main_net": 226_000_000}]},
        )
        candidate = build_candidates(snapshot)[0]
        self.assertLess(candidate.factor_scores["price_volume"], 0.61)
        self.assertLess(candidate.factor_scores["capital"], 1.0)
        self.assertTrue(any("低换手" in reason for reason in candidate.reasons + candidate.rejection_reasons))
        statements = " ".join(item["statement"] for item in candidate.evidence)
        self.assertIn("换手", statements)
        self.assertIn("占成交", statements)

    def test_capital_uses_five_day_relative_flow_when_available(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-15",
            fundamental={"rows": [{
                "code": "000001", "name": "flow-test", "price": 10,
                "change_pct": 1.0, "change_60d_pct": 8.0, "amount": 500_000_000,
                "market_cap": 20_000_000_000, "pe": 15, "history_days": 120,
                "new_high_20d": False,
            }]},
            capital={"rows": [{
                "code": "000001", "main_net": 80_000_000,
                "main_net_5d": 220_000_000, "positive_days_5d": 4, "capital_days": 5,
            }]},
        )
        candidate = build_candidates(snapshot)[0]
        statements = " ".join(item["statement"] for item in candidate.evidence if item["factor"] == "capital")
        self.assertIn("5日", statements)
        self.assertIn("疑似吸筹", statements)

    def test_one_day_capital_cannot_claim_accumulation(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-15",
            fundamental={"rows": [{
                "code": "000002", "name": "one-day", "price": 10,
                "change_pct": 1.0, "change_60d_pct": 8.0, "amount": 500_000_000,
                "market_cap": 20_000_000_000, "pe": 15, "history_days": 120,
            }]},
            capital={"rows": [{"code": "000002", "main_net": 80_000_000}]},
        )
        candidate = build_candidates(snapshot)[0]
        statements = " ".join(item["statement"] for item in candidate.evidence if item["factor"] == "capital")
        self.assertIn("无法判断吸筹", statements)
        self.assertNotIn("疑似吸筹", statements)

    def test_collect_candidate_fund_history_summarizes_five_days(self):
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
            rows = data_collector.collect_candidate_fund_history(["600989"], days=5)

        self.assertEqual(rows[0]["code"], "600989")
        self.assertEqual(rows[0]["main_net_5d"], 65_000_000)
        self.assertEqual(rows[0]["positive_days_5d"], 4)
        self.assertEqual(rows[0]["capital_days"], 5)


if __name__ == "__main__":
    unittest.main()
