import unittest


class TestRecommendationContracts(unittest.TestCase):
    def test_expired_evidence_is_excluded_and_quality_is_degraded(self):
        from ah_recommendation_system.backend.stock_recommend.contracts import (
            EvidenceItem,
            MarketSnapshot,
            Candidate,
        )

        snapshot = MarketSnapshot(as_of="2026-09-12T10:00:00+08:00", price_timestamp="2026-09-12T09:30:00+08:00")
        candidate = Candidate(
            symbol="600000",
            market="A",
            snapshot=snapshot,
            evidence=[
                EvidenceItem(
                    evidence_id="n1",
                    evidence_type="news",
                    source="test",
                    observed_at="2026-09-11T10:00:00+08:00",
                    valid_until="2026-09-12T09:00:00+08:00",
                    claim="old",
                )
            ],
            price=10.0,
        )

        result = candidate.quality_check()

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.active_evidence, [])
        self.assertIn("expired_evidence", result.reasons)

    def test_missing_price_timestamp_rejects_candidate(self):
        from ah_recommendation_system.backend.stock_recommend.contracts import Candidate, MarketSnapshot

        candidate = Candidate(symbol="00700", market="HK", snapshot=MarketSnapshot(as_of="2026-09-12T10:00:00+08:00"))
        result = candidate.quality_check()

        self.assertEqual(result.status, "rejected")
        self.assertIn("missing_price_timestamp", result.reasons)
