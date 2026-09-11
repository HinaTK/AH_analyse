from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import fetch_market_snapshot as snapshot


class ThemeFallbackCandidateTests(unittest.TestCase):
    def write_map(self, rows: list[dict]) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "stock_industry_map.jsonl"
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        return path

    def test_selects_direct_theme_candidates_deterministically(self) -> None:
        path = self.write_map(
            [
                {
                    "code": "300502.SZ",
                    "name": "新易盛",
                    "sub_industry": "光模块/CPO",
                    "direct_themes": ["CPO/光通信"],
                    "default_role": "高弹性/低位扩散",
                },
                {
                    "code": "300308.SZ",
                    "name": "中际旭创",
                    "sub_industry": "光模块/CPO",
                    "direct_themes": ["CPO/光通信"],
                    "default_role": "产业龙头/中军",
                },
                {
                    "code": "600030.SH",
                    "name": "中信证券",
                    "sub_industry": "证券",
                    "direct_themes": ["券商"],
                    "default_role": "产业龙头/中军",
                },
                {
                    "code": "01801.HK",
                    "name": "信达生物",
                    "sub_industry": "港股创新药",
                    "direct_themes": ["创新药"],
                    "default_role": "产业龙头/中军",
                },
            ]
        )

        selected = snapshot.select_mapped_stock_candidates(
            themes=["CPO"],
            stock_map_path=path,
            max_stocks=5,
        )

        self.assertEqual([candidate["code"] for candidate in selected], ["300308.SZ", "300502.SZ"])
        self.assertNotIn("01801.HK", [candidate["code"] for candidate in selected])
        self.assertIn("CPO/光通信", selected[0]["matched_themes"])
        self.assertEqual(selected[0]["execution_status"], "开盘后确认候选")

    def test_build_snapshot_uses_theme_fallback_when_dynamic_candidates_empty(self) -> None:
        path = self.write_map(
            [
                {
                    "code": "300308.SZ",
                    "name": "中际旭创",
                    "sub_industry": "光模块/CPO",
                    "direct_themes": ["CPO/光通信"],
                    "default_role": "产业龙头/中军",
                }
            ]
        )

        quote = snapshot.Quote(
            code="sz300308",
            configured_name="中际旭创",
            name="中际旭创",
            price=100.0,
            pct=1.5,
            open=99.0,
            prev_close=98.5,
            high=101.0,
            low=98.0,
            amount_yi=12.3,
            quote_date="2026-07-01",
            quote_time="09:45:00",
        )

        with patch.object(snapshot, "fetch_sina_quotes", side_effect=[([], None), ([quote], None)]), patch.object(
            snapshot, "fetch_stock_candidates", return_value=([], "dynamic unavailable")
        ):
            payload = snapshot.build_snapshot(
                a_codes={},
                hk_codes={},
                top=0,
                skip_boards=True,
                include_hk=False,
                stock_keywords=[],
                max_stocks=5,
                top_stock_boards=0,
                stock_candidate_mode="auto",
                fallback_themes=["CPO"],
                stock_map_path=path,
            )

        self.assertEqual(len(payload["stock_candidates"]), 1)
        candidate = payload["stock_candidates"][0]
        self.assertEqual(candidate["code"], "sz300308")
        self.assertIn("映射库fallback", candidate["source"])
        self.assertIn("开盘后确认候选", candidate["note"])
        self.assertIn("mapped theme-fit fallback used", payload["stock_candidate_error"])


if __name__ == "__main__":
    unittest.main()
