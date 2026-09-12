import json
import unittest
from unittest.mock import patch

from ah_recommendation_system.backend.stock_recommend.card_content_audit import audit_pre_market_card
from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card, push_to_feishu


def report_fixture():
    return {
        "type": "stock_recommend_pre_market", "as_of": "2026-09-12",
        "summary": "模拟数据预览", "coverage": {"mode": "mock_sample"},
        "generated_at": "2026-09-12 16:52:38", "picks": [],
        "recommendation_contract": {
            "model_version": "recommendation-policy-v1", "candidate_count": 1,
            "decisions": [{"state": "等待触发"}], "verification_plan": [{}, {}, {}],
        },
    }


class TestFeishuPreviewEncoding(unittest.TestCase):
    def test_question_mark_corruption_is_blocked_before_http(self):
        report = report_fixture()
        report["summary"] = "MOCK ?????????????"
        with patch("ah_recommendation_system.backend.stock_recommend.feishu_pusher.requests.post") as post:
            result = push_to_feishu(report, webhook="https://example.invalid/webhook")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "pre_market_content_check_failed")
        post.assert_not_called()

    def test_replacement_character_in_visible_text_fails(self):
        report = report_fixture()
        report["summary"] = "模拟\ufffd预览"
        self.assertFalse(audit_pre_market_card(report, build_card(report))["passed"])

    def test_legitimate_question_and_url_query_are_allowed(self):
        report = report_fixture()
        report["summary"] = "等待确认? 查看 https://example.com/?a=1&b=2"
        self.assertTrue(audit_pre_market_card(report, build_card(report))["passed"])

    def test_utf8_preview_roundtrip_retains_chinese_and_mock_label(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_preview import build_preview_report
        original = report_fixture()
        preview = build_preview_report(original)
        card = json.loads(json.dumps(build_card(preview), ensure_ascii=False).encode("utf-8").decode("utf-8"))
        text = json.dumps(card, ensure_ascii=False)
        self.assertIn("模拟数据", text)
        self.assertIn("等待触发", text)
        self.assertIn("验证计划 3 条", text)
        self.assertIn("预览", card["card"]["header"]["title"]["content"])
        self.assertNotIn("???", text)
        self.assertTrue(audit_pre_market_card(preview, card)["passed"])
        self.assertEqual(original["summary"], "模拟数据预览")

