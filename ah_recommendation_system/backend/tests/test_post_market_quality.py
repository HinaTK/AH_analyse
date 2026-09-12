import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ah_recommendation_system.backend.stock_recommend.post_market import (
    build_post_market_review, closing_observation, format_review_item,
)


class TestPostMarketQuality(unittest.TestCase):
    def test_reference_without_quote_time_is_not_return_evidence(self):
        row = closing_observation({"reference_price": 13.88}, pd.DataFrame([
            {"date": "2026-09-10", "close": 13.14},
            {"date": "2026-09-11", "close": 13.29},
        ]), "2026-09-11")
        self.assertIsNone(row["reference_return_pct"])
        self.assertEqual(row["daily_return_pct"], 1.142)
        self.assertIn("时点未核验", format_review_item(row))

    def test_medium_term_is_not_failed_by_one_day_sector_loss(self):
        report = {"directions": {"medium_term": [{"direction": "银行"}]}}
        review = build_post_market_review(report, direction_outcomes={
            "银行": {"status": "failed", "correction": "downgrade", "evidence": "银行收盘-1.09%"},
        })
        self.assertEqual(review["direction_review"][0]["review_status"], "pending")
        self.assertEqual(review["direction_review"][0]["correction"], "confirm")

    def test_old_close_is_not_counted_as_today_coverage(self):
        review = build_post_market_review({"picks": [{"code": "x"}]}, observations={
            "x": {"close_price": 10, "close_date": "2026-09-10", "data_status": "stale_close"},
        })
        self.assertEqual(review["summary"]["close_count"], 0)
        self.assertEqual(review["run"]["status"], "partial")

    def test_mock_report_does_not_replace_live_report(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import save_report
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = {"as_of": "2026-09-11", "picks": [], "run": {"run_id": "live"}}
            paths = save_report(live, root)
            original = Path(paths["latest_json"]).read_bytes()
            save_report({**live, "run": {"run_id": "mock"}, "coverage": {"mode": "mock_sample"}}, root)
            self.assertEqual(Path(paths["latest_json"]).read_bytes(), original)

    def test_saved_run_survives_later_unpushed_recommendation(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import save_report
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {"as_of": "2026-09-11", "picks": [{"code": "002011"}], "run": {"run_id": "sent"}}
            paths = save_report(report, root)
            archive = Path(paths.get("archive_json", root / "missing"))
            self.assertTrue(archive.exists())
            save_report({**report, "run": {"run_id": "later"}, "picks": [{"code": "600150"}]}, root)
            self.assertEqual(json.loads(archive.read_text(encoding="utf8"))["picks"], report["picks"])

    def test_hithink_epoch_trading_date_uses_china_timezone(self):
        from ah_recommendation_system.backend.data.price_fetcher import PriceFetcher
        with patch("ah_recommendation_system.backend.data.price_fetcher.HithinkClient") as client:
            client.return_value.enabled = True
            client.return_value.historical.return_value = [{"date": 1789056000000, "close": 13.29}]
            frame = PriceFetcher()._get_hithink_history("002011", "20260910", "20260911")
        self.assertEqual(str(frame.iloc[0]["date"].date()), "2026-09-11")

    def test_card_labels_scope_of_verification(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
        report = build_post_market_review({"picks": [{"code": "002011"}]})
        rendered = json.dumps(build_card(report), ensure_ascii=False)
        self.assertIn("T+1已验证", rendered)
        self.assertNotIn("复盘结果**：完成", rendered)
