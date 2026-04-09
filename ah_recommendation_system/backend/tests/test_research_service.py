from datetime import date, datetime
import json
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from ah_recommendation_system.backend.research.research_service import (
    MissingAHMappingError,
    PairBacktestConfig,
    _resolve_pair_backtest_config,
    build_pair_backtest,
    build_stock_research,
)


class TestResearchService(unittest.TestCase):
    def test_resolve_pair_backtest_config_reads_all_thresholds_from_strategy_config(
        self,
    ):
        with mock.patch(
            "ah_recommendation_system.backend.research.research_service.get_pair_trading_strategy"
        ) as get_pair_trading_strategy:
            get_pair_trading_strategy.return_value.config = {
                "premium_lookback": "30",
                "entry_z": "1.8",
                "exit_z": "0.4",
            }

            config = _resolve_pair_backtest_config()

        self.assertEqual(
            config,
            PairBacktestConfig(lookback=30, entry_z=1.8, exit_z=0.4),
        )

    def test_missing_ah_mapping_error_is_not_generic_value_error(self):
        try:
            raise MissingAHMappingError("601398.SH")
        except ValueError as exc:
            self.fail(
                f"MissingAHMappingError leaked into generic ValueError handling: {exc}"
            )
        except MissingAHMappingError as exc:
            self.assertEqual(str(exc), "No AH pair mapping found for 601398.SH")

    def test_build_stock_research_fetches_premium_with_resolved_h_code(self):
        price_fetcher = mock.Mock()
        price_fetcher.get_ah_premium.return_value = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-02")],
                "premium_pct": [1.2],
            }
        )

        with (
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ah_pairs",
                return_value={"601398.SH": "01398.HK"},
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_stock_name",
                return_value="工商银行",
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_price_fetcher",
                return_value=price_fetcher,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_pair_trading_strategy"
            ) as get_pair_trading_strategy,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_multi_factor_strategy"
            ) as get_multi_factor_strategy,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ml_predictor_strategy"
            ) as get_ml_predictor_strategy,
        ):
            get_pair_trading_strategy.return_value.analyze_single_pair.return_value = {
                "signal": "hold"
            }
            get_multi_factor_strategy.return_value.analyze_single_stock.return_value = {
                "total_score": 0.5
            }
            get_ml_predictor_strategy.return_value.predict.return_value = {
                "predicted_direction": "flat"
            }

            build_stock_research("601398.SH")

        price_fetcher.get_ah_premium.assert_called_once_with("601398.SH", "01398.HK")

    def test_build_pair_backtest_reuses_pair_backtest_engine(self):
        premium_df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")],
                "premium_pct": [2.5, 5.25],
            }
        )
        price_fetcher = mock.Mock()
        price_fetcher.get_ah_premium.return_value = premium_df

        backtest_payload = {
            "metrics": {"trades": np.int64(2), "total_return_pct": np.float64(1.5)},
            "equity_curve": [
                {"date": pd.Timestamp("2024-01-02"), "equity": np.float64(1.0)}
            ],
            "trades": [
                {
                    "entry_date": pd.Timestamp("2024-01-02"),
                    "exit_date": pd.Timestamp("2024-01-03"),
                    "pnl_pct": np.float64(0.8),
                }
            ],
            "parameters": {"lookback": np.int64(20)},
        }

        with (
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ah_pairs",
                return_value={"601398.SH": "01398.HK"},
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_price_fetcher",
                return_value=price_fetcher,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_pair_trading_strategy"
            ) as get_pair_trading_strategy,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.DEFAULT_COST_MODEL",
                mock.Mock(estimate_round_trip_cost_pct=mock.Mock(return_value=0.5)),
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.run_backtest_from_premium_df",
                return_value=backtest_payload,
            ) as run_backtest_from_premium_df,
        ):
            get_pair_trading_strategy.return_value.config = {
                "premium_lookback": "30",
                "entry_z": "1.8",
                "exit_z": "0.4",
            }

            payload = build_pair_backtest("601398.SH")

        self.assertEqual(
            payload,
            {
                "metrics": {"trades": 2, "total_return_pct": 1.5},
                "equity_curve": [{"date": "2024-01-02", "equity": 1.0}],
                "trades": [
                    {
                        "entry_date": "2024-01-02",
                        "exit_date": "2024-01-03",
                        "pnl_pct": 0.8,
                    }
                ],
                "parameters": {"lookback": 20},
            },
        )
        price_fetcher.get_ah_premium.assert_called_once_with("601398.SH", "01398.HK")
        run_backtest_from_premium_df.assert_called_once_with(
            df=premium_df,
            lookback=30,
            entry_z=1.8,
            exit_z=0.4,
            round_trip_cost_pct=0.5,
        )

    def test_build_pair_backtest_raises_when_ah_mapping_missing(self):
        with (
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ah_pairs",
                return_value={},
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_price_fetcher"
            ) as get_price_fetcher,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.run_backtest_from_premium_df"
            ) as run_backtest_from_premium_df,
        ):
            with self.assertRaisesRegex(
                MissingAHMappingError, "No AH pair mapping found for 601398.SH"
            ) as ctx:
                build_pair_backtest("601398.SH")

        self.assertIsInstance(ctx.exception, MissingAHMappingError)
        self.assertEqual(ctx.exception.a_code, "601398.SH")
        get_price_fetcher.assert_not_called()
        run_backtest_from_premium_df.assert_not_called()

    def test_build_stock_research_serializes_entire_payload_for_json_boundary(
        self,
    ):
        premium_df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")],
                "a_close": [4.8, 5.1],
                "h_close": [4.2, 4.3],
                "hkd_cny": [0.91, 0.91],
                "premium_pct": [2.5, 5.25],
            }
        )
        price_fetcher = mock.Mock()
        price_fetcher.get_ah_premium.return_value = premium_df

        pair_trading = mock.Mock()
        pair_trading.analyze_single_pair.return_value = {
            "signal": "sell_ah",
            "confidence": np.float32(0.72),
            "last_signal_at": pd.Timestamp("2024-01-04 09:30:00"),
            "windows": [
                np.int64(5),
                {"spread_z": np.float32(1.5), "nan_value": np.nan},
            ],
        }

        multi_factor = mock.Mock()
        multi_factor.analyze_single_stock.return_value = {
            "total_score": np.float64(0.81),
            "factor_scores": {"valuation": np.float32(0.7), "as_of": date(2024, 1, 6)},
            "rebalance_at": datetime(2024, 1, 7, 15, 45, 30),
        }

        ml_predictor = mock.Mock()
        ml_predictor.predict.return_value = {
            "predicted_direction": "premium_increase",
            "confidence": np.float64(0.66),
            "generated_at": pd.Timestamp("2024-01-08"),
            "path": (np.int64(1), pd.Timestamp("2024-01-09"), np.nan),
        }

        with (
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ah_pairs",
                return_value={"601398.SH": "1398.HK"},
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_stock_name",
                return_value="工商银行",
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_price_fetcher",
                return_value=price_fetcher,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_pair_trading_strategy",
                return_value=pair_trading,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_multi_factor_strategy",
                return_value=multi_factor,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ml_predictor_strategy",
                return_value=ml_predictor,
            ),
        ):
            payload = build_stock_research("601398.SH")

        self.assertEqual(
            payload["stock"],
            {
                "a_code": "601398.SH",
                "h_code": "1398.HK",
                "name": "工商银行",
                "latest_premium_pct": 5.25,
            },
        )
        self.assertIn("premium_series", payload)
        self.assertEqual(payload["premium_series"][-1]["date"], "2024-01-03")
        self.assertEqual(payload["premium_series"][-1]["premium_pct"], 5.25)
        json.dumps(payload, allow_nan=False)

        self.assertEqual(payload["pair_trading"]["signal"], "sell_ah")
        self.assertEqual(payload["multi_factor"]["total_score"], 0.81)
        self.assertEqual(
            payload["ml_prediction"]["predicted_direction"], "premium_increase"
        )
        self.assertEqual(
            payload["pair_trading"]["last_signal_at"], "2024-01-04T09:30:00"
        )
        self.assertEqual(
            payload["pair_trading"]["windows"],
            [5, {"spread_z": 1.5, "nan_value": None}],
        )
        self.assertEqual(
            payload["multi_factor"]["factor_scores"]["as_of"], "2024-01-06"
        )
        self.assertEqual(payload["multi_factor"]["rebalance_at"], "2024-01-07T15:45:30")
        self.assertEqual(payload["ml_prediction"]["generated_at"], "2024-01-08")
        self.assertEqual(payload["ml_prediction"]["path"], [1, "2024-01-09", None])

        price_fetcher.get_ah_premium.assert_called_once_with("601398.SH", "1398.HK")
        pair_trading.analyze_single_pair.assert_called_once_with("601398.SH", "1398.HK")
        multi_factor.analyze_single_stock.assert_called_once_with(
            "601398.SH", "1398.HK"
        )
        ml_predictor.predict.assert_called_once_with("601398.SH", "1398.HK")

    def test_build_stock_research_returns_empty_series_when_premium_data_missing(self):
        price_fetcher = mock.Mock()
        price_fetcher.get_ah_premium.return_value = pd.DataFrame()

        with (
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ah_pairs",
                return_value={"601398.SH": "1398.HK"},
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_stock_name",
                return_value="工商银行",
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_price_fetcher",
                return_value=price_fetcher,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_pair_trading_strategy"
            ) as get_pair_trading_strategy,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_multi_factor_strategy"
            ) as get_multi_factor_strategy,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ml_predictor_strategy"
            ) as get_ml_predictor_strategy,
        ):
            get_pair_trading_strategy.return_value.analyze_single_pair.return_value = {
                "signal": "hold"
            }
            get_multi_factor_strategy.return_value.analyze_single_stock.return_value = {
                "total_score": 0.5
            }
            get_ml_predictor_strategy.return_value.predict.return_value = {
                "predicted_direction": "unknown"
            }

            payload = build_stock_research("601398.SH")

        self.assertIsNone(payload["stock"]["latest_premium_pct"])
        self.assertEqual(payload["premium_series"], [])

    def test_build_stock_research_serializes_nested_numpy_datetime64_values(self):
        price_fetcher = mock.Mock()
        price_fetcher.get_ah_premium.return_value = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-02")],
                "premium_pct": [np.float64(1.25)],
            }
        )

        pair_trading = mock.Mock()
        pair_trading.analyze_single_pair.return_value = {
            "signal": "hold",
            "history": [
                {
                    "window_end": np.datetime64("2024-01-10"),
                }
            ],
        }

        multi_factor = mock.Mock()
        multi_factor.analyze_single_stock.return_value = {"total_score": 0.5}

        ml_predictor = mock.Mock()
        ml_predictor.predict.return_value = {"predicted_direction": "flat"}

        with (
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ah_pairs",
                return_value={"601398.SH": "1398.HK"},
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_stock_name",
                return_value="工商银行",
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_price_fetcher",
                return_value=price_fetcher,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_pair_trading_strategy",
                return_value=pair_trading,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_multi_factor_strategy",
                return_value=multi_factor,
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ml_predictor_strategy",
                return_value=ml_predictor,
            ),
        ):
            payload = build_stock_research("601398.SH")

        self.assertEqual(
            payload["pair_trading"]["history"][0]["window_end"], "2024-01-10"
        )
        json.dumps(payload, allow_nan=False)

    def test_build_stock_research_raises_when_ah_mapping_missing(self):
        with (
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ah_pairs",
                return_value={},
            ),
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_price_fetcher"
            ) as get_price_fetcher,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_pair_trading_strategy"
            ) as get_pair_trading_strategy,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_multi_factor_strategy"
            ) as get_multi_factor_strategy,
            mock.patch(
                "ah_recommendation_system.backend.research.research_service.get_ml_predictor_strategy"
            ) as get_ml_predictor_strategy,
        ):
            with self.assertRaisesRegex(
                MissingAHMappingError, "No AH pair mapping found for 601398.SH"
            ) as ctx:
                build_stock_research("601398.SH")

        self.assertIsInstance(ctx.exception, MissingAHMappingError)
        self.assertEqual(ctx.exception.a_code, "601398.SH")
        get_price_fetcher.assert_not_called()
        get_pair_trading_strategy.assert_not_called()
        get_multi_factor_strategy.assert_not_called()
        get_ml_predictor_strategy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
