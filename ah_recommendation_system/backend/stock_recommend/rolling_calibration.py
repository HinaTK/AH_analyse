"""Purged rolling IC fitting, validation selection and untouched test evaluation.

Inspired by Qlib rolling tasks, not AlphaEvo's partition of existing trades.
Input is a dated candidate panel saved before outcomes were known. Returns must
be net executable outcomes. The conservative evaluation holds one cohort until
its latest exit, leaving unused slots in cash; it never compounds overlapping
five-day outcomes as if they were daily portfolio returns.
"""
from __future__ import annotations

import math
from typing import Mapping

import pandas as pd

from .factor_validation import validate_factor_set
from .portfolio_validation import evaluate_cohorts


def _score(row, weights):
    return sum(weights[key] * row["factors"][key] for key in weights) + float(row.get("risk_penalty", 0))


def _evaluate(rows, weights, threshold, top_k=5):
    wealth = peak = 1.0
    drawdown = 0.0
    returns, excess, cohorts, selected_cohorts = [], [], [], []
    free_after = pd.Timestamp.min
    grouped = {}
    for row in rows:
        grouped.setdefault(row["date"], []).append(row)
    for date, group in sorted(grouped.items()):
        if date <= free_after:
            continue
        eligible = [r for r in group if r.get("eligible") is True and (r.get("regime") in {"offense", "balanced"}
                    or (r.get("regime") == "defense" and r.get("defense_qualified") is True))
                    and _score(r, weights) >= threshold]
        chosen, industries = [], set()
        for candidate in sorted(eligible, key=lambda r: (-_score(r, weights), str(r["code"]))):
            groups = set(candidate.get("focus_industries") or [])
            if groups & industries:
                continue
            chosen.append(candidate)
            industries.update(groups)
            if len(chosen) == (min(top_k, 2) if candidate.get("regime") == "defense" else top_k):
                break
        if not chosen:
            continue
        # An unfilled order occupies its allocation as cash for this cohort.
        filled = [r for r in chosen if r["status"] == "filled"]
        selected_cohorts.append(chosen)
        net = sum(r["net_return_pct"] for r in filled) / top_k
        base_return = float(chosen[0].get("benchmark_return_pct", 0))
        active = net - base_return
        wealth *= 1 + net / 100
        peak = max(peak, wealth)
        drawdown = min(drawdown, wealth / peak - 1)
        free_after = max(r["label_end"] for r in chosen)
        returns.append(net)
        excess.append(active)
        cohorts.append({"date": str(date.date()), "exit": str(free_after.date()),
                        "codes": [r["code"] for r in filled], "net_return_pct": net,
                        "net_excess_pct": active, "regime": chosen[0]["regime"]})
    regimes = {}
    for cohort in cohorts:
        regimes.setdefault(cohort["regime"], []).append(cohort["net_excess_pct"])
    calendar = {}
    if rows:
        start_date = min(r["date"] for r in rows).strftime("%Y-%m-%d")
        end_date = max(r["label_end"] for r in rows).strftime("%Y-%m-%d")
        for row in rows:
            for date, bar in (row.get("market_calendar") or {}).items():
                if start_date < date <= end_date:
                    if date in calendar and calendar[date] != bar:
                        raise ValueError("inconsistent_common_benchmark_calendar")
                    calendar[date] = bar
    portfolio = evaluate_cohorts(selected_cohorts, slots=top_k, benchmark_calendar=calendar)
    return {"cohort_count": len(cohorts), "net_return_pct": (wealth - 1) * 100,
            "mean_net_excess_pct": portfolio["net_excess_pct"] if calendar else sum(excess) / len(excess) if excess else 0.0,
            "cohort_drawdown_pct": drawdown * 100,
            "round_trip_turnover": sum(2 * len(c["codes"]) / top_k for c in cohorts),
            "regime_excess_pct": {key: sum(values) / len(values) for key, values in regimes.items()},
            "cohorts": cohorts,
            "portfolio": portfolio,
            "limitation": "fixed_horizon_equal_slot_cohorts; drawdown_at_cohort_closes_only; not_watch_trigger"}


def _fit(rows, baseline, max_delta):
    diagnostic = validate_factor_set(
        {key: [r["factors"][key] for r in rows] for key in baseline},
        forward_returns=[r["excess_return_pct"] for r in rows],
        dates=[r["date"] for r in rows], symbols=[r["code"] for r in rows],
    )
    # Transfer a bounded budget from weakest to strongest IC, preserving total.
    # Redundant factors remain diagnosed; weights cannot silently double count
    # them by increasing both sides of a highly correlated pair.
    ics = {key: diagnostic["factors"][key]["ic"] for key in baseline}
    valid = [key for key in baseline if ics[key] is not None]
    fitted = dict(baseline)
    if len(valid) >= 2:
        best, worst = max(valid, key=lambda key: ics[key]), min(valid, key=lambda key: ics[key])
        if ics[best] > max(0, ics[worst]):
            delta = min(max_delta, fitted[worst])
            fitted[best] += delta
            fitted[worst] -= delta
    return fitted, diagnostic


def rolling_calibrate(panel, *, baseline: Mapping[str, float], as_of: str,
                      train_days=120, validation_days=40, test_days=40,
                      minimum_folds=3, max_delta=.05, baseline_threshold=.55):
    if min(train_days, validation_days, test_days, minimum_folds) < 1:
        raise ValueError("split lengths and minimum_folds must be positive")
    if not baseline or any(not math.isfinite(v) or v < 0 for v in baseline.values()) or abs(sum(baseline.values()) - 1) > 1e-6:
        raise ValueError("baseline weights must be finite nonnegative and sum to one")
    if not 0 <= max_delta <= .05:
        raise ValueError("weight movement cannot exceed .05")
    rows, seen, incomplete_dates = [], set(), set()
    cutoff = pd.Timestamp(as_of).normalize()
    for raw in panel:
        row = dict(raw)
        date, end = pd.Timestamp(row["date"]), pd.Timestamp(row["label_end"])
        identity = (date, str(row["code"]))
        if identity in seen:
            raise ValueError("duplicate date/code in candidate panel")
        seen.add(identity)
        if pd.isna(date) or pd.isna(end) or not date < end < cutoff:
            if not pd.isna(date):
                incomplete_dates.add(date)
            continue
        factors = row.get("factors") or {}
        try:
            values = {key: float(factors[key]) for key in baseline}
            metrics = {key: float(row[key]) for key in ("net_return_pct", "excess_return_pct")}
        except (TypeError, ValueError, KeyError):
            incomplete_dates.add(date)
            continue
        if any(not math.isfinite(v) for v in [*values.values(), *metrics.values()]):
            incomplete_dates.add(date)
            continue
        if row.get("status") not in {"filled", "unfilled"}:
            incomplete_dates.add(date)
            continue
        rows.append(dict(row, date=date, label_end=end, factors=values, **metrics))
    dates = sorted({row["date"] for row in rows})
    folds, deferred_folds = [], []
    for offset in range(train_days + validation_days, len(dates) - test_days + 1, test_days):
        validation_start, test_start = dates[offset - validation_days], dates[offset]
        train_start, test_end = dates[offset - validation_days - train_days], dates[offset + test_days - 1]
        train = [r for r in rows if train_start <= r["date"] < validation_start and r["label_end"] < validation_start]
        # Reserve a fixed five-session nominal horizon before test starts.
        # If an exceptional delay crosses the boundary, defer the whole fold;
        # never remove only that loser from the validation candidate universe.
        available_sessions = sorted({pd.Timestamp(date) for row in rows for date in (row.get("market_calendar") or {})
                                     if pd.Timestamp(date) < test_start})
        # Entry S+1, horizon=5 exit S+6. Six complete sessions must remain
        # strictly before test; use the supplied exchange calendar when present.
        validation_signal_end = (available_sessions[-7] if len(available_sessions) >= 7
                                 else test_start - pd.offsets.BDay(7))
        validation = [r for r in rows if validation_start <= r["date"] <= validation_signal_end]
        if any(r["label_end"] >= test_start for r in validation):
            deferred_folds.append(str(test_start.date()))
            continue
        # Membership is determined by signal date, never by realized exit.
        # Delayed exits remain in the test cohort even beyond the fold end.
        test = [r for r in rows if test_start <= r["date"] <= test_end]
        if not train or not validation or not test:
            continue
        fitted, diagnostics = _fit(train, baseline, max_delta)
        # The candidate family is fixed before reading any test outcomes.
        options = [(dict(baseline), baseline_threshold), (fitted, baseline_threshold),
                   (fitted, min(.8, baseline_threshold + .05))]
        evaluated = [(weights, threshold, _evaluate(validation, weights, threshold)) for weights, threshold in options]
        weights, threshold, validation_metrics = max(evaluated, key=lambda item: (
            item[2]["mean_net_excess_pct"] if item[2]["cohort_count"] >= 2 else -math.inf,
            item[2]["cohort_drawdown_pct"]))
        folds.append({"train_start": str(train_start.date()), "train_label_end": str(max(r["label_end"] for r in train).date()),
                      "validation_start": str(validation_start.date()),
                      "validation_label_end": str(max(r["label_end"] for r in validation).date()),
                      "test_start": str(test_start.date()), "test_end": str(test_end.date()),
                      "train_count": len(train), "validation_count": len(validation), "test_count": len(test),
                      "fitted_weights": fitted, "selected_weights": weights, "selected_threshold": threshold,
                      "factor_diagnostics": diagnostics, "validation_metrics": validation_metrics,
                      "test_metrics": _evaluate(test, weights, threshold),
                      "baseline_metrics": _evaluate(test, baseline, baseline_threshold)})
    reasons = []
    if deferred_folds:
        reasons.append("deferred_validation_fold_cannot_promote")
    if incomplete_dates:
        reasons.append("incomplete_cross_sections_cannot_promote")
    if len(folds) < minimum_folds or len(rows) < 600:
        reasons.append("insufficient_rolling_samples")
    if any(r.get("source") != "live_execution" or not r.get("point_in_time_snapshot") for r in rows):
        reasons.append("non_live_evidence")
    if any(r.get("panel_scope") != "all_saved_candidates" for r in rows):
        reasons.append("selected_pick_bias")
    qualifying = [f for f in folds if f["test_metrics"]["cohort_count"] >= 3
                  and f["test_metrics"]["mean_net_excess_pct"] > max(0, f["baseline_metrics"]["mean_net_excess_pct"])
                  and f["test_metrics"]["cohort_drawdown_pct"] >= f["baseline_metrics"]["cohort_drawdown_pct"]]
    if not folds or len(qualifying) / len(folds) < .67:
        reasons.append("out_of_sample_gain_not_stable")
    if folds and folds[-1] not in qualifying:
        reasons.append("latest_proposal_failed_test")
    risk_passes = bool(folds) and all(
        f["test_metrics"]["portfolio"]["risk_validated"]
        and f["test_metrics"]["portfolio"]["common_calendar"]
        and f["baseline_metrics"]["portfolio"]["risk_validated"]
        and f["test_metrics"]["portfolio"]["max_drawdown_pct"] >= max(-15, f["baseline_metrics"]["portfolio"]["max_drawdown_pct"])
        and f["test_metrics"]["portfolio"]["net_excess_pct"] >= f["baseline_metrics"]["portfolio"]["net_excess_pct"]
        for f in folds)
    if not risk_passes:
        reasons.append("daily_portfolio_risk_validation_failed")
    return {"applied": not reasons, "reasons": reasons, "sample_count": len(rows), "folds": folds,
            "deferred_folds": deferred_folds,
            "methodology": "purged_rolling_ic_v1", "as_of": as_of,
            "weights": folds[-1]["selected_weights"] if not reasons else dict(baseline),
            "threshold": folds[-1]["selected_threshold"] if not reasons else baseline_threshold,
            "proposed_weights": folds[-1]["selected_weights"] if folds else dict(baseline),
            "proposed_threshold": folds[-1]["selected_threshold"] if folds else baseline_threshold}
