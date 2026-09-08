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

_CACHE: Dict[str, Any] = {"ts": {}, "payload": {}}
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


def _compute_health(*, deep: bool) -> Dict[str, Any]:
    # NOTE: Some upstream sources rely on embedded JS runtimes and are not
    # thread-safe in-process (py_mini_racer). Keep checks sequential.
    checks = [
        ("etf_spot_ths", fetch_etf_spot_ths),
        ("etf_spot_sina", fetch_etf_spot_sina),
        ("industry_summary_ths", fetch_industry_summary_ths),
    ]
    if deep:
        checks += [
            ("stock_a_spot_sina", fetch_stock_a_spot_sina),
            ("concept_name_ths", fetch_concept_name_ths),
        ]

    results = [_check_df(name, fn) for name, fn in checks]
    ok = all(r.get("ok") for r in results)
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ok": ok,
        "deep": bool(deep),
        "checks": results,
    }


@router.get("/health", response_model=dict)
async def data_health(deep: bool = False) -> Dict[str, Any]:
    """Lightweight health check for upstream data sources.

    Cached for a short TTL to avoid hammering upstream.
    """
    now = time.time()
    cache_key = "deep" if deep else "lite"
    ts = float((_CACHE.get("ts") or {}).get(cache_key) or 0.0)
    payload = (_CACHE.get("payload") or {}).get(cache_key)
    if payload is not None and (now - ts) < _TTL_SECONDS:
        return payload

    payload2 = await run_in_threadpool(_compute_health, deep=deep)
    (_CACHE.setdefault("ts", {}))[cache_key] = now
    (_CACHE.setdefault("payload", {}))[cache_key] = payload2
    return payload2
