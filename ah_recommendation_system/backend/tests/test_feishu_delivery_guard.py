"""Guards for the Feishu stock_recommend push path only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _live_report(**overrides):
    report = {
        "schema_version": "decision-report-v2",
        "type": "stock_recommend_pre_market",
        "as_of": "2026-09-22",
        "run": {"run_id": "r1", "session": "pre_market", "status": "passed", "trade_date": "2026-09-22"},
        "coverage": {"mode": "full_market", "source": "previous_close", "quote_basis": "previous_close"},
        "quality_gate": {"passed": True, "blocking_reasons": []},
        "picks": [
            {
                "code": "002246",
                "name": "北化股份",
                "action": "WATCH",
                "trigger": "放量站上前高",
                "invalidation": "收盘跌破20日均线",
                "buy_zone": "23.00-23.50",
                "stop_loss": "21.80",
                "target": "26.00",
                "holding_days": "5-10",
                "confidence": 0.72,
                "rationale": "规则入选",
            }
        ],
        "etf_picks": [],
        "market": {"label": "震荡等待确认", "regime": "balanced", "status": "需确认"},
        "directions": {
            "current_attack": [{"direction": "高端制造", "action": "观察", "trigger": "板块不转弱", "invalidation": "相对强度转弱"}],
            "medium_term": [],
            "avoid_or_exit": [],
        },
    }
    report.update(overrides)
    return report


class FeishuDeliveryGuardTests(unittest.TestCase):
    def test_quality_failure_does_not_call_feishu_even_with_force(self):
        from ah_recommendation_system.backend.stock_recommend.run import _deliver_report

        report = _live_report(
            run={"run_id": "bad", "session": "pre_market", "status": "failed", "trade_date": "2026-09-22"},
            quality_gate={"passed": False, "blocking_reasons": ["核心行情不可用"]},
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ah_recommendation_system.backend.stock_recommend.run.push_to_feishu"
        ) as push:
            result = _deliver_report(report, ledger_path=Path(tmp) / "delivery.json", force=True)

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "quality_gate_failed")
        self.assertEqual(push.call_count, 0)
        self.assertFalse(report["delivery"]["accepted"])

    def test_post_market_error_review_is_not_pushed(self):
        from ah_recommendation_system.backend.stock_recommend.run import run_post_market

        with tempfile.TemporaryDirectory() as tmp:
            latest = Path(tmp) / "latest.json"
            latest.write_text(json.dumps({"type": "stock_recommend_pre_market", "as_of": "2026-09-01"}), encoding="utf-8")
            with patch("ah_recommendation_system.backend.stock_recommend.run._backend_root", return_value=Path(tmp)), patch(
                "ah_recommendation_system.backend.stock_recommend.run._deliver_report"
            ) as deliver, patch(
                "ah_recommendation_system.backend.stock_recommend.run.push_to_wechat"
            ) as wechat, patch(
                "ah_recommendation_system.backend.stock_recommend.run.save_review_report",
                return_value={"json_path": str(Path(tmp) / "review.json")},
            ):
                result = run_post_market(push=True, report_path=latest, expected_as_of="2026-09-22")

        self.assertFalse(result["ok"])
        deliver.assert_not_called()
        wechat.assert_not_called()

    def test_mock_report_is_not_sent_to_wechat(self):
        from ah_recommendation_system.backend.stock_recommend.wechat_pusher import push_to_wechat

        with patch("ah_recommendation_system.backend.stock_recommend.wechat_pusher.requests.post") as post, patch.dict(
            "os.environ", {"AH_WECHAT_WEBHOOK": "https://example.invalid/wechat"}, clear=False
        ):
            result = push_to_wechat(_live_report(coverage={"mode": "mock_sample", "source": "mock"}))

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "mock_delivery_blocked")
        post.assert_not_called()

    def test_evening_pre_market_does_not_force_push(self):
        from ah_recommendation_system.backend.scheduler.daily_job import main

        with patch("sys.argv", ["daily_job.py", "--mode", "evening_pre_market"]), patch(
            "ah_recommendation_system.backend.scheduler.daily_job.run_pipeline",
            return_value={"ok": True, "push": {"ok": True}},
        ) as pipeline:
            exit_code = main()

        self.assertEqual(exit_code, 0)
        kwargs = pipeline.call_args.kwargs
        self.assertTrue(kwargs["push"])
        self.assertFalse(kwargs["force_push"])
        self.assertTrue(kwargs["prefer_previous_close"])
        self.assertTrue(kwargs["require_previous_close"])

    def test_premarket_card_is_watch_decision_not_buy_ticket(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        rendered = json.dumps(build_card(_live_report()), ensure_ascii=False)
        self.assertIn("触发", rendered)
        self.assertIn("放量站上前高", rendered)
        self.assertIn("收盘跌破20日均线", rendered)
        self.assertIn("北化股份", rendered)
        self.assertNotIn("买入 23.00-23.50", rendered)
        self.assertNotIn("止损 21.80", rendered)
        self.assertNotIn("目标 26.00", rendered)
        self.assertNotIn("持有 5-10", rendered)
        self.assertNotIn("信心 0.72", rendered)

    def test_quality_failure_sends_alert_not_formal_recommendation(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import push_failure_alert

        report = _live_report(
            run={"run_id": "bad", "session": "pre_market", "status": "failed", "trade_date": "2026-09-22"},
            quality_gate={"passed": False, "blocking_reasons": ["候选历史行情完整率低于80%"]},
            picks=[],
        )
        with patch("ah_recommendation_system.backend.stock_recommend.feishu_pusher.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"code": 0}
            result = push_failure_alert(report, webhook="https://open.feishu.cn/open-apis/bot/v2/hook/test")

        self.assertTrue(result["ok"])
        payload = post.call_args.kwargs["json"]
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertIn("任务异常", rendered)
        self.assertIn("候选历史行情完整率低于80%", rendered)
        self.assertNotIn("北化股份", rendered)
        self.assertNotIn("买入 23.00-23.50", rendered)

    def test_collect_failure_skips_rule_scan(self):
        from ah_recommendation_system.backend.stock_recommend.run import run_pipeline

        with patch("ah_recommendation_system.backend.stock_recommend.run.collect_all") as collect, patch(
            "ah_recommendation_system.backend.stock_recommend.run.load_previous_close_snapshot",
            return_value=[],
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.build_candidates"
        ) as build_cands, patch(
            "ah_recommendation_system.backend.stock_recommend.run.save_report",
            return_value={},
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.push_failure_alert",
            return_value={"ok": True, "reason": "alert_sent"},
        ):
            snap = type("Snap", (), {})()
            snap.date = "2026-09-22"
            snap.errors = ["previous_close_snapshot_missing"]
            snap.fundamental = {"rows": [], "source": None}
            snap.capital = {"rows": []}
            snap.events = {}
            collect.return_value = snap
            result = run_pipeline(mock=False, push=True, prefer_previous_close=True, require_previous_close=True)

        build_cands.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["push"]["reason"], "alert_sent")


if __name__ == "__main__":
    unittest.main()
