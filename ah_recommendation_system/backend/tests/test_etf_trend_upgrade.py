import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class TestEtfTextNormalization(unittest.TestCase):
    def test_normalize_display_text_repairs_common_mojibake(self):
        from ah_recommendation_system.backend.etf_sector.ths_sources import (
            normalize_concept_summary_ths,
            normalize_display_text,
        )

        self.assertEqual(normalize_display_text("ä¸­è¯çº¢å©ETF"), "中证红利ETF")
        self.assertEqual(normalize_display_text("ETF"), "ETF")

        df = pd.DataFrame(
            [
                [
                    "2026-04-16",
                    "äººå·¥æºè½",
                    "æºå¨äººä¸ç®åæ¦å¿µåå¼¹",
                    "ä¸­éæ­å",
                    "42",
                ]
            ]
        )

        items = normalize_concept_summary_ths(df, limit=5)
        self.assertEqual(items[0]["concept"], "人工智能")
        self.assertEqual(items[0]["headline"], "机器人与算力概念反弹")
        self.assertEqual(items[0]["leader"], "中际旭创")
        self.assertEqual(items[0]["constituents"], 42)


class TestEtfTrendHistoryHelpers(unittest.TestCase):
    def test_load_etf_trend_history_skips_missing_reports(self):
        from ah_recommendation_system.backend.etf_sector.etf_trend_history import (
            load_etf_trend_history,
        )
        from ah_recommendation_system.backend.reporting.report_store import ReportStore

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports_dir = root / "data" / "daily_reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            report_with_trend = {
                "generated_at": "2026-04-15 15:00:00",
                "etf_sector": {
                    "etf_trend": {
                        "generated_at": "2026-04-15 15:00:00",
                        "summary": {
                            "regime_label": "偏强轮动",
                            "avg_score": 67.2,
                            "recommended_count": 2,
                            "watch_count": 1,
                            "avoid_count": 0,
                            "strongest_etfs": [
                                {
                                    "code": "510300",
                                    "name": "沪深300ETF",
                                    "trend_score": 79.1,
                                }
                            ],
                        },
                    }
                },
            }
            report_without_trend = {
                "generated_at": "2026-04-14 15:00:00",
                "etf_sector": {},
            }

            (reports_dir / "report_20260415.json").write_text(
                json.dumps(report_with_trend, ensure_ascii=False),
                encoding="utf-8",
            )
            (reports_dir / "report_20260414.json").write_text(
                json.dumps(report_without_trend, ensure_ascii=False),
                encoding="utf-8",
            )

            store = ReportStore(root_dir=root)
            history = load_etf_trend_history(store, limit=10)

            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["report_date"], "20260415")
            self.assertEqual(history[0]["regime_label"], "偏强轮动")
            self.assertEqual(history[0]["recommended_count"], 2)
            self.assertEqual(history[0]["strongest_summary"], "沪深300ETF")


class TestEtfTrendBacktest(unittest.TestCase):
    def test_backtest_from_histories_generates_metrics(self):
        from ah_recommendation_system.backend.backtest.etf_trend_backtest import (
            run_etf_trend_backtest_from_histories,
        )

        dates = pd.date_range("2024-01-01", periods=160, freq="B")
        strong_prices = pd.DataFrame(
            {
                "date": dates,
                "close": [100 + i * 0.6 for i in range(len(dates))],
                "high": [100 + i * 0.6 + 0.5 for i in range(len(dates))],
            }
        )
        weak_prices = pd.DataFrame(
            {
                "date": dates,
                "close": [120 - i * 0.25 for i in range(len(dates))],
                "high": [120 - i * 0.25 + 0.3 for i in range(len(dates))],
            }
        )

        result = run_etf_trend_backtest_from_histories(
            {
                "510300": strong_prices,
                "518880": weak_prices,
            },
            names={"510300": "沪深300ETF", "518880": "黄金ETF"},
            top_n=1,
            rebalance_days=20,
            lookback_short=20,
            lookback_mid=60,
            trade_cost_pct=0.1,
            max_curve_points=120,
        )

        self.assertEqual(result["strategy"], "etf_trend_rotation")
        self.assertGreater(len(result["equity_curve"]), 0)
        self.assertGreater(result["summary"]["rebalance_count"], 0)
        self.assertGreater(result["summary"]["total_return_pct"], 0)
        self.assertTrue(result["latest_holdings"])
        self.assertEqual(result["latest_holdings"][0]["code"], "510300")


class TestEtfTrendFetchResilience(unittest.TestCase):
    def test_fetch_etf_history_with_fallback_uses_sina_after_em_failures(self):
        from ah_recommendation_system.backend.etf_sector.etf_trend_analysis import (
            fetch_etf_history_with_fallback,
        )

        sina_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-04-14", "2026-04-15"]),
                "open": [1.0, 1.1],
                "high": [1.1, 1.2],
                "low": [0.9, 1.0],
                "close": [1.05, 1.15],
                "volume": [1000, 1200],
            }
        )

        with (
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_trend_analysis.fetch_etf_hist_em",
                side_effect=RuntimeError("em_down"),
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_trend_analysis.fetch_etf_hist_em_unadjusted",
                return_value=pd.DataFrame(),
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_trend_analysis.fetch_etf_hist_sina",
                return_value=sina_df,
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_trend_analysis.time.sleep",
                return_value=None,
            ),
        ):
            history, source = fetch_etf_history_with_fallback(
                "510300", "20250101", "20260416"
            )

        self.assertEqual(source, "sina")
        self.assertFalse(history.empty)

    def test_build_one_etf_keeps_fetch_failed_status_when_all_sources_fail(self):
        from ah_recommendation_system.backend.etf_sector.etf_trend_analysis import (
            DEFAULT_PARAMETERS,
            EtfUniverseItem,
            _build_one_etf,
        )

        item = EtfUniverseItem("510300", "沪深300ETF", "宽基", "大盘核心")
        with patch(
            "ah_recommendation_system.backend.etf_sector.etf_trend_analysis.fetch_etf_history_with_fallback",
            side_effect=RuntimeError("all_failed"),
        ):
            result = _build_one_etf(
                item,
                start_date="20250101",
                end_date="20260416",
                params=DEFAULT_PARAMETERS,
            )

        self.assertEqual(result["status"], "fetch_failed")
        self.assertEqual(result["error"], "all_failed")


class TestEtfTrendRouteFallback(unittest.IsolatedAsyncioTestCase):
    async def test_live_trend_all_failed_falls_back_to_stored(self):
        from ah_recommendation_system.backend.api.etf_sector_routes import (
            get_etf_trend_block,
        )

        stored_trend = {
            "generated_at": "2026-04-15 15:00:00",
            "summary": {"market_summary": "stored trend"},
            "coverage": {
                "universe_count": 3,
                "success_count": 2,
                "failed_count": 1,
            },
            "recommendations": [{"code": "510300", "status": "ok"}],
        }
        live_failed_trend = {
            "generated_at": "2026-04-16 10:00:00",
            "coverage": {
                "universe_count": 3,
                "success_count": 0,
                "failed_count": 3,
            },
            "summary": {
                "errors": [
                    {"code": "510300", "error": "fetch_failed"},
                    {"code": "159915", "error": "fetch_failed"},
                    {"code": "518880", "error": "fetch_failed"},
                ]
            },
            "recommendations": [
                {"code": "510300", "status": "fetch_failed"},
                {"code": "159915", "status": "fetch_failed"},
                {"code": "518880", "status": "fetch_failed"},
            ],
        }

        with (
            patch(
                "ah_recommendation_system.backend.api.etf_sector_routes.generate_etf_trend_recommendation_block",
                return_value=live_failed_trend,
            ),
            patch(
                "ah_recommendation_system.backend.api.etf_sector_routes._load_latest_stored_etf_trend",
                return_value=stored_trend,
            ),
        ):
            result = await get_etf_trend_block(source="live")

        self.assertEqual(result["summary"]["market_summary"], "stored trend")
        self.assertEqual(result["fallback_source"], "stored")
        self.assertEqual(result["fallback_reason"], "live_all_fetch_failed")


class TestEtfSectorThemeBuckets(unittest.TestCase):
    def test_generate_etf_sector_block_adds_breakout_theme_lists(self):
        from ah_recommendation_system.backend.etf_sector.etf_sector_report import (
            generate_etf_sector_block,
        )

        sina_df = pd.DataFrame(
            [
                [
                    "sz159633",
                    "机器人ETF",
                    1.11,
                    0.02,
                    3.5,
                    0,
                    0,
                    1.09,
                    1.1,
                    1.12,
                    1.08,
                    100000,
                    9800000,
                ],
                [
                    "sh512880",
                    "证券ETF",
                    1.28,
                    0.01,
                    1.8,
                    0,
                    0,
                    1.26,
                    1.27,
                    1.29,
                    1.25,
                    120000,
                    12000000,
                ],
                [
                    "sh512000",
                    "券商ETF",
                    1.22,
                    0.02,
                    2.6,
                    0,
                    0,
                    1.19,
                    1.2,
                    1.23,
                    1.18,
                    115000,
                    11500000,
                ],
                [
                    "sh515220",
                    "煤炭ETF",
                    0.98,
                    0.00,
                    0.2,
                    0,
                    0,
                    0.98,
                    0.98,
                    0.99,
                    0.97,
                    60000,
                    3500000,
                ],
            ]
        )
        ths_df = pd.DataFrame(
            [
                [
                    1,
                    "159633",
                    "机器人ETF",
                    1.0,
                    1.0,
                    0.98,
                    0.98,
                    0.02,
                    4.2,
                    "开放",
                    "开放",
                    "2026-04-20",
                    1.0,
                    1.0,
                    "股票型",
                    "2026-04-20",
                ],
                [
                    2,
                    "512880",
                    "证券ETF",
                    1.0,
                    1.0,
                    0.99,
                    0.99,
                    0.01,
                    2.1,
                    "开放",
                    "开放",
                    "2026-04-20",
                    1.0,
                    1.0,
                    "股票型",
                    "2026-04-20",
                ],
                [
                    3,
                    "512000",
                    "券商ETF",
                    1.0,
                    1.0,
                    0.99,
                    0.99,
                    0.01,
                    2.8,
                    "开放",
                    "开放",
                    "2026-04-20",
                    1.0,
                    1.0,
                    "股票型",
                    "2026-04-20",
                ],
                [
                    4,
                    "515220",
                    "煤炭ETF",
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    0.0,
                    0.5,
                    "开放",
                    "开放",
                    "2026-04-20",
                    1.0,
                    1.0,
                    "股票型",
                    "2026-04-20",
                ],
            ]
        )
        industry_df = pd.DataFrame(
            [
                [1, "证券", 3.2, 210.0, 0, 0, 0, 0, 0, "东方财富", 5.3],
                [2, "煤炭", 2.6, 180.0, 0, 0, 0, 0, 0, "陕西煤业", 2.1],
                [3, "机器人", 1.4, 95.0, 0, 0, 0, 0, 0, "埃斯顿", 4.8],
            ]
        )
        concept_df = pd.DataFrame(
            [
                ["2026-04-20", "机器人", "机器人概念活跃", "埃斯顿", 56],
                ["2026-04-20", "证券", "券商板块持续走强", "东方财富", 42],
            ]
        )
        news_payload = {
            "generated_at": "2026-04-20 10:00:00",
            "count": 3,
            "items": [
                {
                    "title": "机器人产业链活跃",
                    "url": "u1",
                    "published_at": "2026-04-20 09:00:00",
                },
                {
                    "title": "证券ETF成交持续放大",
                    "url": "u2",
                    "published_at": "2026-04-20 09:10:00",
                },
                {
                    "title": "券商板块再度拉升",
                    "url": "u3",
                    "published_at": "2026-04-20 09:20:00",
                },
            ],
            "hot_keywords": [
                {"keyword": "机器人", "count": 3},
                {"keyword": "证券", "count": 4},
            ],
            "freshness": {"status": "ok"},
        }
        trend_side_effect = [
            [
                {
                    "name": "机器人",
                    "kind": "industry",
                    "ret_5d": 4.5,
                    "ret_10d": 2.0,
                    "ret_20d": -1.0,
                },
                {
                    "name": "煤炭",
                    "kind": "industry",
                    "ret_5d": 1.8,
                    "ret_10d": 3.4,
                    "ret_20d": 5.1,
                },
                {
                    "name": "证券",
                    "kind": "industry",
                    "ret_5d": 5.1,
                    "ret_10d": 6.2,
                    "ret_20d": 8.0,
                },
            ],
            [
                {
                    "name": "机器人",
                    "kind": "concept",
                    "ret_5d": 5.3,
                    "ret_10d": 2.1,
                    "ret_20d": -0.5,
                },
                {
                    "name": "证券",
                    "kind": "concept",
                    "ret_5d": 4.6,
                    "ret_10d": 5.8,
                    "ret_20d": 7.2,
                },
            ],
        ]

        with (
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_sector_report.fetch_etf_spot_sina",
                return_value=sina_df,
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_sector_report.fetch_etf_spot_ths",
                return_value=ths_df,
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_sector_report.fetch_industry_summary_ths",
                return_value=industry_df,
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_sector_report.fetch_concept_summary_ths",
                return_value=concept_df,
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_sector_report.fetch_board_trend_items_ths",
                side_effect=trend_side_effect,
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_sector_report.fetch_news_digest",
                return_value=news_payload,
            ),
            patch(
                "ah_recommendation_system.backend.etf_sector.etf_sector_report.generate_etf_trend_recommendation_block",
                return_value={
                    "generated_at": "2026-04-20 10:00:00",
                    "coverage": {},
                    "recommendations": [
                        {
                            "code": "159633",
                            "name": "机器人ETF",
                            "status": "ok",
                            "trend_score": 63.0,
                            "trend_label": "启动改善",
                            "recommendation": "持有观察",
                        },
                        {
                            "code": "512880",
                            "name": "证券ETF",
                            "status": "ok",
                            "trend_score": 79.0,
                            "trend_label": "强趋势",
                            "recommendation": "优先关注",
                        },
                        {
                            "code": "512000",
                            "name": "券商ETF",
                            "status": "ok",
                            "trend_score": 76.0,
                            "trend_label": "强趋势",
                            "recommendation": "优先关注",
                        },
                    ],
                },
            ),
        ):
            result = generate_etf_sector_block()

        self.assertIn("potential_breakouts", result)
        self.assertIn("confirmed_leaders", result)
        self.assertIn("crowded_risks", result)
        self.assertTrue(result["potential_breakouts"])
        self.assertTrue(result["confirmed_leaders"])
        self.assertTrue(result["crowded_risks"])
        self.assertEqual(result["potential_breakouts"][0]["theme"], "机器人")
        self.assertEqual(result["confirmed_leaders"][0]["theme"], "证券")
        self.assertEqual(result["crowded_risks"][0]["theme"], "证券")
        self.assertEqual(
            result["potential_breakouts"][0]["stage"], "potential_breakout"
        )
        self.assertEqual(result["confirmed_leaders"][0]["stage"], "confirmed_leader")
        self.assertEqual(result["crowded_risks"][0]["stage"], "crowded_risk")
        self.assertIn("related_etfs", result["potential_breakouts"][0])
        self.assertIn("score", result["potential_breakouts"][0])
        self.assertIn("confidence", result["potential_breakouts"][0])
        self.assertIn("reason_dimensions", result["potential_breakouts"][0])
        self.assertEqual(
            result["potential_breakouts"][0]["reason_dimensions"]["acceleration"][
                "signal"
            ],
            "emerging_breakout",
        )
        self.assertEqual(
            result["confirmed_leaders"][0]["reason_dimensions"]["trend"]["signal"],
            "persistent_trend",
        )
        self.assertEqual(
            result["confirmed_leaders"][0]["reason_dimensions"]["relative_strength"][
                "signal"
            ],
            "peer_leader",
        )
        self.assertIn(
            "同类强弱第 1/3",
            result["confirmed_leaders"][0]["reason_dimensions"]["relative_strength"][
                "summary"
            ],
        )
        self.assertEqual(
            result["potential_breakouts"][0]["reason_dimensions"]["etf_breadth"][
                "confirmed_count"
            ],
            1,
        )
        self.assertEqual(
            result["potential_breakouts"][0]["reason_dimensions"]["persistence"][
                "signal"
            ],
            "fresh_turn",
        )
        self.assertEqual(
            result["potential_breakouts"][0]["reason_dimensions"][
                "source_confirmation"
            ]["signal"],
            "multi_source_resonance",
        )
        self.assertGreater(
            result["crowded_risks"][0]["reason_dimensions"]["crowding"]["penalty"],
            0,
        )
        self.assertEqual(
            result["potential_breakouts"][0]["related_etfs"][0]["confirmation"],
            "trend_confirmed",
        )


if __name__ == "__main__":
    unittest.main()
