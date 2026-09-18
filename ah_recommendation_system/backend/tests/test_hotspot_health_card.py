import json
import unittest

from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card


class HotspotHealthCardTests(unittest.TestCase):
    def test_optional_degradation_does_not_claim_narrow_universe(self):
        report = {
            "as_of": "2026-09-14", "data_status": "degraded",
            "coverage": {"label": "全市场观察池"},
            "degraded_sections": ["etf_history"],
            "picks": [{"code": "601872", "name": "招商轮船", "rationale": "趋势确认",
                       "hotspot_match_level": "direct", "hotspot_themes": ["油运景气"],
                       "hotspot_score": 0.15, "hotspot_bonus": 0.015}],
        }
        rendered = json.dumps(build_card(report), ensure_ascii=False)
        self.assertIn("降级模块：etf_history", rendered)
        self.assertIn("全市场观察池", rendered)
        self.assertNotIn("本次仅使用重点行业", rendered)
        self.assertIn("热点：油运景气｜排序加分 1.50/100", rendered)

    def test_unmatched_and_legacy_reports_remain_readable(self):
        row = {"code": "600900", "name": "长江电力", "hotspot_match_level": "none"}
        rendered = json.dumps(build_card({"picks": [row]}), ensure_ascii=False)
        self.assertIn("未匹配当前热点，基础因子入选", rendered)
        del row["hotspot_match_level"]
        rendered = json.dumps(build_card({"picks": [row]}), ensure_ascii=False)
        self.assertIn("长江电力", rendered)
        self.assertNotIn("排序加分", rendered)
