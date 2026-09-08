import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class TestStockRecommendationPipeline(unittest.TestCase):
    def test_windows_installer_has_three_separate_task_registrations(self):
        script = Path(__file__).resolve().parents[3] / "tools" / "install_stock_recommend_tasks.ps1"
        registration_lines = [
            line
            for line in script.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("Register-ScheduledTask")
        ]
        self.assertEqual(len(registration_lines), 3)
        self.assertTrue(all('-Force' in line for line in registration_lines))
        # Windows PowerShell 5.1 reads UTF-8 files without a BOM as an ANSI
        # code page. Keep this installer ASCII-only so quoted descriptions
        # cannot be corrupted into part of the command line.
        script.read_bytes().decode("ascii")

    def test_mock_pipeline_defaults_to_three_picks_and_two_etfs(self):
        from ah_recommendation_system.backend.stock_recommend.run import run_pipeline

        result = run_pipeline(mock=True, push=False)
        report = result["report"]

        self.assertEqual(report["type"], "stock_recommend_pre_market")
        self.assertLessEqual(len(report["picks"]), 3)
        self.assertEqual(len(report["etf_picks"]), 2)
        self.assertEqual(report["coverage"]["scanned_count"], 15)
        self.assertEqual(report["coverage"]["candidate_count"], 15)
        self.assertEqual(report["coverage"]["history_count"], 15)
        self.assertTrue(all(pick.get("factor_scores") for pick in report["picks"]))

    def test_feishu_push_retries_and_returns_failure_after_three_attempts(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import (
            push_to_feishu,
        )

        class Response:
            status_code = 500
            text = "failed"

            def json(self):
                return {"code": 1}

        with patch(
            "ah_recommendation_system.backend.stock_recommend.feishu_pusher.requests.post",
            return_value=Response(),
        ) as post:
            result = push_to_feishu(
                {"as_of": "2026-09-07", "picks": []},
                webhook="https://example.invalid/hook",
                retries=3,
                backoff_seconds=0,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["retry_count"], 3)
        self.assertEqual(post.call_count, 3)

    def test_post_market_review_contains_status_and_next_day_correction(self):
        from ah_recommendation_system.backend.stock_recommend.post_market import (
            build_post_market_review,
        )

        report = {
            "as_of": "2026-09-05",
            "picks": [
                {"code": "600519", "name": "贵州茅台", "action": "WATCH"},
            ],
        }
        prices = {
            "600519": [100.0, 102.0],
        }
        review = build_post_market_review(report, prices=prices)

        self.assertEqual(review["type"], "stock_recommend_post_market")
        self.assertEqual(review["items"][0]["status"], "hit")
        self.assertIn(review["items"][0]["correction"], {"keep", "upgrade"})

    def test_post_market_review_exposes_t1_t5_t20_outcomes(self):
        from ah_recommendation_system.backend.stock_recommend.post_market import (
            build_post_market_review,
        )

        report = {"as_of": "2026-09-05", "picks": [{"code": "600519", "name": "M"}]}
        closes = [100.0] + [101.0] * 19 + [110.0]
        review = build_post_market_review(report, prices={"600519": closes})
        outcomes = {row["horizon"]: row for row in review["items"][0]["outcomes"]}
        self.assertEqual(set(outcomes), {1, 5, 20})
        self.assertAlmostEqual(outcomes[1]["return_pct"], 1.0, places=3)
        self.assertAlmostEqual(outcomes[5]["return_pct"], 1.0, places=3)
        self.assertAlmostEqual(outcomes[20]["return_pct"], 10.0, places=3)

    def test_weekly_reweight_is_bounded(self):
        from ah_recommendation_system.backend.stock_recommend.reweight import (
            adjust_weights,
        )

        old = {"fundamental": 0.4, "capital": 0.35, "event": 0.25}
        stats = {
            "fundamental": {"hit_rate": 0.9},
            "capital": {"hit_rate": 0.1},
            "event": {"hit_rate": 0.5},
        }
        new = adjust_weights(old, stats, max_delta=0.05)

        self.assertAlmostEqual(sum(new.values()), 1.0, places=6)
        for key in old:
            self.assertLessEqual(abs(new[key] - old[key]), 0.05 + 1e-6)

    def test_weekly_reweight_run_persists_weights_and_stats(self):
        from ah_recommendation_system.backend.stock_recommend.reweight import run_weekly_reweight

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "stock-recommend-ledger.jsonl"
            ledger.write_text(
                json.dumps(
                    {
                        "per_pick": [
                            {
                                "factors": {"fundamental_score": 0.9, "capital_score": 0.2},
                                "return_T5_pct": 3.0,
                            },
                            {
                                "factors": {"fundamental_score": 0.1, "capital_score": 0.8},
                                "return_T5_pct": -2.0,
                            },
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_weekly_reweight(ledgers_dir=root)
            self.assertTrue(Path(result["weights_path"]).exists())
            self.assertAlmostEqual(sum(result["weights"].values()), 0.9, places=6)
            self.assertIn("trend", result["stats"])

    def test_rule_selector_never_requires_llm_and_adds_risk_levels(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidates = [
            Candidate(code="600001", name="甲", price=10, composite=0.9, quality_grade="A", reasons=["趋势强"], valid_dimensions={"trend", "price_volume", "value"}, evidence=[{"statement": "趋势强"}]),
            Candidate(code="600002", name="乙", price=20, composite=0.8, quality_grade="A", reasons=["放量"], valid_dimensions={"trend", "price_volume", "value"}, evidence=[{"statement": "放量"}]),
            Candidate(code="600003", name="丙", price=30, composite=0.7, quality_grade="A", reasons=["抗跌"], valid_dimensions={"trend", "price_volume", "value"}, evidence=[{"statement": "抗跌"}]),
            Candidate(code="600004", name="丁", price=40, composite=0.6),
        ]
        result = select_by_rules(candidates, top_n_pick=3)

        self.assertEqual([p["code"] for p in result["picks"]], ["600001", "600002", "600003"])
        self.assertFalse(result["llm_used"])
        self.assertTrue(all(p.get("trigger") and p.get("invalidation") for p in result["picks"]))

    def test_report_discloses_limited_sample_when_coverage_is_low(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"picks": [], "as_of": "2026-09-07"},
            candidates=[],
            snapshot_errors=[],
            coverage={"universe_size": 5300, "scanned_count": 300},
        )
        self.assertEqual(report["coverage"]["label"], "有限样本观察池")


    def test_focused_fallback_merges_focus_industries_and_institution_activity(self):
        from ah_recommendation_system.backend.stock_recommend.focused_collector import build_focused_snapshot

        focus = {
            "科技": [{"code": "000001", "name": "科技甲"}],
            "医疗": [{"code": "000002", "name": "医疗乙"}],
        }
        activity = [
            {"code": "000001", "name": "科技甲", "net_buy": 2_000_000, "source": "lhb_trader"},
            {"code": "000003", "name": "机构丙", "net_buy": 3_000_000, "source": "lhb_institution"},
        ]

        def quote_fetcher(codes):
            names = {"000001": "科技甲", "000002": "医疗乙", "000003": "机构丙"}
            return [{"code": code, "name": names[code], "price": 10.0} for code in codes]

        snap = build_focused_snapshot(
            focus_universe=focus,
            activity_rows=activity,
            quote_fetcher=quote_fetcher,
        )
        rows = {row["code"]: row for row in snap.fundamental["rows"]}
        self.assertEqual(set(rows), {"000001", "000002", "000003"})
        self.assertEqual(rows["000001"]["candidate_sources"], ["focus_industry", "lhb_trader"])
        self.assertEqual(rows["000001"]["focus_industries"], ["科技"])
        self.assertEqual(snap.fundamental["source"], "focused_tencent_quotes")

    def test_pipeline_uses_focused_fallback_when_full_market_is_empty(self):
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot
        from ah_recommendation_system.backend.stock_recommend.run import run_pipeline

        empty = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [], "count": 0, "universe_size": 0},
            capital={"rows": []},
            events={},
            errors=["full_market_unavailable"],
        )
        focused = CollectedSnapshot(
            date="2026-09-08",
            fundamental={
                "rows": [
                    {"code": "000001", "name": "科技甲", "price": 10, "candidate_sources": ["focus_industry"]},
                    {"code": "000002", "name": "机构乙", "price": 20, "candidate_sources": ["lhb_institution"]},
                    {"code": "000003", "name": "共振丙", "price": 30, "candidate_sources": ["focus_industry", "lhb_trader"]},
                ],
                "count": 3,
                "universe_size": 3,
                "source": "focused_tencent_quotes",
            },
            capital={"rows": []},
            events={},
            errors=[],
        )
        with patch("ah_recommendation_system.backend.stock_recommend.run.collect_all", return_value=empty), patch(
            "ah_recommendation_system.backend.stock_recommend.run.collect_focused_market",
            return_value=focused,
        ), patch("ah_recommendation_system.backend.stock_recommend.run.persist_snapshot"), patch(
            "ah_recommendation_system.backend.etf_sector.etf_sector_report.generate_etf_sector_block",
            return_value={},
        ):
            result = run_pipeline(mock=False, push=False)

        self.assertEqual(result["report"]["coverage"]["mode"], "focused_fallback")
        self.assertLessEqual(len(result["report"]["picks"]), 3)
        self.assertIn("full_market_unavailable", result["report"]["data_warnings"])

    def test_focused_snapshot_drops_symbols_without_a_valid_quote(self):
        from ah_recommendation_system.backend.stock_recommend.focused_collector import build_focused_snapshot

        snap = build_focused_snapshot(
            focus_universe={
                "科技": [
                    {"code": "000001", "name": "有效报价"},
                    {"code": "000002", "name": "零价格"},
                    {"code": "000003", "name": "缺失报价"},
                ]
            },
            quote_fetcher=lambda codes: [
                {"code": "000001", "name": "有效报价", "price": 10.0},
                {"code": "000002", "name": "零价格", "price": 0.0},
            ],
        )

        self.assertEqual([row["code"] for row in snap.fundamental["rows"]], ["000001"])
        self.assertEqual(snap.fundamental["count"], 1)
        self.assertEqual(snap.fundamental["requested_count"], 3)

    def test_tencent_quotes_are_requested_in_small_batches(self):
        from ah_recommendation_system.backend.stock_recommend.focused_collector import _quote_tencent

        class Response:
            status_code = 200

            def __init__(self, url):
                symbols = url.split("q=", 1)[1].split(",")
                lines = []
                for symbol in symbols:
                    code = symbol[-6:]
                    fields = [""] * 38
                    fields[1] = f"股票{code}"
                    fields[2] = code
                    fields[3] = "10.0"
                    fields[6] = "100"
                    fields[30] = "20260908101500"
                    fields[32] = "1.2"
                    fields[37] = "1000000"
                    lines.append(f'v_{symbol}="{"~".join(fields)}";')
                self.content = "\n".join(lines).encode("gbk")

            def raise_for_status(self):
                return None

        codes = [f"{index:06d}" for index in range(1, 106)]
        with patch(
            "ah_recommendation_system.backend.stock_recommend.focused_collector.requests.get",
            side_effect=lambda url, **kwargs: Response(url),
        ) as get:
            rows = _quote_tencent(codes, batch_size=40)

        self.assertEqual(len(rows), 105)
        self.assertEqual(get.call_count, 3)
        self.assertTrue(all(call.args[0].count(",") < 40 for call in get.call_args_list))

    def test_lhb_selector_keeps_positive_net_buy_and_deduplicates_each_source(self):
        from ah_recommendation_system.backend.stock_recommend.focused_collector import _select_lhb_activity

        trader = [
            {"code": "000001", "name": "共振股", "net_buy": 10.0, "listing_count": 2},
            {"code": "000001", "name": "共振股", "net_buy": 5.0, "listing_count": 1},
            {"code": "000002", "name": "净卖出", "net_buy": -20.0, "listing_count": 5},
        ]
        institution = [
            {"code": "000001", "name": "共振股", "net_buy": 30.0},
            {"code": "000003", "name": "机构净卖出", "net_buy": -1.0},
        ]

        rows = _select_lhb_activity(trader, institution, top_n_per_source=10)

        self.assertEqual(
            [(row["code"], row["source"], row["net_buy"]) for row in rows],
            [("000001", "lhb_trader", 15.0), ("000001", "lhb_institution", 30.0)],
        )

    def test_focused_candidates_explain_sources_and_gate_unconfirmed_lhb_only_stock(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={
                "rows": [
                    {
                        "code": "000001",
                        "name": "行业机构共振",
                        "price": 10,
                        "change_pct": 1.0,
                        "candidate_sources": ["focus_industry", "lhb_institution"],
                        "focus_industries": ["科技"],
                    },
                    {
                        "code": "000002",
                        "name": "资金但未确认",
                        "price": 20,
                        "change_pct": 2.0,
                        "candidate_sources": ["lhb_trader"],
                    },
                ]
            },
            capital={
                "rows": [
                    {"code": "000001", "main_net": 30_000_000},
                    {"code": "000002", "main_net": 50_000_000},
                ]
            },
            events={},
        )

        candidates = build_candidates(snapshot)
        by_code = {candidate.code: candidate for candidate in candidates}
        selection = select_by_rules(candidates, top_n_pick=3)

        self.assertNotIn("重点行业: 科技", by_code["000001"].reasons)
        self.assertIn("机构席位净买入", by_code["000001"].reasons)
        self.assertTrue(by_code["000002"].observation_only)
        self.assertLessEqual(len(selection["picks"]), 1)

    def test_focused_fallback_has_explicit_limited_pool_label(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"picks": [], "as_of": "2026-09-08"},
            candidates=[],
            coverage={
                "mode": "focused_fallback",
                "universe_size": 25,
                "scanned_count": 25,
                "source": "focused_tencent_quotes",
            },
        )

        self.assertEqual(report["coverage"]["label"], "重点行业+龙虎榜有限观察池")
        self.assertEqual(report["data_status"], "degraded")

    def test_feishu_card_keeps_etfs_visible_when_stock_picks_are_empty(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        card = build_card(
            {
                "as_of": "2026-09-08",
                "picks": [],
                "etf_picks": [
                    {"code": "510300", "name": "沪深300ETF", "rationale": "观察市场风险偏好"}
                ],
                "data_status": "degraded",
                "coverage": {"label": "重点行业+龙虎榜有限观察池"},
            }
        )
        rendered = json.dumps(card, ensure_ascii=False)

        self.assertIn("沪深300ETF", rendered)
        self.assertIn("有限数据源", rendered)
        self.assertIn("重点行业+龙虎榜有限观察池", rendered)

    def test_pipeline_marks_failure_as_data_error_instead_of_no_opportunity(self):
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
        from ah_recommendation_system.backend.stock_recommend.run import run_pipeline

        empty = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [], "count": 0, "universe_size": 0},
            capital={"rows": []},
            events={},
            errors=["upstream unavailable"],
        )
        with patch("ah_recommendation_system.backend.stock_recommend.run.collect_all", return_value=empty), patch(
            "ah_recommendation_system.backend.stock_recommend.run.collect_focused_market",
            return_value=empty,
        ), patch("ah_recommendation_system.backend.stock_recommend.run.persist_snapshot"), patch(
            "ah_recommendation_system.backend.stock_recommend.run.save_report", return_value={}
        ), patch(
            "ah_recommendation_system.backend.etf_sector.etf_sector_report.generate_etf_sector_block",
            return_value={},
        ):
            result = run_pipeline(mock=False, push=False)

        rendered = json.dumps(build_card(result["report"]), ensure_ascii=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["report"]["data_status"], "failed")
        self.assertIn("数据采集失败", rendered)
        self.assertNotIn("暂无推荐", rendered)


if __name__ == "__main__":
    unittest.main()
