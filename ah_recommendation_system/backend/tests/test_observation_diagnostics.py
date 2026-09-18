import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import apply_hotspot_mappings
from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots
from ah_recommendation_system.backend.stock_recommend.local_store import load_previous_close_snapshot, persist_snapshot
from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules


def _verified_candidate(code: str = "601872", *, rejected: bool = True) -> Candidate:
    candidate = Candidate(
        code=code,
        name="招商轮船",
        price=10.0,
        price_as_of="2026-09-17",
        composite=0.52 if rejected else 0.80,
        quality_grade="C" if rejected else "A",
        valid_dimensions={"trend", "price_volume", "event"},
        factor_scores={"trend": 0.75, "price_volume": 0.80},
        evidence=[
            {"factor": "trend", "statement": "60日趋势为正", "value": 12, "as_of": "2026-09-17", "supports": True},
            {"factor": "price_volume", "statement": "成交额已记录", "value": 200000000, "as_of": "2026-09-17", "supports": True},
            {"factor": "event", "statement": "油运运价催化", "as_of": "2026-09-17", "supports": True},
        ],
        rejection_reasons=["quality:正式推荐要求质量A或B"] if rejected else [],
    )
    apply_hotspot_mappings(
        [candidate],
        {code: {
            "matched_themes": ["油运运价"],
            "matched_industries": ["油轮运输"],
            "evidence_refs": ["news-1", "news-2"],
            "mapping_sources": ["focus_universe"],
            "match_level": "direct",
            "matches": [{
                "status": "market_confirmed",
                "direction": "positive",
                "evidence_refs": ["news-1", "news-2"],
                "independent_source_count": 2,
            }],
        }},
        as_of="2026-09-17",
    )
    return candidate


class ObservationDiagnosticsTests(unittest.TestCase):
    def test_verified_observation_has_contract_and_no_role(self):
        candidate = _verified_candidate()
        result = select_by_rules([candidate], top_n_pick=0, coverage_mode="full_market")
        self.assertTrue(result["observation_pool_verified"])
        self.assertEqual(len(result["observation_pool"]), 1)
        item = result["observation_pool"][0]
        self.assertEqual(
            set(item),
            {
                "code", "name", "evidence", "rejection_reasons", "hotspot_themes",
                "hotspot_match_level", "hotspot_evidence", "candidate_sources", "price_as_of",
                "inclusion_reason", "pending_confirmation", "trigger", "invalidation",
            },
        )
        self.assertNotIn("role", item)
        self.assertEqual(result["selection_diagnostics"]["observation_count"], 1)

    def test_empty_reason_prioritizes_data_gap_and_has_diagnostics(self):
        result = select_by_rules([], coverage_mode="focused_fallback")
        self.assertEqual(result["empty_reason_code"], "data_insufficient")
        self.assertTrue(result["empty_reason"])
        diagnostics = result["selection_diagnostics"]
        for key in (
            "scan_as_of", "price_as_of", "coverage_mode", "scanned_count", "candidate_count",
            "evaluated_count", "eligible_count", "selected_count", "observation_count",
            "mapping_gaps", "rejection_summary",
        ):
            self.assertIn(key, diagnostics)

    def test_previous_close_without_explicit_quote_date_is_not_marked_verified(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            persist_snapshot(
                [
                    {"code": str(600000 + index).zfill(6), "name": "X", "price": 10,
                     "source": "hithink_financial_api"}
                    for index in range(1000)
                ],
                root,
                as_of="2026-09-16",
            )
            self.assertEqual(
                load_previous_close_snapshot(root, as_of="2026-09-18", min_rows=1000),
                [],
            )

    def test_previous_close_uses_explicit_quote_date(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            persist_snapshot(
                [
                    {"code": str(600000 + index).zfill(6), "name": "X", "price": 10,
                     "price_as_of": "2026-09-17", "source": "hithink_financial_api"}
                    for index in range(1000)
                ],
                root,
                as_of="2026-09-17",
            )
            rows = load_previous_close_snapshot(root, as_of="2026-09-18", min_rows=1000)
            self.assertEqual(len(rows), 1000)
            self.assertFalse(rows[0]["stale"])
            self.assertEqual(rows[0]["price_as_of"], "2026-09-17")

    def test_previous_close_label_without_quote_date_remains_unknown(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            persist_snapshot(
                [
                    {"code": str(600000 + index).zfill(6), "name": "X", "price": 10,
                     "quote_basis": "previous_close", "source": "hithink_financial_api"}
                    for index in range(1000)
                ],
                root,
                as_of="2026-09-17",
            )
            self.assertEqual(
                load_previous_close_snapshot(root, as_of="2026-09-18", min_rows=1000),
                [],
            )

    def test_hotspot_mapping_without_catalyst_reference_is_discarded(self):
        mapped = validate_and_expand_hotspots(
            [{"theme": "油运运价", "industries": ["油轮运输"], "status": "early_signal"}],
            focus_universe={"油轮运输": [{"code": "601872", "name": "招商轮船"}]},
        )
        self.assertEqual(mapped["candidate_mappings"], {})
        self.assertEqual(mapped["hotspots"][0]["status"], "discarded")

    def test_current_run_without_mapping_clears_prior_verified_mapping(self):
        candidate = _verified_candidate()
        apply_hotspot_mappings([candidate], {}, as_of="2026-09-18")
        result = select_by_rules([candidate], top_n_pick=0, coverage_mode="full_market")
        self.assertFalse(candidate.hotspot_mapping_verified)
        self.assertEqual(result["observation_pool"], [])
        self.assertEqual(candidate.hotspot_themes, [])

    def test_observation_rejects_negative_trend_catalyst_and_p0(self):
        trend = _verified_candidate("601872")
        trend.return_20d_pct = -0.1
        catalyst = _verified_candidate("601873")
        catalyst.evidence[-1]["supports"] = False
        p0 = _verified_candidate("601874")
        p0.llm_risks = ["公司被立案调查"]

        result = select_by_rules(
            [trend, catalyst, p0], top_n_pick=0, coverage_mode="full_market"
        )
        self.assertFalse(result["observation_pool_verified"])
        self.assertEqual(result["observation_pool"], [])

    def test_unknown_market_state_is_data_insufficient(self):
        result = select_by_rules(
            [_verified_candidate()],
            top_n_pick=0,
            coverage_mode="full_market",
            market_regime={"regime": "unknown", "status": "unavailable"},
        )
        self.assertEqual(result["empty_reason_code"], "data_insufficient")


if __name__ == "__main__":
    unittest.main()
