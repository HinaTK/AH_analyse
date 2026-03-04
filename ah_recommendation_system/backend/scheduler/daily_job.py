# 定时调度任务
# ==========

from __future__ import annotations

import argparse

from typing import Any, Dict

import sys
from pathlib import Path

from loguru import logger

# Ensure repo root is on sys.path so `tools.*` imports work when running from this folder.
try:
    SCHEDULER_DIR = Path(__file__).resolve().parent
    REPO_ROOT = SCHEDULER_DIR.parents[3]
    sys.path.insert(0, str(REPO_ROOT))
except Exception:
    pass

from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)
from ah_recommendation_system.backend.run_daily_job import generate_report


class DailyJobScheduler:
    """每日推荐调度器"""

    def generate_daily_report(self) -> Dict[str, Any]:
        logger.info("Generating daily recommendations report...")
        report = generate_report()

        store = get_report_store()
        path = store.save(report)
        logger.info(f"Daily report saved: {path}")
        return report

    def run_now(self) -> Dict[str, Any]:
        return self.generate_daily_report()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-now", action="store_true", help="Generate report immediately"
    )
    args = parser.parse_args()

    scheduler = DailyJobScheduler()
    if args.run_now:
        scheduler.run_now()
        return 0

    # Placeholder: keep behavior deterministic in this repo
    scheduler.run_now()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
