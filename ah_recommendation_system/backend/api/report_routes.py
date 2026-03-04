# Report/history API
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)
from ah_recommendation_system.backend.reporting.report_refresh import (
    refresh_latest_report,
    get_refresh_status,
)

router = APIRouter(prefix="/api/v1/report", tags=["report"])


@router.get("/latest")
async def get_latest_report() -> Dict[str, Any]:
    store = get_report_store()
    report = store.load_latest()
    if not report:
        raise HTTPException(
            status_code=404,
            detail="No stored report found. Run run_daily_job.py first.",
        )
    return report


@router.get("/by-date/{yyyymmdd}")
async def get_report_by_date(yyyymmdd: str) -> Dict[str, Any]:
    store = get_report_store()
    report = store.load_by_date(yyyymmdd)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/list")
async def list_reports(limit: int = 30) -> Dict[str, Any]:
    store = get_report_store()
    return {"success": True, "reports": store.list_reports(limit=limit)}


@router.post("/refresh")
async def refresh_report(mode: str = "live", force: bool = True) -> Dict[str, Any]:
    """Force refresh the stored latest report.

    This regenerates the full report and overwrites today's stored report and latest.json.
    """
    result = await run_in_threadpool(refresh_latest_report, mode=mode, force=force)
    if not result.get("success") and result.get("message") == "refresh_in_progress":
        raise HTTPException(
            status_code=409, detail="Report refresh already in progress"
        )
    if not result.get("success"):
        raise HTTPException(
            status_code=500, detail=result.get("error") or "refresh_failed"
        )
    return result


@router.get("/refresh/status")
async def refresh_report_status() -> Dict[str, Any]:
    return {"success": True, "status": get_refresh_status()}


@router.post("/refresh/reset")
async def reset_refresh_state() -> Dict[str, Any]:
    """Force reset the refresh state if it's stuck."""
    from ah_recommendation_system.backend.reporting.report_refresh import (
        _REFRESH_STATE,
        _REFRESH_LOCK,
    )

    was_stuck = _REFRESH_STATE["in_progress"]
    _REFRESH_STATE["in_progress"] = False
    _REFRESH_STATE["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if was_stuck:
        _REFRESH_STATE["last_error"] = "manual_reset"
    try:
        _REFRESH_LOCK.release()
    except RuntimeError:
        pass

    return {
        "success": True,
        "message": "Reset successful" if was_stuck else "State was not stuck",
        "was_stuck": was_stuck,
    }
