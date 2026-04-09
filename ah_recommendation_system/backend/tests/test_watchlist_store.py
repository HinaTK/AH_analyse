import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ah_recommendation_system.backend.watchlist.watchlist_store import WatchlistStore


class TestWatchlistStore(unittest.TestCase):
    def test_add_list_remove_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))

            store.add_symbol("601398.SH")
            store.add_symbol("601398.SH")
            store.add_symbol("002594.SZ")

            items = store.list_symbols()
            self.assertEqual(
                items,
                [
                    {
                        "a_code": "601398.SH",
                        "h_code": "1398.HK",
                        "name": "工商银行",
                    },
                    {
                        "a_code": "002594.SZ",
                        "h_code": "1211.HK",
                        "name": "比亚迪",
                    },
                ],
            )

            store.remove_symbol("601398.SH")
            items = store.list_symbols()
            self.assertEqual(
                items,
                [
                    {
                        "a_code": "002594.SZ",
                        "h_code": "1211.HK",
                        "name": "比亚迪",
                    }
                ],
            )

    def test_list_symbols_uses_saved_snapshot_when_lookup_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))

            with (
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_ah_pairs",
                    return_value={"601398.SH": "1398.HK"},
                ),
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_stock_name",
                    return_value="工商银行",
                ),
            ):
                store.add_symbol("601398")

            with (
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_ah_pairs",
                    return_value={},
                ),
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_stock_name",
                    return_value="",
                ),
            ):
                self.assertEqual(
                    store.list_symbols(),
                    [
                        {
                            "a_code": "601398.SH",
                            "h_code": "1398.HK",
                            "name": "工商银行",
                        }
                    ],
                )

    def test_list_symbols_migrates_legacy_payload_to_saved_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))
            store._file_path.parent.mkdir(parents=True, exist_ok=True)
            store._file_path.write_text('{"symbols": ["601398.SH"]}', encoding="utf-8")

            with (
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_ah_pairs",
                    return_value={"601398.SH": "1398.HK"},
                ),
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_stock_name",
                    return_value="工商银行",
                ),
            ):
                self.assertEqual(
                    store.list_symbols(),
                    [
                        {
                            "a_code": "601398.SH",
                            "h_code": "1398.HK",
                            "name": "工商银行",
                        }
                    ],
                )

            self.assertEqual(
                json.loads(store._file_path.read_text(encoding="utf-8")),
                {
                    "symbols": [
                        {
                            "a_code": "601398.SH",
                            "h_code": "1398.HK",
                            "name": "工商银行",
                        }
                    ]
                },
            )

            with (
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_ah_pairs",
                    return_value={"601398.SH": "9999.HK"},
                ),
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_stock_name",
                    return_value="新名字",
                ),
            ):
                self.assertEqual(
                    store.list_symbols(),
                    [
                        {
                            "a_code": "601398.SH",
                            "h_code": "1398.HK",
                            "name": "工商银行",
                        }
                    ],
                )

    def test_list_symbols_raises_without_overwriting_legacy_payload_when_snapshot_incomplete(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))
            store._file_path.parent.mkdir(parents=True, exist_ok=True)
            original = '{"symbols": ["601398.SH"]}'
            store._file_path.write_text(original, encoding="utf-8")

            with (
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_ah_pairs",
                    return_value={},
                ),
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_stock_name",
                    return_value="",
                ),
            ):
                with self.assertRaises(ValueError):
                    store.list_symbols()

            self.assertEqual(store._file_path.read_text(encoding="utf-8"), original)

    def test_add_symbol_raises_on_malformed_json_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))
            store._file_path.write_text("{not valid json", encoding="utf-8")
            original = store._file_path.read_text(encoding="utf-8")

            with self.assertRaises(ValueError):
                store.add_symbol("601398.SH")

            self.assertEqual(store._file_path.read_text(encoding="utf-8"), original)

    def test_list_symbols_raises_on_invalid_payload_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))
            store._file_path.write_text('{"symbols": {}}', encoding="utf-8")

            with self.assertRaises(ValueError):
                store.list_symbols()

    def test_list_symbols_raises_on_invalid_symbol_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))
            store._file_path.write_text(
                '{"symbols": ["601398.SH", 123]}', encoding="utf-8"
            )

            with self.assertRaises(ValueError):
                store.list_symbols()

    def test_list_symbols_raises_on_object_payload_with_empty_required_fields(self):
        cases = [
            {"a_code": "601398.SH", "h_code": "", "name": "工商银行"},
            {"a_code": "601398.SH", "h_code": "1398.HK", "name": ""},
        ]

        for payload in cases:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as tmp:
                    store = WatchlistStore(root_dir=Path(tmp))
                    store._file_path.write_text(
                        json.dumps({"symbols": [payload]}, ensure_ascii=False),
                        encoding="utf-8",
                    )

                    with self.assertRaises(ValueError):
                        store.list_symbols()

    def test_add_symbol_skips_write_when_snapshot_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))

            with (
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_ah_pairs",
                    return_value={"601398.SH": "1398.HK"},
                ),
                mock.patch(
                    "ah_recommendation_system.backend.watchlist.watchlist_store.get_stock_name",
                    return_value="",
                ),
            ):
                store.add_symbol("601398.SH")

            self.assertFalse(store._file_path.exists())


if __name__ == "__main__":
    unittest.main()
