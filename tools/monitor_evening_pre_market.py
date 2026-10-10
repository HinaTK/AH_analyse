"""Wait for the 17:00-18:00 previous-close snapshot, then force-push a previous-close pre-market card."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "ah_recommendation_system" / "backend"
PYTHON = sys.executable
MIN_ROWS = 1000
MAX_ATTEMPTS = 6
LOG = BACKEND / "logs" / "evening_pre_market_monitor.jsonl"
LOCK = BACKEND / "logs" / "evening_pre_market_monitor.lock"


def _now() -> datetime:
    return datetime.now()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_lock() -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            existing = int(LOCK.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            existing = 0
        if _pid_alive(existing):
            return False
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _log(event: str, **payload) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _now().strftime("%Y-%m-%d %H:%M:%S"), "event": event, **payload}
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + chr(10))
    print(json.dumps(row, ensure_ascii=False), flush=True)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(BACKEND),
        env=_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def wait_until(target: datetime) -> None:
    while _now() < target:
        remaining = (target - _now()).total_seconds()
        _log("waiting", remaining_seconds=int(remaining), until=target.strftime("%H:%M:%S"))
        time.sleep(min(30, max(1, remaining)))


def parquet_status(as_of: str) -> dict:
    path = BACKEND / "data" / "market_store" / f"a_share_spot_{as_of.replace('-', '')}.parquet"
    if not path.exists():
        return {"exists": False, "path": str(path), "rows": 0, "mtime": None, "ok": False}
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    rows = 0
    try:
        import polars as pl
        rows = int(pl.read_parquet(path).height)
    except Exception as exc:
        return {"exists": True, "path": str(path), "rows": 0, "mtime": mtime.isoformat(), "ok": False, "error": str(exc)}
    cutoff = datetime(mtime.year, mtime.month, mtime.day, 17, 0, 0)
    ok = rows >= MIN_ROWS and mtime >= cutoff
    return {"exists": True, "path": str(path), "rows": rows, "mtime": mtime.isoformat(), "ok": ok}


def collect_snapshot() -> dict:
    proc = _run([PYTHON, "-m", "scheduler.daily_job", "--mode", "previous_close_snapshot"], timeout=420)
    payload = {"returncode": proc.returncode, "stdout_tail": (proc.stdout or "")[-2000:], "stderr_tail": (proc.stderr or "")[-2000:]}
    _log("snapshot_run", **payload)
    return payload


def push_pre_market() -> dict:
    proc = _run([PYTHON, "-m", "scheduler.daily_job", "--mode", "evening_pre_market"], timeout=900)
    payload = {"returncode": proc.returncode, "stdout_tail": (proc.stdout or "")[-4000:], "stderr_tail": (proc.stderr or "")[-4000:]}
    _log("pre_market_run", **payload)
    return payload


def delivery_ok(as_of: str) -> dict:
    ledger_path = BACKEND / "data" / "stock_recommend" / "delivery_ledger.json"
    latest = BACKEND / "data" / "stock_recommend" / "latest.json"
    ledger = {}
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entry = ledger.get(f"{as_of}:pre_market") or {}
    report = {}
    if latest.exists():
        report = json.loads(latest.read_text(encoding="utf-8"))
    coverage = dict(report.get("coverage") or {})
    run = dict(report.get("run") or {})
    delivery = dict(report.get("delivery") or {})
    ok = (
        bool(entry.get("accepted"))
        and str(coverage.get("source") or "") == "previous_close"
        and int(coverage.get("scanned_count") or 0) >= MIN_ROWS
        and bool((report.get("quality_gate") or {}).get("passed"))
        and str(run.get("status") or "") != "failed"
        and bool(delivery.get("accepted"))
    )
    return {
        "ok": ok,
        "ledger": entry,
        "source": coverage.get("source"),
        "quote_basis": coverage.get("quote_basis"),
        "scanned_count": coverage.get("scanned_count"),
        "quality_passed": (report.get("quality_gate") or {}).get("passed"),
        "run_status": run.get("status"),
        "delivery": delivery,
        "generated_at": report.get("generated_at"),
    }


def main() -> int:
    if not acquire_lock():
        _log("already_running")
        return 0
    as_of = _now().strftime("%Y-%m-%d")
    start_at = datetime(_now().year, _now().month, _now().day, 19, 0, 0)
    if _now() > start_at + timedelta(hours=3):
        _log("too_late", as_of=as_of)
        return 1
    wait_until(start_at)
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _log("attempt", attempt=attempt, as_of=as_of)
        status = parquet_status(as_of)
        _log("snapshot_status", **status)
        if not status.get("ok"):
            collect_snapshot()
            status = parquet_status(as_of)
            _log("snapshot_status_after_collect", **status)
            if not status.get("ok"):
                last_error = "previous_close_snapshot_failed"
                time.sleep(20)
                continue
        push_pre_market()
        result = delivery_ok(as_of)
        _log("delivery_status", **result)
        if result.get("ok"):
            _log("success", attempt=attempt)
            return 0
        last_error = str((result.get("delivery") or {}).get("reason") or result.get("run_status") or "pre_market_failed")
        time.sleep(20)
    _log("exhausted", last_error=last_error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
