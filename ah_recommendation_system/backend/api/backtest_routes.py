# Backtest API endpoints

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ah_recommendation_system.backend.backtest.etf_trend_backtest import (
    run_etf_trend_backtest,
)
from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)


router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


def _extract_pair_trading_backtest(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pt = (report or {}).get("pair_trading") or {}
    bt = pt.get("backtest")
    return bt if isinstance(bt, dict) else None


@router.get("/pair-trading/latest")
async def get_pair_trading_backtest_latest() -> Dict[str, Any]:
    store = get_report_store()
    report = store.load_latest()
    if not report:
        raise HTTPException(status_code=404, detail="No stored report found")

    bt = _extract_pair_trading_backtest(report)
    if not bt:
        raise HTTPException(
            status_code=404, detail="No pair trading backtest found in latest report"
        )
    return bt


@router.get("/pair-trading/by-date/{yyyymmdd}")
async def get_pair_trading_backtest_by_date(yyyymmdd: str) -> Dict[str, Any]:
    store = get_report_store()
    report = store.load_by_date(yyyymmdd)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    bt = _extract_pair_trading_backtest(report)
    if not bt:
        raise HTTPException(
            status_code=404, detail="No pair trading backtest found in report"
        )
    return bt


@router.get("/etf-trend")
async def get_etf_trend_backtest(
    codes: Optional[str] = None,
    top_n: int = 1,
    rebalance_days: int = 20,
    lookback_short: Optional[int] = None,
    lookback_mid: Optional[int] = None,
    trade_cost_pct: float = 0.1,
    max_curve_points: int = 180,
) -> Dict[str, Any]:
    try:
        return run_etf_trend_backtest(
            codes=codes,
            top_n=top_n,
            rebalance_days=rebalance_days,
            lookback_short=lookback_short,
            lookback_mid=lookback_mid,
            trade_cost_pct=trade_cost_pct,
            max_curve_points=max_curve_points,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
