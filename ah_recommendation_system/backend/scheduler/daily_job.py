# 定时调度任务
# ==========

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

from loguru import logger

# Ensure absolute package imports work when Task Scheduler has no PYTHONPATH.
SCHEDULER_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCHEDULER_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)
from ah_recommendation_system.backend.run_daily_job import generate_report
from ah_recommendation_system.backend.stock_recommend.run import (
    run_pipeline,
    run_open_confirm,
    run_post_market,
    run_previous_close_snapshot,
    run_weekly_reweight_job,
)


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


def _scheduled_exit_code(result: Dict[str, Any], *, push_requested: bool) -> int:
    if not result.get("ok"):
        return 1
    if push_requested and not (result.get("push") or {}).get("ok"):
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-now", action="store_true", help="Generate report immediately"
    )
    parser.add_argument("--mode", choices=("legacy", "pre_market", "post_market", "open_confirm", "previous_close_snapshot", "evening_pre_market", "weekly_reweight"), default="legacy")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--force-push", action="store_true")
    args = parser.parse_args()

    scheduler = DailyJobScheduler()
    if args.mode == "pre_market":
        result = run_pipeline(mock=args.mock, push=args.push, force_push=args.force_push)
        return _scheduled_exit_code(result, push_requested=args.push)
    if args.mode == "open_confirm":
        result = run_open_confirm(mock=args.mock, push=args.push, force_push=args.force_push)
        return _scheduled_exit_code(result, push_requested=args.push)
    if args.mode == "previous_close_snapshot":
        result = run_previous_close_snapshot(mock=args.mock)
        return 0 if result.get("ok") else 1
    if args.mode == "evening_pre_market":
        result = run_pipeline(
            mock=args.mock,
            push=True,
            force_push=False,
            prefer_previous_close=True,
            require_previous_close=True,
        )
        return _scheduled_exit_code(result, push_requested=True)
    if args.mode == "post_market":
        result = run_post_market(mock=args.mock, push=args.push, force_push=args.force_push)
        return _scheduled_exit_code(result, push_requested=args.push)
    if args.mode == "weekly_reweight":
        run_weekly_reweight_job()
        return 0
    if args.run_now:
        scheduler.run_now()
        return 0

    # Placeholder: keep behavior deterministic in this repo
    scheduler.run_now()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
