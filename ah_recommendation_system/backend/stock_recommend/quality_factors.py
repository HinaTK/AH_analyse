"""Dated financial quality evidence, with explicit units and missingness."""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable, Mapping

import pandas as pd


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def assess_quality(records: Iterable[Mapping[str, Any]], *, as_of: str, industry: str = "") -> dict[str, Any]:
    """Use the latest already-published period, never combine fiscal periods.

    Scores are transparent initial hypotheses requiring subsequent calibration.
    Date-only publication is eligible the NEXT day, including premarket runs.
    ROE/growth/debt inputs are percentages, not fractions. Cash/profit must use
    identical currency, unit, period and reporting scope in the supplied record.
    """
    cutoff = pd.Timestamp(as_of).normalize()
    usable = []
    for record in records:
        published = pd.to_datetime(record.get("published_at"), errors="coerce")
        period = pd.to_datetime(record.get("period_end"), errors="coerce")
        if pd.isna(published) or pd.isna(period) or not record.get("source"):
            continue
        if period <= published < cutoff and (cutoff - period).days <= 550:
            usable.append((period, published, record))
    result: dict[str, Any] = {"score": None, "status": "unavailable", "metric_count": 0,
                              "cash_conversion": None, "missing": [], "metrics": {}, "components": {}}
    if not usable:
        result["missing"] = ["no_eligible_financial_statement"]
        return result
    period, published, row = max(usable, key=lambda item: (item[0], item[1]))
    result.update(source=row["source"], period_end=period.strftime("%Y-%m-%d"),
                  published_at=published.strftime("%Y-%m-%d"))
    result.update(field_provenance=row.get("field_provenance", {}),
                  vintage_status=row.get("vintage_status", "unspecified"),
                  reporting_scope=row.get("reporting_scope", "unspecified"))
    scores = result["components"]
    for field, baseline, scale in (("roe_pct", 0, 20), ("profit_growth_pct", -20, 60)):
        value = number(row.get(field))
        if value is None:
            result["missing"].append(field)
        else:
            result["metrics"][field] = value
            scores[field] = _clip((value - baseline) / scale)
    financial = any(label in industry.lower() for label in ("银行", "证券", "券商", "保险", "bank", "insurance", "securities"))
    if financial:
        result["missing"].append("financial_sector_requires_specialized_cash_and_capital_metrics")
    else:
        debt = number(row.get("debt_to_assets_pct"))
        if debt is not None and 0 <= debt <= 100:
            scores["debt_to_assets_pct"] = _clip((90 - debt) / 60)
            result["metrics"]["debt_to_assets_pct"] = debt
        else:
            result["missing"].append("debt_to_assets_pct")
        cash, profit = number(row.get("operating_cash_flow")), number(row.get("net_profit"))
        units_match = (row.get("cash_currency") and row.get("cash_currency") == row.get("profit_currency")
                       and row.get("cash_unit") and row.get("cash_unit") == row.get("profit_unit"))
        direct_ratio = number(row.get("cash_conversion_ratio"))
        if (direct_ratio is not None and row.get("cash_ratio_unit") == "ratio"
                and row.get("cash_ratio_source") and profit is not None and profit > 0):
            result["cash_conversion"] = direct_ratio
            scores["cash_conversion"] = _clip(direct_ratio / 1.5)
        elif not units_match:
            result["missing"].append("cash_unit_or_currency_mismatch")
        elif cash is None or profit is None or profit <= 0:
            result["missing"].append("cash_conversion_unavailable")
        else:
            ratio = cash / profit
            result["cash_conversion"] = ratio
            scores["cash_conversion"] = _clip(ratio / 1.5)
    result["metric_count"] = len(scores)
    if scores:
        result["score"] = round(sum(scores.values()) / len(scores), 6)
        result["status"] = "available" if len(scores) == 4 else "partial"
    return result
