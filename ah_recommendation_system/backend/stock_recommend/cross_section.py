"""Missing-aware cross-sectional transforms for ranking features."""
from __future__ import annotations

from typing import Any, Dict, List


def _finite(value: Any):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def cross_sectional_ranks(rows: List[Dict[str, Any]], key: str, *, higher_is_better: bool = True) -> List:
    """Percentile rank among finite values; missing stays None."""
    values = [_finite(row.get(key)) for row in rows]
    present = sorted(v for v in values if v is not None)
    if not present:
        return [None for _ in rows]
    def pct(v):
        below = sum(1 for item in present if item < v)
        ties = sum(1 for item in present if item == v)
        return (below + (ties - 1) / 2) / len(present)
    result = [pct(v) if v is not None else None for v in values]
    if not higher_is_better:
        result = [(1.0 - r) if r is not None else None for r in result]
    return result


def cross_sectional_zscores(rows: List[Dict[str, Any]], key: str) -> List:
    """Population z-score among finite values; missing stays None."""
    values = [_finite(row.get(key)) for row in rows]
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return [None for _ in rows]
    mean = sum(present) / len(present)
    var = sum((v - mean) ** 2 for v in present) / len(present)
    if var == 0:
        return [None for _ in rows]
    std = var ** 0.5
    return [(v - mean) / std if v is not None else None for v in values]
