"""Capital-constrained daily marking for non-overlapping equal-slot cohorts.

Trade paths include actual order fees. A slot uses one fixed share order with
its own initial cost as numeraire; this is an equal-capital research portfolio,
not a claim that a live account can buy fractional A-share lots. Lot rounding
and account size require a separate broker/account simulation.
"""
from __future__ import annotations

import math

import pandas as pd


def evaluate_cohorts(cohorts: list[list[dict]], *, slots: int = 5, benchmark_calendar: dict | None = None) -> dict:
    if slots < 1:
        raise ValueError("slots must be positive")
    equity = benchmark = peak = 1.0
    drawdown = turnover = 0.0
    free_after = pd.Timestamp.min
    curve, reasons, regimes = [], [], {}
    for cohort in cohorts:
        if not cohort:
            continue
        if len(cohort) > slots:
            raise ValueError("cohort exceeds capital slots")
        signal = min(pd.Timestamp(row["date"]) for row in cohort)
        if signal <= free_after:
            raise ValueError("overlapping_cohorts_double_spend_capital")
        free_after = max(pd.Timestamp(row["label_end"]) for row in cohort)
        paths = [row.get("daily_benchmark") or {} for row in cohort]
        if not all(paths):
            reasons.append("incomplete_or_mismatched_benchmark")
            continue
        # The benchmark is common to the cohort but delayed exits may provide
        # longer individual paths. Require agreement on the shared prefix and
        # use the longest complete calendar through the latest exit.
        common_dates = sorted(set(paths[0]).intersection(*[set(path) for path in paths[1:]]))
        if any(path.get(date) != paths[0].get(date) for path in paths[1:] for date in common_dates):
            reasons.append("incomplete_or_mismatched_benchmark")
            continue
        dates = sorted(set().union(*[set(path) for path in paths]))
        benchmark_path = {date: next(path[date] for path in paths if date in path) for date in dates}
        if dates[-1] != str(free_after.date()) or any(sorted(path) != dates[:len(path)] for path in paths):
            reasons.append("incomplete_or_mismatched_benchmark")
            continue
        filled = [row for row in cohort if row.get("status") == "filled"]
        marked = []
        for row in filled:
            own_dates = [date for date in dates if date <= str(pd.Timestamp(row["label_end"]).date())]
            marks = row.get("daily_equity") or {}
            if set(marks) != set(own_dates) or not own_dates:
                break
            marked.append({**row, "daily_equity": {date: marks.get(date, marks[own_dates[-1]]) for date in dates}})
        if len(marked) != len(filled):
            reasons.append("incomplete_daily_marks")
            continue
        filled = marked
        values = list(benchmark_path.values()) + [value for row in filled for value in row["daily_equity"].values()]
        if not dates or any(not isinstance(v, (float, int)) or not math.isfinite(v) or v <= 0 for v in values):
            reasons.append("invalid_daily_marks")
            continue
        start_equity, start_benchmark = equity, benchmark
        for date in dates:
            equity = start_equity * (1 + sum(row["daily_equity"][date] - 1 for row in filled) / slots)
            benchmark = start_benchmark * benchmark_path[date]
            peak = max(peak, equity)
            drawdown = min(drawdown, equity / peak - 1)
            curve.append({"date": date, "equity": equity, "benchmark": benchmark})
        turnover += sum(1 + row["daily_equity"][dates[-1]] for row in filled) / slots
        regime = str(cohort[0].get("regime") or "unknown")
        regimes.setdefault(regime, []).append((equity / start_equity - benchmark_path[dates[-1]]) * 100)
    if benchmark_calendar:
        calendar_dates = sorted(benchmark_calendar)
        quotes = [float(bar[field]) for bar in benchmark_calendar.values() for field in ("open", "close")]
        if any(not math.isfinite(value) or value <= 0 for value in quotes):
            reasons.append("invalid_common_benchmark")
        elif any(point["date"] not in benchmark_calendar for point in curve):
            reasons.append("common_calendar_missing_trade_marks")
        else:
            marks = {point["date"]: point["equity"] for point in curve}
            base_open = benchmark_calendar[calendar_dates[0]]["open"]
            full_curve, current, peak, drawdown = [], 1.0, 1.0, 0.0
            for date in calendar_dates:
                current = marks.get(date, current)
                peak = max(peak, current)
                drawdown = min(drawdown, current / peak - 1)
                benchmark = benchmark_calendar[date]["close"] / base_open
                full_curve.append({"date": date, "equity": current, "benchmark": benchmark})
            curve, equity = full_curve, current
    return {"risk_validated": bool(curve) and not reasons, "reasons": sorted(set(reasons)),
            "net_return_pct": (equity - 1) * 100, "benchmark_return_pct": (benchmark - 1) * 100,
            "net_excess_pct": (equity - benchmark) * 100, "max_drawdown_pct": drawdown * 100,
            "turnover": turnover, "daily_curve": curve,
            "regime_mean_excess_pct": {key: sum(values) / len(values) for key, values in regimes.items()},
            "methodology": "equal_slot_nonoverlapping_daily_close_v1",
            "common_calendar": bool(benchmark_calendar),
            "limitations": ["fixed_horizon_not_watch_trigger", "equal_capital_normalized_orders",
                            "close_to_close_drawdown_not_intraday"] + ([] if benchmark_calendar else ["benchmark_exposed_during_cohorts_only"])}
