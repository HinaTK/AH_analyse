import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


class TestEvidenceRecommendation(unittest.TestCase):
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
            {"trend", "price_volume", "value_quality", "capital", "relative_strength", "risk"},
        )
        self.assertLess(candidate.factor_scores["risk"], 0)
        self.assertAlmostEqual(candidate.composite, 0.8016, places=4)

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

    def test_hithink_full_market_collection_defers_expensive_enrichment(self):
        from ah_recommendation_system.backend.stock_recommend.data_collector import _collect_a_share_spot

        with patch("ah_recommendation_system.backend.stock_recommend.data_collector._is_mock_mode", return_value=False), patch(
            "ah_recommendation_system.backend.stock_recommend.hithink_client.HithinkClient.market_snapshot",
            return_value=[{"code": "600519", "name": "600519", "price": 1500, "observed_at": int(datetime.now().timestamp() * 1000)}],
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.hithink_client.HithinkClient.enrich_snapshot"
        ) as enrich:
            rows = _collect_a_share_spot(limit=6000)

        self.assertEqual(rows[0]["source"], "hithink_financial_api")
        enrich.assert_not_called()

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

        self.assertEqual(set(stats), {"trend", "price_volume", "value_quality", "capital", "relative_strength"})
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
        self.assertEqual([item["code"] for item in result["observation_pool"]], ["000002", "000003", "000004"])

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
            path.write_text(json.dumps({"factor_version": "evidence-v1", "weights": current}), encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
