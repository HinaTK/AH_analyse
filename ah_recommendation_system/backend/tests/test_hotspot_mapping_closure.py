import unittest

from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import (
    apply_hotspot_mappings,
    validate_and_expand_hotspots,
)
from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules
from ah_recommendation_system.backend.stock_recommend.market_hotspots import summarize_hotspot_mapping


class HotspotMappingClosureTests(unittest.TestCase):
    def test_narrow_hotspot_does_not_match_broad_parent_industry(self):
        result = validate_and_expand_hotspots(
            [{"theme": "油运运价", "industries": ["油轮运输"], "evidence_refs": ["a", "b"]}],
            focus_universe={"航运": [{"code": "600150", "name": "中国船舶"}]},
        )
        self.assertEqual(result["candidate_mappings"], {})

    def test_mapping_is_returned_by_code_with_auditable_fields(self):
        result = validate_and_expand_hotspots(
            [{
                "theme": "油运运价",
                "industries": ["油轮运输"],
                "evidence_refs": ["a", "b"],
                "independent_source_count": 2,
                "status": "early_signal",
            }],
            focus_universe={"油轮运输": [{"code": "601872", "name": "招商轮船"}]},
        )
        mapping = result["candidate_mappings"]["601872"]
        self.assertEqual(mapping["matched_themes"], ["油运运价"])
        self.assertEqual(mapping["matched_industries"], ["油轮运输"])
        self.assertEqual(mapping["mapping_source"], "focus_universe")
        self.assertEqual(result["hotspots"][0]["mapped_codes"], ["601872"])

    def test_candidate_mappings_are_not_truncated_to_ten_representatives(self):
        members = [{"code": f"60{index:04d}", "name": f"成员{index}"} for index in range(12)]
        result = validate_and_expand_hotspots(
            [{"theme": "银行分红", "industries": ["银行"], "evidence_refs": ["a", "b"]}],
            focus_universe={"银行": members},
        )
        self.assertEqual(len(result["candidate_mappings"]), 12)

    def test_broad_new_energy_bucket_is_display_only_for_battery_hotspot(self):
        result = validate_and_expand_hotspots(
            [{"theme": "动力电池", "industries": ["动力电池"], "evidence_refs": ["a", "b"]}],
            focus_universe={"新能源": [{"code": "600900", "name": "长江电力"}]},
        )
        self.assertEqual(result["candidate_mappings"], {})

    def test_normalized_trusted_synonym_matches_without_matching_parent_bucket(self):
        result = validate_and_expand_hotspots(
            [{"theme": "油运", "industries": ["油轮运输（申万）"], "evidence_refs": ["a", "b"]}],
            focus_universe={
                "油运": [{"code": "601872", "name": "招商轮船"}],
                "石油石化": [{"code": "600028", "name": "中国石化"}],
            },
        )
        self.assertEqual(set(result["candidate_mappings"]), {"601872"})
        self.assertNotIn("600028", result["candidate_mappings"])

    def test_negative_stale_or_unknown_market_mapping_has_zero_score(self):
        candidate = Candidate(code="601872", name="招商轮船", factor_scores={"price_volume": .8})
        mapping = {
            "matched_themes": ["油运"], "matched_industries": ["油轮运输"],
            "evidence_refs": ["a", "b"], "mapping_sources": ["focus_universe"],
            "matches": [{"status": "confirmed", "direction": "negative", "evidence_refs": ["a", "b"], "independent_source_count": 2}],
        }
        apply_hotspot_mappings([candidate], {"601872": mapping})
        self.assertEqual(candidate.hotspot_score, 0.0)
        mapping["matches"][0]["direction"] = "positive"
        mapping["matches"][0]["freshness_status"] = "stale"
        apply_hotspot_mappings([candidate], {"601872": mapping})
        self.assertEqual(candidate.hotspot_score, 0.0)
        mapping["matches"][0]["freshness_status"] = "fresh"
        apply_hotspot_mappings([candidate], {"601872": mapping}, market_regime={"status": "unavailable"})
        self.assertEqual(candidate.hotspot_score, 0.0)

    def test_hotspot_bonus_reorders_eligible_without_changing_base_score(self):
        def candidate(code, composite):
            return Candidate(
                code=code,
                name=code,
                composite=composite,
                quality_grade="A",
                valid_dimensions={"trend", "price_volume", "event"},
                evidence=[
                    {"factor": "trend", "supports": True, "statement": "trend"},
                    {"factor": "price_volume", "supports": True, "statement": "volume"},
                    {"factor": "event", "supports": True, "statement": "event"},
                ],
                factor_scores={"trend": .8, "price_volume": .8},
                hotspot_score=0.0,
            )

        plain = candidate("000001", .600)
        hot = candidate("000002", .595)
        hot.hotspot_themes = ["油运运价"]
        hot.hotspot_score = .15
        result = select_by_rules([plain, hot], minimum_score=.55)
        self.assertEqual(result["picks"][0]["code"], "000002")
        self.assertEqual(result["picks"][0]["score"], 59.5)
        self.assertEqual(result["picks"][0]["hotspot_score"], .15)

    def test_hotspot_bonus_cannot_cross_eligibility_threshold(self):
        candidate = Candidate(
            code="000001", name="候选", composite=.54, quality_grade="A",
            valid_dimensions={"trend", "price_volume", "event"}, hotspot_score=.15,
            evidence=[
                {"factor": "trend", "supports": True, "statement": "trend"},
                {"factor": "price_volume", "supports": True, "statement": "volume"},
                {"factor": "event", "supports": True, "statement": "event"},
            ],
        )
        self.assertEqual(select_by_rules([candidate], minimum_score=.55)["picks"], [])

    def test_mapping_summary_distinguishes_recommended_observation_and_unmapped(self):
        summary = summarize_hotspot_mapping(
            [{"theme": "油运"}, {"theme": "银行"}, {"theme": "电池"}],
            candidate_mappings={
                "601872": {"matched_themes": ["油运"]},
                "002142": {"matched_themes": ["银行"]},
            },
            picks=[{"code": "601872"}],
        )
        self.assertEqual([row["outcome"] for row in summary["themes"]], ["recommended", "mapped_observation", "unmapped"])


if __name__ == "__main__":
    unittest.main()
