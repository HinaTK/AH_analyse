"""Small, point-in-time factor diagnostics used before changing weights."""
from __future__ import annotations

from itertools import combinations
from typing import Iterable, Mapping, Any

import pandas as pd


def _series(values: Iterable[Any]) -> pd.Series:
    return pd.to_numeric(pd.Series(list(values), dtype=object), errors="coerce").replace([float("inf"), -float("inf")], float("nan"))


def _rank_correlation(left: pd.Series, right: pd.Series) -> float | None:
    aligned = pd.concat([left, right], axis=1).dropna()
    if len(aligned) < 3 or any(aligned.iloc[:, i].nunique() < 2 for i in range(2)):
        return None
    return float(aligned.iloc[:, 0].rank().corr(aligned.iloc[:, 1].rank()))


def validate_factor_set(
    factors: Mapping[str, Iterable[Any]],
    *,
    forward_returns: Iterable[Any] | None = None,
    correlation_threshold: float = 0.7,
    dates: Iterable[Any] | None = None,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Diagnose aligned observations; dated inputs use daily cross-sections.

    This is an evidence diagnostic, never permission to change live weights.
    Forward returns must be matured, point-in-time outcomes supplied by the
    caller. The undated mode describes one cross-section only.
    """
    if not 0 < correlation_threshold <= 1:
        raise ValueError("correlation_threshold must be in (0, 1]")
    columns = {name: _series(values) for name, values in factors.items()}
    returns = _series(forward_returns) if forward_returns is not None else None
    count = len(next(iter(columns.values()))) if columns else 0
    date_values = list(dates) if dates is not None else None
    symbol_values = list(symbols) if symbols is not None else None
    vectors = list(columns.values()) + ([returns] if returns is not None else [])
    vectors += [v for v in (date_values, symbol_values) if v is not None]
    if any(len(v) != count for v in vectors):
        raise ValueError("all input vectors must have identical lengths")
    if (date_values is None) != (symbol_values is None):
        raise ValueError("dates and symbols must be supplied together")
    groups = [pd.RangeIndex(count)]
    mode = "single_cross_section"
    if date_values is not None:
        metadata = pd.DataFrame({"date": pd.to_datetime(date_values, errors="raise").normalize(), "symbol": symbol_values})
        if metadata.isna().any().any() or metadata.duplicated().any():
            raise ValueError("dates/symbols must be present and unique per day")
        groups = list(metadata.groupby("date").groups.values())
        mode = "daily_cross_sections"
    diagnostics: dict[str, dict[str, Any]] = {}
    for name, values in columns.items():
        aligned = pd.concat([values, returns], axis=1).dropna() if returns is not None else values.dropna().to_frame()
        ics = []
        if returns is not None:
            for indexes in groups:
                ic = _rank_correlation(values.loc[indexes], returns.loc[indexes])
                if ic is not None:
                    ics.append(ic)
        ic_std = float(pd.Series(ics, dtype=float).std(ddof=1)) if len(ics) > 1 else None
        rank_changes = []
        if date_values is not None:
            previous = None
            for indexes in groups:
                ranked = pd.Series(values.loc[indexes].to_numpy(), index=[symbol_values[i] for i in indexes]).rank(pct=True)
                if previous is not None:
                    aligned_ranks = pd.concat([previous, ranked], axis=1).dropna()
                    if len(aligned_ranks):
                        rank_changes.append(float((aligned_ranks.iloc[:, 0] - aligned_ranks.iloc[:, 1]).abs().mean()))
                previous = ranked
        diagnostics[name] = {
            "ic": round(sum(ics) / len(ics), 6) if ics else None,
            "sample_count": int(len(aligned)),
            "period_count": len(ics),
            "positive_period_fraction": sum(ic > 0 for ic in ics) / len(ics) if ics else None,
            "ic_std": ic_std,
            "ic_ir": (sum(ics) / len(ics)) / ic_std if ic_std is not None and ic_std > 1e-12 else None,
            "rank_turnover": sum(rank_changes) / len(rank_changes) if rank_changes else None,
            "minimum_periods_met": len(ics) >= 20,
        }
    redundant: list[tuple[str, str]] = []
    pair_diagnostics = []
    for left, right in combinations(columns, 2):
        correlations = [
            corr for indexes in groups
            if (corr := _rank_correlation(columns[left].loc[indexes], columns[right].loc[indexes])) is not None
        ]
        mean_absolute = sum(abs(corr) for corr in correlations) / len(correlations) if correlations else None
        pair_diagnostics.append({"left": left, "right": right, "mean_absolute_correlation": mean_absolute, "period_count": len(correlations)})
        if mean_absolute is not None and mean_absolute >= correlation_threshold:
            redundant.append((left, right))
    return {
        "factors": diagnostics, "redundant_pairs": redundant,
        "correlations": pair_diagnostics, "mode": mode,
        "correlation_threshold": correlation_threshold,
        "calibration_eligible": False,
        "calibration_reason": "diagnostics_only_requires_rolling_out_of_sample_validation",
    }
