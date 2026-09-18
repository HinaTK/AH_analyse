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
    error_kind: Optional[str] = None
    cache_age_seconds: Optional[float] = None
    status: str = "ok"


def classify_error(exc: BaseException) -> str:
    """Map provider failures to stable categories used by health reporting."""
    text = str(exc or "").lower()
    if "cookie" in text or "auth" in text or "token" in text or "login" in text:
        return "auth_or_cookie"
    if "429" in text or "rate limit" in text or "too many" in text:
        return "rate_limit"
    if isinstance(exc, (TimeoutError,)) or "timeout" in text or "timed out" in text:
        return "timeout"
    if isinstance(exc, (ConnectionError, OSError)) or any(
        marker in text for marker in ("connection", "disconnect", "remote end", "network")
    ):
        return "connection"
    if "empty" in text or "no data" in text:
        return "empty_data"
    if "schema" in text or "column" in text:
        return "schema_error"
    return "provider_error"


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
        retry_attempts: int = 2,
        retry_delays: Iterable[float] = (0.05, 0.15),
        cache_ttl_seconds: float = 60.0,
        stale_cache_ttl_seconds: float = 900.0,
    ):
        self.providers = dict(providers)
        self.order = {k: list(v) for k, v in (order or {}).items()}
        self.breakers = {
            name: CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)
            for name in self.providers
        }
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_delays = tuple(max(0.0, float(item)) for item in retry_delays)
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self.stale_cache_ttl_seconds = max(0.0, float(stale_cache_ttl_seconds))
        self._cache: Dict[tuple, tuple[float, List[Dict[str, Any]], str]] = {}
        self._health: Dict[str, Dict[str, Any]] = {
            name: {"state": "closed", "failures": 0, "last_status": "never", "attempts": 0}
            for name in self.providers
        }

    @staticmethod
    def _cache_key(capability: str, args: tuple, kwargs: Mapping[str, Any]) -> tuple:
        # Router inputs are normally strings; repr keeps this safe for unusual
        # provider arguments without requiring them to be hashable.
        return capability, repr(args), repr(sorted(kwargs.items()))

    def _cached(self, key: tuple, *, allow_stale: bool = False) -> Optional[DataResult]:
        item = self._cache.get(key)
        if not item:
            return None
        timestamp, rows, source = item
        age = max(0.0, time.time() - timestamp)
        ttl = self.stale_cache_ttl_seconds if allow_stale else self.cache_ttl_seconds
        if ttl <= 0 or age > ttl:
            return None
        return DataResult(
            rows=[dict(row) for row in rows], source=f"cache:{source}",
            fresh=(not allow_stale) and age <= self.cache_ttl_seconds, attempts=0,
            cache_age_seconds=round(age, 3), status="stale" if allow_stale or age > self.cache_ttl_seconds else "cached",
        )

    def _fetch(self, capability: str, *args: Any, **kwargs: Any) -> DataResult:
        key = self._cache_key(capability, args, kwargs)
        cached = self._cached(key)
        if cached is not None:
            return cached
        errors: List[str] = []
        error_kind: Optional[str] = None
        total_attempts = 0
        names = self.order.get(capability, list(self.providers))
        for level, name in enumerate(names):
            provider = self.providers.get(name)
            breaker = self.breakers.setdefault(name, CircuitBreaker())
            if provider is None or not breaker.allow_request():
                self._health.setdefault(name, {}).update({"state": breaker.state(), "skipped": True})
                continue
            provider_attempts = 0
            for attempt in range(self.retry_attempts):
                provider_attempts += 1
                total_attempts += 1
                try:
                    value = provider(*args, **kwargs)
                    rows = [dict(x) for x in (value or [])]
                    if not rows:
                        raise RuntimeError("empty_result")
                    breaker.record_success()
                    self._health.setdefault(name, {}).update({
                        "state": breaker.state(), "failures": breaker.failures,
                        "last_status": "ok", "attempts": provider_attempts,
                        "last_error_kind": None,
                    })
                    result = DataResult(rows=rows, source=name, fallback_level=level, attempts=total_attempts)
                    if self.stale_cache_ttl_seconds > 0:
                        self._cache[key] = (time.time(), [dict(row) for row in rows], name)
                    return result
                except Exception as exc:
                    error_kind = classify_error(exc)
                    errors.append(f"{name}:{error_kind}:{exc}")
                    retryable = error_kind in {"timeout", "connection", "rate_limit", "provider_error"}
                    if not retryable or attempt >= self.retry_attempts - 1:
                        break
                    if attempt < len(self.retry_delays):
                        time.sleep(self.retry_delays[attempt])
            breaker.record_failure()
            self._health.setdefault(name, {}).update({
                "state": breaker.state(), "failures": breaker.failures,
                "last_status": "failed", "attempts": provider_attempts,
                "last_error_kind": error_kind,
            })
        stale = self._cached(key, allow_stale=True)
        if stale is not None:
            stale.error = "; ".join(errors) or "all_providers_unavailable"
            stale.error_kind = error_kind
            stale.status = "stale"
            stale.attempts = total_attempts
            return stale
        return DataResult(
            rows=[], source="none", fresh=False,
            error="; ".join(errors) or "all_providers_unavailable",
            error_kind=error_kind, attempts=max(1, total_attempts), status="unavailable",
        )

    def fetch_history(self, code: str, start: str, end: str) -> DataResult:
        return self._fetch("history", code, start, end)

    def health(self) -> Dict[str, Any]:
        result = {}
        for name, breaker in self.breakers.items():
            item = dict(self._health.get(name) or {})
            item.update({"state": breaker.state(), "failures": breaker.failures})
            result[name] = item
        return result
