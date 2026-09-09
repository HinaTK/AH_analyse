import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestLlmEventReview(unittest.TestCase):
    def test_blends_only_event_dimension_and_reorders_candidates(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import (
            Candidate,
        )
        from ah_recommendation_system.backend.stock_recommend.llm_review import (
            apply_llm_event_scores,
        )

        first = Candidate(code="000001", name="甲", composite=0.70, event_score=0.40)
        second = Candidate(code="000002", name="乙", composite=0.68, event_score=0.90)
        first.factor_scores = {"trend": 0.7, "price_volume": 0.7, "value_quality": 0.7, "capital": 0.7, "relative_strength": 0.7, "event": 0.4, "risk": 0.0}
        second.factor_scores = {"trend": 0.695, "price_volume": 0.695, "value_quality": 0.695, "capital": 0.695, "relative_strength": 0.695, "event": 0.9, "risk": 0.0}

        result = apply_llm_event_scores(
            [first, second],
            {"000001": {"overall_score": 1.0}, "000002": {"overall_score": 0.0}},
        )

        self.assertEqual([item.code for item in result], ["000002", "000001"])
        self.assertAlmostEqual(first.event_score, 0.58, places=3)
        self.assertAlmostEqual(second.event_score, 0.63, places=3)
        self.assertEqual(first.factor_scores["trend"], 0.7)
        self.assertEqual(first.factor_scores["event"], first.event_score)

    def test_invalid_llm_event_score_is_ignored(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.llm_review import apply_llm_event_scores

        candidate = Candidate(code="000003", name="丙", event_score=0.4, composite=0.6)
        candidate.factor_scores = {"trend": 0.6, "price_volume": 0.6, "value_quality": 0.6, "capital": 0.6, "relative_strength": 0.6, "event": 0.4, "risk": 0.0}

        result = apply_llm_event_scores([candidate], {"000003": {"overall_score": 2.0}})

        self.assertEqual(result[0].event_score, 0.4)
        self.assertNotIn("event_score_llm", result[0].factor_scores)

    def test_codex_client_reports_disabled_without_running_process(self):
        from ah_recommendation_system.backend.stock_recommend.codex_cli_client import CodexCliClient

        client = CodexCliClient(binary="definitely-not-a-real-codex-binary")
        result = client.analyze("{}")

        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["output_valid"])

    def test_codex_client_runs_in_isolated_utf8_workspace(self):
        from ah_recommendation_system.backend.stock_recommend.codex_cli_client import CodexCliClient

        captured = {}

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(args, **kwargs):
            captured["args"] = list(args)
            captured["kwargs"] = dict(kwargs)
            output_index = args.index("--output-last-message") + 1
            Path(args[output_index]).write_text('{"ok": true}', encoding="utf-8")
            return Completed()

        with patch.dict(os.environ, {}, clear=True), patch(
            "ah_recommendation_system.backend.stock_recommend.codex_cli_client.shutil.which",
            return_value="C:/bin/codex.exe",
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.codex_cli_client.subprocess.run",
            side_effect=fake_run,
        ):
            result = CodexCliClient(binary="codex").analyze("return json")

        self.assertEqual(result["status"], "used")
        self.assertIn("--skip-git-repo-check", captured["args"])
        self.assertIn('model_reasoning_effort="low"', captured["args"])
        self.assertIn('web_search="disabled"', captured["args"])
        self.assertEqual(captured["kwargs"]["encoding"], "utf-8")
        self.assertEqual(captured["kwargs"]["errors"], "replace")
        self.assertEqual(captured["kwargs"]["timeout"], 90.0)
        self.assertNotEqual(Path(captured["kwargs"]["cwd"]).resolve(), Path.cwd().resolve())

    def test_hotspot_prompt_bounds_news_summaries_and_candidate_context(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_analyzer import build_hotspot_prompt

        macro_news = {
            "items": [
                {"event_id": f"news-{index}", "title": f"title-{index}", "summary": "x" * 1000}
                for index in range(30)
            ]
        }
        candidates = [
            {"code": f"{index:06d}", "name": f"candidate-{index}"}
            for index in range(25)
        ]

        prompt = build_hotspot_prompt(
            macro_news=macro_news,
            candidates=candidates,
            as_of="2026-09-09",
        )

        self.assertIn("news-23", prompt)
        self.assertNotIn("news-24", prompt)
        self.assertNotIn("x" * 301, prompt)
        self.assertIn("candidate-19", prompt)
        self.assertNotIn("candidate-20", prompt)

    def test_event_review_prompt_excludes_candidates_without_event_evidence(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.llm_review import build_event_review_prompt

        with_event = Candidate(
            code="000001",
            name="有消息",
            event_score_rule=0.6,
            evidence=[{"factor": "event", "event_id": "event-1", "statement": "订单增长"}],
        )
        without_event = Candidate(code="000002", name="无消息", evidence=[])

        prompt = build_event_review_prompt([with_event, without_event], as_of="2026-09-09")

        self.assertIn("000001", prompt)
        self.assertIn("event-1", prompt)
        self.assertNotIn("000002", prompt)

    def test_event_review_prompt_caps_each_candidate_to_five_events(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.llm_review import build_event_review_prompt

        candidate = Candidate(
            code="000001",
            name="消息较多",
            evidence=[
                {"factor": "event", "event_id": f"event-{index}", "statement": f"消息{index}"}
                for index in range(7)
            ],
        )

        prompt = build_event_review_prompt([candidate], as_of="2026-09-09")

        self.assertIn("event-4", prompt)
        self.assertNotIn("event-5", prompt)

    def test_event_review_reports_actual_submitted_and_reviewed_counts(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.llm_review import review_candidate_events

        class Client:
            @staticmethod
            def analyze(prompt):
                return {
                    "status": "used",
                    "data": {"reviews": [{
                        "code": "000001",
                        "overall_score": 0.8,
                        "evidence_refs": ["event-1"],
                    }]},
                }

        result = review_candidate_events(
            [
                Candidate(code="000001", name="有消息", evidence=[{
                    "factor": "event", "event_id": "event-1", "statement": "订单增长",
                }]),
                Candidate(code="000002", name="无消息", evidence=[]),
            ],
            as_of="2026-09-09",
            client=Client(),
        )

        self.assertEqual(result["input_candidate_count"], 2)
        self.assertEqual(result["submitted_count"], 1)
        self.assertEqual(result["reviewed_count"], 1)

    def test_normalize_llm_review_rejects_unknown_event_refs(self):
        from ah_recommendation_system.backend.stock_recommend.llm_review import normalize_llm_reviews

        result = normalize_llm_reviews(
            {"reviews": [{"code": "000004", "overall_score": 0.8, "evidence_refs": ["event-x"]}]},
            valid_event_ids={"event-y"},
        )

        self.assertEqual(result, {})

    def test_feishu_renders_rule_and_ai_event_scores(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        card = build_card({
            "as_of": "2026-09-08",
            "picks": [{
                "code": "000005", "name": "测试股", "factors": {
                    "composite": 0.7, "trend": 0.8, "price_volume": 0.7,
                    "value_quality": 0.6, "capital": 0.6, "relative_strength": 0.8,
                    "event": 0.74, "event_score_rule": 0.7, "event_score_llm": 0.8,
                },
                "llm_review": "订单催化与主营相关，等待放量确认。",
            }],
        })
        rendered = json.dumps(card, ensure_ascii=False)

        self.assertIn("规则 70", rendered)
        self.assertIn("AI 80", rendered)
        self.assertIn("订单催化与主营相关", rendered)

    def test_event_llm_weight_requires_samples_and_is_capped(self):
        from ah_recommendation_system.backend.stock_recommend.reweight import decide_event_llm_weight

        insufficient = decide_event_llm_weight(
            current_llm_weight=0.3, sample_count=99, rule_hit_rate=0.5, llm_hit_rate=0.8
        )
        improved = decide_event_llm_weight(
            current_llm_weight=0.6, sample_count=120, rule_hit_rate=0.5, llm_hit_rate=0.56,
            rule_false_positive_rate=0.1, llm_false_positive_rate=0.12,
        )

        self.assertFalse(insufficient["applied"])
        self.assertEqual(insufficient["llm_weight"], 0.3)
        self.assertEqual(improved["llm_weight"], 0.5)

    def test_event_calibration_requires_two_consecutive_qualifying_weeks(self):
        from ah_recommendation_system.backend.stock_recommend.reweight import (
            evaluate_event_llm_calibration,
        )

        records = [
            {
                "outcome": i % 2,
                "rule_score": 0.55,
                "llm_score": 0.9 if i % 2 else 0.1,
                "p0": i % 2 == 0,
            }
            for i in range(100)
        ]
        first = evaluate_event_llm_calibration(records, current_share=0.3, qualifying_streak=0)
        second = evaluate_event_llm_calibration(records, current_share=0.3, qualifying_streak=first["qualifying_streak"])

        self.assertFalse(first["applied"])
        self.assertEqual(first["qualifying_streak"], 1)
        self.assertTrue(second["applied"])
        self.assertEqual(second["llm_share"], 0.4)
        self.assertGreaterEqual(second["metrics"]["brier_improvement_pct"], 5.0)
        self.assertGreaterEqual(second["metrics"]["accuracy_improvement_pp"], 3.0)

    def test_custom_llm_share_only_changes_event_dimension(self):
        from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
        from ah_recommendation_system.backend.stock_recommend.llm_review import apply_llm_event_scores

        candidate = Candidate(
            code="000001",
            name="测试股",
            price=10,
            event_score=0.2,
            event_score_rule=0.2,
            factor_scores={
                "trend": 0.8,
                "price_volume": 0.7,
                "value_quality": 0.6,
                "capital": 0.5,
                "relative_strength": 0.4,
                "event": 0.2,
                "risk": 0.0,
            },
        )
        result = apply_llm_event_scores(
            [candidate],
            {"000001": {"overall_score": 0.8, "reason": "证据内复核"}},
            llm_share=0.4,
        )[0]

        self.assertAlmostEqual(result.event_score, 0.44)
        self.assertEqual(result.factor_scores["trend"], 0.8)

    def test_event_calibration_state_is_loaded_separately_from_factor_weights(self):
        from ah_recommendation_system.backend.stock_recommend.reweight import (
            build_event_calibration_records,
            load_event_llm_share,
        )

        ledger_rows = [{
            "per_pick": [{
                "return_T5_pct": 2.0,
                "factors": {"event_score_rule": 0.4, "event_score_llm": 0.8},
                "risk_flags": [],
            }]
        }]
        records = build_event_calibration_records(ledger_rows)
        self.assertEqual(records[0]["outcome"], 1)
        self.assertEqual(records[0]["rule_score"], 0.4)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weights.json"
            path.write_text(json.dumps({"event_llm_calibration": {"llm_share": 0.4}}), encoding="utf-8")
            self.assertEqual(load_event_llm_share(path), 0.4)

    def test_hotspot_requires_two_existing_evidence_references(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_analyzer import normalize_hotspots

        result = normalize_hotspots(
            {"hotspots": [
                {"theme": "有效热点", "industries": ["半导体"], "confidence": 0.8, "evidence_refs": ["n1", "n2"]},
                {"theme": "证据不足", "industries": ["软件"], "confidence": 0.9, "evidence_refs": ["n1"]},
            ]},
            valid_refs={"n1", "n2"},
        )

        self.assertEqual([item["theme"] for item in result], ["有效热点"])

    def test_hotspot_prompt_includes_macro_and_stock_news(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_analyzer import analyze_hotspots

        class Client:
            def __init__(self):
                self.prompt = ""

            def analyze(self, prompt):
                self.prompt = prompt
                return {"status": "failed", "output_valid": False, "error": "test"}

        client = Client()
        analyze_hotspots(
            macro_news={
                "items": [{"event_id": "m1", "title": "宏观利好"}],
                "stock_news": [{"event_id": "s1", "title": "个股订单增长"}],
            },
            candidates=[],
            as_of="2026-09-08",
            client=client,
        )

        self.assertIn("个股订单增长", client.prompt)
        self.assertIn("s1", client.prompt)

    def test_hotspot_mapper_uses_only_real_constituents(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots

        result = validate_and_expand_hotspots(
            [{"theme": "算力", "industries": ["半导体"], "evidence_refs": ["n1", "n2"]}],
            focus_universe={"半导体": [
                {"code": "688001", "name": "甲"}, {"code": "688002", "name": "乙"}, {"code": "688003", "name": "丙"},
            ]},
            rows=[{"code": "688001", "name": "甲", "price": 10}],
        )

        self.assertEqual(result["hotspots"][0]["status"], "confirmed")
        self.assertEqual({item["code"] for item in result["rows"]}, {"688001", "688002", "688003"})
        self.assertTrue(all("llm_hotspot" in item["candidate_sources"] for item in result["rows"]))

    def test_hotspot_mapper_matches_existing_row_industry_tags_without_catalog(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots

        rows = [
            {"code": "600001", "name": "甲", "industry": "半导体"},
            {"code": "600002", "name": "乙", "industries": ["半导体", "芯片"]},
            {"code": "600003", "name": "丙", "focus_industries": ["半导体"]},
            {"code": "600004", "name": "丁", "industry": "银行"},
        ]
        result = validate_and_expand_hotspots(
            [{"theme": "算力", "industries": ["半导体"], "evidence_refs": ["n1", "n2"]}],
            rows=rows,
        )

        self.assertEqual(result["hotspots"][0]["status"], "confirmed")
        self.assertEqual({item["code"] for item in result["rows"]}, {"600001", "600002", "600003"})


if __name__ == "__main__":
    unittest.main()
