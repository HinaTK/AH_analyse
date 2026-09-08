from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ah_recommendation_system.backend.reporting.report_store import ReportStore
from ah_recommendation_system.backend.review.review_service import build_etf_sector_review


def _write_report(reports_dir: Path, date_str: str, payload: dict) -> None:
    (reports_dir / f"report_{date_str}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _make_sample_report(date_text: str) -> dict:
    return {
        "etf_sector": {
            "generated_at": f"{date_text} 10:00:00",
            "potential_breakouts": [
                {
                    "theme": "机器人",
                    "confidence": 0.82,
                    "score": 82,
                    "reasons": ["短线转强", "量能回升"],
                    "reason_dimensions": {"trend": {"summary": "5/10/20日趋势同步走强"}},
                    "related_etfs": [{"code": "159633", "name": "机器人ETF"}],
                }
            ],
            "confirmed_leaders": [],
            "crowded_risks": [
                {
                    "theme": "算力",
                    "confidence": 0.35,
                    "score": 35,
                    "reasons": ["涨幅过快"],
                    "reason_dimensions": {"heat": {"summary": "板块拥挤度偏高"}},
                    "related_etfs": [{"code": "512480", "name": "算力ETF"}],
                }
            ],
            "etf_trend": {
                "recommendations": [
                    {
                        "code": "510300",
                        "name": "沪深300ETF",
                        "recommendation": "优先关注",
                        "trend_score": 78,
                        "reasons": ["趋势延续", "回撤受控"],
                    },
                    {
                        "code": "159915",
                        "name": "创业板ETF",
                        "recommendation": "持有观察",
                        "trend_score": 52,
                        "reasons": ["仍在整理"],
                    },
                ]
            },
        }
    }


class TestReviewModule(unittest.TestCase):
    @patch("ah_recommendation_system.backend.review.review_service.fetch_etf_hist_em")
    def test_build_review_includes_human_facing_sections(self, mock_fetch_hist):
        def fake_hist(code: str, start_date: str, end_date: str):
            mapping = {
                ("159633", "20260401", "20260406"): [100, 109],
                ("159633", "20260401", "20260421"): [100, 112],
                ("512480", "20260401", "20260406"): [100, 105],
                ("512480", "20260401", "20260421"): [100, 111],
                ("510300", "20260401", "20260406"): [100, 101],
                ("510300", "20260401", "20260421"): [100, 103],
                ("159915", "20260401", "20260406"): [100, 102],
                ("159915", "20260401", "20260421"): [100, 104],
            }
            prices = mapping.get((code, start_date, end_date))
            if not prices:
                return pd.DataFrame()
            return pd.DataFrame(
                {
                    "date": pd.to_datetime([start_date, end_date]),
                    "close": prices,
                }
            )

        mock_fetch_hist.side_effect = fake_hist

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports_dir = root / "data" / "daily_reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            for day in range(1, 23):
                date_str = f"202604{day:02d}"
                date_text = f"2026-04-{day:02d}"
                _write_report(reports_dir, date_str, _make_sample_report(date_text))

            store = ReportStore(root)
            result = build_etf_sector_review(store, limit_reports=30)

        self.assertIn("summary", result)
        self.assertIn("monthly_stats", result)
        self.assertIn("confidence_stats", result)
        self.assertIn("weekly_summary", result)
        self.assertTrue(result["monthly_stats"]["cards"])
        self.assertEqual(len(result["confidence_stats"]["buckets"]), 3)
        self.assertTrue(result["weekly_summary"]["bullets"])

        first_item = result["items"][0]
        self.assertIn("human_summary", first_item)
        self.assertIn("reason_summary", first_item)
        self.assertIn("confidence_bucket_label", first_item)

        outcome5 = next(outcome for outcome in first_item["outcomes"] if outcome["horizon"] == 5)
        self.assertIn("status_cn", outcome5)
        self.assertIn("review_sentence", outcome5)
        self.assertIsInstance(outcome5["error_tags"], list)

        confidence_labels = [bucket["label"] for bucket in result["confidence_stats"]["buckets"]]
        self.assertEqual(confidence_labels, ["高置信", "中置信", "低置信"])

    @patch("ah_recommendation_system.backend.review.review_service.fetch_etf_hist_em")
    def test_build_review_classifies_mapping_and_market_data_gaps(self, mock_fetch_hist):
        def fake_hist(code: str, start_date: str, end_date: str):
            if code == "510300":
                return pd.DataFrame(
                    {
                        "date": pd.to_datetime([start_date, end_date]),
                        "close": [100, 101],
                    }
                )
            return pd.DataFrame()

        mock_fetch_hist.side_effect = fake_hist

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports_dir = root / "data" / "daily_reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            base_report = {
                "etf_sector": {
                    "generated_at": "2026-04-01 10:00:00",
                    "potential_breakouts": [
                        {
                            "theme": "无映射主题",
                            "confidence": 0.6,
                            "score": 60,
                            "reasons": ["主题升温"],
                            "related_etfs": [],
                        }
                    ],
                    "confirmed_leaders": [],
                    "crowded_risks": [],
                    "etf_trend": {
                        "recommendations": [
                            {
                                "code": "159915",
                                "name": "创业板ETF",
                                "recommendation": "优先关注",
                                "trend_score": 75,
                                "reasons": ["趋势修复"],
                            }
                        ]
                    },
                }
            }

            for day in range(1, 8):
                date_str = f"202604{day:02d}"
                _write_report(reports_dir, date_str, base_report)

            store = ReportStore(root)
            result = build_etf_sector_review(store, limit_reports=10)

        theme_item = next(
            item
            for item in result["items"]
            if item["entity_name"] == "无映射主题" and item["report_date"] == "20260401"
        )
        etf_item = next(
            item
            for item in result["items"]
            if item["entity_code"] == "159915" and item["report_date"] == "20260401"
        )

        theme_outcome = next(outcome for outcome in theme_item["outcomes"] if outcome["horizon"] == 5)
        etf_outcome = next(outcome for outcome in etf_item["outcomes"] if outcome["horizon"] == 5)

        self.assertEqual(theme_outcome["status"], "pending")
        self.assertEqual(theme_outcome["error_tags"][0]["label"], "缺少ETF映射")
        self.assertEqual(etf_outcome["status"], "pending")
        self.assertEqual(etf_outcome["error_tags"][0]["label"], "行情缺口")


if __name__ == "__main__":
    unittest.main()
