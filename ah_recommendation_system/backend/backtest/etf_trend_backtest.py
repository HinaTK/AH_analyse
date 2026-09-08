from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from ah_recommendation_system.backend.etf_sector.etf_trend_analysis import (
    DEFAULT_PARAMETERS,
    fetch_etf_hist_em,
    resolve_etf_universe,
    sanitize_trend_analysis_parameters,
    _normalize_history,
)


def _to_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _to_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _prepare_close_series(history: pd.DataFrame, code: str) -> pd.DataFrame:
    normalized = _normalize_history(history)
    if normalized.empty:
        return pd.DataFrame(columns=["date", code])
    out = normalized[["date", "close"]].copy()
    out = out.dropna(subset=["date", "close"])
    out = out.rename(columns={"close": code})
    out[code] = pd.to_numeric(out[code], errors="coerce")
    return out.dropna(subset=[code]).drop_duplicates(subset=["date"], keep="last")


def _build_price_matrix(histories: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    matrix: Optional[pd.DataFrame] = None
    for code, history in histories.items():
        prepared = _prepare_close_series(history, code)
        if prepared.empty:
            continue
        matrix = (
            prepared
            if matrix is None
            else matrix.merge(prepared, on="date", how="outer")
        )

    if matrix is None or matrix.empty:
        return pd.DataFrame(columns=["date"])

    matrix = matrix.sort_values("date").reset_index(drop=True)
    code_columns = [col for col in matrix.columns if col != "date"]
    if code_columns:
        matrix[code_columns] = matrix[code_columns].ffill(limit=3)
    return matrix.dropna(how="all", subset=code_columns)


def _max_drawdown_pct(equity_values: List[float]) -> float:
    if not equity_values:
        return 0.0
    peak = equity_values[0]
    max_drawdown = 0.0
    for value in equity_values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, value / peak - 1.0)
    return round(max_drawdown * 100.0, 3)


def _downsample_curve(
    curve: List[Dict[str, Any]], max_points: int = 180
) -> List[Dict[str, Any]]:
    if len(curve) <= max_points:
        return curve
    step = max(1, len(curve) // max_points)
    sampled = [curve[index] for index in range(0, len(curve), step)]
    if sampled[-1] != curve[-1]:
        sampled.append(curve[-1])
    return sampled[:max_points]


def run_etf_trend_backtest_from_histories(
    histories: Dict[str, pd.DataFrame],
    *,
    names: Optional[Dict[str, str]] = None,
    top_n: int = 1,
    rebalance_days: int = 20,
    lookback_short: int = DEFAULT_PARAMETERS.lookback_short,
    lookback_mid: int = DEFAULT_PARAMETERS.lookback_mid,
    trade_cost_pct: float = 0.1,
    max_curve_points: int = 180,
) -> Dict[str, Any]:
    price_matrix = _build_price_matrix(histories)
    code_columns = [col for col in price_matrix.columns if col != "date"]
    if price_matrix.empty or not code_columns:
        return {
            "strategy": "etf_trend_rotation",
            "summary": {
                "universe_count": 0,
                "eligible_count": 0,
                "rebalance_count": 0,
                "total_return_pct": 0.0,
                "annualized_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "positive_period_ratio": 0.0,
                "cash_days": 0,
            },
            "equity_curve": [],
            "rebalances": [],
            "latest_holdings": [],
        }

    prices = price_matrix[code_columns]
    returns = prices.pct_change().fillna(0.0)
    ma_mid = prices.rolling(lookback_mid).mean()
    short_ret = prices / prices.shift(lookback_short) - 1.0
    mid_ret = prices / prices.shift(lookback_mid) - 1.0
    score = short_ret * 0.6 + mid_ret * 0.4
    trend_filter = (prices > ma_mid) & (short_ret > 0) & (mid_ret > 0)

    warmup = max(lookback_mid, lookback_short) + 1
    if len(price_matrix) <= warmup:
        return {
            "strategy": "etf_trend_rotation",
            "summary": {
                "universe_count": len(histories),
                "eligible_count": 0,
                "rebalance_count": 0,
                "total_return_pct": 0.0,
                "annualized_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "positive_period_ratio": 0.0,
                "cash_days": 0,
            },
            "equity_curve": [],
            "rebalances": [],
            "latest_holdings": [],
        }

    equity = 1.0
    weights = {code: 0.0 for code in code_columns}
    equity_curve: List[Dict[str, Any]] = [
        {
            "date": price_matrix.iloc[warmup - 1]["date"].strftime("%Y-%m-%d"),
            "equity": 1.0,
        }
    ]
    rebalances: List[Dict[str, Any]] = []
    positive_days = 0
    invested_days = 0
    cash_days = 0

    for index in range(warmup, len(price_matrix)):
        day_return = 0.0
        active_codes = [code for code, weight in weights.items() if weight > 0]
        if active_codes:
            day_return = sum(
                weights[code] * float(returns.iloc[index][code])
                for code in active_codes
            )
            invested_days += 1
            if day_return > 0:
                positive_days += 1
        else:
            cash_days += 1

        equity *= 1.0 + day_return
        current_date = price_matrix.iloc[index]["date"].strftime("%Y-%m-%d")
        equity_curve.append({"date": current_date, "equity": round(equity, 6)})

        should_rebalance = (
            not rebalances
            or (index - warmup) % rebalance_days == 0
            or index == len(price_matrix) - 1
        )
        if not should_rebalance:
            continue

        today_score = score.iloc[index]
        today_filter = trend_filter.iloc[index]
        candidates: List[Dict[str, Any]] = []
        for code in code_columns:
            score_value = today_score.get(code)
            if pd.isna(score_value) or not bool(today_filter.get(code)):
                continue
            candidates.append(
                {
                    "code": code,
                    "name": (names or {}).get(code) or code,
                    "score": round(float(score_value) * 100.0, 3),
                    "short_return_pct": round(
                        float(short_ret.iloc[index][code]) * 100.0, 3
                    ),
                    "mid_return_pct": round(
                        float(mid_ret.iloc[index][code]) * 100.0, 3
                    ),
                }
            )

        candidates.sort(key=lambda item: (-item["score"], item["code"]))
        selected = candidates[:top_n]
        new_weights = {code: 0.0 for code in code_columns}
        if selected:
            weight = 1.0 / len(selected)
            for item in selected:
                new_weights[item["code"]] = weight

        turnover = sum(
            abs(new_weights[code] - weights.get(code, 0.0)) for code in code_columns
        )
        if turnover > 0:
            equity *= max(0.0, 1.0 - (turnover * trade_cost_pct / 100.0))
            equity_curve[-1]["equity"] = round(equity, 6)

        weights = new_weights
        rebalances.append(
            {
                "date": current_date,
                "selected": selected,
                "turnover": round(turnover, 4),
                "holding_count": len(selected),
                "in_cash": len(selected) == 0,
                "equity": round(equity, 6),
            }
        )

    total_periods = max(0, len(equity_curve) - 1)
    total_return = equity - 1.0
    annualized_return = 0.0
    if total_periods > 0 and equity > 0:
        annualized_return = equity ** (252.0 / total_periods) - 1.0

    latest_holdings = []
    if rebalances:
        latest_holdings = rebalances[-1]["selected"]

    return {
        "strategy": "etf_trend_rotation",
        "summary": {
            "universe_count": len(histories),
            "eligible_count": len(
                [
                    code
                    for code in code_columns
                    if prices[code].notna().sum() > lookback_mid
                ]
            ),
            "rebalance_count": len(rebalances),
            "total_return_pct": round(total_return * 100.0, 3),
            "annualized_return_pct": round(annualized_return * 100.0, 3),
            "max_drawdown_pct": _max_drawdown_pct(
                [float(item["equity"]) for item in equity_curve]
            ),
            "positive_period_ratio": round(
                (positive_days / invested_days) if invested_days else 0.0, 4
            ),
            "cash_days": cash_days,
        },
        "equity_curve": _downsample_curve(equity_curve, max_points=max_curve_points),
        "rebalances": rebalances[-24:],
        "latest_holdings": latest_holdings,
    }


def run_etf_trend_backtest(
    *,
    codes: Optional[str] = None,
    top_n: Any = 1,
    rebalance_days: Any = 20,
    lookback_short: Any = None,
    lookback_mid: Any = None,
    trade_cost_pct: Any = 0.1,
    max_curve_points: Any = 180,
) -> Dict[str, Any]:
    params = sanitize_trend_analysis_parameters(
        lookback_short=lookback_short,
        lookback_mid=lookback_mid,
        lookback_long=DEFAULT_PARAMETERS.lookback_long,
        breakout_window=DEFAULT_PARAMETERS.breakout_window,
    )
    sanitized_top_n = _to_int(top_n, default=1, minimum=1, maximum=5)
    sanitized_rebalance_days = _to_int(
        rebalance_days, default=20, minimum=5, maximum=60
    )
    sanitized_trade_cost_pct = _to_float(
        trade_cost_pct, default=0.1, minimum=0.0, maximum=2.0
    )
    sanitized_curve_points = _to_int(
        max_curve_points, default=180, minimum=30, maximum=240
    )

    universe = resolve_etf_universe(codes)
    names = {item.code: item.name for item in universe}
    end = datetime.now()
    history_days = max(params.lookback_mid * 6, 540)
    start = end - timedelta(days=history_days)
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")

    histories: Dict[str, pd.DataFrame] = {}
    errors: List[Dict[str, str]] = []
    for item in universe:
        try:
            histories[item.code] = fetch_etf_hist_em(item.code, start_date, end_date)
        except Exception as exc:
            errors.append({"code": item.code, "name": item.name, "error": str(exc)})

    result = run_etf_trend_backtest_from_histories(
        histories,
        names=names,
        top_n=sanitized_top_n,
        rebalance_days=sanitized_rebalance_days,
        lookback_short=params.lookback_short,
        lookback_mid=params.lookback_mid,
        trade_cost_pct=sanitized_trade_cost_pct,
        max_curve_points=sanitized_curve_points,
    )
    result["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["source"] = "eastmoney"
    result["parameters"] = {
        "codes": codes,
        "top_n": sanitized_top_n,
        "rebalance_days": sanitized_rebalance_days,
        "lookback_short": params.lookback_short,
        "lookback_mid": params.lookback_mid,
        "trade_cost_pct": sanitized_trade_cost_pct,
        "start_date": start_date,
        "end_date": end_date,
    }
    result["errors"] = errors
    result["summary"]["failed_count"] = len(errors)
    result["summary"]["selected_universe_count"] = len(universe)
    return result
