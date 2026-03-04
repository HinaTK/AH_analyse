# Backtest API endpoints

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

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
