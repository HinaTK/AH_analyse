import json
import unittest


class TestMarketHotspotPush(unittest.TestCase):
    def test_verified_news_hotspot_pushes_driver_industry_and_evidence_status(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"as_of": "2026-09-09", "picks": [], "etf_picks": []},
            candidates=[],
            llm_context={
                "hotspots": [{
                    "theme": "算力扩容",
                    "drivers": ["运营商资本开支增加"],
                    "industries": ["光模块", "数据中心"],
                    "status": "confirmed",
                    "confidence": 0.82,
                    "evidence_refs": ["n1", "n2"],
                }],
                "llm": {"hotspot_status": "used"},
            },
        )

        rendered = json.dumps(build_card(report), ensure_ascii=False)
        self.assertEqual(report["market_hotspots"][0]["source_type"], "news")
        self.assertIn("市场热点", rendered)
        self.assertIn("算力扩容", rendered)
        self.assertIn("运营商资本开支增加", rendered)
        self.assertIn("光模块、数据中心", rendered)
        self.assertIn("消息验证", rendered)
        self.assertIn("证据2条", rendered)

    def test_etf_trend_alone_does_not_become_market_hotspot(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={
                "as_of": "2026-09-09",
                "picks": [{
                    "code": "600256",
                    "name": "广汇能源",
                    "score": 71.4,
                    "rationale": "趋势和成交确认",
                    "evidence": [{"statement": "站上中期均线且成交放大"}],
                }],
                "etf_picks": [{
                    "code": "159981",
                    "name": "能源化工ETF",
                    "theme_group": "能源化工",
                    "position": "主线",
                    "score": 68.3,
                    "factor_scores": {"trend": 70, "relative_strength": 65, "liquidity": 80, "risk_control": 60, "theme_match": 50},
                    "rationale": "20/60日趋势向上",
                }],
            },
            candidates=[],
            llm_context={"hotspots": [], "llm": {"hotspot_status": "unavailable"}},
        )

        rendered = json.dumps(build_card(report), ensure_ascii=False)
        self.assertEqual(report["market_hotspots"], [])
        self.assertIn("暂无已验证市场热点", rendered)

    def test_sector_breadth_signal_can_be_marked_as_market_hotspot(self):
        from ah_recommendation_system.backend.stock_recommend.market_hotspots import build_market_hotspots

        hotspots = build_market_hotspots(
            market_signals=[{
                "theme": "有色金属",
                "change_pct": 2.8,
                "advance_count": 34,
                "total_count": 40,
                "turnover_yi": 128.0,
                "leader": "示例资源(600001)",
            }]
        )

        self.assertEqual(hotspots[0]["source_type"], "market")
        self.assertEqual(hotspots[0]["status_label"], "盘面确认")
        self.assertIn("涨幅 2.8%", hotspots[0]["drivers"][0])
        self.assertIn("上涨34/40", hotspots[0]["drivers"][0])

    def test_empty_evidence_pushes_explicit_no_verified_hotspot_message(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        rendered = json.dumps(build_card({"as_of": "2026-09-09", "picks": [], "etf_picks": []}), ensure_ascii=False)
        self.assertIn("市场热点", rendered)
        self.assertIn("暂无已验证市场热点", rendered)


if __name__ == "__main__":
    unittest.main()
