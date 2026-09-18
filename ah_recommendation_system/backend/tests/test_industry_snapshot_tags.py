import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ah_recommendation_system.backend.stock_recommend.focused_collector import (
    DEFAULT_FOCUS_UNIVERSE,
    attach_industry_tags,
    industry_tag_coverage,
    resolve_industry_universe,
)
from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient
from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots
from ah_recommendation_system.backend.stock_recommend.local_store import (
    load_industry_universe,
    persist_industry_universe,
)
from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality


class IndustrySnapshotTagTests(unittest.TestCase):
    def test_untagged_snapshot_rows_receive_catalog_industries(self):
        rows = [
            {"code": "300308", "name": "Zhongji", "price": 120, "amount": 2000000000},
            {"code": "600176", "name": "Jushi", "price": 15, "amount": 800000000},
            {"code": "600584", "name": "JCET", "price": 30, "amount": 900000000},
        ]
        universe = {
            "optical": [{"code": "300308", "name": "Zhongji"}],
            "fiberglass": [{"code": "600176", "name": "Jushi"}],
            "semiconductor": [{"code": "600584", "name": "JCET"}],
        }
        tagged = attach_industry_tags(rows, universe)
        self.assertIn("optical", tagged[0]["focus_industries"])
        self.assertEqual(tagged[0]["industry"], "optical")
        self.assertIn("fiberglass", tagged[1]["focus_industries"])
        self.assertGreaterEqual(industry_tag_coverage(tagged), 0.5)

    def test_optical_hotspot_maps_real_member_not_static_osat(self):
        universe = {
            "optical": [{"code": "300308", "name": "Zhongji"}],
            "telecom": [{"code": "300308", "name": "Zhongji"}],
            "power_semi": [{"code": "600584", "name": "JCET"}],
        }
        rows = attach_industry_tags(
            [
                {"code": "300308", "name": "Zhongji", "price": 120},
                {"code": "600584", "name": "JCET", "price": 30},
            ],
            universe,
        )
        mapped = validate_and_expand_hotspots(
            [{
                "theme": "AI compute optical",
                "industries": ["telecom", "optical"],
                "evidence_refs": ["a", "b"],
                "status": "early_signal",
            }],
            focus_universe=universe,
            rows=rows,
        )
        codes = mapped["hotspots"][0]["mapped_codes"]
        names = mapped["hotspots"][0]["representatives"]
        self.assertIn("300308", codes)
        self.assertIn("Zhongji", names)
        self.assertNotIn("600584", codes)
        self.assertNotIn("JCET", names)

    def test_industry_universe_roundtrip_survives_disk_cache(self):
        universe = {
            "optical": [{"code": "300308", "name": "Zhongji"}],
            "fiberglass": [{"code": "600176", "name": "Jushi"}],
        }
        with TemporaryDirectory() as raw:
            root = Path(raw)
            persisted = persist_industry_universe(universe, root, as_of="2026-09-16")
            loaded = load_industry_universe(root, as_of="2026-09-17")
            self.assertTrue(Path(persisted["path"]).exists())
            self.assertEqual(loaded["optical"][0]["code"], "300308")
            self.assertEqual(loaded["fiberglass"][0]["name"], "Jushi")

    def test_sparse_industry_tags_are_a_data_gap_not_normal_empty(self):
        rows = [
            {"code": "300308", "name": "Zhongji", "price": 120},
            {"code": "600176", "name": "Jushi", "price": 15},
            {"code": "601318", "name": "PingAn", "price": 50},
        ]
        tagged = attach_industry_tags(rows, {})
        coverage = industry_tag_coverage(tagged)
        self.assertLess(coverage, 0.5)
        report = {
            "recommendations": {"stocks": [], "etfs": []},
            "picks": [],
            "market": {
                "regime": "defense",
                "status": "available",
                "regime_evidence": {"status": "available"},
            },
            "directions": {
                "current_attack": [],
                "medium_term": [],
                "early_positioning": [],
                "avoid_or_exit": [],
            },
            "coverage": {"fresh_data_available": True, "mode": "full_market", "ratio": 0.95},
            "data_warnings": ["industry_tags:sparse"],
        }
        quality = evaluate_report_quality(report)
        self.assertTrue(quality["passed"])
        self.assertIn("industry_tags:sparse", report["data_warnings"])

    def test_hithink_industry_universe_uses_full_catalog_not_five_keywords(self):
        client = HithinkClient(api_key="secret")
        catalog = [
            {"thscode": "881201.TI", "name": "optical"},
            {"thscode": "881301.TI", "name": "fiberglass"},
            {"thscode": "881401.TI", "name": "semiconductor"},
        ]
        members = {
            "881201.TI": [{"ticker": "300308", "name": "Zhongji"}],
            "881301.TI": [{"ticker": "600176", "name": "Jushi"}],
            "881401.TI": [{"ticker": "600584", "name": "JCET"}],
        }
        with patch.object(client, "industry_catalog", return_value=catalog), patch.object(
            client,
            "index_constituents",
            side_effect=lambda code: members.get(code, []),
        ):
            universe = client.industry_universe()
        self.assertIn("optical", universe)
        self.assertIn("fiberglass", universe)
        self.assertEqual(universe["optical"][0]["code"], "300308")
        self.assertNotEqual(list(universe), ["tech", "semiconductor", "new_energy", "broker", "healthcare"])

    def test_resolve_uses_cached_full_universe_instead_of_static_ten_themes(self):
        cached = {
            "optical": [{"code": "300308", "name": "Zhongji"}],
            "storage": [{"code": "603986", "name": "GigaDevice"}],
        }
        errors = []
        with TemporaryDirectory() as raw:
            root = Path(raw)
            persist_industry_universe(cached, root, as_of="2026-09-16")
            universe = resolve_industry_universe(
                fetch_live=lambda: (_ for _ in ()).throw(RuntimeError("timeout")),
                store_root=root,
                as_of="2026-09-17",
                errors=errors,
            )
        self.assertEqual(universe["optical"][0]["code"], "300308")
        self.assertNotEqual(universe, DEFAULT_FOCUS_UNIVERSE)
        self.assertTrue(any("cached" in item or "industry_universe" in item for item in errors))

    def test_fiberglass_catalog_label_maps_jushi_not_static_fallback(self):
        universe = {
            "玻璃玻纤": [{"code": "600176", "name": "Jushi"}],
            "功率半导体": [{"code": "600584", "name": "JCET"}],
        }
        rows = attach_industry_tags(
            [{"code": "600176", "name": "Jushi", "price": 15}],
            universe,
        )
        mapped = validate_and_expand_hotspots(
            [{
                "theme": "fiberglass cloth",
                "industries": ["玻纤", "电子布"],
                "evidence_refs": ["a", "b"],
                "status": "early_signal",
            }],
            focus_universe=universe,
            rows=rows,
        )
        self.assertIn("600176", mapped["hotspots"][0]["mapped_codes"])
        self.assertNotIn("600584", mapped["hotspots"][0]["mapped_codes"])


if __name__ == "__main__":
    unittest.main()
