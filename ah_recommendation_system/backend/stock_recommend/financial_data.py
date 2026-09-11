"""BaoStock statement adapter with publication-aware, same-period joins.

The raw quarterly roeAvg / YOYNI / liabilityToAsset are fractions (the same
representation used by Qlib's PIT collector). Our scoring schema uses percent.
Provider history can contain revisions; it is NOT a historical vintage archive.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

import pandas as pd

from .execution_data import _SESSION_LOCK
from .quality_factors import number


FIELDS = {
    "profit": {"roeAvg": ("roe_pct", 100), "netProfit": ("net_profit", 1)},
    "growth": {"YOYNI": ("profit_growth_pct", 100)},
    "balance": {"liabilityToAsset": ("debt_to_assets_pct", 100)},
    "cash_flow": {"CFOToNP": ("cash_conversion_ratio", 1)},
}


def merge_statements(tables: Mapping, *, as_of: str) -> list[dict]:
    cutoff = pd.Timestamp(as_of).normalize()
    latest = {}
    for table, fields in FIELDS.items():
        for row in tables.get(table, []):
            published = pd.to_datetime(row.get("pubDate"), errors="coerce")
            period = pd.to_datetime(row.get("statDate"), errors="coerce")
            if pd.isna(published) or pd.isna(period) or not period <= published < cutoff:
                continue
            key = (period, table)
            if key not in latest or published > latest[key][0]:
                latest[key] = (published, row)
    merged = {}
    for (period, table), (published, raw) in latest.items():
        row = merged.setdefault(period, {
            "period_end": period.strftime("%Y-%m-%d"), "published_at": "",
            "source": "baostock:quarterly", "field_provenance": {},
            "vintage_status": "provider_history_not_revision_archive",
        })
        row["published_at"] = max(row["published_at"], published.strftime("%Y-%m-%d"))
        for field, (target, scale) in FIELDS[table].items():
            value = number(raw.get(field))
            if value is None:
                continue
            row[target] = value * scale
            row["field_provenance"][target] = {
                "field": field, "table": table, "published_at": published.strftime("%Y-%m-%d"),
                "raw_value": value, "scale": scale,
            }
        if table == "profit":
            row.update(profit_currency="CNY", profit_unit="yuan")
        if table == "cash_flow":
            row["cash_ratio_unit"] = "ratio"
            row["cash_ratio_source"] = "baostock:CFOToNP"
    return [merged[key] for key in sorted(merged, reverse=True)]


class FinancialDataProvider:
    """Bounded annual statement queries; no estimates or synthetic fallback.

    Annual reports avoid comparing a quarterly ROE with an annual threshold.
    Cache lifetime is one provider instance/run, so revised dates are rechecked.
    """

    def __init__(self, api=None):
        self.api = api
        self._cache = {}

    def get_records(self, code: str, *, as_of: str) -> list[dict]:
        key = (code, as_of)
        if key in self._cache:
            return self._cache[key]
        if len(code) != 6 or not code.isdigit() or code.startswith(("8", "43", "92")):
            raise ValueError("financial_provider_unsupported_symbol")
        api = self.api
        if api is None:
            import baostock as api
        symbol = ("sh." if code.startswith("6") else "sz.") + code
        tables = {name: [] for name in FIELDS}
        with _SESSION_LOCK:
            if str(api.login().error_code) != "0":
                raise RuntimeError("financial_provider_login_failed")
            try:
                # Two annual periods cover the pre-publication part of a year.
                for year in (pd.Timestamp(as_of).year - 1, pd.Timestamp(as_of).year - 2):
                    for table in FIELDS:
                        response = getattr(api, f"query_{table}_data")(code=symbol, year=year, quarter=4)
                        if str(response.error_code) != "0":
                            raise RuntimeError(f"financial_query_failed:{table}:{response.error_code}")
                        while response.next():
                            tables[table].append(dict(zip(response.fields, response.get_row_data())))
                        if str(response.error_code) != "0":
                            raise RuntimeError(f"financial_incomplete_response:{table}")
            finally:
                api.logout()
        rows = merge_statements(tables, as_of=as_of)
        for row in rows:
            row.update(observed_at=datetime.now(timezone.utc).isoformat(), reporting_scope="annual")
        self._cache[key] = rows
        return rows
