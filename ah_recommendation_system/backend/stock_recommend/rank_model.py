"""Cross-sectional ranker with missing-aware linear fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RankerModel:
    kind: str
    feature_keys: List[str]
    coefficients: Dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    mean: Dict[str, float] = field(default_factory=dict)
    std: Dict[str, float] = field(default_factory=dict)


def fit_ranker(train_rows: List[Dict[str, Any]], *, feature_keys: List[str]) -> RankerModel:
    """Ridge-regression ranker on finite features only; no zero imputation."""
    try:
        import lightgbm as lgb
    except ImportError:
        lgb = None

    if lgb is not None and len(train_rows) > 200:
        raise NotImplementedError("LightGBM rank path is optional and not wired in this task")

    finite_rows = []
    for row in train_rows:
        factors = row.get("factors") or {}
        values = [factors.get(key) for key in feature_keys]
        if all(v is not None for v in values):
            try:
                excess = float(row.get("excess_return_pct"))
            except (TypeError, ValueError):
                continue
            finite_rows.append(([float(v) for v in values], excess))
    if len(finite_rows) < 2:
        raise ValueError("insufficient_finite_training_rows")

    n = len(feature_keys)
    mean = [sum(row[0][j] for row in finite_rows) / len(finite_rows) for j in range(n)]
    std = [(sum((row[0][j] - mean[j]) ** 2 for row in finite_rows) / len(finite_rows)) ** 0.5 for j in range(n)]
    std = [s if s > 1e-9 else 1.0 for s in std]
    X = [[(row[0][j] - mean[j]) / std[j] for j in range(n)] for row in finite_rows]
    y = [row[1] for row in finite_rows]

    ridge = 1.0
    XtX = [[sum(X[i][a] * X[i][b] for i in range(len(X))) + (ridge if a == b else 0.0) for b in range(n)] for a in range(n)]
    Xty = [sum(X[i][a] * y[i] for i in range(len(X))) for a in range(n)]
    coeffs = _solve(XtX, Xty)

    return RankerModel(
        kind="linear",
        feature_keys=list(feature_keys),
        coefficients={key: coeffs[j] for j, key in enumerate(feature_keys)},
        intercept=sum(y[j] for j in range(len(y))) / len(y) - sum(coeffs[j] * mean[j] / std[j] for j in range(n)),
        mean={key: mean[j] for j, key in enumerate(feature_keys)},
        std={key: std[j] for j, key in enumerate(feature_keys)},
    )


def _solve(matrix, vector):
    """Gaussian elimination with partial pivoting for small dense systems."""
    import copy

    a = [list(row) + [vector[i]] for i, row in enumerate(matrix)]
    n = len(vector)
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return [0.0] * n
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]
    result = [0.0] * n
    for row in reversed(range(n)):
        result[row] = (a[row][n] - sum(a[row][k] * result[k] for k in range(row + 1, n))) / a[row][row]
    return result


def predict_scores(model: RankerModel, rows: List[Dict[str, Any]]) -> List[Optional[float]]:
    results = []
    for row in rows:
        factors = row.get("factors") or {}
        values = [factors.get(key) for key in model.feature_keys]
        if any(v is None for v in values):
            results.append(None)
            continue
        score = model.intercept + sum(model.coefficients[key] * (float(values[j]) - model.mean[key]) / model.std[key]
                                      for j, key in enumerate(model.feature_keys))
        results.append(score)
    return results
