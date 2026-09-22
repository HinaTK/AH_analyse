import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_load_previous_close_skips_incomplete_intraday_overwrite(self):
        from ah_recommendation_system.backend.stock_recommend.local_store import load_previous_close_snapshot, persist_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_snapshot(
                [{"code": str(600000 + i).zfill(6), "name": "A", "price": 10, "pe": 8, "price_as_of": "2026-09-14", "source": "hithink_financial_api"} for i in range(2000)],
                root,
                as_of="2026-09-14",
            )
            persist_snapshot(
                [{"code": "000001", "name": "残缺", "price": 10, "price_as_of": "2026-09-15", "source": "focused_tencent_quotes"} for _ in range(110)],
                root,
                as_of="2026-09-15",
            )
            rows = load_previous_close_snapshot(root, as_of="2026-09-15", min_rows=1000)
            self.assertGreaterEqual(len(rows), 2000)
            self.assertEqual(rows[0]["source"], "previous_close")
            self.assertEqual(rows[0]["original_source"], "hithink_financial_api")
            self.assertFalse(rows[0]["stale"])

    def test_load_previous_close_accepts_explicit_observed_at_timestamp(self):
        from ah_recommendation_system.backend.stock_recommend.local_store import load_previous_close_snapshot, persist_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observed_at = int(__import__("datetime").datetime(2026, 9, 18, 17, 30).timestamp() * 1000)
            persist_snapshot(
                [
                    {
                        "code": str(600000 + i).zfill(6),
                        "name": "A",
                        "price": 10,
                        "observed_at": observed_at,
                        "source": "hithink_financial_api",
                    }
                    for i in range(1200)
                ],
                root,
                as_of="2026-09-18",
            )

            rows = load_previous_close_snapshot(root, as_of="2026-09-21", min_rows=1000)

            self.assertEqual(len(rows), 1200)
            self.assertEqual(rows[0]["price_as_of"], "2026-09-18")



    def test_persist_snapshot_skips_below_min_rows(self):
        from ah_recommendation_system.backend.stock_recommend.local_store import persist_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = persist_snapshot(
                [{"code": "000001", "name": "thin", "price": 10, "source": "hithink_financial_api"}],
                root,
                as_of="2026-09-15",
                min_rows=1000,
            )
            self.assertEqual(result["skipped"], "below_min_rows")
            self.assertFalse((root / "data" / "market_store" / "a_share_spot_20260915.parquet").exists())


    def test_previous_close_snapshot_job_persists_full_market_without_push(self):
        from ah_recommendation_system.backend.stock_recommend import run as run_module

        rows = [
            {"code": str(600000 + i).zfill(6), "name": "A", "price": 10, "price_as_of": "2026-09-15", "source": "hithink_financial_api"}
            for i in range(1200)
        ]
        with patch("ah_recommendation_system.backend.stock_recommend.run.DEFAULT_COLLECTION_RUNTIME.run") as collect_run, patch(
            "ah_recommendation_system.backend.stock_recommend.run._enrich_with_daily_features",
            return_value=0,
        ), patch(
            "ah_recommendation_system.backend.stock_recommend.run.persist_snapshot",
            return_value={"parquet_path": "x.parquet"},
        ) as persist:
            collect_run.return_value = {
                "fundamental": type("R", (), {"status": "ok", "value": {"rows": rows, "source": "hithink_financial_api", "as_of": "2026-09-15"}, "error": None, "error_kind": None})()
            }
            result = run_module.run_previous_close_snapshot(mock=False, min_rows=1000, require_window=False)

        self.assertTrue(result["ok"])
        self.assertTrue(result["persisted"])
        self.assertIsNone(result["push"])
        self.assertEqual(result["row_count"], 1200)
        persist.assert_called_once()
        self.assertEqual(persist.call_args.kwargs["min_rows"], 1000)
        self.assertEqual(persist.call_args.kwargs["as_of"], "2026-09-15")


    def test_load_today_close_requires_post_close_mtime(self):
        from datetime import datetime
        import os
        from ah_recommendation_system.backend.stock_recommend.local_store import (
            load_previous_close_snapshot,
            persist_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_snapshot(
                [{"code": str(600000 + i).zfill(6), "name": "A", "price": 10, "price_as_of": "2026-09-15", "source": "hithink_financial_api"} for i in range(1200)],
                root,
                as_of="2026-09-15",
            )
            parquet = root / "data" / "market_store" / "a_share_spot_20260915.parquet"
            morning = datetime(2026, 9, 15, 10, 22).timestamp()
            os.utime(parquet, (morning, morning))
            skipped = load_previous_close_snapshot(
                root,
                as_of="2026-09-15",
                min_rows=1000,
                include_as_of=True,
                min_mtime=datetime(2026, 9, 15, 17, 0),
            )
            self.assertEqual(skipped, [])
            evening = datetime(2026, 9, 15, 17, 30).timestamp()
            os.utime(parquet, (evening, evening))
            rows = load_previous_close_snapshot(
                root,
                as_of="2026-09-15",
                min_rows=1000,
                include_as_of=True,
                min_mtime=datetime(2026, 9, 15, 17, 0),
            )
            self.assertGreaterEqual(len(rows), 1200)
