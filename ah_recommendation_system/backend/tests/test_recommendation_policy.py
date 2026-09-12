import math
import unittest

from stock_recommend.recommendation_policy import build_decisions, constrain_portfolio


def candidate(candidate_id="c1", symbol="000001.SZ", theme="科技", **overrides):
    factors = {
        name: {"score": score, "confidence": 0.9, "completeness": 1.0, "evidence_refs": ["e1"]}
        for name, score in {
            "quality": 82, "value": 72, "trend": 86, "flow": 80, "catalyst": 75, "risk": 20
        }.items()
    }
    item = {
        "candidate_id": candidate_id, "symbol": symbol, "market": "A",
        "instrument_type": "stock", "theme": theme, "price": 10.0,
        "benchmark": "000300.SH", "source_modules": ["scanner"],
        "evidence": [{"evidence_id": "e1", "evidence_type": "market_data", "reliability": "high",
                      "direction": "support", "active": True, "claim": "量价确认"}],
        "factors": factors,
        "quality": {"status": "passed", "reasons": [], "active_evidence": ["e1"]},
        "signals": {"slow_variable_improving": True, "trend_confirmed": True,
                    "relative_strength_improving": True, "volume_confirmed": True,
                    "breadth_confirmed": True, "p0": False, "invalidated": False,
                    "support_price": 9.5, "stop_price": 9.0, "liquidity_ok": True,
                    "fx_available": True},
    }
    item.update(overrides)
    return item


class RecommendationPolicyTests(unittest.TestCase):
    def test_confirmed_candidate_becomes_current_attack_with_auditable_fields(self):
        decision = build_decisions([candidate()], as_of="2026-09-12T10:00:00+08:00")[0]
        self.assertEqual("当前主攻", decision["state"])
        self.assertEqual("有效", decision["status_label"])
        self.assertTrue(decision["selected"])
        self.assertEqual({"short", "swing", "medium"}, set(decision["horizon_scores"]))
        self.assertEqual("recommendation-policy-v1", decision["model_version"])
        self.assertEqual(9.0, decision["execution_conditions"]["stop_price"])
        self.assertIn("e1", decision["evidence_refs"])
        self.assertIn("1-5", decision["verification_window"])

    def test_score_alone_cannot_promote_and_missing_values_are_penalized(self):
        weak = candidate(signals={**candidate()["signals"], "volume_confirmed": False})
        missing = candidate(candidate_id="c2", symbol="000002.SZ")
        missing["factors"]["trend"] = {"score": math.nan, "confidence": 1, "completeness": 1,
                                         "evidence_refs": []}
        missing["factors"]["flow"] = {"score": None, "confidence": 1, "completeness": 1,
                                        "evidence_refs": []}
        decisions = build_decisions([weak, missing], as_of="2026-09-12")
        self.assertNotIn(decisions[0]["state"], {"当前主攻", "右侧确认"})
        self.assertIsNone(decisions[1]["horizon_scores"]["short"]["factors"]["trend"])
        self.assertLess(decisions[1]["horizon_scores"]["short"]["score"],
                        decisions[0]["horizon_scores"]["short"]["score"])

    def test_quality_and_p0_gates_are_conservative(self):
        degraded = candidate(quality={"status": "degraded", "reasons": ["coverage"], "active_evidence": ["e1"]})
        rejected = candidate(candidate_id="c2", quality={"status": "rejected", "reasons": ["bad"], "active_evidence": []})
        p0 = candidate(candidate_id="c3", signals={**candidate()["signals"], "p0": True})
        states = [d["state"] for d in build_decisions([degraded, rejected, p0], as_of="2026-09-12")]
        self.assertEqual("降级观察", states[0])
        self.assertEqual("回避", states[1])
        self.assertEqual("回避", states[2])

    def test_invalidation_wins_and_conflicting_evidence_is_retained(self):
        item = candidate(signals={**candidate()["signals"], "invalidated": True})
        item["evidence"].append({"evidence_id": "e2", "evidence_type": "filing", "reliability": "high",
                                 "direction": "contradict", "active": True, "claim": "基本面证伪"})
        decision = build_decisions([item], as_of="2026-09-12")[0]
        self.assertEqual("已失效", decision["state"])
        self.assertEqual("已失效", decision["status_label"])
        self.assertFalse(decision["selected"])
        self.assertEqual("e2", decision["contradictions"][0]["evidence_id"])

    def test_ambush_requires_explicit_slow_variable_and_has_bounded_trial_size(self):
        signals = {**candidate()["signals"], "trend_confirmed": False,
                   "relative_strength_improving": False, "volume_confirmed": False}
        ambush = build_decisions([candidate(signals=signals)], as_of="2026-09-12")[0]
        self.assertEqual("可小仓埋伏", ambush["state"])
        self.assertGreaterEqual(ambush["trial_position_limit"], 0.1)
        self.assertLessEqual(ambush["trial_position_limit"], 0.3)
        signals["slow_variable_improving"] = False
        waiting = build_decisions([candidate(signals=signals)], as_of="2026-09-12")[0]
        self.assertEqual("等待触发", waiting["state"])
        self.assertIsNone(waiting["trial_position_limit"])

    def test_portfolio_deduplicates_and_applies_security_theme_and_cash_caps(self):
        items = [candidate("a", "AAA", "科技"), candidate("b", "AAA", "科技"),
                 candidate("c", "CCC", "科技"), candidate("d", "DDD", None),
                 candidate("e", "EEE", None)]
        decisions = build_decisions(items, as_of="2026-09-12")
        result = constrain_portfolio(decisions, items)
        selected = [d for d in result["decisions"] if d["selected"]]
        self.assertEqual(1, sum(d["symbol"] == "AAA" for d in selected))
        self.assertTrue(all(d["model_weight"] <= 0.2 for d in selected))
        theme_weights = result["constraints"]["theme_weights"]
        self.assertTrue(all(weight <= 0.4 for weight in theme_weights.values()))
        self.assertGreaterEqual(result["constraints"]["cash_weight"], 0)
        self.assertEqual("unassessed_missing_data", result["constraints"]["correlation_status"])
        self.assertIn("research basket", result["constraints"]["scope"])


if __name__ == "__main__":
    unittest.main()
