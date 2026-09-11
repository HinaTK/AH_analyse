import unittest

import pandas as pd


class TestEfinanceValuationMapping(unittest.TestCase):
    def test_dynamic_pe_column_is_mapped_with_kind(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import EfinanceSnapshotProvider

        class FakeStock:
            @staticmethod
            def get_realtime_quotes():
                return pd.DataFrame([{
                    "股票代码": "002142",
                    "股票名称": "宁波银行",
                    "最新价": 35.87,
                    "涨跌幅": 3.49,
                    "成交额": 1602459052.49,
                    "总市值": 236870801709,
                    "动态市盈率": "7.15",
                }])

        class FakeEfinance:
            stock = FakeStock()

        rows = EfinanceSnapshotProvider(efinance_module=FakeEfinance(), rate_limiter=None).snapshot(limit=10)
        self.assertEqual(rows[0]["code"], "002142")
        self.assertEqual(rows[0]["pe"], 7.15)
        self.assertEqual(rows[0]["pe_kind"], "dynamic")
        self.assertEqual(rows[0]["source"], "efinance")
        self.assertEqual(rows[0]["price"], 35.87)
        self.assertEqual(rows[0]["change_pct"], 3.49)

    def test_0834_parquet_dynamic_pe_replays_into_candidates(self):
        import polars as pl
        from ah_recommendation_system.backend.stock_recommend.market_data import EfinanceSnapshotProvider
        from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality
        import json

        sample = pd.DataFrame([
            {"股票代码": "002142", "股票名称": "宁波银行", "最新价": "35.87", "涨跌幅": "3.49", "动态市盈率": "7.15", "总市值": 236870801709, "成交额": 1602459052.49},
            {"股票代码": "002011", "股票名称": "盾安环境", "最新价": "13.14", "涨跌幅": "5.54", "动态市盈率": "15.12", "总市值": 14118632234, "成交额": 1633041297.6},
            {"股票代码": "601872", "股票名称": "招商轮船", "最新价": "20.58", "涨跌幅": "-1.95", "动态市盈率": "11.94", "总市值": 166174002371, "成交额": 4356377053.0},
        ])

        class FakeStock:
            @staticmethod
            def get_realtime_quotes():
                return sample

        class FakeEfinance:
            stock = FakeStock()

        rows = EfinanceSnapshotProvider(efinance_module=FakeEfinance(), rate_limiter=None).snapshot(limit=10)
        by_code = {row["code"]: row for row in rows}
        self.assertEqual(by_code["002142"]["pe"], 7.15)
        self.assertEqual(by_code["002011"]["pe"], 15.12)
        self.assertEqual(by_code["601872"]["pe"], 11.94)
        self.assertEqual(by_code["002142"]["price"], 35.87)

    def test_negative_pe_is_kept_as_loss_not_missing(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import normalize_numeric_fields

        rows = normalize_numeric_fields([{"pe": "-12.3", "pb": "--", "amount": "100"}])
        self.assertEqual(rows[0]["pe"], -12.3)
        self.assertIsNone(rows[0]["pb"])


class TestQualityGateDataVsStrategy(unittest.TestCase):
    def _base(self, **changes):
        report = {
            "coverage": {"mode": "full_market", "ratio": 1.0, "fresh_data_available": True},
            "market": {"regime": "defense", "status": "降级观察"},
            "directions": {
                "current_attack": [],
                "medium_term": [],
                "early_positioning": [],
                "avoid_or_exit": [],
            },
            "picks": [],
            "etf_picks": [],
            "quality": {
                "eligible_count": 0,
                "recommended_count": 0,
                "rejected_count": 30,
                "rejection_reasons": {"quality": 32},
            },
            "candidate_panel": [
                {"code": f"{i:06d}", "rejection_reasons": ["quality:估值缺失或无效"]}
                for i in range(30)
            ],
        }
        report.update(changes)
        return report

    def test_all_candidates_missing_pe_blocks_quality_gate(self):
        from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality

        quality = evaluate_report_quality(self._base())
        self.assertFalse(quality["passed"])
        self.assertTrue(any("估值" in reason or "数据" in reason for reason in quality["blocking_reasons"]))

    def test_complete_data_with_zero_picks_still_passes(self):
        from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality

        quality = evaluate_report_quality(self._base(
            quality={
                "eligible_count": 4,
                "recommended_count": 0,
                "rejected_count": 26,
                "rejection_reasons": {"market": 20, "risk": 6},
            },
            candidate_panel=[
                {"code": "002142", "pe": 7.15, "rejection_reasons": ["market:防守期缺少逆势强度及独立确认"]},
                {"code": "002011", "pe": 15.12, "rejection_reasons": ["market:防守期缺少逆势强度及独立确认"]},
            ],
        ))
        self.assertTrue(quality["passed"])


class TestHotspotRepresentatives(unittest.TestCase):
    def test_mapped_members_are_written_as_representatives(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots
        from ah_recommendation_system.backend.stock_recommend.market_hotspots import build_market_hotspots

        mapped = validate_and_expand_hotspots(
            [{
                "theme": "航运运价上行",
                "industries": ["油轮运输"],
                "drivers": ["油运运价维持高位"],
                "confidence": 0.78,
                "evidence_refs": ["macro-a", "macro-b"],
                "status": "early_signal",
            }],
            focus_universe={"油轮运输": [{"code": "601872", "name": "招商轮船"}]},
            rows=[],
        )
        hotspot = mapped["hotspots"][0]
        self.assertEqual(hotspot["mapped_count"], 1)
        self.assertEqual(hotspot["status"], "early_signal")
        self.assertIn("招商轮船", hotspot.get("representatives") or [])
        display = build_market_hotspots(news_hotspots=mapped["hotspots"])[0]
        self.assertEqual(display["representatives"], ["招商轮船"])

    def test_member_count_does_not_confirm_news(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots

        mapped = validate_and_expand_hotspots(
            [{
                "theme": "原油上涨",
                "industries": ["石油开采"],
                "confidence": 0.9,
                "evidence_refs": ["macro-a", "macro-b"],
                "status": "early_signal",
            }],
            focus_universe={"石油开采": [
                {"code": "600028", "name": "中国石化"},
                {"code": "601857", "name": "中国石油"},
                {"code": "600938", "name": "海油发展"},
            ]},
        )
        self.assertEqual(mapped["hotspots"][0]["status"], "early_signal")
        self.assertEqual(mapped["hotspots"][0]["mapped_count"], 3)

    def test_industry_alias_maps_bank_theme(self):
        from ah_recommendation_system.backend.stock_recommend.focused_collector import DEFAULT_FOCUS_UNIVERSE
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots

        mapped = validate_and_expand_hotspots(
            [{
                "theme": "上市银行中期分红与高股息",
                "industries": ["银行"],
                "confidence": 0.76,
                "evidence_refs": ["macro-a", "macro-b"],
                "status": "early_signal",
            }],
            focus_universe=DEFAULT_FOCUS_UNIVERSE,
        )
        self.assertIn("宁波银行", mapped["hotspots"][0].get("representatives") or [])

    def test_new_energy_alias_does_not_pull_unrelated_power_names_from_other_buckets(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots

        mapped = validate_and_expand_hotspots(
            [{
                "theme": "新能源汽车渗透率强化与电池整合",
                "industries": ["新能源汽车", "动力电池"],
                "confidence": 0.66,
                "evidence_refs": ["macro-a", "macro-b"],
                "status": "early_signal",
            }],
            focus_universe={
                "新能源": [
                    {"code": "300750", "name": "宁德时代"},
                    {"code": "002594", "name": "比亚迪"},
                    {"code": "000027", "name": "深圳能源"},
                    {"code": "000037", "name": "深南电A"},
                ],
                "电力": [{"code": "000027", "name": "深圳能源"}, {"code": "000037", "name": "深南电A"}],
            },
        )
        reps = mapped["hotspots"][0].get("representatives") or []
        self.assertIn("宁德时代", reps)
        self.assertNotIn("深圳能源", reps)
        self.assertNotIn("深南电A", reps)



    def test_semiconductor_alias_does_not_pull_broad_tech_bucket(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots
        from ah_recommendation_system.backend.stock_recommend.focused_collector import DEFAULT_FOCUS_UNIVERSE

        mapped = validate_and_expand_hotspots(
            [{
                "theme": "AI算力链业绩兑现与功率半导体",
                "industries": ["半导体", "算力硬件", "功率器件"],
                "confidence": 0.57,
                "evidence_refs": ["macro-a", "macro-b"],
                "status": "early_signal",
            }],
            focus_universe=DEFAULT_FOCUS_UNIVERSE,
        )
        reps = mapped["hotspots"][0].get("representatives") or []
        self.assertIn("长电科技", reps)
        self.assertIn("韦尔股份", reps)
        self.assertNotIn("宁德时代", reps)
        self.assertNotIn("东方财富", reps)
        self.assertNotIn("立讯精密", reps)

    def test_row_tags_do_not_substring_match_across_industries(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots

        mapped = validate_and_expand_hotspots(
            [{
                "theme": "能源通胀",
                "industries": ["能源"],
                "confidence": 0.7,
                "evidence_refs": ["macro-a", "macro-b"],
                "status": "early_signal",
            }],
            rows=[
                {"code": "000027", "name": "深圳能源", "industry": "电力"},
                {"code": "300750", "name": "宁德时代", "focus_industries": ["新能源"]},
            ],
        )
        reps = mapped["hotspots"][0].get("representatives") or []
        self.assertNotIn("宁德时代", reps)
        self.assertNotIn("深圳能源", reps)


class TestPreMarketTurnoverReference(unittest.TestCase):
    def test_incomplete_last_tick_is_not_used_as_liquidity(self):
        from unittest.mock import patch
        from ah_recommendation_system.backend.stock_recommend.run import _apply_daily_feature_row

        row = {"code": "002142", "amount": 5_489_565.0}
        bars = [
            {"date": "2026-09-08", "open": 34, "high": 35, "low": 33, "close": 34.66, "volume": 17_425_068, "amount": 604_176_357},
            {"date": "2026-09-09", "open": 34, "high": 36, "low": 34, "close": 35.87, "volume": 44_975_091, "amount": 1_602_459_052},
            {"date": "2026-09-10", "open": 35.95, "high": 36.0, "low": 35.38, "close": 35.59, "volume": 152_700, "amount": 5_489_565},
        ]
        with patch(
            "ah_recommendation_system.backend.stock_recommend.run.calculate_features",
            return_value={"history_days": 120, "return_60d_pct": 20.3},
        ):
            self.assertTrue(_apply_daily_feature_row(row, bars))
        self.assertEqual(row["amount"], 1_602_459_052)
        self.assertEqual(row["amount_reference"], "latest_completed_daily_bar")

    def test_zero_or_premarket_amount_is_treated_as_missing_for_supplement(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import merge_quote_fields

        primary = {"price": 35.95, "change_pct": 0.22, "amount": 0, "volume": 0, "pe": 7.6}
        secondary = {"amount": 1_602_459_052.49, "volume": 44_975_091, "pe": 7.2}
        filled = merge_quote_fields(primary, secondary)
        self.assertIn("amount", filled)
        self.assertEqual(primary["amount"], 1_602_459_052.49)
        self.assertEqual(primary["pe"], 7.6)

class TestNewsDedupAndConfidence(unittest.TestCase):
    def test_same_story_different_urls_collapse_to_one_event(self):
        from ah_recommendation_system.backend.stock_recommend.news_ranker import select_hotspot_evidence

        selected = select_hotspot_evidence([
            {"event_id": "0", "title": "Issuer announces capacity expansion", "url": "https://a.example/news/1?utm_source=rss"},
            {"event_id": "1", "title": "Issuer announces capacity expansion", "url": "https://b.example/news/2"},
        ])
        self.assertEqual(len(selected), 1)
        self.assertGreaterEqual(int(selected[0].get("reprint_count") or 1), 2)

    def test_feishu_does_not_render_model_confidence_percent(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        card = build_card({
            "schema_version": "decision-report-v2",
            "as_of": "2026-09-11",
            "run": {"status": "passed", "session": "pre_market"},
            "quality_gate": {"passed": True, "blocking_reasons": []},
            "market": {"label": "防守", "status": "降级观察", "regime": "defense"},
            "directions": {
                "current_attack": [],
                "medium_term": [],
                "early_positioning": [],
                "avoid_or_exit": [],
            },
            "recommendations": {"stocks": [], "etfs": []},
            "picks": [],
            "etf_picks": [],
            "market_hotspots": [{
                "theme": "原油上涨与能源成本传导",
                "status_label": "消息待确认",
                "confidence": 0.9,
                "evidence_count": 3,
                "independent_source_count": 1,
                "source_type": "news",
                "drivers": ["油价上行"],
                "industries": ["石油开采"],
                "representatives": ["中国石化"],
                "evidence_grade": "媒体报道待核实",
            }],
        })
        text = str(card)
        self.assertNotIn("置信90%", text)
        self.assertNotIn("·置信", text)
        self.assertIn("中国石化", text)
        self.assertIn("待核实", text)


if __name__ == "__main__":
    unittest.main()
