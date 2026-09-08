from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ah_recommendation_system.backend.reporting.report_store import get_report_store
from ah_recommendation_system.backend.review.review_service import build_etf_sector_review


router = APIRouter(prefix="/api/v1/review", tags=["review"])


@router.get("/etf-sector")
async def get_etf_sector_review(limit_reports: int = 40) -> Dict[str, Any]:
    try:
        return build_etf_sector_review(get_report_store(), limit_reports=limit_reports)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
