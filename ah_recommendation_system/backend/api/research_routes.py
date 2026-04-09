from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from ah_recommendation_system.backend.research.research_service import (
    MissingAHMappingError,
)

router = APIRouter(prefix="/api/v1/research", tags=["research"])


def _run_research_builder(builder: Callable[[str], dict], a_code: str) -> dict:
    try:
        return builder(a_code)
    except MissingAHMappingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def build_stock_research(a_code: str) -> dict:
    from ah_recommendation_system.backend.research.research_service import (
        build_stock_research as _build_stock_research,
    )

    return _build_stock_research(a_code)


def build_pair_backtest(a_code: str) -> dict:
    from ah_recommendation_system.backend.research.research_service import (
        build_pair_backtest as _build_pair_backtest,
    )

    return _build_pair_backtest(a_code)


@router.get("/{a_code}")
async def get_stock_research(a_code: str) -> dict:
    return _run_research_builder(build_stock_research, a_code)


@router.get("/{a_code}/backtest")
async def get_stock_research_backtest(a_code: str) -> dict:
    return _run_research_builder(build_pair_backtest, a_code)
