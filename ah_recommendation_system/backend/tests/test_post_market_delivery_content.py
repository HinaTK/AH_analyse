import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card, push_to_feishu
from ah_recommendation_system.backend.stock_recommend.post_market import build_post_market_review
from ah_recommendation_system.backend.stock_recommend.report_builder import save_review_report


def sample_review():
    return build_post_market_review(
        {"as_of": "2026-09-11", "picks": [{"code": "002011", "name": "盾安环境"}],
         "directions": {"current_attack": [{"direction": "银行"}],
                        "medium_term": [{"direction": "银行"}],
                        "avoid_or_exit": [{"direction": "A股全市场宽度"}]}},
        observations={"002011": {"close_price": 13.29, "close_date": "2026-09-11",
                                "previous_close": 13.14, "previous_close_date": "2026-09-10",
                                "reference_price": 13.88, "reference_date": None,
                                "reference_source": "premarket_candidate_snapshot",
                                "daily_return_pct": 1.142, "reference_return_pct": None,
                                "data_status": "available"}},
        direction_outcomes={"银行": {"status": "failed", "correction": "downgrade",
                                   "evidence": "银行收盘涨跌幅 -1.09%（来源：ths）"}},
    )


class TestPostMarketDeliveryContent(unittest.TestCase):
    def test_real_card_and_saved_markdown_are_readable_chinese(self):
        report = sample_review()
        payload = json.loads(json.dumps(build_card(report), ensure_ascii=False).encode("utf-8"))
        visible = "\n".join(e.get("text", {}).get("content", "") for e in payload["card"]["elements"])
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_review_report(report, Path(tmp))
            markdown = Path(paths["md_path"]).read_text(encoding="utf-8")
        for content in (visible, markdown):
            with self.subTest(content=content):
                self.assertNotRegex(content, r"\?{2,}|\ufffd|\b(?:failed|pending|confirm|downgrade)\b")
                self.assertNotIn("premarket_candidate_snapshot", content)
                self.assertNotIn("数据不足", content)
                self.assertIn("时点未核验", content)
                self.assertIn("不计算相对收益", content)
                self.assertIn("单日行业涨跌不足以验证", content)
                self.assertIn("上涨/下跌家数", content)
                self.assertIn("当日走弱", content)

    def test_corrupt_direction_text_is_blocked_before_network(self):
        for field in ("review_status", "correction", "evidence"):
            report = sample_review()
            report["direction_review"][0][field] = "???"
            with self.subTest(field=field), patch(
                "ah_recommendation_system.backend.stock_recommend.feishu_pusher.requests.post"
            ) as post:
                result = push_to_feishu(report, webhook="https://example.invalid/hook", secret="")
                self.assertFalse(result["ok"])
                self.assertEqual(result.get("reason"), "post_market_content_check_failed")
                self.assertFalse(result.get("content_audit", {}).get("passed", True))
                post.assert_not_called()

    def test_actual_outgoing_json_is_checked_and_hash_matches(self):
        report = sample_review()
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0}
        with patch("ah_recommendation_system.backend.stock_recommend.feishu_pusher.requests.post",
                   return_value=response) as post:
            result = push_to_feishu(report, webhook="https://example.invalid/hook", secret="")
        outgoing = post.call_args.kwargs["json"]
        encoded = json.dumps(outgoing, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(result["payload_hash"], hashlib.sha256(encoded).hexdigest())
        self.assertTrue(result.get("content_audit", {}).get("passed", False))
        self.assertNotIn(b"???", encoded)

    def test_rendered_untranslated_status_is_blocked(self):
        report = sample_review()
        payload = build_card(report)
        payload["card"]["elements"][0]["text"]["content"] = "review failed pending confirm"
        with patch("ah_recommendation_system.backend.stock_recommend.feishu_pusher.build_card", return_value=payload), patch(
            "ah_recommendation_system.backend.stock_recommend.feishu_pusher.requests.post"
        ) as post:
            result = push_to_feishu(report, webhook="https://example.invalid/hook", secret="")
        self.assertFalse(result["ok"])
        post.assert_not_called()
