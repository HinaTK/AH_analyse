"""Small, dependency-light routing layer for market data providers."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


@dataclass
class DataResult:
    rows: List[Dict[str, Any]]
    source: str
    fresh: bool = True
    error: Optional[str] = None
    attempts: int = 1
    fallback_level: int = 0


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 2, cooldown_seconds: float = 60.0):
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.failures = 0
        self.opened_at: Optional[float] = None

    def state(self, *, now: Optional[float] = None) -> str:
        current = time.time() if now is None else float(now)
        if self.opened_at is None:
            return "closed"
        if current - self.opened_at >= self.cooldown_seconds:
            return "half_open"
        return "open"

    def allow_request(self, *, now: Optional[float] = None) -> bool:
        return self.state(now=now) != "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self, *, now: Optional[float] = None) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.time() if now is None else float(now)


def parse_sina_quotes(payload: bytes | str) -> List[Dict[str, Any]]:
    text = payload.decode("gbk", errors="replace") if isinstance(payload, bytes) else str(payload)
    rows: List[Dict[str, Any]] = []
    for _market, code, raw in re.findall(r'hq_str_(sh|sz)(\d{6})="([^"]*)"', text):
        parts = raw.split(",")
        if len(parts) < 4:
            continue
        try:
            previous_close = float(parts[2] or 0)
            price = float(parts[3] or 0)
            rows.append({
                "code": code,
                "name": parts[0],
                "price": price,
                "change_pct": ((price / previous_close - 1) * 100) if previous_close > 0 else None,
                "amount": float(parts[9] or 0) if len(parts) > 9 else None,
                "quote_time": " ".join(parts[30:32]) if len(parts) > 31 else None,
            })
        except (TypeError, ValueError):
            continue
    return rows


class DataSourceRouter:
    def __init__(
        self,
        *,
        providers: Mapping[str, Callable[..., Any]],
        order: Optional[Mapping[str, Iterable[str]]] = None,
        failure_threshold: int = 2,
        cooldown_seconds: float = 60.0,
    ):
        self.providers = dict(providers)
        self.order = {k: list(v) for k, v in (order or {}).items()}
        self.breakers = {
            name: CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)
            for name in self.providers
        }

    def _fetch(self, capability: str, *args: Any, **kwargs: Any) -> DataResult:
        errors: List[str] = []
        names = self.order.get(capability, list(self.providers))
        for level, name in enumerate(names):
            provider = self.providers.get(name)
            breaker = self.breakers.setdefault(name, CircuitBreaker())
            if provider is None or not breaker.allow_request():
                continue
            try:
                value = provider(*args, **kwargs)
                rows = [dict(x) for x in (value or [])]
                if rows:
                    breaker.record_success()
                    return DataResult(rows=rows, source=name, fallback_level=level)
                raise RuntimeError("empty_result")
            except Exception as exc:
                breaker.record_failure()
                errors.append(f"{name}:{exc}")
        return DataResult(rows=[], source="none", fresh=False, error="; ".join(errors) or "all_providers_unavailable", attempts=max(1, len(errors)))

    def fetch_history(self, code: str, start: str, end: str) -> DataResult:
        return self._fetch("history", code, start, end)

    def health(self) -> Dict[str, Any]:
        return {
            name: {"state": breaker.state(), "failures": breaker.failures}
            for name, breaker in self.breakers.items()
        }
