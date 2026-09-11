import tempfile
import unittest
from pathlib import Path

from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules


class TestLiveMonitorRepairs(unittest.TestCase):
    def test_nested_empty_snapshot_fields_roundtrip(self):
        from ah_recommendation_system.backend.stock_recommend.local_store import persist_snapshot, load_last_snapshot
        row = {"code": "600001", "source": "live", "provider_health": {}, "financial_records": [{"fields": {}}]}
        with tempfile.TemporaryDirectory() as tmp:
            persist_snapshot([row], Path(tmp), as_of="2026-09-11")
            restored = load_last_snapshot(Path(tmp))[0]
        self.assertEqual(restored["provider_health"], {})
        self.assertEqual(restored["financial_records"], row["financial_records"])

    def test_beijing_symbol_routed_to_bj(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import _thscode
        self.assertEqual(_thscode("920268"), "920268.BJ")
        self.assertEqual(_thscode("430047"), "430047.BJ")
        self.assertEqual(_thscode("600519"), "600519.SH")

    def test_defense_allows_only_verified_relative_leaders_and_caps_two(self):
        candidates = []
        for i in range(4):
            c = Candidate(code=f"60000{i}", name="test", quality_grade="A", composite=.75,
                          valid_dimensions={"trend", "price_volume", "relative_strength", "capital"},
                          factor_scores={"trend": .85, "relative_strength": .7},
                          evidence=[{"factor": key, "statement": key, "supports": True}
                                    for key in ("trend", "price_volume", "relative_strength", "capital")])
            candidates.append(c)
        result = select_by_rules(candidates, top_n_pick=5, market_regime={"regime": "defense", "status": "available"})
        self.assertEqual(len(result["picks"]), 2)
        self.assertIn("防守", result["market_view"])
        self.assertTrue(all(p["action"] == "WATCH" for p in result["picks"]))

    def test_defense_never_fills_quota_with_weak_or_missing_relative_strength(self):
        c = Candidate(code="600001", name="test", quality_grade="A", composite=.9,
                      valid_dimensions={"trend", "price_volume", "capital"}, factor_scores={"trend": .9})
        result = select_by_rules([c], market_regime={"regime": "defense", "status": "available"})
        self.assertEqual(result["picks"], [])
