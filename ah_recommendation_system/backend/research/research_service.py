from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List

import pandas as pd

from ah_recommendation_system.backend.backtest.pair_trading_backtest import (
    run_backtest_from_premium_df,
)
from ah_recommendation_system.backend.data.ah_stock_list import (
    get_ah_pairs,
    get_stock_name,
)
from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.strategies.ml_predictor import (
    get_ml_predictor_strategy,
)
from ah_recommendation_system.backend.strategies.multi_factor import (
    get_multi_factor_strategy,
)
from ah_recommendation_system.backend.strategies.pair_trading import (
    get_pair_trading_strategy,
)
from ah_recommendation_system.backend.trading.cost_model import DEFAULT_COST_MODEL


@dataclass(frozen=True)
class PairBacktestConfig:
    lookback: int
    entry_z: float
    exit_z: float


class MissingAHMappingError(LookupError):
    def __init__(self, a_code: str):
        super().__init__(f"No AH pair mapping found for {a_code}")
        self.a_code = a_code


def _format_datetime_like(value: datetime) -> str:
    if (
        value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
        and getattr(value, "nanosecond", 0) == 0
    ):
        return value.date().isoformat()

    return value.isoformat()


def _serialize_scalar(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else _format_datetime_like(value)

    if isinstance(value, datetime):
        return _format_datetime_like(value)

    if isinstance(value, date):
        return value.isoformat()

    if hasattr(value, "item"):
        try:
            converted = value.item()
        except (AttributeError, TypeError, ValueError):
            pass
        else:
            if converted is not value:
                return _serialize_scalar(converted)

            value = converted

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    return value


def _serialize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _serialize_json_value(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_serialize_json_value(item) for item in value]

    return _serialize_scalar(value)


def _serialize_premium_series(premium_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if premium_df.empty:
        return []

    return _serialize_json_value(premium_df.to_dict(orient="records"))


def _resolve_h_code(a_code: str) -> str:
    ah_pairs = get_ah_pairs()
    h_code = ah_pairs.get(a_code)
    if not h_code:
        raise MissingAHMappingError(a_code)

    return h_code


def _coerce_int_config(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value)

    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default

    return default


def _coerce_float_config(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default

    return default


def _resolve_pair_backtest_config() -> PairBacktestConfig:
    strategy_config = getattr(get_pair_trading_strategy(), "config", {}) or {}

    return PairBacktestConfig(
        lookback=_coerce_int_config(strategy_config.get("premium_lookback", 20), 20),
        entry_z=_coerce_float_config(strategy_config.get("entry_z", 1.5), 1.5),
        exit_z=_coerce_float_config(strategy_config.get("exit_z", 0.2), 0.2),
    )


def build_pair_backtest(a_code: str) -> Dict[str, Any]:
    h_code = _resolve_h_code(a_code)
    premium_df = get_price_fetcher().get_ah_premium(a_code, h_code)
    backtest_config = _resolve_pair_backtest_config()

    payload = run_backtest_from_premium_df(
        df=premium_df,
        lookback=backtest_config.lookback,
        entry_z=backtest_config.entry_z,
        exit_z=backtest_config.exit_z,
        round_trip_cost_pct=float(DEFAULT_COST_MODEL.estimate_round_trip_cost_pct()),
    )

    return _serialize_json_value(payload)


def build_stock_research(a_code: str) -> Dict[str, Any]:
    h_code = _resolve_h_code(a_code)

    price_fetcher = get_price_fetcher()
    premium_df = price_fetcher.get_ah_premium(a_code, h_code)

    latest_premium_pct = None
    if not premium_df.empty and "premium_pct" in premium_df.columns:
        latest_premium_pct = premium_df.iloc[-1]["premium_pct"]

    payload = {
        "stock": {
            "a_code": a_code,
            "h_code": h_code,
            "name": get_stock_name(a_code),
            "latest_premium_pct": latest_premium_pct,
        },
        "premium_series": _serialize_premium_series(premium_df),
        "pair_trading": get_pair_trading_strategy().analyze_single_pair(a_code, h_code),
        "multi_factor": get_multi_factor_strategy().analyze_single_stock(
            a_code, h_code
        ),
        "ml_prediction": get_ml_predictor_strategy().predict(a_code, h_code),
    }

    return _serialize_json_value(payload)
