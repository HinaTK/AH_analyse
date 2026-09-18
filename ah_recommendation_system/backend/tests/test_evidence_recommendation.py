import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class TestEvidenceRecommendation(unittest.TestCase):
    def test_risk_review_vetoes_p0_event(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.risk_review import review_candidate_risks

        candidate = Candidate(code="000001", name="风险股", evidence=[{"statement": "公司被立案调查", "factor": "event"}])
        result = review_candidate_risks([candidate])
        self.assertEqual(result["p0_count"], 1)
        self.assertTrue(any(reason.startswith("p0:") for reason in candidate.rejection_reasons))
    def test_focused_sample_requires_news_or_capital_confirmation_for_formal_pick(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="300760", name="有限样本股", price=100, composite=0.70,
            change_60d_pct=15, pe=20, focus_industries=["医疗"],
            evidence=[
                {"factor": "trend", "statement": "趋势确认", "source": "test", "supports": True},
                {"factor": "price_volume", "statement": "量价确认", "source": "test", "supports": True},
                {"factor": "value_quality", "statement": "估值质量确认", "source": "test", "supports": True},
            ], valid_dimensions={"trend", "price_volume", "value_quality"}, quality_grade="A",
        )
        result = select_by_rules([candidate], coverage_mode="focused_fallback")
        self.assertEqual(result["picks"], [])
        self.assertTrue(any(reason.startswith("coverage") for reason in candidate.rejection_reasons))

    def test_observation_pool_does_not_assign_synthetic_roles(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidates = []
        for idx in range(1, 7):
            candidates.append(Candidate(
                code=f"6000{idx:02d}", name=f"候选{idx}", price=10, composite=0.5 - idx * 0.01,
                focus_industries=["行业"], observation_only=True,
            ))
        result = select_by_rules(candidates, top_n_pick=0)
        self.assertEqual(result["observation_pool"], [])
        self.assertFalse(result["observation_pool_verified"])
    def test_missing_metrics_are_not_scored_as_neutral_or_selected(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="000001", name="缺数据", price=10, composite=0.99,
            focus_industries=["科技"], candidate_sources=["focus_industry"],
            quality_grade="B",
        )
        result = select_by_rules([candidate])

        self.assertEqual(result["picks"], [])
        self.assertTrue(any(reason.startswith("quality") or reason.startswith("evidence") for reason in candidate.rejection_reasons))

    def test_industry_tag_is_not_an_investment_reason(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="000002", name="证据股", price=10, composite=0.8,
            change_60d_pct=12, main_net=30_000_000, pe=18,
            focus_industries=["科技"], candidate_sources=["focus_industry"],
            evidence=[
                {"factor": "trend", "statement": "60日趋势+12.0%", "source": "test", "as_of": "2026-09-08"},
                {"factor": "capital", "statement": "主力净流入0.30亿", "source": "test", "as_of": "2026-09-08"},
                {"factor": "value", "statement": "PE 18.0", "source": "test", "as_of": "2026-09-08"},
            ],
            valid_dimensions={"trend", "capital", "value"},
            quality_grade="A",
        )
        result = select_by_rules([candidate])

        self.assertEqual(len(result["picks"]), 1)
        self.assertNotIn("重点行业", result["picks"][0]["rationale"])
        self.assertEqual(len(result["picks"][0]["evidence"]), 3)

    def test_single_capital_signal_stays_observation_only(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="000003", name="仅资金", price=10, composite=0.9,
            main_net=50_000_000,
            candidate_sources=["lhb_institution"],
            valid_dimensions={"capital"},
            quality_grade="C",
        )
        result = select_by_rules([candidate])

        self.assertEqual(result["picks"], [])
        self.assertTrue(any(reason.startswith("evidence") for reason in candidate.rejection_reasons))

    def test_price_plan_uses_atr_and_support_when_available(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="000004", name="技术股", price=10, composite=0.8,
            atr=0.4, support=9.5, resistance=11.2,
            valid_dimensions={"trend", "price_volume", "value"},
            evidence=[
                {"factor": "trend", "statement": "站上MA20", "source": "daily", "as_of": "2026-09-08"},
                {"factor": "price_volume", "statement": "量比1.8", "source": "daily", "as_of": "2026-09-08"},
                {"factor": "value", "statement": "PE 20", "source": "snapshot", "as_of": "2026-09-08"},
            ],
            quality_grade="A",
        )
        pick = select_by_rules([candidate])["picks"][0]

        self.assertEqual(pick["buy_zone"], "9.50-10.00")
        self.assertEqual(pick["stop_loss"], "9.00")
        self.assertEqual(pick["target"], "11.20")

    def test_hithink_client_without_key_is_disabled_without_network(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="")
        result = client.probe()

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "missing_api_key")

    def test_hithink_api_key_supports_ths_key_download_filename(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import resolve_api_key

        original_read_text = Path.read_text

        def read_test_key(path, *args, **kwargs):
            if str(path).replace("/", "\\").endswith(r"Downloads\ths_key.txt"):
                return "test-key\n"
            return original_read_text(path, *args, **kwargs)

        with patch.dict(
            "os.environ",
            {"HITHINK_FINANCE_API_KEY": "", "HITHINK_FINANCE_API_KEY_FILE": ""},
            clear=False,
        ), patch.object(Path, "read_text", read_test_key):
            self.assertEqual(resolve_api_key(), "test-key")

    def test_feishu_webhook_extracts_url_from_wrapped_file_value(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import resolve_webhook

        value = "{web_hook, https://open.feishu.cn/open-apis/bot/v2/hook/abc-123}"
        self.assertEqual(resolve_webhook(value), "https://open.feishu.cn/open-apis/bot/v2/hook/abc-123")

    def test_feishu_webhook_reads_local_key_file_when_env_is_missing(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import resolve_webhook

        with patch.dict("os.environ", {"AH_FEISHU_WEBHOOK": ""}, clear=False), patch(
            "ah_recommendation_system.backend.stock_recommend.feishu_pusher.Path.read_text",
            return_value="{web_hook, https://open.feishu.cn/open-apis/bot/v2/hook/file-123}",
        ):
            self.assertEqual(
                resolve_webhook(),
                "https://open.feishu.cn/open-apis/bot/v2/hook/file-123",
            )

    def test_hithink_snapshot_uses_documented_field_names(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        row = HithinkClient._normalize_snapshot({
            "thscode": "600519.SH", "last_price": 1500.0,
            "price_change_ratio_pct": 1.2, "turnover": 800_000_000,
            "volume": 500_000,
        })

        self.assertEqual(row["code"], "600519")
        self.assertEqual(row["price"], 1500.0)
        self.assertEqual(row["change_pct"], 1.2)
        self.assertEqual(row["amount"], 800_000_000)

    def test_weekly_reweight_does_not_change_weights_before_sixty_samples(self):
        from ah_recommendation_system.backend.stock_recommend.reweight import DEFAULT_WEIGHTS, decide_weekly_weights

        stats = {name: {"sample_count": 12.0, "hit_rate": 0.9} for name in DEFAULT_WEIGHTS}
        result = decide_weekly_weights(DEFAULT_WEIGHTS, stats, minimum_samples=60)

        self.assertFalse(result["applied"])
        self.assertEqual(result["weights"], DEFAULT_WEIGHTS)

    def test_daily_features_calculate_trend_and_atr(self):
        from ah_recommendation_system.backend.stock_recommend.technical_features import calculate_features

        bars = []
        base = datetime(2026, 1, 1)
        for i in range(130):
            close = 10 + i * 0.05
            bars.append({
                "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": close - 0.1, "high": close + 0.2,
                "low": close - 0.2, "close": close, "volume": 1000 + i,
            })
        features = calculate_features(bars)

        self.assertEqual(features["history_days"], 130)
        self.assertGreater(features["return_60d_pct"], 0)
        self.assertTrue(features["above_ma20"])
        self.assertGreater(features["atr"], 0)
        self.assertIsNotNone(features["rsi_14"])
        self.assertIsNotNone(features["macd"])
        self.assertIsNotNone(features["macd_signal"])

    def test_dynamic_scanner_adds_price_volume_and_new_high_tags(self):
        from ah_recommendation_system.backend.stock_recommend.dynamic_scanner import scan_snapshot

        rows = [
            {"code": "000005", "name": "强势", "price": 12, "change_pct": 6,
             "change_60d_pct": 25, "amount": 500_000_000, "volume_ratio": 2.0,
             "high_20d": 12},
        ]
        seeds = scan_snapshot(rows, focus_industries={"科技": [{"code": "000005"}]})

        self.assertEqual(seeds[0]["code"], "000005")
        self.assertIn("market_leader", seeds[0]["source_tags"])
        self.assertIn("volume_expansion", seeds[0]["source_tags"])
        self.assertIn("new_high", seeds[0]["source_tags"])
        self.assertIn("科技", seeds[0]["industries"])

    def test_dynamic_scanner_ignores_non_numeric_amount_strings(self):
        from ah_recommendation_system.backend.stock_recommend.dynamic_scanner import scan_snapshot

        rows = [
            {"code": "000005", "name": "无效额度", "price": 12, "change_pct": 6, "amount": "-", "change_60d_pct": 0},
            {"code": "000006", "name": "正常", "price": 10, "change_pct": 1, "amount": 200_000_000},
        ]
        seeds = scan_snapshot(rows, limit=10)

        codes = [seed["code"] for seed in seeds]
        self.assertNotIn("000005", codes)
        valid_seed = next(seed for seed in seeds if seed["code"] == "000006")
        self.assertIn("liquidity_leader", valid_seed["source_tags"])

    def test_scan_snapshot_keeps_untagged_tradable_names(self):
        from ah_recommendation_system.backend.stock_recommend.dynamic_scanner import scan_snapshot

        rows = [
            {"code": "000001", "name": "平安银行", "price": 10.0, "amount": 200_000_000, "change_pct": 0.2},
            {"code": "000002", "name": "ST示例", "price": 10.0, "amount": 500_000_000, "change_pct": 5.0},
            {"code": "000003", "name": "无成交", "price": 10.0, "amount": 1_000_000, "change_pct": 4.0},
            {"code": "000004", "name": "无价格", "amount": 200_000_000, "change_pct": 4.0},
            {"code": "bad", "name": "代码无效", "price": 10.0, "amount": 200_000_000, "change_pct": 1.0},
        ]
        seeds = scan_snapshot(rows, limit=None)

        codes = [row["code"] for row in seeds]
        self.assertEqual(codes, ["000001"])
        self.assertIn("source_tags_sidecar", seeds[0])

    def test_missing_valuation_or_market_cap_fails_hard_screen(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000006", "name": "缺估值", "price": 10,
                "change_pct": 2, "change_60d_pct": 12,
                "amount": 500_000_000, "volume_ratio": 1.8,
            }]},
            capital={"rows": [{"code": "000006", "main_net": 20_000_000}]},
        )
        candidate = build_candidates(snapshot)[0]

        self.assertTrue(candidate.observation_only)
        self.assertTrue(any("估值" in reason for reason in candidate.rejection_reasons))
        self.assertTrue(any("市值" in reason for reason in candidate.rejection_reasons))

    def test_price_volume_accepts_normal_liquidity_ratio_from_completed_bar(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000007", "name": "liquidity-test", "price": 10,
                "change_pct": 0.5, "change_60d_pct": 12,
                "amount": 240_000_000, "volume_ratio": 0.9,
                "pe": 20, "market_cap": 10_000_000_000,
                "history_days": 120,
            }]},
            capital={"rows": [{"code": "000007", "main_net": 20_000_000}]},
        )
        candidate = build_candidates(snapshot)[0]

        self.assertIn("price_volume", candidate.valid_dimensions)

    def test_selector_limits_formal_picks_to_one_per_industry(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        def eligible(code, industry, score):
            return Candidate(
                code=code, name=code, price=10, composite=score,
                focus_industries=[industry], quality_grade="A",
                valid_dimensions={"trend", "price_volume", "value"},
                evidence=[{"statement": "趋势"}, {"statement": "量价"}, {"statement": "估值"}],
            )

        result = select_by_rules([
            eligible("000007", "科技", 0.9),
            eligible("000008", "科技", 0.8),
            eligible("000009", "医疗", 0.7),
        ])

        self.assertEqual([pick["code"] for pick in result["picks"]], ["000007", "000009"])

    def test_hithink_history_is_normalized_for_feature_calculation(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        with patch.object(client, "_get", return_value={"item": [{
            "date_ms": 1788796800000, "open_price": 10,
            "high_price": 11, "low_price": 9.5, "close_price": 10.5,
            "volume": 1000, "turnover": 10_000,
        }]}):
            rows = client.historical("000001", start_ms=1, end_ms=2)

        self.assertEqual(rows[0]["open"], 10)
        self.assertEqual(rows[0]["close"], 10.5)
        self.assertEqual(rows[0]["amount"], 10_000)

    def test_wechat_webhook_renders_zero_pick_report(self):
        from ah_recommendation_system.backend.stock_recommend.wechat_pusher import build_wechat_payload

        payload = build_wechat_payload({
            "as_of": "2026-09-08", "picks": [], "observation_pool": [],
            "coverage": {"label": "有限样本观察池"}, "data_status": "degraded",
        })

        content = payload["markdown"]["content"]
        self.assertIn("今日无正式个股推荐", content)
        self.assertIn("有限样本观察池", content)

    def test_candidate_exposes_six_factor_scores_and_risk_penalty(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000010", "name": "六因子", "price": 20,
                "change_pct": 8.4, "change_60d_pct": 18,
                "amount": 600_000_000, "volume_ratio": 2.2,
                "market_cap": 20_000_000_000, "pe": 25,
                "above_ma20": True, "above_ma60": True,
                "volatility_20d_pct": 55, "max_drawdown_pct": -22,
            }]},
            capital={"rows": [{"code": "000010", "main_net": 50_000_000}]},
        )
        candidate = build_candidates(snapshot)[0]

        self.assertEqual(
            set(candidate.factor_scores),
            {"trend", "price_volume", "value_quality", "capital", "relative_strength", "event", "risk"},
        )
        self.assertLess(candidate.factor_scores["risk"], 0)
        # No benchmark was supplied: momentum cannot earn another 15% as RS.
        self.assertEqual(candidate.factor_scores["relative_strength"], 0.0)
        self.assertAlmostEqual(candidate.composite, 0.691, places=4)

    def test_formal_pick_exposes_evidence_factor_scores_directly(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="600000",
            name="测试股票",
            price=10,
            valid_dimensions={"trend", "price_volume", "value", "capital"},
            evidence=[
                {"factor": "trend", "statement": "站上MA20", "source": "test", "as_of": "2026-09-08"},
                {"factor": "price_volume", "statement": "量比1.5", "source": "test", "as_of": "2026-09-08"},
                {"factor": "value", "statement": "PE 18", "source": "test", "as_of": "2026-09-08"},
            ],
        )
        candidate.quality_grade = "A"
        candidate.composite = 0.72
        candidate.factor_scores = {
            "trend": 0.8,
            "price_volume": 0.7,
            "value_quality": 0.6,
            "capital": 0.75,
            "relative_strength": 0.65,
            "risk": -0.03,
        }
        result = select_by_rules([candidate], top_n_pick=3)
        self.assertEqual(len(result["picks"]), 1)
        self.assertEqual(result["picks"][0]["factor_scores"], candidate.factor_scores)

    def test_structured_evidence_has_falsifier_and_support_role(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000011", "name": "证据完整", "price": 15,
                "change_pct": 2, "change_60d_pct": 10,
                "amount": 300_000_000, "market_cap": 10_000_000_000, "pe": 20,
            }]},
            capital={"rows": [{"code": "000011", "main_net": 30_000_000}]},
        )
        evidence = build_candidates(snapshot)[0].evidence

        self.assertTrue(all(item.get("supports") for item in evidence))
        self.assertTrue(all(item.get("falsifier") for item in evidence))

    def test_quality_c_or_low_score_candidate_cannot_be_formal_pick(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        low_quality = Candidate(
            code="000012", name="质量C", price=10, composite=0.9, quality_grade="C",
            valid_dimensions={"trend", "price_volume", "value"},
            evidence=[{"statement": "趋势"}, {"statement": "量价"}, {"statement": "估值"}],
        )
        low_score = Candidate(
            code="000013", name="低分", price=10, composite=0.4, quality_grade="A",
            valid_dimensions={"trend", "price_volume", "value"},
            evidence=[{"statement": "趋势"}, {"statement": "量价"}, {"statement": "估值"}],
        )

        self.assertEqual(select_by_rules([low_quality, low_score])["picks"], [])

    def test_hithink_enrichment_merges_names_valuation_and_market_cap(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        rows = [{"code": "600519", "name": "600519", "price": 1500}]
        with patch.object(client, "ticker_names", return_value={"600519": "贵州茅台"}), patch.object(
            client, "valuations", return_value={"600519": {"pe_ttm": 22, "pb_mrq": 8}}
        ), patch.object(client, "auction_metrics", return_value={"600519": {"float_market_cap": 1_000_000_000_000}}):
            enriched = client.enrich_snapshot(rows)

        self.assertEqual(enriched[0]["name"], "贵州茅台")
        self.assertEqual(enriched[0]["pe"], 22)
        self.assertEqual(enriched[0]["pb"], 8)
        self.assertEqual(enriched[0]["market_cap"], 1_000_000_000_000)

    def test_hithink_enrichment_does_not_erase_existing_fields_when_optional_calls_fail(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        rows = [{"code": "600519", "name": "贵州茅台", "price": 1500, "pe": 20, "pb": 6, "market_cap": 9e11, "turnover_pct": 0.2}]
        with patch.object(client, "ticker_names", return_value={}), patch.object(
            client, "valuations", return_value={}
        ), patch.object(client, "auction_metrics", return_value={}):
            enriched = client.enrich_snapshot(rows)

        self.assertEqual(enriched[0]["pe"], 20)
        self.assertEqual(enriched[0]["market_cap"], 9e11)

    def test_hithink_enrichment_keeps_valuations_when_ticker_names_fail(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        rows = [{"code": "002349", "name": "精华制药", "price": 8.01}]
        with patch.object(client, "ticker_names", side_effect=RuntimeError("timeout")), patch.object(
            client, "valuations", return_value={"002349": {"pe_ttm": 32.57, "pb_mrq": 2.58}}
        ), patch.object(client, "auction_metrics", return_value={"002349": {"float_market_cap": 8.5e9}}):
            enriched = client.enrich_snapshot(rows)

        self.assertEqual(enriched[0]["pe"], 32.57)
        self.assertEqual(enriched[0]["pb"], 2.58)
        self.assertEqual(enriched[0]["market_cap"], 8.5e9)
        self.assertEqual(enriched[0]["name"], "精华制药")

    def test_hithink_enrichment_skips_name_catalog_when_quotes_already_named(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        rows = [{"code": "300750", "name": "宁德时代", "price": 330.51, "quote_source": "tencent"}]
        with patch.object(client, "ticker_names") as ticker_names, patch.object(
            client, "valuations", return_value={"300750": {"pe_ttm": 18.41, "pb_mrq": 4.13}}
        ), patch.object(client, "auction_metrics", return_value={}):
            enriched = client.enrich_snapshot(rows)

        ticker_names.assert_not_called()
        self.assertEqual(enriched[0]["pe"], 18.41)
        self.assertEqual(enriched[0]["pb"], 4.13)

    def test_hithink_full_market_collection_keeps_enriched_snapshot(self):
        from ah_recommendation_system.backend.stock_recommend import data_collector

        quotes = [{"code": "600519", "name": "600519", "price": 1500,
                   "observed_at": int(datetime.now().timestamp() * 1000)}]
        enriched = [{**quotes[0], "name": "贵州茅台", "pe": 22, "pb": 8,
                     "market_cap": 1.8e12, "float_cap": 1.8e12,
                     "amount": 8e8, "volume": 5000, "turnover_pct": 0.4}]
        manager = data_collector.MarketDataManager(cache_ttl_seconds=0)
        with patch.object(data_collector, "_is_mock_mode", return_value=False), patch.object(
            data_collector, "MarketDataManager", return_value=manager
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.hithink_client.HithinkClient.market_snapshot",
            return_value=quotes,
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.hithink_client.HithinkClient.enrich_snapshot",
            return_value=enriched,
        ), patch("requests.sessions.Session.request", side_effect=AssertionError("unexpected network")):
            rows = data_collector._collect_a_share_spot(limit=6000)

        self.assertEqual(rows[0]["source"], "hithink_financial_api")
        self.assertEqual(rows[0]["price"], 1500)
        self.assertEqual(rows[0]["pe"], 22)
        self.assertEqual(rows[0]["provider_health"]["attempted_sources"], ["hithink_financial_api"])

    def test_usable_hithink_snapshot_supplements_missing_fields_from_akshare(self):
        from ah_recommendation_system.backend.stock_recommend import data_collector

        managed_rows = [{
            "code": "600519", "name": "Moutai", "price": 1500.0, "change_pct": 1.0,
            "pe": 22.0, "amount": 8e8,
            "observed_at": int(datetime.now().timestamp() * 1000),
        }]
        akshare_rows = [{
            "code": "600519", "price": 1501.0, "pe": 22.0, "pb": 8.0,
            "market_cap": 1.8e12, "float_cap": 1.8e12, "turnover_pct": 0.4,
            "amount": 8e8, "volume": 5000,
        }]
        manager = object.__new__(data_collector.MarketDataManager)
        manager.fetch_snapshot = lambda *, limit: data_collector.SnapshotResult(
            rows=managed_rows,
            source="hithink_financial_api",
            attempted=["hithink_financial_api", "akshare:supplement"],
            supplemented_fields={"pe": ["600519"], "amount": ["600519"]},
            stats={"up_count": 1},
        )
        with patch.object(data_collector, "_is_mock_mode", return_value=False), patch.object(
            data_collector, "MarketDataManager", return_value=manager
        ):
            rows = data_collector._collect_a_share_spot(limit=6000)

        self.assertEqual(rows[0]["price"], 1500.0)
        self.assertEqual(rows[0]["pe"], 22.0)
        self.assertEqual(rows[0]["amount"], 8e8)
        self.assertEqual(rows[0]["provider_health"]["attempted_sources"], ["hithink_financial_api", "akshare:supplement"])

    def test_incomplete_hithink_snapshot_falls_through_to_akshare(self):
        from ah_recommendation_system.backend.stock_recommend.data_collector import _collect_a_share_spot

        class FakeAk:
            @staticmethod
            def stock_zh_a_spot_em():
                return pd.DataFrame([{
                    "代码": "600519", "名称": "贵州茅台", "最新价": 1500.0,
                    "涨跌幅": 1.2, "成交额": 800000000.0,
                    "市盈率-动态": 22.0, "总市值": 2.0e12,
                }])

        with patch("ah_recommendation_system.backend.stock_recommend.data_collector._is_mock_mode", return_value=False), patch(
            "ah_recommendation_system.backend.stock_recommend.hithink_client.HithinkClient.market_snapshot",
            return_value=[{"code": "600519", "name": "600519", "price": None, "change_pct": None, "amount": 0, "observed_at": int(datetime.now().timestamp() * 1000)} for _ in range(10)],
        ), patch("ah_recommendation_system.backend.stock_recommend.data_collector.ak", FakeAk()):
            rows = _collect_a_share_spot(limit=6000)

        self.assertEqual(rows[0]["price"], 1500.0)
        self.assertNotEqual(rows[0].get("source"), "hithink_financial_api")

    def test_hithink_snapshot_preserves_zero_change_and_response_timestamp(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        with patch.object(client, "_get", return_value={
            "timestamp": 1_789_000_000_000,
            "item": [{"thscode": "601398.SH", "last_price": 6.8, "price_change_ratio_pct": 0.0}],
        }):
            rows = client.market_snapshot(limit=1)

        self.assertEqual(rows[0]["change_pct"], 0.0)
        self.assertEqual(rows[0]["observed_at"], 1_789_000_000_000)

    def test_hithink_dragon_tiger_reads_stock_items(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        with patch.object(client, "_get", return_value={"stock_items": [{"thscode": "600000.SH"}]}):
            rows = client.dragon_tiger(board_type="org")

        self.assertEqual(rows[0]["thscode"], "600000.SH")

    def test_hithink_valuation_batch_failure_falls_back_per_symbol(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        calls = []

        def fake_get(path, params):
            calls.append(params["thscodes"])
            if "," in params["thscodes"]:
                raise RuntimeError("invalid symbol in batch")
            if params["thscodes"] == "600519.SH":
                return {"item": [{"thscode": "600519.SH", "pe_ttm": 22}]}
            raise RuntimeError("unknown symbol")

        with patch.object(client, "_get", side_effect=fake_get):
            result = client.valuations(["600519", "000003"])

        self.assertEqual(result["600519"]["pe_ttm"], 22)
        self.assertEqual(calls[0], "600519.SH,000003.SZ")
        self.assertIn("000003.SZ", calls)

    def test_hithink_auction_batch_failure_keeps_valid_symbols(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")

        def fake_get(path, params):
            if "," in params["thscodes"]:
                raise RuntimeError("invalid symbol in batch")
            if params["thscodes"] == "600519.SH":
                return {"item": [{"thscode": "600519.SH", "float_market_cap": 1_000_000_000_000}]}
            raise RuntimeError("unknown symbol")

        with patch.object(client, "_get", side_effect=fake_get):
            result = client.auction_metrics(["600519", "000003"])

        self.assertEqual(result["600519"]["float_market_cap"], 1_000_000_000_000)

    def test_scanner_uses_cross_sectional_liquidity_when_history_is_absent(self):
        from ah_recommendation_system.backend.stock_recommend.dynamic_scanner import scan_snapshot

        rows = [
            {"code": f"{index:06d}", "name": str(index), "price": 10,
             "change_pct": 0.5, "amount": 1_000_000_000 - index}
            for index in range(200)
        ]
        seeds = scan_snapshot(rows, limit=80)

        self.assertEqual(len(seeds), 80)
        self.assertTrue(all("liquidity_leader" in row["source_tags"] for row in seeds))

    def test_hithink_builds_dynamic_focus_industry_constituents(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        with patch.object(client, "industry_catalog", return_value=[{"thscode": "881001.TI", "name": "半导体行业"}]), patch.object(
            client, "index_constituents", return_value=[{"ticker": "688981", "name": "中芯国际"}]
        ):
            result = client.focus_universe(["半导体"])

        self.assertEqual(result["半导体"][0]["code"], "688981")

    def test_hithink_focus_alias_expands_broad_theme_to_catalog_industries(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient

        client = HithinkClient(api_key="secret")
        with patch.object(
            client,
            "industry_catalog",
            return_value=[
                {"thscode": "881121.TI", "name": "半导体"},
                {"thscode": "881123.TI", "name": "通信设备"},
            ],
        ), patch.object(
            client,
            "index_constituents",
            side_effect=lambda code: [{"ticker": "688981", "name": "中芯国际"}] if code == "881121.TI" else [],
        ):
            result = client.focus_universe(["科技"])

        self.assertEqual(result["科技"][0]["code"], "688981")

    def test_report_quality_counts_eligible_candidates_not_only_picks(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"picks": [{"code": "000001"}], "eligible_count": 4},
            candidates=[{"code": str(i), "observation_only": i >= 4} for i in range(10)],
            coverage={"universe_size": 100, "scanned_count": 10},
        )

        self.assertEqual(report["quality"]["eligible_count"], 4)
        self.assertEqual(report["quality"]["recommended_count"], 1)

    def test_six_factor_weights_change_candidate_ranking_score(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000014", "name": "权重股", "price": 10,
                "change_pct": 1, "change_60d_pct": 20,
                "amount": 500_000_000, "market_cap": 10_000_000_000, "pe": 20,
            }]},
            capital={"rows": [{"code": "000014", "main_net": 20_000_000}]},
        )
        trend_only = {"trend": 0.9, "price_volume": 0, "value_quality": 0, "capital": 0, "relative_strength": 0}
        value_only = {"trend": 0, "price_volume": 0, "value_quality": 0.9, "capital": 0, "relative_strength": 0}

        trend_score = build_candidates(snapshot, weights=trend_only)[0].composite
        value_score = build_candidates(snapshot, weights=value_only)[0].composite

        self.assertGreater(trend_score, value_score)

    def test_capital_rows_are_aggregated_per_stock(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000015", "name": "资金汇总", "price": 10,
                "change_pct": 1, "change_60d_pct": 8, "amount": 200_000_000,
                "market_cap": 8_000_000_000, "pe": 15,
            }]},
            capital={"rows": [
                {"code": "000015", "main_net": 10_000_000},
                {"code": "000015", "main_net": 20_000_000},
            ]},
        )

        self.assertEqual(build_candidates(snapshot)[0].main_net, 30_000_000)

    def test_new_default_reweight_stats_match_ranking_factors(self):
        from ah_recommendation_system.backend.stock_recommend.reweight import DEFAULT_WEIGHTS, aggregate_factor_stats

        factors = {name: 0.8 for name in DEFAULT_WEIGHTS}
        stats = aggregate_factor_stats([{"per_pick": [{"factors": factors, "return_T5_pct": 2.0}]}])

        self.assertEqual(set(stats), {"trend", "price_volume", "value_quality", "capital", "relative_strength", "event"})
        self.assertTrue(all(item["sample_count"] == 1 for item in stats.values()))

    def test_non_selected_eligible_candidates_are_returned_as_observations(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidates = []
        for index in range(5):
            candidates.append(Candidate(
                code=f"{index:06d}", name=str(index), price=10,
                composite=0.9 - index * 0.05, quality_grade="A",
                focus_industries=[f"行业{index}"],
                valid_dimensions={"trend", "price_volume", "value"},
                evidence=[{"statement": "趋势"}, {"statement": "量价"}, {"statement": "估值"}],
            ))

        result = select_by_rules(candidates, top_n_pick=2)

        self.assertEqual(len(result["picks"]), 2)
        self.assertEqual(result["observation_pool"], [])

    def test_invalid_support_or_resistance_does_not_create_price_plan(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="000016", name="错误边界", price=10, composite=0.8,
            quality_grade="A", support=10.5, resistance=9.8, atr=0.3,
            valid_dimensions={"trend", "price_volume", "value"},
            evidence=[{"statement": "趋势"}, {"statement": "量价"}, {"statement": "估值"}],
        )
        pick = select_by_rules([candidate])["picks"][0]

        self.assertEqual(pick["buy_zone"], "等待支撑位确认")
        self.assertEqual(pick["target"], "等待压力位确认")

    def test_persisted_factor_weights_are_loaded_only_for_current_version(self):
        import json
        import tempfile
        from pathlib import Path
        from ah_recommendation_system.backend.stock_recommend.reweight import DEFAULT_WEIGHTS, load_factor_weights

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weights.json"
            current = dict(DEFAULT_WEIGHTS)
            current["trend"] += 0.02
            current["capital"] -= 0.02
            path.write_text(json.dumps({"factor_version": "evidence-v2", "weights": current}), encoding="utf-8")
            self.assertEqual(load_factor_weights(path), current)
            path.write_text(json.dumps({"factor_version": "legacy", "weights": current}), encoding="utf-8")
            self.assertEqual(load_factor_weights(path), DEFAULT_WEIGHTS)

    def test_stale_snapshot_candidate_can_only_be_observed(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000017", "name": "缓存股", "price": 10,
                "change_pct": 1, "change_60d_pct": 12, "amount": 300_000_000,
                "market_cap": 10_000_000_000, "pe": 20, "stale": True,
            }]},
            capital={"rows": [{"code": "000017", "main_net": 30_000_000}]},
        )
        candidate = build_candidates(snapshot)[0]

        self.assertTrue(candidate.observation_only)
        self.assertTrue(any(reason.startswith("stale") for reason in candidate.rejection_reasons))

    def test_load_last_snapshot_marks_every_row_stale(self):
        import tempfile
        from pathlib import Path
        from ah_recommendation_system.backend.stock_recommend.local_store import load_last_snapshot, persist_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_snapshot([{"code": "000001", "name": "缓存", "price": 10}], root, as_of="2026-09-07")
            rows = load_last_snapshot(root)

        self.assertEqual(rows[0]["code"], "000001")
        self.assertTrue(rows[0]["stale"])
        self.assertEqual(rows[0]["source"], "last_good_snapshot")

    def test_fresh_disk_snapshot_can_be_used_as_live_fallback(self):
        import tempfile
        from pathlib import Path
        from ah_recommendation_system.backend.stock_recommend.local_store import load_last_snapshot, persist_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_snapshot(
                [{"code": "000001", "name": "缓存", "price": 10, "amount": 200_000_000}],
                root,
                as_of="2026-09-10",
            )
            fresh = load_last_snapshot(root, max_age_seconds=300)
            parquet = next((root / "data" / "market_store").glob("a_share_spot_*.parquet"))
            parquet.touch()
            import os
            os.utime(parquet, (1_000_000_000, 1_000_000_000))
            stale = load_last_snapshot(root, max_age_seconds=300)

        self.assertEqual(fresh[0]["source"], "disk_cache")
        self.assertFalse(fresh[0]["stale"])
        self.assertEqual(stale[0]["source"], "last_good_snapshot")
        self.assertTrue(stale[0]["stale"])

    def test_candidate_requires_sixty_daily_bars_for_formal_recommendation(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000018", "name": "历史不足", "price": 10,
                "change_pct": 1, "change_60d_pct": 10, "amount": 300_000_000,
                "market_cap": 10_000_000_000, "pe": 20, "history_days": 59,
            }]},
            capital={"rows": [{"code": "000018", "main_net": 30_000_000}]},
        )
        candidate = build_candidates(snapshot)[0]

        self.assertEqual(select_by_rules([candidate])["picks"], [])
        self.assertTrue(any("历史日线" in reason for reason in candidate.rejection_reasons))

    def test_stale_coverage_is_reported_as_degraded(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"picks": []}, candidates=[],
            coverage={"mode": "limited_sample", "universe_size": 100, "scanned_count": 30, "stale": True},
        )

        self.assertEqual(report["data_status"], "degraded")
        self.assertEqual(report["coverage"]["label"], "有限样本观察池")

    def test_negative_news_is_a_risk_veto_with_traceable_source(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{
                "code": "000019", "name": "风险公司", "price": 10,
                "change_pct": 1, "change_60d_pct": 10, "amount": 300_000_000,
                "market_cap": 10_000_000_000, "pe": 20, "history_days": 120,
            }]},
            capital={"rows": [{"code": "000019", "main_net": 30_000_000}]},
            events={"stock_news": [
                {"title": "风险公司000019发布一般经营动态", "source": "媒体", "published_at": "2026-09-08"},
                {
                    "title": "风险公司000019遭立案调查", "source": "交易所公告",
                    "url": "https://example.invalid/notice", "published_at": "2026-09-08",
                },
            ]},
        )
        candidate = build_candidates(snapshot)[0]

        self.assertTrue(candidate.observation_only)
        event = next(item for item in candidate.evidence if item["factor"] == "event" and not item["supports"])
        self.assertEqual(event["source"], "交易所公告")
        self.assertEqual(event["url"], "https://example.invalid/notice")
        self.assertTrue(any(reason.startswith("p0") for reason in candidate.rejection_reasons))

    def test_notice_fallback_filters_candidate_codes_and_preserves_source(self):
        from ah_recommendation_system.backend.stock_recommend.data_collector import _collect_notice_news

        class AkModule:
            @staticmethod
            def stock_notice_report(*, symbol, date):
                return pd.DataFrame([
                    {"代码": "000001", "名称": "甲公司", "公告标题": "甲公司获得订单", "公告类型": "重大事项", "公告日期": "2026-09-09", "网址": "https://example.com/a"},
                    {"代码": "000002", "名称": "乙公司", "公告标题": "乙公司日常公告", "公告类型": "其他", "公告日期": "2026-09-09", "网址": "https://example.com/b"},
                ])

        rows = _collect_notice_news(limit=10, codes=["000001"], ak_module=AkModule())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "000001")
        self.assertEqual(rows[0]["source"], "上市公司公告聚合")
        self.assertEqual(rows[0]["url"], "https://example.com/a")

    def test_stock_news_uses_python_strings_for_akshare_pandas3_compatibility(self):
        from ah_recommendation_system.backend.stock_recommend import data_collector

        class AkModule:
            @staticmethod
            def stock_news_em(*, symbol):
                if pd.options.future.infer_string:
                    raise RuntimeError("Arrow regex backend rejects AKShare unicode escape")
                return pd.DataFrame([{
                    "新闻标题": f"{symbol}获得订单",
                    "新闻内容": "订单金额同比增长",
                    "发布时间": "2026-09-09 08:00:00",
                    "文章来源": "测试媒体",
                    "新闻链接": "https://example.com/news",
                }])

        with patch.object(data_collector, "ak", AkModule()), patch.object(
            data_collector, "_is_mock_mode", return_value=False
        ):
            rows = data_collector._collect_news_em(limit=1, codes=["000001"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "000001获得订单")
        self.assertEqual(rows[0]["source"], "测试媒体")
        self.assertEqual(rows[0]["url"], "https://example.com/news")
        self.assertTrue(pd.options.future.infer_string)

    def test_macro_news_fallback_uses_non_rss_sources(self):
        from ah_recommendation_system.backend.stock_recommend.data_collector import _collect_macro_news_fallback

        class AkModule:
            @staticmethod
            def stock_info_global_em():
                return pd.DataFrame([
                    {"标题": "海外市场重要变化", "摘要": "风险偏好变化", "发布时间": "2026-09-09 07:30:00", "链接": "https://example.com/global"}
                ])

            @staticmethod
            def stock_info_global_sina():
                return pd.DataFrame()

            @staticmethod
            def news_economic_baidu():
                return pd.DataFrame([
                    {"标题": "国内宏观数据发布", "摘要": "需求改善", "时间": "2026-09-09 08:00:00", "链接": "https://example.com/macro"}
                ])

        rows = _collect_macro_news_fallback(limit=10, ak_module=AkModule())
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["source"] for row in rows}, {"东方财富全球财经", "百度宏观资讯"})
    def test_notice_fallback_without_codes_keeps_stock_code(self):
        from ah_recommendation_system.backend.stock_recommend.data_collector import _collect_notice_news

        class AkModule:
            @staticmethod
            def stock_notice_report(*, symbol, date):
                return pd.DataFrame([
                    {"代码": "600036", "名称": "招商银行", "公告标题": "招商银行回购进展", "公告类型": "回购", "公告日期": "2026-09-15", "网址": "https://example.com/c"},
                ])

        rows = _collect_notice_news(limit=10, codes=None, ak_module=AkModule())
        self.assertEqual(rows[0]["code"], "600036")
        self.assertIn("回购", rows[0]["title"])

    def test_event_evidence_matches_news_code_field(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot

        snapshot = CollectedSnapshot(
            date="2026-09-15",
            fundamental={"rows": [{
                "code": "600036", "name": "招商银行", "price": 40,
                "change_pct": 1, "change_60d_pct": 10, "amount": 300_000_000,
                "market_cap": 100_000_000_000, "pe": 7, "history_days": 120,
            }]},
            capital={"rows": []},
            events={"stock_news": [{
                "code": "600036",
                "title": "公司回购部分股份",
                "source": "巨潮资讯网",
                "published_at": "2026-09-15",
            }]},
        )
        candidate = build_candidates(snapshot)[0]
        self.assertIn("event", candidate.valid_dimensions)
        self.assertTrue(any(item.get("factor") == "event" and item.get("supports") for item in candidate.evidence))

    def test_sina_moneyflow_rank_parses_net_inflow(self):
        from ah_recommendation_system.backend.stock_recommend import data_collector

        class Resp:
            def raise_for_status(self):
                return None
            def json(self):
                return [{"symbol": "sh600036", "name": "招商银行", "r0_net": "123456789.0", "netamount": "1"}]

        with patch.object(data_collector, "_is_mock_mode", return_value=False), patch.object(
            data_collector.requests, "get", return_value=Resp()
        ):
            rows = data_collector._collect_sina_moneyflow_rank(pages=1, page_size=1)
        self.assertEqual(rows[0]["code"], "600036")
        self.assertEqual(rows[0]["main_net"], 123456789.0)
        self.assertEqual(rows[0]["source"], "sina.moneyflow_rank")

if __name__ == "__main__":
    unittest.main()
