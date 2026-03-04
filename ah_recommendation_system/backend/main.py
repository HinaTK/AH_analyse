# AH Share Recommendation System - FastAPI entry

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

import loguru
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# Ensure this directory is on sys.path so we can use absolute imports like `from api...`
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"

# Add repo root so `tools.*` imports work when running from this folder.
try:
    # repo root contains the `tools/` directory
    REPO_ROOT = BACKEND_DIR.parents[2]
    sys.path.insert(0, str(REPO_ROOT))
except Exception:
    pass

sys.path.insert(0, str(BACKEND_DIR))

from ah_recommendation_system.backend.api.export_routes import (
    router as export_router,
)  # noqa: E402
from ah_recommendation_system.backend.api.backtest_routes import (
    router as backtest_router,
)  # noqa: E402
from ah_recommendation_system.backend.api.etf_sector_routes import (
    router as etf_sector_router,
)  # noqa: E402
from ah_recommendation_system.backend.api.data_health_routes import (
    router as data_router,
)  # noqa: E402
from ah_recommendation_system.backend.api.report_routes import (
    router as report_router,
)  # noqa: E402
from ah_recommendation_system.backend.api.stock_routes import (
    router as stock_router,
)  # noqa: E402
from ah_recommendation_system.backend.api.strategy_routes import (
    router as strategy_router,
)  # noqa: E402
from ah_recommendation_system.backend.config import LOGGING_CONFIG  # noqa: E402
from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher  # noqa: E402
from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)  # noqa: E402
from ah_recommendation_system.backend.reporting.report_refresh import (
    refresh_latest_report,
)  # noqa: E402


# Logging
loguru.logger.remove()
loguru.logger.add(
    LOGGING_CONFIG["file"],
    level=LOGGING_CONFIG["level"],
    format=LOGGING_CONFIG["format"],
    rotation="1 day",
    retention="7 days",
)
logger = loguru.logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AH recommendation server starting")

    os.makedirs(BACKEND_DIR / "data" / "exports", exist_ok=True)
    os.makedirs(BACKEND_DIR / "data" / "daily_reports", exist_ok=True)
    os.makedirs(BACKEND_DIR / "data" / "models", exist_ok=True)
    os.makedirs(BACKEND_DIR / "logs", exist_ok=True)

    # Data mode: live (fetch upstream) or mock (offline demo)
    data_mode = (os.environ.get("AH_DATA_MODE") or "mock").strip().lower()
    fetcher = get_price_fetcher()
    if data_mode in ("mock", "demo"):
        fetcher.enable_mock_data()
        logger.info("Data mode: mock")
    else:
        fetcher.use_mock_data = False
        logger.info("Data mode: live")

    # Ensure there is at least one stored report for the UI to display.
    store = get_report_store()
    if not store.load_latest():
        logger.info("No stored report found; generating an initial report...")
        try:
            refresh_latest_report(mode=data_mode, force=True)
            logger.info("Initial report generated")
        except Exception as e:
            logger.warning(f"Initial report generation failed: {e}")

    # Hourly refresh (APScheduler)
    scheduler = None
    hourly_enabled = (
        os.environ.get("AH_HOURLY_REFRESH") or "1"
    ).strip().lower() not in (
        "0",
        "false",
        "no",
    )
    if hourly_enabled:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.interval import IntervalTrigger

            scheduler = BackgroundScheduler(daemon=True)
            scheduler.add_job(
                refresh_latest_report,
                trigger=IntervalTrigger(hours=1),
                kwargs={"mode": data_mode, "force": True},
                id="hourly_report_refresh",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            scheduler.start()
            logger.info("Hourly refresh enabled")
        except Exception as e:
            logger.warning(f"Hourly refresh init failed: {e}")

    yield

    if scheduler:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass

    logger.info("AH recommendation server stopped")


app = FastAPI(
    title="AH Share Daily Recommendation",
    description="Pair trading, multi-factor ranking, and ML prediction",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend directory for any optional static assets
if FRONTEND_DIR.exists():
    app.mount("/ui-static", StaticFiles(directory=str(FRONTEND_DIR)), name="ui-static")

# API routes
app.include_router(strategy_router)
app.include_router(export_router)
app.include_router(stock_router)
app.include_router(report_router)
app.include_router(backtest_router)
app.include_router(etf_sector_router)
app.include_router(data_router)


@app.get("/", response_class=HTMLResponse)
async def ui_root() -> HTMLResponse:
    """Interactive UI (single page)."""
    if not FRONTEND_INDEX.exists():
        return HTMLResponse(
            "<h1>UI not found</h1><p>Missing frontend/index.html</p>",
            status_code=404,
        )
    return HTMLResponse(FRONTEND_INDEX.read_text(encoding="utf-8"))


@app.get("/api-info")
async def api_info() -> Dict[str, Any]:
    fetcher = get_price_fetcher()
    return {
        "name": "AH Share Daily Recommendation",
        "version": "1.0.0",
        "mode": "mock" if getattr(fetcher, "use_mock_data", False) else "live",
        "endpoints": {
            "ui": "/",
            "pair_trading": "/api/v1/pair-trading?source=stored",
            "multi_factor": "/api/v1/multi-factor?source=stored",
            "ml_prediction": "/api/v1/ml-prediction?source=stored",
            "backtest_pair_trading": "/api/v1/backtest/pair-trading/latest",
            "report_latest": "/api/v1/report/latest",
            "report_list": "/api/v1/report/list",
            "report_refresh": "/api/v1/report/refresh",
            "stocks": "/api/v1/stocks",
            "export": "/api/v1/export",
            "docs": "/docs",
        },
    }


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    fetcher = get_price_fetcher()
    return {
        "status": "healthy",
        "mode": "mock" if getattr(fetcher, "use_mock_data", False) else "live",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
