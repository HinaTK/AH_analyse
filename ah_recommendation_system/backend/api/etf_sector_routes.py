from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ah_recommendation_system.backend.etf_sector.etf_sector_report import (
    generate_etf_sector_block,
)
from ah_recommendation_system.backend.etf_sector.etf_trend_analysis import (
    generate_etf_trend_recommendation_block,
)
from ah_recommendation_system.backend.etf_sector.etf_universe_selector import (
    select_hot_etf_candidates,
)
from ah_recommendation_system.backend.etf_sector.etf_trend_history import (
    extract_etf_trend_from_report,
    load_etf_trend_history,
    normalize_history_limit,
    summarize_etf_trend_snapshot,
)
from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)


router = APIRouter(prefix="/api/v1/etf-sector", tags=["etf-sector"])


def _load_latest_stored_etf_trend() -> Optional[Dict[str, Any]]:
    store = get_report_store()
    report = store.load_latest()
    if not report:
        return None
    blk = report.get("etf_sector") or {}
    trend = blk.get("etf_trend")
    return trend if isinstance(trend, dict) and trend else None


def _stored_trend_fallback(reason: str) -> Optional[Dict[str, Any]]:
    stored = _load_latest_stored_etf_trend()
    if not stored:
        return None
    return {
        **stored,
        "fallback_source": "stored",
        "fallback_reason": reason,
        "data_status": "degraded",
        "fresh_data_available": False,
        "data_warning": "实时采集失败，展示历史存储报告（非实时）；请核对原始报告时间。",
    }


def _should_fallback_to_stored_trend(trend: Dict[str, Any]) -> bool:
    coverage = trend.get("coverage") if isinstance(trend, dict) else None
    if not isinstance(coverage, dict):
        return False
    universe_count = coverage.get("universe_count")
    success_count = coverage.get("success_count")
    failed_count = coverage.get("failed_count")
    try:
        universe_count = int(universe_count)
        success_count = int(success_count)
        failed_count = int(failed_count)
    except (TypeError, ValueError):
        return False
    return universe_count > 0 and success_count == 0 and failed_count == universe_count


@router.get("/", response_model=dict)
async def get_etf_sector_block(
    source: str = "stored",
    codes: Optional[str] = None,
    lookback_short: Optional[int] = None,
    lookback_mid: Optional[int] = None,
    lookback_long: Optional[int] = None,
    breakout_window: Optional[int] = None,
) -> Dict[str, Any]:
    """Read ETF/sector/news block from latest stored report or generate live."""
    try:
        if source == "stored":
            store = get_report_store()
            report = store.load_latest()
            if not report:
                raise HTTPException(status_code=404, detail="No stored report")
            blk = report.get("etf_sector")
            if not blk:
                raise HTTPException(
                    status_code=404, detail="etf_sector not available in latest report"
                )
            return blk
        return generate_etf_sector_block(
            trend_codes=codes,
            trend_lookback_short=lookback_short,
            trend_lookback_mid=lookback_mid,
            trend_lookback_long=lookback_long,
            trend_breakout_window=breakout_window,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trend/history", response_model=dict)
async def get_etf_trend_history(limit: int = 30) -> Dict[str, Any]:
    """Return recent ETF trend snapshots extracted from stored reports."""
    try:
        store = get_report_store()
        items = load_etf_trend_history(store, limit=limit)
        return {
            "items": items,
            "limit": normalize_history_limit(limit),
            "count": len(items),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trend/by-date/{yyyymmdd}", response_model=dict)
async def get_etf_trend_by_date(yyyymmdd: str) -> Dict[str, Any]:
    """Read ETF trend recommendation block from one stored report date."""
    try:
        store = get_report_store()
        report = store.load_by_date(yyyymmdd)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        trend = extract_etf_trend_from_report(report)
        if not trend:
            raise HTTPException(
                status_code=404, detail="etf_trend not available in report"
            )

        return {
            "snapshot": summarize_etf_trend_snapshot(trend, report_date=yyyymmdd),
            "trend": trend,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trend", response_model=dict)
async def get_etf_trend_block(
    source: str = "stored",
    codes: Optional[str] = None,
    lookback_short: Optional[int] = None,
    lookback_mid: Optional[int] = None,
    lookback_long: Optional[int] = None,
    breakout_window: Optional[int] = None,
) -> Dict[str, Any]:
    """Read ETF trend recommendation block from stored report or generate live."""
    try:
        if source == "stored":
            trend = _load_latest_stored_etf_trend()
            if not trend:
                raise HTTPException(
                    status_code=404,
                    detail="etf_trend not available in latest report",
                )
            return trend
        auto_selection = None
        effective_codes = codes
        if not isinstance(effective_codes, str) or not effective_codes.strip():
            auto_selection = select_hot_etf_candidates(limit=10)
            selected_codes = auto_selection.get("codes") or []
            if selected_codes:
                effective_codes = ",".join(selected_codes)
        trend = generate_etf_trend_recommendation_block(
            codes=effective_codes,
            universe_items=(auto_selection.get("items") if auto_selection else None),
            lookback_short=lookback_short,
            lookback_mid=lookback_mid,
            lookback_long=lookback_long,
            breakout_window=breakout_window,
        )
        if auto_selection and isinstance(trend, dict):
            trend["selection"] = auto_selection
            coverage = trend.get("coverage")
            if isinstance(coverage, dict):
                coverage["custom_universe"] = False
                coverage["selection_mode"] = auto_selection.get("mode")
        if _should_fallback_to_stored_trend(trend):
            stored_trend = _stored_trend_fallback("live_all_fetch_failed")
            if stored_trend:
                return stored_trend
        return trend
    except HTTPException:
        raise
    except Exception as e:
        if source != "stored":
            stored_trend = _stored_trend_fallback("live_fetch_exception")
            if stored_trend:
                return stored_trend
        raise HTTPException(status_code=500, detail=str(e))
