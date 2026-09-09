"""Best-effort cross-market context collection for the daily decision layer."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional


def _value(row: Dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _rows(frame: Any, *, limit: int = 20) -> list[Dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    output = []
    for raw in frame.head(limit).to_dict("records"):
        row = dict(raw)
        name = _value(row, ("名称", "指数名称", "name", "symbol"))
        latest = _number(_value(row, ("最新价", "最新", "close", "price")))
        change = _number(_value(row, ("涨跌幅", "涨跌幅%", "change_pct", "pct_change")))
        if name:
            output.append({"name": str(name), "price": latest, "change_pct": change})
    return output


def collect_cross_market(*, ak_module: Any = None) -> Dict[str, Any]:
    """Collect compact US/HK/FX/rate context without blocking core scanning."""
    if ak_module is None:
        import akshare as ak_module  # type: ignore

    errors: Dict[str, str] = {}

    def call(name: str) -> Any:
        try:
            return getattr(ak_module, name)()
        except Exception as exc:
            errors[name] = type(exc).__name__
            return None

    global_rows = _rows(call("index_global_spot_em"), limit=100)
    us = [
        row
        for row in global_rows
        if any(token in row["name"].lower() for token in ("纳斯达克", "标普", "道琼斯", "nasdaq", "s&p", "dow"))
    ][:5]
    hong_kong = _rows(call("stock_hk_index_spot_em"), limit=10)
    fx = _rows(call("forex_spot_em"), limit=100)
    fx = [row for row in fx if "人民币" in row["name"] or "cny" in row["name"].lower()][:5]

    rates = []
    rate_frame = call("bond_zh_us_rate")
    if rate_frame is not None and not getattr(rate_frame, "empty", True):
        raw = dict(rate_frame.tail(1).to_dict("records")[0])
        rate = _number(_value(raw, ("美国国债收益率10年", "美国10年期国债收益率", "10年期美债收益率")))
        rates.append({"name": "美国10年期国债收益率", "value": rate, "date": str(raw.get("日期") or "")})

    us_changes = [row["change_pct"] for row in us if row.get("change_pct") is not None]
    risk_level = "high" if us_changes and sum(us_changes) / len(us_changes) <= -2.0 else "normal"
    usable_groups = sum(bool(group) for group in (us, hong_kong, fx, rates))
    return {
        "status": "ok" if usable_groups >= 2 else "degraded" if usable_groups else "failed",
        "observed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "risk_level": risk_level,
        "markets": {
            "united_states": us,
            "hong_kong": hong_kong,
            "fx": fx,
            "rates": rates,
        },
        "errors": errors,
        "source": "akshare_cross_market",
    }
