from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)
from ah_recommendation_system.backend.run_daily_job import generate_report


_REFRESH_LOCK = threading.Lock()

_REFRESH_STATE: Dict[str, Any] = {
    "in_progress": False,
    "mode": None,
    "force": None,
    "started_at": None,
    "finished_at": None,
    "last_success_at": None,
    "last_error": None,
}

# Maximum time a refresh can be "in_progress" before we consider it stuck
_REFRESH_TIMEOUT_SECONDS = 300  # 5 minutes


def _parse_datetime_str(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse datetime string in format 'YYYY-MM-DD HH:MM:SS'."""
    if not dt_str:
        return None
    try:
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _reset_stale_state() -> bool:
    """Reset state if refresh has been stuck for too long.

    Returns True if state was reset, False otherwise.
    """
    if not _REFRESH_STATE["in_progress"]:
        return False
    started = _parse_datetime_str(_REFRESH_STATE["started_at"])
    if not started:
        return False
    elapsed = (datetime.now() - started).total_seconds()
    if elapsed > _REFRESH_TIMEOUT_SECONDS:
        logger.warning(f"Refresh has been stuck for {elapsed:.0f}s, resetting state")
        _REFRESH_STATE["in_progress"] = False
        _REFRESH_STATE["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _REFRESH_STATE["last_error"] = "timeout_reset"
        try:
            _REFRESH_LOCK.release()
        except RuntimeError:
            pass
        return True
    return False


def get_refresh_status() -> Dict[str, Any]:
    """Get current refresh status, resetting if stale."""
    # Check for stale state first
    _reset_stale_state()
    # Copy to avoid exposing mutable global.
    return dict(_REFRESH_STATE)


def refresh_latest_report(*, mode: str = "live", force: bool = True) -> Dict[str, Any]:
    """Generate and persist a fresh report.

    mode:
    - live: fetch data from upstream sources
    - mock: use mock data (no external network)

    force:
    - True: clears in-memory caches first
    """
    # Check for stale state before acquiring lock
    _reset_stale_state()

    if not _REFRESH_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "message": "refresh_in_progress",
        }

    try:
        _REFRESH_STATE["in_progress"] = True
        _REFRESH_STATE["mode"] = mode
        _REFRESH_STATE["force"] = force
        _REFRESH_STATE["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _REFRESH_STATE["finished_at"] = None
        _REFRESH_STATE["last_error"] = None

        fetcher = get_price_fetcher()
        mode_norm = (mode or "").strip().lower()
        if mode_norm in ("mock", "demo"):
            fetcher.enable_mock_data()
        else:
            # Disable mock mode if it was enabled at startup.
            fetcher.use_mock_data = False

        if force:
            fetcher.clear_cache()

        report = generate_report()

        # Protect against empty reports (e.g., network failures)
        # If all recommendations are empty, don't overwrite existing data
        def _is_empty_report(r: dict) -> bool:
            pt = r.get("pair_trading", {}).get("recommendations", [])
            mf = r.get("multi_factor", {}).get("recommendations", [])
            ml = r.get("ml_prediction", {}).get("recommendations", [])
            # Also check signals in pair_trading
            pt_signals = r.get("pair_trading", {}).get("signals", {})
            pt_buy = pt_signals.get("buy_ah", [])
            pt_sell = pt_signals.get("sell_ah", [])
            pt_hold = pt_signals.get("hold", [])
            return (
                len(pt) == 0
                and len(pt_buy) == 0
                and len(pt_sell) == 0
                and len(pt_hold) == 0
                and len(mf) == 0
                and len(ml) == 0
            )

        if _is_empty_report(report):
            logger.warning(
                "Generated report is empty (likely network failure), keeping existing data"
            )
            _REFRESH_STATE["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _REFRESH_STATE["last_error"] = "empty_report_network_failure"
            return {
                "success": False,
                "message": "empty_report",
                "error": "Generated report is empty (likely network failure). Existing data preserved.",
            }

        store = get_report_store()
        path = store.save(report)
        logger.info(f"Latest report refreshed (mode={mode_norm or 'live'}): {path}")

        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _REFRESH_STATE["finished_at"] = finished_at
        _REFRESH_STATE["last_success_at"] = finished_at

        generated_at: Optional[str] = None
        if isinstance(report, dict):
            generated_at = report.get("generated_at")

        return {
            "success": True,
            "message": "ok",
            "generated_at": generated_at,
            "path": str(path),
        }
    except Exception as e:
        logger.exception(f"Report refresh failed: {e}")
        _REFRESH_STATE["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _REFRESH_STATE["last_error"] = str(e)
        return {
            "success": False,
            "message": "refresh_failed",
            "error": str(e),
        }
    finally:
        _REFRESH_STATE["in_progress"] = False
        try:
            _REFRESH_LOCK.release()
        except RuntimeError:
            pass
