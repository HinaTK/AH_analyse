import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class TestStockRecommendationPipeline(unittest.TestCase):
    def test_focused_candidates_use_hithink_valuation_enrichment(self):
        from ah_recommendation_system.backend.stock_recommend.run import _enrich_hithink_candidates

        rows = [{"code": "300750", "name": "宁德时代", "price": 335.0, "source": "focused_tencent_quotes", "quote_source": "tencent"}]
        with patch("ah_recommendation_system.backend.stock_recommend.run.HithinkClient") as client_cls:
            client_cls.return_value.enabled = True
            client_cls.return_value.enrich_snapshot.return_value = [
                {**rows[0], "pe": 18.1, "pb": 4.0, "market_cap": 1.4e12}
            ]
            enriched = _enrich_hithink_candidates(rows)

        client_cls.return_value.enrich_snapshot.assert_called_once()
        self.assertEqual(enriched[0]["pe"], 18.1)
        self.assertEqual(enriched[0]["market_cap"], 1.4e12)

    def test_daily_feature_enrichment_uses_latest_completed_turnover_when_realtime_empty(self):
        from ah_recommendation_system.backend.stock_recommend.run import _enrich_with_daily_features

        class FakeFetcher:
            def get_a_share_price(self, code, start, end):
                return pd.DataFrame([
                    {"date": "2026-09-05", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "amount": 80_000_000},
                    {"date": "2026-09-08", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 120, "amount": 240_000_000},
                ])

        rows = [{"code": "300750", "amount": 0}]
        with patch(
            "ah_recommendation_system.backend.stock_recommend.run.calculate_features",
            return_value={"history_days": 2, "return_60d_pct": 5.0},
        ):
            enriched = _enrich_with_daily_features(rows, FakeFetcher(), as_of="2026-09-09")

        self.assertEqual(enriched, 1)
        self.assertEqual(rows[0]["amount"], 240_000_000)
        self.assertEqual(rows[0]["amount_reference"], "latest_completed_daily_bar")

    def test_a_share_breadth_signal_uses_full_snapshot(self):
        from ah_recommendation_system.backend.stock_recommend.run import _extract_a_share_signal

        signal = _extract_a_share_signal([
            {"change_pct": 2.0, "amount": 200_000_000},
            {"change_pct": 1.0, "amount": 300_000_000},
            {"change_pct": 0.5, "amount": 100_000_000},
            {"change_pct": -0.2, "amount": 50_000_000},
        ])
        self.assertEqual(signal["advance_count"], 3)
        self.assertEqual(signal["total_count"], 4)
        self.assertAlmostEqual(signal["change_pct"], 0.75)
        self.assertAlmostEqual(signal["turnover_yi"], 6.5)

    def test_candidate_news_refresh_preserves_existing_macro_news(self):
        from ah_recommendation_system.backend.stock_recommend.run import _merge_candidate_events

        existing = {
            "macro_news": {"items": [{"event_id": "macro-1"}], "count": 1},
            "stock_news": [],
            "provider_health": {"rss": "healthy", "macro_fallback": "healthy"},
        }
        refreshed = {
            "macro_news": {},
            "stock_news": [{"event_id": "stock-1"}],
            "count": 1,
            "status": "available",
            "provider_health": {"akshare_stock_news": "healthy", "company_notices": "healthy"},
        }

        merged = _merge_candidate_events(existing, refreshed)

        self.assertEqual(merged["macro_news"]["items"][0]["event_id"], "macro-1")
        self.assertEqual(merged["stock_news"][0]["event_id"], "stock-1")
        self.assertEqual(merged["provider_health"]["rss"], "healthy")
        self.assertEqual(merged["provider_health"]["company_notices"], "healthy")

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

    def test_scheduler_cli_bootstraps_repo_without_pythonpath(self):
        import subprocess
        import sys

        backend = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        result = subprocess.run(
            [sys.executable, "-m", "scheduler.daily_job", "--help"],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_scheduler_returns_nonzero_when_analysis_fails(self):
        from ah_recommendation_system.backend.scheduler.daily_job import main

        with patch("sys.argv", ["daily_job.py", "--mode", "pre_market", "--push"]), patch(
            "ah_recommendation_system.backend.scheduler.daily_job.run_pipeline",
            return_value={"ok": False, "push": {"ok": True}},
        ):
            exit_code = main()

        self.assertEqual(exit_code, 1)

    def test_scheduler_returns_nonzero_when_requested_push_fails(self):
        from ah_recommendation_system.backend.scheduler.daily_job import main

        with patch("sys.argv", ["daily_job.py", "--mode", "pre_market", "--push"]), patch(
            "ah_recommendation_system.backend.scheduler.daily_job.run_pipeline",
            return_value={"ok": True, "push": {"ok": False}},
        ):
            exit_code = main()

        self.assertEqual(exit_code, 1)

    def test_mock_pipeline_never_fills_etfs_without_quality_screening(self):
        from ah_recommendation_system.backend.stock_recommend.run import run_pipeline

        result = run_pipeline(mock=True, push=False)
        report = result["report"]

        self.assertEqual(report["type"], "stock_recommend_pre_market")
        self.assertLessEqual(len(report["picks"]), 5)
        self.assertEqual(report["etf_picks"], [])
        self.assertEqual(report["etf_selection"]["selection_mode"], "rule_quality_diversified")
        self.assertEqual(
            [stage["name"] for stage in report["run"]["stages"]],
            ["collect", "rule_scan", "llm_review", "etf_selection", "quality_gate"],
        )
        self.assertTrue(all(stage["duration_ms"] >= 0 for stage in report["run"]["stages"]))
        self.assertEqual(report["coverage"]["scanned_count"], 15)
        self.assertEqual(report["coverage"]["candidate_count"], 15)
        self.assertEqual(report["coverage"]["history_count"], 15)
        self.assertEqual(report["coverage"]["mode"], "mock_sample")
        self.assertTrue(report["quality_gate"]["passed"])
        self.assertEqual(report["run"]["status"], "passed")
        self.assertTrue(all(pick.get("factor_scores") for pick in report["picks"]))

    def test_pipeline_clamps_requested_stock_count_to_five(self):
        from ah_recommendation_system.backend.stock_recommend.run import run_pipeline

        result = run_pipeline(mock=True, top_n_pick=99, push=False)

        self.assertEqual(len(result["report"]["picks"]), 5)
        self.assertTrue(result["report"]["quality_gate"]["passed"])

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

    def test_feishu_timeout_is_ambiguous_and_is_not_retried(self):
        import requests

        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import push_to_feishu

        with patch(
            "ah_recommendation_system.backend.stock_recommend.feishu_pusher.requests.post",
            side_effect=requests.exceptions.ReadTimeout("response lost"),
        ) as post:
            result = push_to_feishu(
                {"as_of": "2026-09-09", "picks": []},
                webhook="https://example.invalid/hook",
                retries=3,
                backoff_seconds=0,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["delivery_ambiguous"])
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(post.call_count, 1)

    def test_feishu_card_displays_chinese_compound_factor_scores_in_one_line(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        card = build_card({
            "as_of": "2026-09-08",
            "type": "stock_recommend_pre_market",
            "observation_pool": [{"code": "000001", "name": "不推送观察股", "rejection_reasons": ["等待确认"]}],
            "etf_picks": [{"code": "510300", "name": "沪深300ETF", "rationale": "20日收益 +3.2%；价格站上 MA20 与 MA60"}],
            "picks": [{
                "code": "600001", "name": "测试股", "action": "WATCH", "confidence": 0.7,
                "factors": {
                    "composite": 0.66, "trend": 0.8, "price_volume": 0.7,
                    "value_quality": 0.6, "capital": 0.5, "relative_strength": 0.9,
                },
            }],
        })
        content = "\n".join(
            element.get("text", {}).get("content", "")
            for element in card["card"]["elements"]
            if element.get("tag") == "div"
        )
        self.assertIn("综合评分 66.0/100", content)
        self.assertIn("趋势 80", content)
        self.assertIn("量价 70", content)
        self.assertIn("估值质量 60", content)
        self.assertNotIn("composite:", content)
        self.assertNotIn("不推送观察股", content)
        self.assertIn("20日收益 +3.2%", content)

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

    def test_rule_selection_persists_premarket_reference_price(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        candidate = Candidate(
            code="600519",
            name="贵州茅台",
            price=100.0,
            composite=0.8,
            quality_grade="A",
            valid_dimensions={"trend", "price_volume", "value"},
            evidence=[
                {"factor": "trend", "statement": "趋势向上", "supports": True},
                {"factor": "price_volume", "statement": "量价确认", "supports": True},
                {"factor": "value", "statement": "估值可比", "supports": True},
            ],
        )

        selection = select_by_rules([candidate], top_n_pick=1)

        self.assertEqual(selection["picks"][0]["reference_price"], 100.0)

    def test_post_market_rejects_stale_premarket_report(self):
        from ah_recommendation_system.backend.stock_recommend.run import run_post_market

        with tempfile.TemporaryDirectory() as tmp:
            latest = Path(tmp) / "latest.json"
            latest.write_text(
                json.dumps({"as_of": "2026-09-08", "type": "stock_recommend_pre_market", "picks": []}),
                encoding="utf-8",
            )
            with patch(
                "ah_recommendation_system.backend.stock_recommend.run.save_review_report",
                return_value={},
            ):
                result = run_post_market(
                    mock=True,
                    push=False,
                    report_path=latest,
                    expected_as_of="2026-09-09",
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["review"]["run"]["status"], "failed")
        self.assertIn("不是当日盘前报告", "".join(result["review"]["quality_gate"]["blocking_reasons"]))

    def test_post_market_uses_saved_reference_price_for_same_day_close(self):
        from ah_recommendation_system.backend.stock_recommend.run import run_post_market

        class FakeFetcher:
            use_mock_data = False

            def enable_mock_data(self):
                self.use_mock_data = True

            def get_a_share_price(self, code, start, end):
                return pd.DataFrame([{"date": "2026-09-09", "close": 102.0}])

        report = {
            "as_of": "2026-09-09",
            "type": "stock_recommend_pre_market",
            "picks": [{"code": "600519", "name": "贵州茅台", "reference_price": 100.0}],
            "directions": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            latest = Path(tmp) / "latest.json"
            latest.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            with patch(
                "ah_recommendation_system.backend.stock_recommend.run.get_price_fetcher",
                return_value=FakeFetcher(),
            ), patch(
                "ah_recommendation_system.backend.stock_recommend.run._collect_closing_industry_rows",
                return_value=[],
            ), patch(
                "ah_recommendation_system.backend.stock_recommend.run.save_review_report",
                return_value={},
            ):
                result = run_post_market(
                    mock=False,
                    push=False,
                    report_path=latest,
                    expected_as_of="2026-09-09",
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["review"]["items"][0]["return_pct"], 2.0)
        self.assertEqual(result["review"]["summary"]["completed_count"], 1)

    def test_post_market_direction_outcomes_use_close_confirmed_industry_data(self):
        from ah_recommendation_system.backend.stock_recommend.run import _build_direction_outcomes

        report = {
            "directions": {
                "current_attack": [{"direction": "半导体"}],
                "medium_term": [{"direction": "创新药"}],
            }
        }
        outcomes = _build_direction_outcomes(
            report,
            [
                {"name": "半导体", "chg_pct": 1.8, "source": "ths"},
                {"name": "创新药", "chg_pct": -1.2, "source": "ths"},
            ],
        )

        self.assertEqual(outcomes["半导体"]["status"], "confirmed")
        self.assertEqual(outcomes["半导体"]["correction"], "keep")
        self.assertEqual(outcomes["创新药"]["status"], "failed")
        self.assertEqual(outcomes["创新药"]["correction"], "downgrade")
        self.assertIn("收盘", outcomes["半导体"]["evidence"])

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
            self.assertAlmostEqual(sum(result["weights"].values()), 1.0, places=6)
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
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.data_collector.collect_events",
            return_value={"macro_news": {}, "stock_news": [], "provider_health": {}},
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run._enrich_with_daily_features",
            return_value=3,
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.analyze_hotspots",
            return_value={"status": "disabled", "hotspots": []},
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.review_candidate_events",
            return_value={"status": "disabled", "reviews": {}},
        ), patch("ah_recommendation_system.backend.stock_recommend.run.persist_snapshot"), patch(
            "ah_recommendation_system.backend.etf_sector.etf_sector_report.generate_etf_sector_block",
            return_value={},
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.save_report",
            return_value={},
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.HithinkClient"
        ) as hithink:
            hithink.return_value.enabled = False
            hithink.return_value.probe.return_value = {"available": False, "capabilities": {}}
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

    def test_sina_quotes_are_used_as_direct_realtime_fallback(self):
        from ah_recommendation_system.backend.stock_recommend.focused_collector import _quote_sina

        payload = 'var hq_str_sh600519="贵州茅台,1490.00,1480.00,1500.00,1510.00,1470.00,0,0,0,800000000";'
        with patch(
            "ah_recommendation_system.backend.stock_recommend.focused_collector.requests.get"
        ) as get:
            get.return_value.content = payload.encode("gbk")
            get.return_value.raise_for_status.return_value = None
            rows = _quote_sina(["600519"])
        self.assertEqual(rows[0]["code"], "600519")
        self.assertEqual(rows[0]["price"], 1500.0)

    def test_quote_fallback_uses_sina_when_tencent_fails(self):
        from ah_recommendation_system.backend.stock_recommend.focused_collector import _quote_with_fallback

        with patch(
            "ah_recommendation_system.backend.stock_recommend.focused_collector._quote_tencent",
            side_effect=RuntimeError("tencent down"),
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.focused_collector._quote_sina",
            return_value=[{"code": "600519", "price": 1500.0}],
        ):
            self.assertEqual(_quote_with_fallback(["600519"])[0]["code"], "600519")

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

    def test_pipeline_hotspot_llm_cannot_expand_rule_candidates_but_event_llm_can_rerank(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot
        from ah_recommendation_system.backend.stock_recommend.run import run_pipeline

        def candidate(code, composite, event_score):
            return Candidate(
                code=code,
                name=f"Stock-{code}",
                price=10.0,
                composite=composite,
                quality_grade="A",
                valid_dimensions={"trend", "price_volume", "value", "event"},
                event_score=event_score,
                event_score_rule=event_score,
                evidence=[
                    {"factor": "trend", "statement": "trend", "supports": True},
                    {"factor": "price_volume", "statement": "volume", "supports": True},
                    {"factor": "value", "statement": "value", "supports": True},
                    {"factor": "event", "event_id": f"event-{code}", "statement": "news", "supports": True},
                ],
                factor_scores={
                    "trend": 0.8,
                    "price_volume": 0.8,
                    "value_quality": 0.8,
                    "capital": 0.8,
                    "relative_strength": 0.8,
                    "event": event_score,
                    "risk": 0.0,
                },
            )

        initial = [candidate("000001", 0.80, 0.50), candidate("000002", 0.79, 0.50)]
        hotspot_inputs = []
        mapper_inputs = []
        event_inputs = []
        scan_focus_inputs = []

        snapshot = CollectedSnapshot(
            date="2026-09-08",
            fundamental={"rows": [{"code": "000001", "name": "Stock-000001", "price": 10.0}], "count": 1, "universe_size": 1},
            capital={"rows": []},
            events={
                "macro_news": {"items": [{"event_id": "m1"}, {"event_id": "m2"}]},
                "stock_news": [{"event_id": "s1", "title": "stock catalyst"}],
            },
            errors=[],
        )

        def fake_hotspots(**kwargs):
            hotspot_inputs.append(kwargs["candidates"])
            self.assertEqual(kwargs["macro_news"].get("stock_news")[0]["event_id"], "s1")
            return {"status": "used", "hotspots": [{"theme": "Theme", "industries": ["Tech"], "evidence_refs": ["m1", "m2"]}]}

        def fake_mapper(hotspots, **kwargs):
            mapper_inputs.append((hotspots, list(kwargs["rows"])))
            return {"hotspots": [{"theme": "Theme", "industries": ["Tech"], "status": "confirmed"}], "rows": [{"code": "000003", "name": "Stock-000003", "hotspot_themes": ["Theme"]}]}

        def fake_review(candidates, **kwargs):
            event_inputs.append(list(candidates))
            return {
                "status": "used",
                "input_candidate_count": 2,
                "submitted_count": 2,
                "reviewed_count": 2,
                "reviews": {
                    "000001": {"overall_score": 0.0},
                    "000002": {"overall_score": 1.0},
                    "000003": {"overall_score": 1.0},
                },
            }

        def fake_scan(rows, **kwargs):
            scan_focus_inputs.append(kwargs.get("focus_industries"))
            return []

        with patch("ah_recommendation_system.backend.stock_recommend.run.collect_all", return_value=snapshot), patch(
            "ah_recommendation_system.backend.stock_recommend.run.scan_snapshot", side_effect=fake_scan
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.build_candidates", return_value=initial
        ) as build, patch(
            "ah_recommendation_system.backend.stock_recommend.run.analyze_hotspots", side_effect=fake_hotspots
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.validate_and_expand_hotspots", side_effect=fake_mapper
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.review_candidate_events", side_effect=fake_review
        ), patch("ah_recommendation_system.backend.stock_recommend.run.persist_snapshot"), patch(
            "ah_recommendation_system.backend.stock_recommend.run._enrich_with_daily_features", return_value=0
        ), patch("ah_recommendation_system.backend.stock_recommend.run.save_report", return_value={}), patch(
            "ah_recommendation_system.backend.stock_recommend.run.HithinkClient"
        ) as hithink, patch(
            "ah_recommendation_system.backend.etf_sector.etf_sector_report.generate_etf_sector_block", return_value={}
        ):
            hithink.return_value.enabled = False
            hithink.return_value.probe.return_value = {"available": False, "capabilities": {}}
            result = run_pipeline(mock=False, top_n_pick=1, push=False)

        self.assertEqual(build.call_count, 1)
        self.assertTrue(scan_focus_inputs and scan_focus_inputs[0])
        self.assertIn("科技", scan_focus_inputs[0])
        self.assertEqual(len(hotspot_inputs), 1)
        self.assertEqual(len(hotspot_inputs[0]), 2)
        self.assertEqual(len(mapper_inputs[0][1]), 1)
        self.assertEqual(len(event_inputs), 1)
        self.assertEqual([item.code for item in event_inputs[0]], ["000001", "000002"])
        self.assertEqual(result["report"]["picks"][0]["code"], "000002")
        self.assertEqual(result["report"]["llm"]["candidate_count_before"], 2)
        self.assertEqual(result["report"]["llm"]["candidate_count_after"], 2)
        self.assertEqual(result["report"]["llm"]["event_input_candidate_count"], 2)
        self.assertEqual(result["report"]["llm"]["event_submitted_count"], 2)
        self.assertEqual(result["report"]["llm"]["event_reviewed_count"], 2)

    def test_wechat_payload_never_contains_internal_observation_pool(self):
        from ah_recommendation_system.backend.stock_recommend.wechat_pusher import build_wechat_payload

        payload = build_wechat_payload({
            "as_of": "2026-09-09",
            "coverage": {"label": "全市场"},
            "picks": [],
            "observation_pool": [{"code": "000001", "name": "不应推送的观察股"}],
        })

        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("观察池", rendered)
        self.assertNotIn("不应推送的观察股", rendered)


if __name__ == "__main__":
    unittest.main()
