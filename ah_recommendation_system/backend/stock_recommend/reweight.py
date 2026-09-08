"""Bounded, explainable weekly factor reweighting."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping


DEFAULT_WEIGHTS = {
    "trend": 0.25,
    "price_volume": 0.20,
    "value_quality": 0.15,
    "capital": 0.15,
    "relative_strength": 0.15,
}


def load_factor_weights(path: Path) -> Dict[str, float]:
    """Load only a complete, current-version weight set with a valid total."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        stored = payload.get("weights") if isinstance(payload, Mapping) else None
        if payload.get("factor_version") != "evidence-v1" or not isinstance(stored, Mapping):
            return dict(DEFAULT_WEIGHTS)
        if set(stored) != set(DEFAULT_WEIGHTS):
            return dict(DEFAULT_WEIGHTS)
        candidate = {key: float(stored[key]) for key in DEFAULT_WEIGHTS}
        if abs(sum(candidate.values()) - sum(DEFAULT_WEIGHTS.values())) >= 1e-6:
            return dict(DEFAULT_WEIGHTS)
        return candidate
    except Exception:
        return dict(DEFAULT_WEIGHTS)


def adjust_weights(
    old_weights: Mapping[str, float],
    stats: Mapping[str, Mapping[str, float]],
    *,
    max_delta: float = 0.05,
) -> Dict[str, float]:
    if not old_weights:
        return {}
    keys = list(old_weights)
    scores = {k: float((stats.get(k) or {}).get("hit_rate", 0.5)) for k in keys}
    mean = sum(scores.values()) / len(scores)
    raw = {
        k: max(0.05, float(old_weights[k]) + max(-max_delta, min(max_delta, (scores[k] - mean) * max_delta * 2)))
        for k in keys
    }
    target_total = sum(float(value) for value in old_weights.values())
    total = sum(raw.values())
    normalized = {k: raw[k] / total * target_total for k in keys}
    # A second clamp guarantees the final result cannot move more than max_delta.
    bounded = {k: min(float(old_weights[k]) + max_delta, max(float(old_weights[k]) - max_delta, normalized[k])) for k in keys}
    total = sum(bounded.values())
    return {k: bounded[k] / total * target_total for k in keys}


def decide_weekly_weights(
    old_weights: Mapping[str, float],
    stats: Mapping[str, Mapping[str, float]],
    *,
    minimum_samples: int = 60,
    max_delta: float = 0.05,
) -> Dict[str, Any]:
    """Keep configured weights unchanged until every factor has evidence."""
    sample_counts = [float((stats.get(key) or {}).get("sample_count", 0)) for key in old_weights]
    if not sample_counts or min(sample_counts) < minimum_samples:
        return {"applied": False, "weights": dict(old_weights), "reason": "insufficient_samples", "minimum_samples": minimum_samples}
    return {"applied": True, "weights": adjust_weights(old_weights, stats, max_delta=max_delta), "reason": "sample_threshold_met", "minimum_samples": minimum_samples}


def _read_jsonl(path: Path) -> Iterable[Mapping[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, Mapping):
            rows.append(value)
    return rows


def aggregate_factor_stats(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Aggregate factor hit rates from the recommendation verification ledger."""
    buckets: Dict[str, list[bool]] = {k: [] for k in DEFAULT_WEIGHTS}
    for row in rows:
        for pick in row.get("per_pick") or []:
            if not isinstance(pick, Mapping):
                continue
            result = pick.get("return_T5_pct")
            if result is None:
                continue
            factors = pick.get("factors") or {}
            hit = float(result) > 0
            for factor in DEFAULT_WEIGHTS:
                score_key = factor
                if factor == "value_quality":
                    score_key = "value_quality"
                try:
                    active = float(factors.get(score_key, 0)) >= 0.55
                except (TypeError, ValueError):
                    active = False
                if active:
                    buckets[factor].append(hit)
    return {
        factor: {
            "sample_count": float(len(values)),
            "hit_rate": sum(values) / len(values) if values else 0.5,
        }
        for factor, values in buckets.items()
    }


def run_weekly_reweight(
    *,
    ledgers_dir: Path,
    weights_path: Path | None = None,
    max_delta: float = 0.05,
) -> Dict[str, Any]:
    """Update persisted factor weights using completed T+5 ledger outcomes.

    The bounded adjustment deliberately stays small and falls back to neutral
    0.5 hit rates when a factor has no verified observations yet.
    """
    ledgers_dir = Path(ledgers_dir)
    ledger_path = ledgers_dir / "stock-recommend-ledger.jsonl"
    if weights_path is None:
        weights_path = ledgers_dir.parent.parent / "ah_recommendation_system" / "backend" / "data" / "stock_recommend" / "factor_weights.json"
    weights_path = Path(weights_path)
    old = load_factor_weights(weights_path) if weights_path.exists() else dict(DEFAULT_WEIGHTS)
    stats = aggregate_factor_stats(_read_jsonl(ledger_path))
    decision = decide_weekly_weights(old, stats, max_delta=max_delta)
    new = decision["weights"]
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "factor_version": "evidence-v1",
        "max_delta": max_delta,
        "weights": new,
        "stats": stats,
        "applied": decision["applied"],
        "decision_reason": decision["reason"],
    }
    weights_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "weights_path": str(weights_path), "weights": new, "stats": stats}
