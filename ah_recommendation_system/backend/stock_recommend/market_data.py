"""Unified full-market snapshot management with failover and field supplement."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import time
from threading import RLock
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pandas as pd
from loguru import logger

try:
    import akshare as ak  # type: ignore
except Exception:  # pragma: no cover
    ak = None  # type: ignore

try:
    import efinance as ef  # type: ignore
except Exception:  # pragma: no cover
    ef = None  # type: ignore

from ah_recommendation_system.backend.stock_recommend.data_source_router import CircuitBreaker


SUPPLEMENT_FIELDS = (
    "pe", "pb", "market_cap", "float_cap", "turnover_pct", "amount", "volume",
)
NUMERIC_FIELDS = SUPPLEMENT_FIELDS + ("price", "change_pct", "open", "high", "low", "volume_ratio")


def coerce_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number and number not in {float("inf"), float("-inf")} else None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "None", "nan", "NaN"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _pe_kind_from_column(name: str) -> str:
    if "动态" in name or name.lower() in {"pe_ttm", "pe_dynamic"}:
        return "dynamic"
    if "静态" in name or "lyr" in name.lower():
        return "static"
    if "ttm" in name.lower():
        return "ttm"
    return "unspecified"


@dataclass
class UnifiedRealtimeQuote:
    code: str
    name: Optional[str] = None
    price: Optional[float] = None
    change_pct: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    pre_close: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    volume_ratio: Optional[float] = None
    turnover_pct: Optional[float] = None
    amplitude: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    market_cap: Optional[float] = None
    float_cap: Optional[float] = None
    source: str = "unknown"

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "UnifiedRealtimeQuote":
        known = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in row.items() if key in known})

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}

    def missing_fields(self, fields: Iterable[str] = SUPPLEMENT_FIELDS) -> List[str]:
        return [name for name in fields if getattr(self, name, None) is None]


def _missing_quote_value(name: str, value: Any) -> bool:
    if value is None:
        return True
    if name in {"amount", "volume"}:
        number = coerce_number(value)
        return number is None or number <= 0
    return False



def _field_present(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    if key == 'pe':
        return value is not None and value != ''
    if key in {'amount', 'volume'}:
        number = coerce_number(value)
        return number is not None and number > 0
    return value is not None and value != '' and value != 0


def snapshot_field_coverage(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    if total <= 0:
        return {'row_count': 0, 'price_ratio': 0.0, 'change_ratio': 0.0, 'pe_ratio': 0.0, 'activity_ratio': 0.0}
    price_ratio = sum(_field_present(row, 'price') for row in rows) / total
    change_ratio = sum(_field_present(row, 'change_pct') for row in rows) / total
    pe_ratio = sum(_field_present(row, 'pe') for row in rows) / total
    activity_ratio = sum(_field_present(row, 'change_pct') or _field_present(row, 'amount') for row in rows) / total
    return {
        'row_count': total,
        'price_ratio': round(price_ratio, 4),
        'change_ratio': round(change_ratio, 4),
        'pe_ratio': round(pe_ratio, 4),
        'activity_ratio': round(activity_ratio, 4),
    }


def snapshot_meets_field_contract(rows: Sequence[Mapping[str, Any]]) -> bool:
    if not rows:
        return False
    if len(rows) == 1:
        return _field_present(rows[0], 'price')
    coverage = snapshot_field_coverage(rows)
    if coverage['price_ratio'] < 0.6 or coverage['activity_ratio'] < 0.4:
        return False
    if len(rows) >= 5 and coverage['pe_ratio'] < 0.6:
        return False
    return True


def merge_quote_fields(primary: Mapping[str, Any], secondary: Mapping[str, Any], fields: Sequence[str] = SUPPLEMENT_FIELDS) -> List[str]:
    """Fill only missing fields; primary price/change identity stays untouched."""
    filled: List[str] = []
    for name in fields:
        if _missing_quote_value(name, primary.get(name)) and not _missing_quote_value(name, secondary.get(name)):
            primary[name] = secondary[name]
            filled.append(name)
    return filled


def normalize_numeric_fields(rows: List[Dict[str, Any]], fields: Sequence[str] = NUMERIC_FIELDS) -> List[Dict[str, Any]]:
    """Coerce provider placeholders such as '-' to None without changing prices."""
    for row in rows:
        for name in fields:
            value = row.get(name)
            if name not in row:
                continue
            coerced = coerce_number(value)
            if value is None or coerced is not None or (isinstance(value, str) and not str(value).strip()) or str(value).strip() in {"-", "--", "None", "nan", "NaN"}:
                row[name] = coerced
    return rows


@dataclass
class SnapshotResult:
    rows: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "none"
    attempted: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    supplemented_fields: Dict[str, List[str]] = field(default_factory=dict)
    fallback_level: int = 0
    error: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    extra_health: Dict[str, Any] = field(default_factory=dict)

    def health(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "attempted": list(self.attempted),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
            "supplemented_fields": dict(self.supplemented_fields),
            "fallback_level": self.fallback_level,
            **self.extra_health,
        }


class RateLimiter:
    """Serialize and space out AKShare/Efinance snapshot calls."""

    def __init__(self, min_interval_seconds: float = 0.2):
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._lock = RLock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.perf_counter()
            remaining = self.min_interval_seconds - (now - self._last_call)
            if remaining > 0:
                time.sleep(remaining)
            self._last_call = time.perf_counter()


DEFAULT_SNAPSHOT_LIMITER = RateLimiter(min_interval_seconds=0.2)
TRANSIENT_SNAPSHOT_ERRORS = (ConnectionError, TimeoutError, OSError)


def retry_transient(call, *, attempts: int = 2):
    last_exc: Optional[Exception] = None
    for index in range(max(1, attempts)):
        try:
            return call()
        except TRANSIENT_SNAPSHOT_ERRORS as exc:
            last_exc = exc
            if index >= attempts - 1:
                raise
            time.sleep(0.05 * (index + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_transient exhausted")


class AkshareSnapshotProvider:
    name = "akshare"

    def __init__(self, akshare_module: Any = None, rate_limiter: Optional[RateLimiter] = None):
        self.akshare_module = akshare_module
        self.rate_limiter = rate_limiter or DEFAULT_SNAPSHOT_LIMITER

    def usable_snapshot(self, limit: int) -> List[Dict[str, Any]]:
        rows = self.snapshot(limit=limit)
        return rows if rows and self.usable(rows) else []

    def snapshot(self, limit: int) -> List[Dict[str, Any]]:
        akshare = self.akshare_module or ak
        if akshare is None:
            return []

        def call():
            with pd.option_context("future.infer_string", False):
                return akshare.stock_zh_a_spot_em()

        if self.rate_limiter is not None:
            self.rate_limiter.wait()
        frame = retry_transient(call)
        if frame is None or frame.empty:
            return []
        frame = frame.rename(columns={
            "代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "change_pct",
            "成交量": "volume", "成交额": "amount", "换手率": "turnover_pct",
            "市盈率-动态": "pe", "市净率": "pb", "总市值": "market_cap", "流通市值": "float_cap",
            "60日涨跌幅": "change_60d_pct", "年初至今涨跌幅": "change_ytd_pct",
        })
        if "code" in frame.columns:
            frame["code"] = frame["code"].astype(str).str.zfill(6)
        if limit and len(frame) > limit:
            frame = frame.head(limit)
        rows = normalize_numeric_fields(frame.replace({pd.NA: None}).to_dict(orient="records"))
        for row in rows:
            row.setdefault("source", self.name)
            if row.get("pe") is not None:
                row.setdefault("pe_kind", "dynamic")
                row.setdefault("pe_source", self.name)
        return rows

    @staticmethod
    def usable(rows: Sequence[Mapping[str, Any]]) -> bool:
        if not rows:
            return False
        def present(row: Mapping[str, Any], key: str) -> bool:
            value = row.get(key)
            return value is not None and value != "" and value != 0
        if len(rows) == 1:
            return present(rows[0], "price")
        price_ratio = sum(present(row, "price") for row in rows) / len(rows)
        activity_ratio = sum(present(row, "change_pct") or present(row, "amount") for row in rows) / len(rows)
        return price_ratio >= 0.6 and activity_ratio >= 0.4


class HithinkSnapshotProvider:
    name = "hithink_financial_api"

    def __init__(self):
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient
        self.client = HithinkClient()

    @property
    def enabled(self) -> bool:
        return bool(self.client.enabled)

    def usable_snapshot(self, limit: int) -> List[Dict[str, Any]]:
        rows = self.snapshot(limit=limit)
        if not rows:
            return []
        observed = rows[0].get("observed_at")
        try:
            value = float(observed)
            if value > 10_000_000_000:
                value /= 1000.0
            fresh = datetime.now() - datetime.fromtimestamp(value) <= timedelta(days=4)
        except (TypeError, ValueError, OSError):
            fresh = False
        return rows if fresh and AkshareSnapshotProvider.usable(rows) else []

    def snapshot(self, limit: int) -> List[Dict[str, Any]]:
        # The price snapshot has activity but no valuation fields. Merge the
        # separately available valuation/market-cap snapshot before the field
        # contract can reject an otherwise complete full-market panel.
        rows = [dict(row) for row in self.client.market_snapshot(limit=limit)]
        try:
            return self.client.enrich_snapshot(rows)
        except Exception:
            return rows


class EfinanceSnapshotProvider:
    name = "efinance"

    def __init__(self, efinance_module: Any = None, rate_limiter: Optional[RateLimiter] = None):
        self.efinance_module = efinance_module
        self.rate_limiter = rate_limiter or DEFAULT_SNAPSHOT_LIMITER

    def snapshot(self, limit: int) -> List[Dict[str, Any]]:
        efinance = self.efinance_module or ef
        if efinance is None:
            return []
        if self.rate_limiter is not None:
            self.rate_limiter.wait()

        def call():
            return efinance.stock.get_realtime_quotes()

        frame = retry_transient(call)
        if frame is None or frame.empty:
            return []
        candidates = (
            ("股票代码", "code"), ("代码", "code"), ("股票名称", "name"), ("名称", "name"),
            ("最新价", "price"), ("涨跌幅", "change_pct"), ("成交量", "volume"),
            ("成交额", "amount"), ("换手率", "turnover_pct"), ("量比", "volume_ratio"),
            ("动态市盈率", "pe"), ("市盈率-动态", "pe"), ("市盈率", "pe"),
            ("市净率", "pb"), ("总市值", "market_cap"), ("流通市值", "float_cap"),
            ("最高", "high"), ("最低", "low"), ("今开", "open"),
        )
        rename = {}
        pe_kind = None
        for source, target in candidates:
            if source not in frame.columns or target in rename.values():
                continue
            rename[source] = target
            if target == "pe" and pe_kind is None:
                pe_kind = _pe_kind_from_column(source)
        frame = frame.rename(columns=rename)
        if "code" in frame.columns:
            frame["code"] = frame["code"].astype(str).str.zfill(6)
        if limit and len(frame) > limit:
            frame = frame.head(limit)
        rows = normalize_numeric_fields(frame.replace({pd.NA: None}).to_dict(orient="records"))
        for row in rows:
            row["source"] = self.name
            if row.get("pe") is not None:
                row["pe_kind"] = pe_kind or "unspecified"
                row["pe_source"] = self.name
        return rows


class MarketDataManager:
    _shared_cache_lock = RLock()
    _shared_cache_rows: Optional[List[Dict[str, Any]]] = None
    _shared_cache_timestamp: Optional[float] = None
    _shared_cache_source = "none"

    def __init__(
        self,
        *,
        order: Optional[Sequence[str]] = None,
        failure_threshold: int = 2,
        cooldown_seconds: float = 60.0,
        akshare_module: Any = None,
        efinance_module: Any = None,
        cache_ttl_seconds: float = 60.0,
        stale_cache_ttl_seconds: float = 0.0,
    ):
        self.order = list(order or ["hithink_financial_api", "akshare", "efinance"])
        self.breakers = {
            "hithink_financial_api": CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds),
            "akshare": CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds),
            "efinance": CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds),
        }
        self._hithink: Optional[HithinkSnapshotProvider] = None
        self._akshare = AkshareSnapshotProvider(akshare_module=akshare_module)
        self._efinance = EfinanceSnapshotProvider(efinance_module=efinance_module)
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self.stale_cache_ttl_seconds = max(0.0, float(stale_cache_ttl_seconds))
        self._cache_rows: Optional[List[Dict[str, Any]]] = None
        self._cache_timestamp: Optional[float] = None
        self._cache_source = "none"
        self._shared_cache = cache_ttl_seconds > 0
        self._rows: List[Dict[str, Any]] = []

    def _snapshot(self, name: str, limit: int) -> List[Dict[str, Any]]:
        if name == "hithink_financial_api":
            if self._hithink is None:
                self._hithink = HithinkSnapshotProvider()
            return self._hithink.snapshot(limit)
        if name == "akshare":
            if self._akshare is None:
                self._akshare = AkshareSnapshotProvider()
            return self._akshare.snapshot(limit)
        if name == "efinance":
            return self._efinance.snapshot(limit)
        raise ValueError(f"unknown provider: {name}")

    def prefetch_snapshot(self, *, limit: int = 6000) -> SnapshotResult:
        return self.fetch_snapshot(limit=limit)

    def _usable(self, name: str, rows: List[Dict[str, Any]]) -> bool:
        return AkshareSnapshotProvider.usable(rows)

    def fetch_snapshot(self, *, limit: int = 6000) -> SnapshotResult:
        result = SnapshotResult()
        now = time.time()
        with self._shared_cache_lock:
            cache_rows = self._shared_cache_rows if self._shared_cache else self._cache_rows
            cache_timestamp = self._shared_cache_timestamp if self._shared_cache else self._cache_timestamp
            cache_source = self._shared_cache_source if self._shared_cache else self._cache_source
            if (
                cache_rows is not None
                and cache_timestamp is not None
                and 0 <= now - cache_timestamp < self.cache_ttl_seconds
            ):
                cached = SnapshotResult(
                    rows=[dict(row) for row in cache_rows],
                    source=f"cache:{cache_source}",
                    attempted=[f"cache:{cache_source}"],
                    stats=self.derive_stats(cache_rows),
                    extra_health={
                        "cache_hit": True,
                        "cache_age_seconds": round(now - cache_timestamp, 3),
                    },
                )
                return cached
        result = self._fetch_uncached_snapshot(limit=limit)
        if not result.rows:
            with self._shared_cache_lock:
                cache_rows = self._shared_cache_rows if self._shared_cache else self._cache_rows
                cache_timestamp = self._shared_cache_timestamp if self._shared_cache else self._cache_timestamp
                cache_source = self._shared_cache_source if self._shared_cache else self._cache_source
            cache_age = time.time() - cache_timestamp if cache_timestamp is not None else None
            if cache_rows and cache_age is not None and 0 <= cache_age < self.stale_cache_ttl_seconds:
                return SnapshotResult(
                    rows=[dict(row) for row in cache_rows],
                    source=f"cache:{cache_source}",
                    attempted=list(result.attempted),
                    skipped=list(result.skipped),
                    errors=list(result.errors),
                    stats=self.derive_stats(cache_rows),
                    extra_health={
                        "cache_hit": True,
                        "cache_stale": True,
                        "cache_age_seconds": round(cache_age, 3),
                        "freshness_status": "stale",
                    },
                )
        if result.rows and self._shared_cache:
            with self._shared_cache_lock:
                self._shared_cache_rows = [dict(row) for row in result.rows]
                self._shared_cache_timestamp = time.time()
                self._shared_cache_source = result.source
        return result

    def _fetch_uncached_snapshot(self, *, limit: int) -> SnapshotResult:
        result = SnapshotResult()
        primary: Optional[List[Dict[str, Any]]] = None
        primary_name = "none"
        for level, name in enumerate(self.order):
            breaker = self.breakers.setdefault(name, CircuitBreaker())
            if not breaker.allow_request():
                result.skipped.append(name)
                continue
            result.attempted.append(name)
            try:
                rows = self._snapshot(name, limit)
                if rows and self._usable(name, rows):
                    primary, primary_name = rows, name
                    breaker.record_success()
                    result.source, result.fallback_level = name, level
                    break
                breaker.record_failure()
                result.errors.append(f"{name}:empty_or_unusable")
            except Exception as exc:
                breaker.record_failure()
                result.errors.append(f"{name}:{type(exc).__name__}:{exc}")

        if primary is None:
            result.error = "; ".join(result.errors) or "all_providers_unavailable"
            return result

        result.rows = [dict(row, source=row.get("source") or primary_name) for row in primary]
        failed_or_skipped = set()
        for item in result.errors:
            failed_or_skipped.add(str(item).split(":", 1)[0])
        failed_or_skipped.update(result.skipped)
        supplement_names = [
            name for name in self.order
            if name != primary_name and name not in failed_or_skipped
        ]
        missing_fields: set[str] = {
            field_name
            for row in result.rows
            for field_name in SUPPLEMENT_FIELDS
            if _missing_quote_value(field_name, row.get(field_name))
        }
        if not missing_fields:
            supplement_names = []
        for name in supplement_names:
            breaker = self.breakers.setdefault(name, CircuitBreaker())
            if not breaker.allow_request():
                result.skipped.append(f"{name}:supplement")
                continue
            result.attempted.append(f"{name}:supplement")
            try:
                secondary_rows = self._snapshot(name, limit)
                by_code = {str(row.get("code") or "").zfill(6): row for row in secondary_rows}
                filled_by_field: Dict[str, List[str]] = {}
                for row in result.rows:
                    code = str(row.get("code") or "").zfill(6)
                    secondary = by_code.get(code)
                    if not secondary:
                        continue
                    filled = merge_quote_fields(row, secondary)
                    for key in filled:
                        filled_by_field.setdefault(key, []).append(code)
                result.supplemented_fields = {key: codes for key, codes in filled_by_field.items()}
                breaker.record_success()
                missing_fields -= set(result.supplemented_fields)
                if missing_fields:
                    continue
                break
            except Exception as exc:
                breaker.record_failure()
                result.errors.append(f"{name}:supplement:{type(exc).__name__}")
        coverage = snapshot_field_coverage(result.rows)
        result.extra_health['field_coverage'] = coverage
        if not snapshot_meets_field_contract(result.rows):
            missing = []
            if coverage.get('pe_ratio', 1) < 0.6:
                missing.append('pe')
            if coverage.get('price_ratio', 1) < 0.6:
                missing.append('price')
            label = ','.join(missing) or 'required_fields'
            result.errors.append(f'{primary_name}:missing_required_fields:{label}')
            result.error = '; '.join(result.errors) or 'missing_required_fields'
            result.rows = []
            result.source = 'none'
            result.stats = {}
            return result
        result.stats = self.derive_stats(result.rows)
        self._cache_rows = [dict(row) for row in result.rows]
        self._cache_timestamp = time.time()
        self._cache_source = primary_name
        return result

    @staticmethod
    def derive_stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        changes: List[float] = []
        amounts: List[float] = []
        for row in rows:
            try:
                change = row.get("change_pct")
                if change is not None:
                    changes.append(float(change))
            except (TypeError, ValueError):
                pass
            try:
                amount = row.get("amount")
                if amount is not None:
                    amounts.append(float(amount))
            except (TypeError, ValueError):
                pass
        return {
            "up_count": sum(value > 0 for value in changes),
            "down_count": sum(value < 0 for value in changes),
            "flat_count": sum(value == 0 for value in changes),
            "limit_up_count": sum(value >= 9.9 for value in changes),
            "limit_down_count": sum(value <= -9.9 for value in changes),
            "total_amount": sum(amounts),
        }

    def market_stats(self) -> Dict[str, Any]:
        return self.derive_stats(self._rows)
