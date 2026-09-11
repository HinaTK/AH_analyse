"""Benchmark-relative signals computed only from completed dated bars."""
from __future__ import annotations

import pandas as pd


def _closes(frame: pd.DataFrame, as_of: str) -> pd.Series:
    if frame is None or not {"date", "close"}.issubset(frame.columns):
        return pd.Series(dtype=float)
    dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    values = pd.to_numeric(frame["close"], errors="coerce").replace([float("inf"), -float("inf")], float("nan"))
    result = pd.Series(values.to_numpy(), index=dates)
    if result.index.has_duplicates or result.index.isna().any():
        return pd.Series(dtype=float)
    # Date-only reports are conservative premarket snapshots.
    return result[result.index < pd.Timestamp(as_of).normalize()].sort_index()


def relative_strength(stock: pd.DataFrame, benchmark: pd.DataFrame, *, as_of: str, period: int = 60) -> dict:
    if period < 1:
        raise ValueError("period must be positive")
    own, base = _closes(stock, as_of), _closes(benchmark, as_of)
    result = {"excess_pct": None, "status": "unavailable", "period": period}
    if len(base) <= period:
        return result
    start, end = base.index[-period - 1], base.index[-1]
    if (pd.Timestamp(as_of).normalize() - end).days > 10:
        return dict(result, reason="stale_benchmark")
    if start not in own.index or end not in own.index:
        return result
    endpoints = [own.loc[start], own.loc[end], base.loc[start], base.loc[end]]
    if any(pd.isna(value) or value <= 0 for value in endpoints):
        return result
    result.update(excess_pct=((own.loc[end] / own.loc[start]) / (base.loc[end] / base.loc[start]) - 1) * 100,
                  status="available", start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
    return result


def classify_regime(benchmark: pd.DataFrame, *, as_of: str) -> dict:
    close = _closes(benchmark, as_of)
    if len(close) < 65 or close.tail(65).isna().any() or (close.tail(65) <= 0).any():
        return {"regime": "unknown", "status": "unavailable", "as_of": as_of}
    if (pd.Timestamp(as_of).normalize() - close.index[-1]).days > 10:
        return {"regime": "unknown", "status": "unavailable", "as_of": as_of, "reason": "stale_benchmark"}
    ma20 = close.tail(20).mean()
    ma60 = close.tail(60).mean()
    old_ma60 = close.iloc[-65:-5].mean()
    if close.iloc[-1] > ma20 > ma60 and ma60 > old_ma60:
        regime = "offense"
    elif close.iloc[-1] < ma60 and ma60 < old_ma60:
        regime = "defense"
    else:
        regime = "balanced"
    return {"regime": regime, "status": "available", "as_of": as_of,
            "price_as_of": close.index[-1].strftime("%Y-%m-%d"), "ma20": float(ma20), "ma60": float(ma60),
            "methodology": "benchmark_ma20_ma60_slope_v1"}
