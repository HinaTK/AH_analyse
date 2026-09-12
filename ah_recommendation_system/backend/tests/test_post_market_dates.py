import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import pandas as pd

from ah_recommendation_system.backend.stock_recommend.post_market import build_post_market_review
from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card


class TestPostMarketDates(unittest.TestCase):
    def review(self, bars, reference=100):
        from ah_recommendation_system.backend.stock_recommend.run import run_post_market
        report = {
            "as_of": "2026-09-10", "generated_at": "2026-09-10 19:30:00",
            "type": "stock_recommend_pre_market", "run": {"run_id": "original-run"},
            "picks": [{"code": "002142", "name": "宁波银行", "reference_price": reference}],
            "directions": {"current_attack": [{"direction": "新闻驱动待确认"}]},
        }
        fetcher = Mock(use_mock_data=False)
        fetcher.get_a_share_price.return_value = pd.DataFrame(bars)
        with tempfile.TemporaryDirectory() as tmp:
            latest = Path(tmp) / "latest.json"
            latest.write_text(json.dumps(report), encoding="utf-8")
            with patch("ah_recommendation_system.backend.stock_recommend.run.get_price_fetcher", return_value=fetcher), patch(
                "ah_recommendation_system.backend.stock_recommend.run._collect_closing_industry_rows", return_value=[]
            ), patch("ah_recommendation_system.backend.stock_recommend.run._backend_root", return_value=Path(tmp)):
                result = run_post_market(report_path=latest, expected_as_of="2026-09-10")
                saved = json.loads(Path(result["paths"]["json_path"]).read_text(encoding="utf-8"))
                self.assertEqual(saved, result["review"])
                return result["review"]

    def test_same_close_is_baseline_not_completed_prediction(self):
        review = self.review([{"date": "2026-09-10", "close": 100}])
        self.assertIsNone(review["items"][0]["return_pct"])
        self.assertEqual(review["summary"]["completed_count"], 0)
        self.assertEqual(review["items"][0].get("close_price"), 100)
        self.assertEqual(review.get("source_report", {}).get("run_id"), "original-run")

    def test_daily_move_uses_sorted_previous_close_and_ignores_future(self):
        review = self.review([
            {"date": "2026-09-11", "close": 120},
            {"date": "2026-09-10", "close": 102},
            {"date": "2026-09-09", "close": 100},
            {"date": "2026-09-10", "close": 102},
        ], reference=102)
        row = review["items"][0]
        self.assertEqual(row.get("daily_return_pct"), 2)
        self.assertIsNone(row.get("reference_return_pct"))
        self.assertIsNone(row["return_pct"])
        self.assertEqual(row.get("close_date"), "2026-09-10")

    def test_stale_undated_and_invalid_closes_are_not_completed(self):
        for bars in ([{"date": "2026-09-09", "close": 100}], [{"close": 100}],
                     [{"date": "2026-09-10", "close": float("nan")}],
                     [{"date": "2026-09-10", "close": -1}]):
            with self.subTest(bars=bars):
                review = self.review(bars)
                self.assertEqual(review["summary"]["completed_count"], 0)
                row = review["items"][0]
                if bars[0].get("date") == "2026-09-09" and bars[0].get("close") == 100:
                    self.assertIn(row.get("data_status"), {"stale_close", "insufficient"})
                else:
                    self.assertIsNone(row.get("close_price"))
                self.assertEqual(review["run"]["status"], "partial")

    def test_genuine_flat_return_is_completed_but_nonfinite_is_pending(self):
        report = {"picks": [{"code": "x"}]}
        flat = build_post_market_review(report, prices={"x": [100, 100]})
        self.assertEqual(flat["summary"]["completed_count"], 1)
        for series in ([100, float("nan")], [100, float("inf")], [100, -1], ["bad", 100]):
            with self.subTest(series=series):
                review = build_post_market_review(report, prices={"x": series})
                self.assertIsNone(review["items"][0]["return_pct"])
                self.assertEqual(review["summary"]["completed_count"], 0)

    def test_card_distinguishes_daily_move_and_pending_verification(self):
        review = self.review([{"date": "2026-09-09", "close": 100}, {"date": "2026-09-10", "close": 102}])
        rendered = json.dumps(build_card(review), ensure_ascii=False)
        self.assertIn("当日涨跌", rendered)
        self.assertIn("+2.00%", rendered)
        self.assertIn("待验证", rendered)
        self.assertNotIn("None%", rendered)
        self.assertIn("未匹配", review["direction_review"][0]["evidence"])
