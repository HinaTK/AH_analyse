from __future__ import annotations

import time
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from ah_recommendation_system.backend.etf_sector.ths_sources import (
    fetch_concept_name_ths,
    fetch_etf_spot_sina,
    fetch_etf_spot_ths,
    fetch_industry_summary_ths,
    fetch_stock_a_spot_sina,
)


router = APIRouter(prefix="/api/v1/data", tags=["data"])

_CACHE: Dict[str, Any] = {"ts": 0.0, "payload": None}
_TTL_SECONDS = 60.0


def _check_df(name: str, fn) -> Dict[str, Any]:
    try:
        df = fn()
        ok = isinstance(df, pd.DataFrame) and not df.empty
        return {
            "name": name,
            "ok": bool(ok),
            "rows": int(len(df)) if isinstance(df, pd.DataFrame) else None,
            "cols": int(len(df.columns)) if isinstance(df, pd.DataFrame) else None,
            "error": None,
        }
    except Exception as e:
        return {"name": name, "ok": False, "rows": None, "cols": None, "error": str(e)}


def _compute_health() -> Dict[str, Any]:
    checks = [
        ("etf_spot_ths", fetch_etf_spot_ths),
        ("etf_spot_sina", fetch_etf_spot_sina),
        ("stock_a_spot_sina", fetch_stock_a_spot_sina),
        ("industry_summary_ths", fetch_industry_summary_ths),
        ("concept_name_ths", fetch_concept_name_ths),
    ]
    results = [_check_df(name, fn) for name, fn in checks]
    ok = all(r.get("ok") for r in results)
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ok": ok,
        "checks": results,
    }


@router.get("/health", response_model=dict)
async def data_health() -> Dict[str, Any]:
    """Lightweight health check for upstream data sources.

    Cached for a short TTL to avoid hammering upstream.
    """
    now = time.time()
    if (
        _CACHE.get("payload") is not None
        and (now - float(_CACHE.get("ts") or 0.0)) < _TTL_SECONDS
    ):
        return _CACHE["payload"]

    payload = await run_in_threadpool(_compute_health)
    _CACHE["ts"] = now
    _CACHE["payload"] = payload
    return payload
