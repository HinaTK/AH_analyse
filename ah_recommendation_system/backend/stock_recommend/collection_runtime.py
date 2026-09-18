"""Bounded soft-timeout runtime for third-party collectors.

Python cannot safely stop a thread blocked inside a provider library.  This
runtime therefore bounds both the caller wait and the number of outstanding
daemon workers, and it suppresses duplicate work while a key remains pending.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Dict, Mapping, Tuple

from ah_recommendation_system.backend.stock_recommend.data_source_router import classify_error


@dataclass
class TaskResult:
    value: Any = None
    status: str = "ok"
    latency_ms: int = 0
    error: str | None = None
    error_kind: str | None = None


class _Pending:
    def __init__(self):
        self.done = threading.Event()
        self.result = TaskResult(status="pending")


class CollectionRuntime:
    def __init__(self, *, max_workers: int = 4):
        self.max_workers = max(1, int(max_workers))
        self._lock = threading.RLock()
        self._pending: Dict[str, _Pending] = {}

    def _start(self, key: str, fn: Callable[[], Any]) -> _Pending | None:
        with self._lock:
            existing = self._pending.get(key)
            if existing is not None and not existing.done.is_set():
                return existing
            self._pending = {name: item for name, item in self._pending.items() if not item.done.is_set()}
            if len(self._pending) >= self.max_workers:
                return None
            pending = _Pending()
            self._pending[key] = pending

        def execute() -> None:
            started = time.perf_counter()
            try:
                pending.result = TaskResult(value=fn(), status="ok")
            except Exception as exc:
                pending.result = TaskResult(
                    status="failed", error=f"{type(exc).__name__}:{exc}",
                    error_kind=classify_error(exc),
                )
            finally:
                pending.result.latency_ms = int((time.perf_counter() - started) * 1000)
                pending.done.set()

        threading.Thread(target=execute, name=f"collector-{key}", daemon=True).start()
        return pending

    def run(self, tasks: Mapping[str, Tuple[Callable[[], Any], float]]) -> Dict[str, TaskResult]:
        started: Dict[str, tuple[_Pending | None, float]] = {}
        for key, (fn, timeout_seconds) in tasks.items():
            started[key] = (self._start(key, fn), max(0.0, float(timeout_seconds)))
        results: Dict[str, TaskResult] = {}
        for key, (pending, timeout_seconds) in started.items():
            if pending is None:
                results[key] = TaskResult(status="capacity_exhausted", error_kind="provider_error")
                continue
            if pending.done.wait(timeout_seconds):
                results[key] = pending.result
            else:
                results[key] = TaskResult(
                    status="timeout_pending", latency_ms=int(timeout_seconds * 1000),
                    error="soft_timeout; underlying provider request remains bounded and pending",
                    error_kind="timeout",
                )
        return results

    def reclaim(self, key: str, extra_wait_seconds: float = 0.0) -> TaskResult:
        """Return a late success from a still-pending worker without starting another call."""
        with self._lock:
            pending = self._pending.get(key)
        if pending is None:
            return TaskResult(status="missing", error="no pending collector", error_kind="provider_error")
        if pending.done.wait(max(0.0, float(extra_wait_seconds))):
            return pending.result
        return TaskResult(
            status="timeout_pending",
            latency_ms=int(max(0.0, float(extra_wait_seconds)) * 1000),
            error="soft_timeout; underlying provider request remains bounded and pending",
            error_kind="timeout",
        )


DEFAULT_COLLECTION_RUNTIME = CollectionRuntime(max_workers=4)
