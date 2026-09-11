import tempfile
import unittest
from pathlib import Path

from ah_recommendation_system.backend.stock_recommend.local_store import load_last_snapshot, persist_snapshot


class TestSnapshotProvenance(unittest.TestCase):
    def test_mock_data_never_becomes_fresh_live_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_snapshot([{"code": "600001", "source": "mock", "price": 10}], root, as_of="2026-09-10")
            self.assertEqual(load_last_snapshot(root, max_age_seconds=300), [])

    def test_refreshing_stale_file_does_not_remove_stale_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_snapshot([{"code": "600001", "source": "last_good_snapshot", "stale": True}], root, as_of="2026-09-10")
            result = load_last_snapshot(root, max_age_seconds=300)
            self.assertTrue(result[0]["stale"])

    def test_cache_retains_original_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_snapshot([{"code": "600001", "source": "tencent"}], root, as_of="2026-09-10")
            result = load_last_snapshot(root, max_age_seconds=300)
            self.assertEqual(result[0]["original_source"], "tencent")
