from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)


router = APIRouter(prefix="/api/v1/etf-sector", tags=["etf-sector"])


@router.get("/", response_model=dict)
async def get_etf_sector_block() -> Dict[str, Any]:
    """Read ETF/sector/news block from latest stored report."""
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
