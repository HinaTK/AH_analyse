"""Bounded evidence enrichment shared by the live pipeline and replay tests."""
from __future__ import annotations

import pandas as pd
from loguru import logger

from .execution_data import ExecutionDataProvider
from .financial_data import FinancialDataProvider
from .market_factors import classify_regime, relative_strength


def enrich_evidence(rows: list[dict], *, as_of: str, market_provider=None,
                    financial_provider=None, limit: int = 100) -> dict:
    market_provider = market_provider or ExecutionDataProvider()
    financial_provider = financial_provider or FinancialDataProvider()
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=250)).strftime("%Y-%m-%d")
    errors = []
    benchmark = pd.DataFrame()
    try:
        benchmark = market_provider.get_benchmark_bars(start, as_of)
    except Exception as exc:
        errors.append(f"benchmark:{type(exc).__name__}")
    regime = classify_regime(benchmark, as_of=as_of)
    regime["source"] = "baostock:sh.000300"
    targets = rows[:max(0, limit)]
    quality_count = relative_count = 0
    for row in targets:
        code = str(row.get("code") or "")
        try:
            records = financial_provider.get_records(code, as_of=as_of)
            row["financial_records"] = records
            quality_count += bool(records)
        except Exception as exc:
            row.setdefault("feature_errors", []).append(f"financial:{type(exc).__name__}")
        if not benchmark.empty:
            try:
                signal_fetcher = getattr(market_provider, "get_signal_bars", market_provider.get_stock_bars)
                stock = signal_fetcher(code, start, as_of)
                stock = stock[pd.to_datetime(stock["date"], errors="coerce") < pd.Timestamp(as_of)].sort_values("date")
                # Unadjusted series cannot safely measure momentum across an
                # ex-right/dividend discontinuity. Omit RS until adjusted PIT
                # factors are available, instead of scoring the discontinuity.
                if stock.attrs.get("adjustment") != "forward" and "prev_close" in stock and len(stock) > 1:
                    close = pd.to_numeric(stock["close"], errors="coerce").shift(1)
                    previous = pd.to_numeric(stock["prev_close"], errors="coerce")
                    if ((previous - close).abs() > .011).any():
                        raise ValueError("corporate_action_requires_adjusted_relative_strength")
                result = relative_strength(stock, benchmark, as_of=as_of)
                row["relative_strength_evidence"] = result
                if result["status"] == "available":
                    row.update(benchmark_excess_60d_pct=result["excess_pct"],
                               benchmark_source=regime["source"], benchmark_end=result["end"])
                    relative_count += 1
            except Exception as exc:
                row.setdefault("feature_errors", []).append(f"relative_strength:{type(exc).__name__}:{exc}")
        logger.info("candidate evidence code={} financial={} relative_strength={}", code,
                    bool(row.get("financial_records")), (row.get("relative_strength_evidence") or {}).get("status", "unavailable"))
    return {"market_regime": regime, "errors": errors, "as_of": as_of,
            "coverage": "bounded_candidate_sample", "candidate_count": len(rows),
            "attempted_count": len(targets), "financial_count": quality_count,
            "relative_strength_count": relative_count,
            "financial_scope": "annual_statements_provider_history_not_vintage_archive"}
