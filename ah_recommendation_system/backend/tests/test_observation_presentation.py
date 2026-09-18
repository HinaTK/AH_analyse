import json
import unittest


def _observation(code, name):
    return {
        "code": code,
        "name": name,
        "evidence": [{"statement": "近20日相对强度保持正值"}],
        "rejection_reasons": ["成交量尚未确认"],
        "hotspot_themes": ["高端制造"],
        "hotspot_match_level": "direct",
        "hotspot_evidence": [{"statement": "产业订单出现改善线索"}],
        "candidate_sources": ["full_market_scan"],
        "price_as_of": "2026-09-17",
        "inclusion_reason": "规则初筛与热点映射同时命中",
        "pending_confirmation": "等待成交额超过20日均值",
        "trigger": "放量站上前一交易日高点",
        "invalidation": "收盘跌破20日均线",
    }


def _report(**overrides):
    report = {
        "schema_version": "decision-report-v2",
        "type": "stock_recommend_pre_market",
        "as_of": "2026-09-18",
        "generated_at": "2026-09-18 08:06:00",
        "run": {"status": "passed", "session": "pre_market"},
        "quality_gate": {"passed": True, "blocking_reasons": []},
        "data_status": "ok",
        "coverage": {
            "mode": "full_market",
            "label": "昨收全市场观察池",
            "source": "previous_close",
            "quote_basis": "previous_close",
            "universe_size": 5500,
            "scanned_count": 5300,
            "fresh_data_available": True,
            "stale": False,
        },
        "market": {"regime": "balanced", "status": "需确认", "label": "震荡等待确认"},
        "directions": {},
        "cross_market": {},
        "market_hotspots": [],
        "picks": [],
        "etf_picks": [],
        "recommendations": {"stocks": [], "etfs": []},
        "observation_pool_verified": True,
        "observation_pool": [_observation("000001", "观察甲")],
        "empty_reason_code": "awaiting_confirmation",
        "empty_reason": "今日无正式个股推荐：候选仍待价格、成交或证据确认。",
        "selection_diagnostics": {
            "scan_as_of": "2026-09-18 08:05:00",
            "price_as_of": "2026-09-17",
            "coverage_mode": "full_market",
            "scanned_count": 5300,
            "candidate_count": 30,
            "evaluated_count": 30,
            "eligible_count": 1,
            "selected_count": 0,
            "observation_count": 1,
            "mapping_gaps": ["新能源设备行业映射不完整"],
            "rejection_summary": {"成交量尚未确认": 12},
        },
    }
    report.update(overrides)
    return report


class TestObservationPresentation(unittest.TestCase):
    def _rendered(self, report):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_markdown

        return build_markdown(report), json.dumps(build_card(report), ensure_ascii=False)

    def test_verified_pool_has_same_required_layers_in_markdown_and_card(self):
        markdown, card = self._rendered(_report())

        for expected in (
            "正式个股推荐",
            "候选仍待价格、成交或证据确认",
            "待确认个股观察（非正式推荐）",
            "观察甲 (000001)",
            "高端制造",
            "规则初筛与热点映射同时命中",
            "等待成交额超过20日均值",
            "放量站上前一交易日高点",
            "收盘跌破20日均线",
            "行情日：2026-09-17",
            "数据缺口 / 筛选概况",
            "规则种子 30",
            "实际评估 30",
            "新能源设备行业映射不完整",
            "盘中触发待确认",
        ):
            self.assertIn(expected, markdown)
            self.assertIn(expected, card)
        self.assertIn("非候选评估数", markdown)
        self.assertIn("非候选评估数", card)

    def test_unverified_or_failed_pool_never_leaks_names(self):
        unverified = _report(observation_pool_verified=False)
        failed = _report(
            data_status="failed",
            run={"status": "failed", "session": "pre_market"},
            quality_gate={"passed": False, "blocking_reasons": ["核心行情不可用"]},
        )

        for report in (unverified, failed):
            markdown, card = self._rendered(report)
            self.assertNotIn("观察甲", markdown)
            self.assertNotIn("观察甲", card)
            self.assertIn("本次无经核验观察名单", markdown)
            self.assertIn("本次无经核验观察名单", card)
        self.assertIn("数据不足", self._rendered(failed)[0])

    def test_observation_pool_is_capped_deduplicated_and_excludes_formal_pick(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import presentation_observations

        rows = [_observation("000001", "正式股")]
        rows += [_observation(f"00000{index}", f"观察{index}") for index in range(2, 9)]
        rows.append(_observation("000002", "观察2重复"))
        report = _report(
            picks=[{"code": "000001", "name": "正式股"}],
            recommendations={"stocks": [{"code": "000001", "name": "正式股"}], "etfs": []},
            observation_pool=rows,
        )

        visible = presentation_observations(report)
        self.assertEqual(len(visible), 6)
        self.assertNotIn("000001", [item["code"] for item in visible])
        self.assertEqual(len({item["code"] for item in visible}), 6)

        report["picks"][0]["code"] = 1
        report["recommendations"]["stocks"][0]["code"] = 1
        visible = presentation_observations(report)
        self.assertNotIn("000001", [item["code"] for item in visible])

    def test_missing_observation_fields_are_unknown_not_invented(self):
        report = _report(observation_pool=[{"code": "000777", "name": "字段缺失股"}])
        markdown, card = self._rendered(report)

        self.assertGreaterEqual(markdown.count("未知"), 6)
        self.assertGreaterEqual(card.count("未知"), 6)
        self.assertNotIn("充分验证", markdown)
        self.assertNotIn("充分验证", card)

    def test_screened_out_requires_complete_diagnostics(self):
        report = _report(
            observation_pool_verified=False,
            observation_pool=[],
            empty_reason_code="screened_out",
            empty_reason="数据覆盖与评估充分，但没有候选通过正式门槛。",
            selection_diagnostics={
                "coverage_mode": "full_market", "scanned_count": 5300,
                "candidate_count": 30, "evaluated_count": 30,
                "eligible_count": 0, "selected_count": 0,
            },
        )
        markdown, card = self._rendered(report)
        self.assertIn("数据不足，未完成有效筛选", markdown)
        self.assertIn("数据不足，未完成有效筛选", card)
        self.assertNotIn("数据覆盖与评估充分", markdown)
        self.assertNotIn("数据覆盖与评估充分", card)

    def test_failed_card_remains_an_alert_and_hides_observation_pool(self):
        report = _report(
            data_status="failed",
            run={"status": "failed", "session": "pre_market"},
            quality_gate={"passed": False, "blocking_reasons": ["核心行情不可用"]},
        )
        _, card = self._rendered(report)

        self.assertIn("任务异常", card)
        self.assertIn("核心行情不可用", card)
        self.assertNotIn("观察甲", card)
        self.assertNotIn("已完整筛选", card)

    def test_build_report_does_not_promote_legacy_pool_without_verified_flag(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"as_of": "2026-09-18", "picks": [], "observation_pool": [_observation("000001", "旧池股")]},
            candidates=[],
            coverage={"mode": "full_market", "universe_size": 5500, "scanned_count": 5300, "fresh_data_available": True},
            decision={"regime": "balanced", "status": "需确认", "directions": {
                "current_attack": [], "medium_term": [], "early_positioning": [], "avoid_or_exit": [],
            }},
        )

        self.assertFalse(report["observation_pool_verified"])
        self.assertEqual(report["observation_pool"], [])
        self.assertEqual(report["internal_observation_pool"][0]["name"], "旧池股")
        self.assertNotIn("旧池股", json.dumps(__import__(
            "ah_recommendation_system.backend.stock_recommend.feishu_pusher",
            fromlist=["build_card"],
        ).build_card(report), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
