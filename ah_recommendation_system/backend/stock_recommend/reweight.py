"""Bounded, explainable weekly factor reweighting."""
from __future__ import annotations

import json
import math
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping


DEFAULT_WEIGHTS = {
    "trend": 0.25,
    "price_volume": 0.20,
    "value_quality": 0.15,
    "capital": 0.15,
    "relative_strength": 0.15,
    "event": 0.10,
}


def decide_event_llm_weight(
    *,
    current_llm_weight: float,
    sample_count: int,
    rule_hit_rate: float,
    llm_hit_rate: float,
    rule_false_positive_rate: float = 0.0,
    llm_false_positive_rate: float = 0.0,
) -> Dict[str, Any]:
    """Adjust only the message sub-weight after a sufficiently large sample."""
    current = max(0.3, min(0.5, float(current_llm_weight)))
    if sample_count < 100:
        return {"applied": False, "llm_weight": current, "reason": "insufficient_samples"}
    improvement = float(llm_hit_rate) - float(rule_hit_rate)
    fp_change = float(llm_false_positive_rate) - float(rule_false_positive_rate)
    if improvement >= 0.05 and fp_change <= 0.03:
        new = min(0.5, current + 0.1)
        return {"applied": new != current, "llm_weight": new, "reason": "llm_outperforms_rule"}
    if improvement < 0 or fp_change > 0.03:
        new = max(0.3, current - 0.1)
        return {"applied": new != current, "llm_weight": new, "reason": "llm_underperforms_or_overalerts"}
    return {"applied": False, "llm_weight": current, "reason": "no_significant_gain"}


def evaluate_event_llm_calibration(
    rows: Iterable[Mapping[str, Any]],
    *,
    current_share: float = 0.3,
    qualifying_streak: int = 0,
) -> Dict[str, Any]:
    """Compare rule and mixed event probabilities using completed outcomes.

    Positive streaks represent qualifying weeks and negative streaks represent
    consecutive regressions.  Two consecutive weeks are required in either
    direction before changing the share by 0.1.
    """
    records = []
    for row in rows:
        try:
            outcome = int(row.get("outcome"))
            rule = float(row.get("rule_score"))
            llm = float(row.get("llm_score"))
        except (TypeError, ValueError):
            continue
        if outcome not in {0, 1} or not (0 <= rule <= 1 and 0 <= llm <= 1):
            continue
        records.append((outcome, rule, llm, bool(row.get("p0"))))

    share = max(0.3, min(0.5, float(current_share)))
    if not records:
        return {
            "applied": False,
            "llm_share": share,
            "qualifying_streak": 0,
            "reason": "insufficient_samples",
            "metrics": {"sample_count": 0},
        }

    mixed_rows = [(outcome, rule, (1.0 - share) * rule + share * llm, p0) for outcome, rule, llm, p0 in records]
    rule_brier = sum((rule - outcome) ** 2 for outcome, rule, _, _ in mixed_rows) / len(mixed_rows)
    mixed_brier = sum((mixed - outcome) ** 2 for outcome, _, mixed, _ in mixed_rows) / len(mixed_rows)
    rule_accuracy = sum((rule >= 0.5) == bool(outcome) for outcome, rule, _, _ in mixed_rows) / len(mixed_rows)
    mixed_accuracy = sum((mixed >= 0.5) == bool(outcome) for outcome, _, mixed, _ in mixed_rows) / len(mixed_rows)
    p0_rows = [row for row in mixed_rows if row[3] and row[0] == 0]
    rule_p0_misses = sum(rule >= 0.5 for _, rule, _, _ in p0_rows)
    mixed_p0_misses = sum(mixed >= 0.5 for _, _, mixed, _ in p0_rows)
    brier_improvement = ((rule_brier - mixed_brier) / rule_brier * 100.0) if rule_brier else 0.0
    accuracy_improvement = (mixed_accuracy - rule_accuracy) * 100.0
    metrics = {
        "sample_count": len(mixed_rows),
        "rule_brier": round(rule_brier, 6),
        "mixed_brier": round(mixed_brier, 6),
        "brier_improvement_pct": round(brier_improvement, 3),
        "rule_accuracy_pct": round(rule_accuracy * 100.0, 3),
        "mixed_accuracy_pct": round(mixed_accuracy * 100.0, 3),
        "accuracy_improvement_pp": round(accuracy_improvement, 3),
        "rule_p0_misses": rule_p0_misses,
        "mixed_p0_misses": mixed_p0_misses,
    }
    qualifies = (
        len(mixed_rows) >= 100
        and brier_improvement >= 5.0
        and accuracy_improvement >= 3.0
        and mixed_p0_misses <= rule_p0_misses
    )
    regresses = (
        len(mixed_rows) >= 100
        and (brier_improvement < 0 or accuracy_improvement < 0 or mixed_p0_misses > rule_p0_misses)
    )
    if qualifies:
        streak = qualifying_streak + 1 if qualifying_streak > 0 else 1
    elif regresses:
        streak = qualifying_streak - 1 if qualifying_streak < 0 else -1
    else:
        streak = 0

    applied = False
    reason = "quality_threshold_not_met"
    if streak >= 2 and share < 0.5:
        share = round(min(0.5, share + 0.1), 1)
        applied, streak, reason = True, 0, "two_week_outperformance"
    elif streak <= -2 and share > 0.3:
        share = round(max(0.3, share - 0.1), 1)
        applied, streak, reason = True, 0, "two_week_regression"
    elif qualifies:
        reason = "awaiting_second_qualifying_week"
    elif regresses:
        reason = "awaiting_second_regression_week"
    return {
        "applied": applied,
        "llm_share": share,
        "qualifying_streak": streak,
        "reason": reason,
        "metrics": metrics,
    }


def load_factor_weights(path: Path) -> Dict[str, float]:
    """Load only a complete, current-version weight set with a valid total."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        stored = payload.get("weights") if isinstance(payload, Mapping) else None
        if payload.get("factor_version") != "evidence-v2" or not isinstance(stored, Mapping):
            return dict(DEFAULT_WEIGHTS)
        if set(stored) != set(DEFAULT_WEIGHTS):
            return dict(DEFAULT_WEIGHTS)
        candidate = {key: float(stored[key]) for key in DEFAULT_WEIGHTS}
        if any(not math.isfinite(value) or value < 0 for value in candidate.values()):
            return dict(DEFAULT_WEIGHTS)
        if abs(sum(candidate.values()) - sum(DEFAULT_WEIGHTS.values())) >= 1e-6:
            return dict(DEFAULT_WEIGHTS)
        return candidate
    except Exception:
        return dict(DEFAULT_WEIGHTS)


def load_event_llm_share(path: Path) -> float:
    """Load the independently calibrated share inside the event sub-score."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        value = float((payload.get("event_llm_calibration") or {}).get("llm_share", 0.3))
        return max(0.3, min(0.5, value))
    except Exception:
        return 0.3


def load_selection_threshold(path: Path) -> float:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        value = float(payload.get("minimum_score", .55))
        if payload.get("factor_version") == "evidence-v2" and math.isfinite(value) and .55 <= value <= .8:
            return value
    except (OSError, ValueError, TypeError):
        pass
    return .55


def build_event_calibration_records(rows: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    records: list[Dict[str, Any]] = []
    for row in _latest_verifications(rows):
        for pick in row.get("per_pick") or []:
            result = _verification_return(row, pick)
            if result is None:
                continue
            factors = pick.get("factors") or {}
            try:
                rule_score = float(factors.get("event_score_rule"))
                llm_score = float(factors.get("event_score_llm"))
                outcome = 1 if result > 0 else 0
            except (TypeError, ValueError):
                continue
            risk_flags = [str(item) for item in (pick.get("risk_flags") or [])]
            records.append({
                "outcome": outcome,
                "rule_score": rule_score,
                "llm_score": llm_score,
                "p0": any(flag.startswith("p0") for flag in risk_flags),
            })
    return records


def _latest_verifications(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Latest append-only ledger entry wins per signal date and factor version."""
    dated: dict[tuple[str, str], Mapping[str, Any]] = {}
    legacy = []
    for row in rows:
        if not row.get("verification_version"):
            legacy.append(row)
            continue
        key = (str(row.get("as_of", "")), str(row.get("factor_version", "")))
        previous = dated.get(key)
        if previous is None or str(row.get("verified_at", "")) >= str(previous.get("verified_at", "")):
            dated[key] = row
    return legacy + list(dated.values())


def _verification_return(row: Mapping[str, Any], pick: Any) -> float | None:
    if not isinstance(pick, Mapping) or row.get("verification_status") == "excluded":
        return None
    if row.get("verification_version"):
        execution = (pick.get("execution") or {}).get("5") or {}
        if execution.get("status") != "filled":
            return None
        value = execution.get("excess_return_pct")
    else:
        # Compatibility for old diagnostic consumers only. The live weekly
        # job explicitly excludes these rows from parameter promotion.
        value = pick.get("return_T5_pct")
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


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
    for row in _latest_verifications(rows):
        for pick in row.get("per_pick") or []:
            result = _verification_return(row, pick)
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
    """Promote only dated rolling-tested weights; retain defaults without proof."""
    ledgers_dir = Path(ledgers_dir)
    ledger_path = ledgers_dir / "stock-recommend-ledger.jsonl"
    if weights_path is None:
        weights_path = ledgers_dir.parent.parent / "ah_recommendation_system" / "backend" / "data" / "stock_recommend" / "factor_weights.json"
    weights_path = Path(weights_path)
    ledger_rows = [row for row in _latest_verifications(_read_jsonl(ledger_path))
                   if row.get("verification_version") == "execution-v1"
                   and row.get("verification_status") == "complete"
                   and row.get("calibration_eligible") is True]
    old = load_factor_weights(weights_path) if weights_path.exists() else dict(DEFAULT_WEIGHTS)
    stats = aggregate_factor_stats(ledger_rows)
    from .rolling_calibration import rolling_calibrate
    evidence_rows = [row for row in _latest_verifications(_read_jsonl(ledger_path))
                    if row.get("factor_version") == "evidence-v2" and row.get("verification_status") != "excluded"]
    panel = [candidate for row in evidence_rows
             if row.get("candidate_panel_complete") is True
             for candidate in row.get("candidate_outcomes", [])]
    fingerprint = hashlib.sha256(json.dumps(panel, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    decision = rolling_calibrate(panel, baseline=old, as_of=datetime.now().strftime("%Y-%m-%d"), max_delta=max_delta,
                                 baseline_threshold=load_selection_threshold(weights_path))
    # Never drop an older unresolved signal date while retaining surrounding
    # winners. Recently unmatured reports may wait without invalidating history.
    if any(row.get("candidate_panel_complete") is not True
           and (datetime.now() - datetime.strptime(row["as_of"], "%Y-%m-%d")).days > 40
           for row in evidence_rows if row.get("as_of")):
        decision.update(applied=False, weights=old, threshold=load_selection_threshold(weights_path))
        decision["reasons"].append("unresolved_historical_candidate_panel")
    previous_payload = {}
    if weights_path.exists():
        try:
            previous_payload = json.loads(weights_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if previous_payload.get("last_promoted_fingerprint") == fingerprint:
        decision.update(applied=False, weights=old, threshold=load_selection_threshold(weights_path))
        decision["reasons"].append("same_evidence_already_promoted")
    new = decision["weights"]
    old_calibration: Dict[str, Any] = {}
    if weights_path.exists():
        try:
            old_calibration = dict(
                (json.loads(weights_path.read_text(encoding="utf-8")).get("event_llm_calibration") or {})
            )
        except Exception:
            old_calibration = {}
    event_calibration = evaluate_event_llm_calibration(
        build_event_calibration_records(ledger_rows),
        current_share=float(old_calibration.get("llm_share", 0.3)),
        qualifying_streak=int(old_calibration.get("qualifying_streak", 0)),
    )
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "factor_version": "evidence-v2",
        "max_delta": max_delta,
        "weights": new,
        "stats": stats,
        "applied": decision["applied"],
        "decision_reason": decision["reasons"],
        "minimum_score": decision["threshold"],
        "rolling_validation": decision,
        "evidence_fingerprint": fingerprint,
        "last_promoted_fingerprint": fingerprint if decision["applied"] else previous_payload.get("last_promoted_fingerprint"),
        "event_llm_calibration": event_calibration,
    }
    weights_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "weights_path": str(weights_path),
        "weights": new,
        "stats": stats,
        "event_llm_calibration": event_calibration,
        "rolling_validation": decision,
    }
