from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException

from ah_recommendation_system.backend.watchlist.watchlist_store import (
    MissingAHMappingError,
)

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


class WatchlistStoreLike(Protocol):
    def list_symbols(self) -> list[dict]: ...

    def add_symbol(self, a_code: str) -> None: ...

    def remove_symbol(self, a_code: str) -> None: ...


def get_watchlist_store() -> WatchlistStoreLike:
    from ah_recommendation_system.backend.watchlist.watchlist_store import (
        WatchlistStore,
    )

    return WatchlistStore()


@router.get("")
async def list_watchlist(
    store: WatchlistStoreLike = Depends(get_watchlist_store),
) -> dict:
    try:
        return {"items": store.list_symbols()}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{a_code}")
async def add_watchlist_symbol(
    a_code: str,
    store: WatchlistStoreLike = Depends(get_watchlist_store),
) -> dict:
    try:
        store.add_symbol(a_code)
        return {"items": store.list_symbols()}
    except MissingAHMappingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{a_code}")
async def delete_watchlist_symbol(
    a_code: str,
    store: WatchlistStoreLike = Depends(get_watchlist_store),
) -> dict:
    try:
        store.remove_symbol(a_code)
        return {"items": store.list_symbols()}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
