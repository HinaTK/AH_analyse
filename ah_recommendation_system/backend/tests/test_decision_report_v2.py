import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestDecisionReportV2(unittest.TestCase):
    def test_market_decision_always_provides_actionable_direction_layers(self):
        from ah_recommendation_system.backend.stock_recommend.decision_engine import (
            build_market_decision,
        )

        decision = build_market_decision(
            as_of="2026-09-09",
            market_signals=[
                {
                    "theme": "半导体",
                    "change_pct": 2.4,
                    "advance_count": 31,
                    "total_count": 40,
                    "turnover_yi": 420,
                    "source": "industry_board",
                }
            ],
            hotspots=[
                {
                    "theme": "半导体设备",
                    "status": "confirmed",
                    "industries": ["半导体"],
                    "evidence_refs": ["official-1", "market-1"],
                }
            ],
            coverage={"mode": "full_market", "ratio": 0.93},
        )

        self.assertIn(decision["regime"], {"offense", "balanced", "defense"})
        self.assertIn(decision["status"], {"有效", "需确认", "降级观察", "已失效"})
        self.assertTrue(decision["directions"]["current_attack"])
        self.assertTrue(decision["directions"]["medium_term"])
        self.assertIn("early_positioning", decision["directions"])
        self.assertIn("avoid_or_exit", decision["directions"])
        self.assertTrue(decision["invalidation"])

    def test_news_only_hotspots_cannot_become_effective_current_attack(self):
        from ah_recommendation_system.backend.stock_recommend.decision_engine import build_market_decision

        decision = build_market_decision(
            as_of="2026-09-09",
            market_signals=[],
            hotspots=[
                {"theme": f"新闻主题{i}", "status": "confirmed", "evidence_refs": [f"a{i}", f"b{i}"]}
                for i in range(4)
            ],
            coverage={"mode": "full_market", "ratio": 0.95},
        )
        current = decision["directions"]["current_attack"][0]
        self.assertNotEqual(current["status"], "有效")
        self.assertIn("价格", current["action"])

    def test_market_breadth_is_environment_evidence_not_an_industry_direction(self):
        from ah_recommendation_system.backend.stock_recommend.decision_engine import build_market_decision

        decision = build_market_decision(
            as_of="2026-09-09",
            market_signals=[{
                "theme": "A股全市场宽度",
                "change_pct": 1.2,
                "advance_count": 4000,
                "total_count": 5200,
                "source": "a_share_full_snapshot",
            }],
            coverage={"mode": "full_market", "ratio": 0.95},
        )
        self.assertNotEqual(
            decision["directions"]["current_attack"][0]["direction"],
            "A股全市场宽度",
        )

    def test_report_v2_keeps_explicit_empty_etfs_and_has_quality_gate(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={
                "as_of": "2026-09-09",
                "picks": [],
                "etf_picks": [],
                "summary": "震荡环境，等待价格确认。",
            },
            candidates=[],
            coverage={
                "mode": "full_market",
                "universe_size": 5500,
                "scanned_count": 5200,
                "fresh_data_available": True,
            },
            decision={
                "score": 55,
                "regime": "balanced",
                "label": "震荡",
                "status": "需确认",
                "evidence": [{"statement": "全市场覆盖充足", "source": "scanner"}],
                "invalidation": ["成交与市场宽度同时转弱"],
                "directions": {
                    "current_attack": [{"direction": "无确认主线", "action": "等待触发"}],
                    "medium_term": [{"direction": "高景气产业", "action": "等待确认"}],
                    "early_positioning": [],
                    "avoid_or_exit": [{"direction": "利好不涨", "action": "回避"}],
                },
            },
            cross_market={"status": "ok", "risk_level": "normal", "markets": {"united_states": []}},
        )

        self.assertEqual(report["schema_version"], "decision-report-v2")
        self.assertEqual(report["recommendations"]["etfs"], [])
        self.assertEqual(report["etf_picks"], [])
        self.assertNotEqual(report["etf_selection"]["selection_mode"], "default_mock")
        self.assertTrue(report["quality_gate"]["passed"])
        self.assertEqual(report["run"]["status"], "passed")
        self.assertEqual(report["cross_market"]["risk_level"], "normal")

    def test_stale_only_report_is_blocked_and_renders_alert_card(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"as_of": "2026-09-09", "picks": [], "etf_picks": []},
            candidates=[],
            snapshot_errors=["using_stale_last_good_snapshot"],
            coverage={
                "mode": "limited_sample",
                "source": "last_good_snapshot",
                "universe_size": 5000,
                "scanned_count": 5000,
                "fresh_data_available": False,
                "stale": True,
            },
        )

        rendered = json.dumps(build_card(report), ensure_ascii=False)
        self.assertFalse(report["quality_gate"]["passed"])
        self.assertEqual(report["run"]["status"], "failed")
        self.assertIn("任务异常", rendered)
        self.assertIn("仅有旧缓存", rendered)
        self.assertNotIn("暂无推荐", rendered)

    def test_formal_stock_without_traceable_evidence_is_blocked(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={
                "as_of": "2026-09-09",
                "picks": [{"code": "000001", "name": "测试股", "rationale": "看起来不错", "evidence": []}],
                "etf_picks": [],
            },
            candidates=[],
            coverage={
                "mode": "full_market",
                "universe_size": 5500,
                "scanned_count": 5300,
                "fresh_data_available": True,
            },
        )
        self.assertFalse(report["quality_gate"]["passed"])
        self.assertIn("证据", "".join(report["quality_gate"]["blocking_reasons"]))

    def test_low_candidate_history_completeness_blocks_normal_report(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"as_of": "2026-09-09", "picks": [], "etf_picks": []},
            candidates=[],
            coverage={
                "mode": "full_market",
                "universe_size": 5500,
                "scanned_count": 5300,
                "candidate_count": 30,
                "history_count": 20,
                "fresh_data_available": True,
            },
        )
        self.assertFalse(report["quality_gate"]["passed"])
        self.assertIn("历史行情完整率", "".join(report["quality_gate"]["blocking_reasons"]))

    def test_llm_failure_is_visible_as_non_blocking_quality_warning(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"as_of": "2026-09-09", "picks": [], "etf_picks": []},
            candidates=[],
            coverage={
                "mode": "full_market",
                "universe_size": 100,
                "scanned_count": 100,
                "fresh_data_available": True,
            },
            llm_context={
                "llm": {
                    "hotspot_status": "failed",
                    "hotspot_error": "no_valid_hotspots",
                    "event_status": "used",
                }
            },
        )

        self.assertTrue(report["quality_gate"]["passed"])
        self.assertIn("LLM热点分析失败", "".join(report["quality_gate"]["warnings"]))

    def test_provider_fallback_errors_are_visible_as_non_blocking_quality_warning(self):
        from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality

        quality = evaluate_report_quality({
            "coverage": {
                "mode": "full_market",
                "ratio": 1.0,
                "fresh_data_available": True,
                "circuit_breakers": ["hithink_financial_api:RuntimeError", "akshare:ConnectionError"],
            },
            "market": {"regime": "balanced", "status": "需确认"},
            "directions": {
                "current_attack": [],
                "medium_term": [],
                "early_positioning": [],
                "avoid_or_exit": [],
            },
            "picks": [],
            "etf_picks": [],
        })

        self.assertTrue(quality["passed"])
        self.assertIn("部分数据源异常", "".join(quality["warnings"]))
        self.assertIn("兜底", "".join(quality["warnings"]))

    def test_unknown_market_regime_cannot_pass_quality_gate(self):
        """Catches placeholder market output being treated as usable evidence."""
        from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality

        quality = evaluate_report_quality({
            "coverage": {"mode": "full_market", "ratio": 1.0, "fresh_data_available": True},
            "market": {
                "regime": "unknown",
                "status": "unavailable",
                "regime_evidence": {"status": "unavailable"},
            },
            "directions": {
                "current_attack": [], "medium_term": [],
                "early_positioning": [], "avoid_or_exit": [],
            },
            "picks": [],
            "etf_picks": [],
        })

        self.assertFalse(quality["passed"])
        self.assertIn("缺少可用市场姿态证据", quality["blocking_reasons"])

    def test_focused_fallback_does_not_block_on_degraded_hithink(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"picks": [], "etf_picks": []},
            candidates=[],
            coverage={
                "mode": "focused_fallback",
                "source": "focused_tencent_quotes",
                "fresh_data_available": True,
                "universe_size": 110,
                "scanned_count": 110,
                "provider_health": {"hithink_financial_api": "degraded"},
            },
            decision={"regime": "balanced", "status": "需确认", "label": "震荡等待确认"},
        )

        self.assertIn("hithink_financial_api", report["degraded_sections"])
        self.assertEqual(report["blocking_sections"], [])
        self.assertNotEqual(report.get("data_status"), "failed")

    def test_only_verified_observation_pool_is_rendered_in_feishu(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        report = {
            "schema_version": "decision-report-v2",
            "as_of": "2026-09-09",
            "run": {"status": "passed", "session": "pre_market"},
            "quality_gate": {"passed": True, "blocking_reasons": []},
            "market": {"label": "震荡", "status": "需确认", "regime": "balanced"},
            "directions": {
                "current_attack": [],
                "medium_term": [],
                "early_positioning": [],
                "avoid_or_exit": [],
            },
            "recommendations": {"stocks": [], "etfs": []},
            "cross_market": {
                "status": "ok",
                "risk_level": "normal",
                "observed_at": "2026-09-09 08:20:00",
                "markets": {
                    "united_states": [{"name": "纳斯达克", "change_pct": 1.1}],
                    "hong_kong": [{"name": "恒生指数", "change_pct": 0.5}],
                },
            },
            "picks": [],
            "etf_picks": [],
            "observation_pool": [{
                "code": "000001",
                "name": "待确认观察股",
                "inclusion_reason": "趋势保持完整",
                "pending_confirmation": "等待成交放大",
                "trigger": "放量站上前高",
                "invalidation": "收盘跌破支撑",
                "price_as_of": "2026-09-08",
            }],
        }
        unverified = json.dumps(build_card(report), ensure_ascii=False)
        self.assertNotIn("待确认观察股", unverified)
        self.assertIn("本次无经核验观察名单", unverified)

        report["observation_pool_verified"] = True
        verified = json.dumps(build_card(report), ensure_ascii=False)
        self.assertIn("待确认观察股", verified)
        self.assertIn("待确认个股观察（非正式推荐）", verified)
        self.assertIn("等待成交放大", verified)

    def test_quality_gate_rejects_more_than_five_stocks_or_three_etfs(self):
        from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality

        report = {
            "coverage": {"mode": "full_market", "ratio": 1.0, "fresh_data_available": True},
            "market": {"regime": "balanced", "status": "需确认"},
            "directions": {
                "current_attack": [],
                "medium_term": [],
                "early_positioning": [],
                "avoid_or_exit": [],
            },
            "picks": [
                {"code": f"00000{i}", "rationale": "有依据", "evidence": [{"statement": "证据"}]}
                for i in range(6)
            ],
            "etf_picks": [
                {"code": f"51030{i}", "score": 70, "factor_scores": {"trend": 70}}
                for i in range(4)
            ],
        }

        quality = evaluate_report_quality(report)

        self.assertFalse(quality["passed"])
        self.assertIn("正式股票超过5只", quality["blocking_reasons"])
        self.assertIn("正式ETF超过3只", quality["blocking_reasons"])

    def test_unified_card_renders_market_posture_and_all_direction_layers(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        card = build_card(
            {
                "schema_version": "decision-report-v2",
                "as_of": "2026-09-09",
                "run": {"status": "passed", "session": "pre_market"},
                "quality_gate": {"passed": True, "blocking_reasons": []},
                "market": {
                    "score": 68,
                    "label": "结构性进攻",
                    "status": "有效",
                    "regime": "offense",
                    "invalidation": ["指数与主线同步转弱"],
                },
                "directions": {
                    "current_attack": [{"direction": "半导体", "action": "回踩确认", "status": "有效", "trigger": "放量", "invalidation": "跌破支撑"}],
                    "medium_term": [{"direction": "先进制造", "action": "分批观察", "status": "需确认", "trigger": "订单改善", "invalidation": "订单证伪"}],
                    "early_positioning": [{"direction": "创新药", "action": "小仓试错", "status": "需确认", "trial_position_limit": "目标方向仓位10%-30%", "trigger": "右侧转强", "invalidation": "新低"}],
                    "avoid_or_exit": [{"direction": "利好不涨", "action": "回避", "status": "有效", "trigger": "重新转强再分析", "invalidation": "结构修复"}],
                },
                "recommendations": {"stocks": [], "etfs": []},
                "cross_market": {
                    "status": "ok",
                    "risk_level": "normal",
                    "observed_at": "2026-09-09 08:20:00",
                    "markets": {
                        "united_states": [{"name": "纳斯达克", "change_pct": 1.1}],
                        "hong_kong": [{"name": "恒生指数", "change_pct": 0.5}],
                    },
                },
                "picks": [],
                "etf_picks": [],
                "data_status": "ok",
                "coverage": {"label": "全市场观察池"},
            }
        )
        rendered = json.dumps(card, ensure_ascii=False)
        for expected in ("结构性进攻", "跨市场", "纳斯达克", "恒生指数", "当前主攻", "半导体", "未来1~3个月", "先进制造", "提前布局", "创新药", "回避/撤退"):
            self.assertIn(expected, rendered)

    def test_successful_feishu_push_returns_payload_hash(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import push_to_feishu

        class Response:
            status_code = 200
            text = '{"code":0}'

            @staticmethod
            def json():
                return {"code": 0}

        with patch("ah_recommendation_system.backend.stock_recommend.feishu_pusher.requests.post", return_value=Response()):
            result = push_to_feishu(
                {"as_of": "2026-09-09", "picks": [], "etf_picks": [], "data_status": "ok"},
                webhook="https://open.feishu.cn/open-apis/bot/v2/hook/test",
                retries=1,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["payload_hash"]), 64)

    def test_market_decision_contains_explicit_position_guidance(self):
        from ah_recommendation_system.backend.stock_recommend.decision_engine import build_market_decision

        decision = build_market_decision(as_of="2026-09-10", market_signals=[], hotspots=[], coverage={"ratio": 1.0})
        self.assertIn("position_guidance", decision)
        self.assertRegex(decision["position_guidance"], r"\d+%.*\d+%")

    def test_cross_market_report_contains_actionable_conclusion(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"as_of": "2026-09-10", "picks": [], "etf_picks": []},
            candidates=[],
            cross_market={
                "status": "ok",
                "risk_level": "normal",
                "markets": {"united_states": [{"name": "纳斯达克", "change_pct": 1.2}]},
            },
        )
        self.assertTrue(report["cross_market"].get("conclusion"))
        self.assertIn("A股", report["cross_market"]["conclusion"])

    def test_ambiguous_delivery_blocks_automatic_same_session_retry(self):
        from ah_recommendation_system.backend.stock_recommend.delivery_guard import (
            record_delivery,
            should_deliver,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "delivery.json"
            record_delivery(
                ledger,
                trade_date="2026-09-09",
                session="pre_market",
                run_id="run-1",
                payload_hash="abc",
                accepted=False,
                ambiguous=True,
            )

            self.assertFalse(should_deliver(ledger, trade_date="2026-09-09", session="pre_market"))
            self.assertTrue(
                should_deliver(ledger, trade_date="2026-09-09", session="pre_market", force=True)
            )

    def test_post_market_card_has_review_title_and_no_premarket_hotspot_filler(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        card = build_card(
            {
                "type": "stock_recommend_post_market",
                "as_of": "2026-09-09",
                "summary": {"pick_count": 1, "completed_count": 1, "hit_count": 1},
                "items": [{"code": "000001", "name": "测试股", "status": "hit", "return_pct": 1.2, "correction": "keep"}],
                "closing_market": {
                    "source": "ths_industry_close",
                    "top_gainers": [{"name": "半导体", "chg_pct": 2.1}],
                    "top_losers": [{"name": "煤炭", "chg_pct": -1.3}],
                },
            }
        )
        rendered = json.dumps(card, ensure_ascii=False)
        self.assertIn("盘后复盘", rendered)
        self.assertIn("收盘最强", rendered)
        self.assertIn("半导体 +2.10%", rendered)
        self.assertIn("收盘最弱", rendered)
        self.assertIn("煤炭 -1.30%", rendered)
        self.assertNotIn("暂无已验证市场热点", rendered)

    def test_post_market_review_carries_direction_corrections(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
        from ah_recommendation_system.backend.stock_recommend.post_market import build_post_market_review

        review = build_post_market_review(
            {
                "as_of": "2026-09-09",
                "picks": [],
                "market": {"regime": "offense", "label": "结构性进攻", "status": "有效"},
                "directions": {
                    "current_attack": [{"direction": "半导体", "status": "有效"}],
                    "medium_term": [{"direction": "先进制造", "status": "需确认"}],
                    "early_positioning": [],
                    "avoid_or_exit": [{"direction": "利好不涨", "status": "有效"}],
                },
            },
            direction_outcomes={"半导体": {"status": "confirmed", "evidence": "收盘放量且宽度扩散"}},
        )
        rendered = json.dumps(build_card(review), ensure_ascii=False)
        self.assertEqual(review["schema_version"], "decision-report-v2")
        self.assertEqual(review["run"]["session"], "post_market")
        self.assertEqual(review["direction_review"][0]["review_status"], "confirmed")
        self.assertIn("方向复盘", rendered)
        self.assertIn("半导体", rendered)
        self.assertIn("收盘放量且宽度扩散", rendered)

    def test_post_market_markdown_persists_direction_review(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import save_review_report

        review = {
            "as_of": "2026-09-09",
            "summary": {"pick_count": 0, "completed_count": 0, "hit_count": 0},
            "items": [],
            "direction_review": [{
                "layer": "current_attack",
                "direction": "semiconductor",
                "review_status": "confirmed",
                "evidence": "close-price breadth confirmed",
                "correction": "keep",
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_review_report(review, Path(tmp))
            markdown = Path(paths["md_path"]).read_text(encoding="utf-8")

        self.assertIn("方向复盘", markdown)
        self.assertIn("semiconductor", markdown)
        self.assertIn("close-price breadth confirmed", markdown)

    def test_markdown_contains_decision_layers_and_research_audit(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import (
            build_markdown,
            build_report,
        )

        report = build_report(
            selection={"as_of": "2026-09-09", "picks": [], "etf_picks": []},
            candidates=[],
            coverage={
                "mode": "full_market",
                "universe_size": 5500,
                "scanned_count": 5300,
                "fresh_data_available": True,
                "provider_health": {"news": {"official": "healthy"}},
            },
            decision={
                "score": 66,
                "regime": "offense",
                "label": "结构性进攻",
                "status": "有效",
                "evidence": [],
                "invalidation": ["量价转弱"],
                "directions": {
                    "current_attack": [{"direction": "半导体", "action": "回踩确认", "status": "有效", "trigger": "放量", "invalidation": "破位"}],
                    "medium_term": [{"direction": "先进制造", "action": "分批观察", "status": "需确认", "trigger": "订单", "invalidation": "证伪"}],
                    "early_positioning": [],
                    "avoid_or_exit": [{"direction": "利好不涨", "action": "回避", "status": "有效", "trigger": "修复", "invalidation": "转强"}],
                },
            },
        )
        markdown = build_markdown(report)
        for expected in ("大盘环境判断", "结构性进攻", "提前布局判断", "半导体", "未来1~3个月", "搜索与数据通道审计", "X早期信号已按用户偏好禁用"):
            self.assertIn(expected, markdown)

    def test_cross_market_collector_normalizes_inputs_and_flags_risk(self):
        import pandas as pd

        from ah_recommendation_system.backend.stock_recommend.cross_market import collect_cross_market

        class AkModule:
            @staticmethod
            def index_global_spot_em():
                return pd.DataFrame([
                    {"名称": "纳斯达克", "最新价": 18000, "涨跌幅": -2.6},
                    {"名称": "标普500", "最新价": 5200, "涨跌幅": -2.1},
                ])

            @staticmethod
            def stock_hk_index_spot_em():
                return pd.DataFrame([{"名称": "恒生指数", "最新价": 22000, "涨跌幅": 1.2}])

            @staticmethod
            def forex_spot_em():
                return pd.DataFrame([{"名称": "美元兑人民币", "最新价": 7.15, "涨跌幅": 0.3}])

            @staticmethod
            def bond_zh_us_rate():
                return pd.DataFrame([{"日期": "2026-09-08", "美国国债收益率10年": 4.35}])

        result = collect_cross_market(ak_module=AkModule())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["risk_level"], "high")
        self.assertEqual(result["markets"]["hong_kong"][0]["name"], "恒生指数")
        self.assertTrue(result["observed_at"])

    def test_delivery_ledger_prevents_duplicate_successful_push(self):
        from ah_recommendation_system.backend.stock_recommend.delivery_guard import (
            record_delivery,
            should_deliver,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "delivery.json"
            self.assertTrue(should_deliver(ledger, trade_date="2026-09-09", session="pre_market"))
            record_delivery(
                ledger,
                trade_date="2026-09-09",
                session="pre_market",
                run_id="run-1",
                payload_hash="abc",
                accepted=True,
            )
            self.assertFalse(should_deliver(ledger, trade_date="2026-09-09", session="pre_market"))
            self.assertTrue(should_deliver(ledger, trade_date="2026-09-09", session="pre_market", force=True))

    def test_windows_schedule_rejects_overlapping_instances(self):
        script = (
            Path(__file__).resolve().parents[3] / "tools" / "install_stock_recommend_tasks.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("-MultipleInstances IgnoreNew", script)
        self.assertIn("--mode pre_market --push", script)
        self.assertIn("--mode post_market --push", script)

    def test_delivery_orchestrator_records_hash_and_skips_duplicate(self):
        from ah_recommendation_system.backend.stock_recommend.run import _deliver_report

        report = {
            "as_of": "2026-09-09",
            "run": {"run_id": "r1", "session": "pre_market", "status": "passed"},
            "delivery": {"channel": "feishu", "payload_hash": "", "accepted": False},
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ah_recommendation_system.backend.stock_recommend.run.push_to_feishu",
            return_value={"ok": True, "payload_hash": "hash-1", "status": 200},
        ) as push:
            ledger = Path(tmp) / "delivery.json"
            first = _deliver_report(report, ledger_path=ledger)
            second = _deliver_report(report, ledger_path=ledger)

        self.assertTrue(first["ok"])
        self.assertEqual(first["payload_hash"], "hash-1")
        self.assertTrue(second["skipped"])
        self.assertEqual(push.call_count, 1)
        self.assertTrue(report["delivery"]["accepted"])

    def test_force_delivery_never_sends_mock_report_to_production_webhook(self):
        """Catches --force-push bypassing the mock/production boundary."""
        from ah_recommendation_system.backend.stock_recommend.run import _deliver_report

        report = {
            "as_of": "2026-09-14",
            "run": {"run_id": "mock-run", "session": "pre_market", "status": "passed"},
            "coverage": {"mode": "mock_sample", "source": "mock"},
            "quality_gate": {"passed": True, "blocking_reasons": []},
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ah_recommendation_system.backend.stock_recommend.run.push_to_feishu"
        ) as push:
            result = _deliver_report(report, ledger_path=Path(tmp) / "delivery.json", force=True)

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "mock_delivery_blocked")
        self.assertEqual(push.call_count, 0)
        self.assertFalse(report["delivery"]["accepted"])

    def test_duplicate_delivery_restores_success_audit_on_new_report_object(self):
        from ah_recommendation_system.backend.stock_recommend.delivery_guard import record_delivery
        from ah_recommendation_system.backend.stock_recommend.run import _deliver_report

        report = {
            "as_of": "2026-09-09",
            "run": {"run_id": "rerun", "session": "post_market", "status": "passed"},
            "delivery": {"channel": "feishu", "payload_hash": "", "accepted": False},
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ah_recommendation_system.backend.stock_recommend.run.push_to_feishu"
        ) as push:
            ledger = Path(tmp) / "delivery.json"
            record_delivery(
                ledger,
                trade_date="2026-09-09",
                session="post_market",
                run_id="first-run",
                payload_hash="existing-hash",
                accepted=True,
            )
            result = _deliver_report(report, ledger_path=ledger)

        self.assertTrue(result["skipped"])
        self.assertEqual(push.call_count, 0)
        self.assertTrue(report["delivery"]["accepted"])
        self.assertEqual(report["delivery"]["payload_hash"], "existing-hash")
        self.assertTrue(report["delivery"]["skipped"])

    def test_ambiguous_previous_delivery_is_not_reported_as_success(self):
        from ah_recommendation_system.backend.stock_recommend.delivery_guard import record_delivery
        from ah_recommendation_system.backend.stock_recommend.run import _deliver_report

        report = {
            "as_of": "2026-09-09",
            "run": {"run_id": "retry", "session": "pre_market", "status": "passed"},
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ah_recommendation_system.backend.stock_recommend.run.push_to_feishu"
        ) as push:
            ledger = Path(tmp) / "delivery.json"
            record_delivery(
                ledger,
                trade_date="2026-09-09",
                session="pre_market",
                run_id="first-run",
                payload_hash="ambiguous-hash",
                accepted=False,
                ambiguous=True,
            )
            result = _deliver_report(report, ledger_path=ledger)

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "previous_delivery_ambiguous")
        self.assertEqual(push.call_count, 0)
        self.assertTrue(report["delivery"]["ambiguous"])

    def test_failed_quality_delivery_does_not_block_same_session_retry(self):
        from ah_recommendation_system.backend.stock_recommend.delivery_guard import should_deliver
        from ah_recommendation_system.backend.stock_recommend.run import _deliver_report

        report = {
            "as_of": "2026-09-11",
            "run": {"run_id": "bad", "session": "pre_market", "status": "failed"},
            "quality_gate": {"passed": False, "blocking_reasons": ["候选估值字段大面积缺失，数据不完整，推荐结论受限"]},
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ah_recommendation_system.backend.stock_recommend.run.push_to_feishu",
            return_value={"ok": True, "payload_hash": "bad-hash", "status": 200},
        ) as push:
            ledger = Path(tmp) / "delivery.json"
            first = _deliver_report(report, ledger_path=ledger)
            can_retry = should_deliver(ledger, trade_date="2026-09-11", session="pre_market")

        self.assertTrue(first["ok"])
        self.assertEqual(push.call_count, 1)
        self.assertFalse(report["delivery"]["accepted"])
        self.assertTrue(can_retry)

    def test_previous_close_full_market_is_usable_pre_market_data(self):
        from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality

        quality = evaluate_report_quality({
            "coverage": {
                "mode": "full_market",
                "ratio": 1.0,
                "source": "previous_close",
                "fresh_data_available": True,
                "stale": False,
                "quote_basis": "previous_close",
            },
            "market": {
                "regime": "defense",
                "status": "available",
                "regime_evidence": {"status": "available"},
            },
            "directions": {
                "current_attack": [],
                "medium_term": [],
                "early_positioning": [],
                "avoid_or_exit": [],
            },
            "picks": [],
            "etf_picks": [],
        })
        self.assertTrue(quality["passed"])
        self.assertFalse(any("过期" in reason or "无法确认当日有效行情" in reason for reason in quality["blocking_reasons"]))

if __name__ == "__main__":
    unittest.main()
