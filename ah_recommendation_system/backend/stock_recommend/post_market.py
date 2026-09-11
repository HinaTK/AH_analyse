"""Build a deterministic post-market review for the pre-market picks."""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional


HORIZONS = (1, 5, 20)


def positive_price(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def closing_observation(pick: Mapping[str, Any], frame: Any, as_of: str) -> Dict[str, Any]:
    """Use dated daily bars for daily performance, never as future outcomes."""
    import pandas as pd

    reference = positive_price(pick.get("reference_price", pick.get("price")))
    row = {
        "reference_price": reference, "reference_date": pick.get("reference_date"),
        "close_price": None, "close_date": None, "previous_close": None,
        "previous_close_date": None, "daily_return_pct": None,
        "reference_return_pct": None, "data_status": "insufficient",
        "data_reason": "缺少当日有效收盘价或行情日期",
    }
    if frame is None or frame.empty or not {"date", "close"}.issubset(frame.columns):
        return row
    bars = frame.copy()
    bars["date"] = pd.to_datetime(bars["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    bars = bars.loc[bars["date"] <= as_of].sort_values("date").drop_duplicates("date", keep="last")
    today = bars.loc[bars["date"] == as_of]
    if today.empty:
        return row
    close = positive_price(today.iloc[-1]["close"])
    if close is None:
        return row
    row.update(close_price=close, close_date=as_of, data_status="available", data_reason="")
    previous = bars.loc[bars["date"] < as_of]
    if not previous.empty:
        previous_close = positive_price(previous.iloc[-1]["close"])
        if previous_close is not None:
            row.update(previous_close=previous_close, previous_close_date=previous.iloc[-1]["date"],
                       daily_return_pct=round((close / previous_close - 1) * 100, 3))
    if reference is not None:
        row["reference_return_pct"] = round((close / reference - 1) * 100, 3)
    if row["daily_return_pct"] is None:
        row.update(data_status="insufficient", data_reason="缺少有效昨收，无法计算当日涨跌")
    return row


def format_review_item(item: Mapping[str, Any]) -> str:
    def percent(value: Any) -> str:
        return "数据不足" if value is None else f"{value:+.2f}%"

    status = {"pending": "待验证", "hit": "上涨", "miss": "下跌", "neutral": "平盘"}.get(item.get("status"), "待验证")
    correction = {"keep": "保留观察", "downgrade": "降级观察", "confirm": "等待确认"}.get(item.get("correction"), "等待确认")
    text = (
        f"**{item.get('name', '')} ({item.get('code', '')})** · 当日涨跌 {percent(item.get('daily_return_pct'))}\n"
        f"昨收 {item.get('previous_close') or '缺失'}（{item.get('previous_close_date') or '日期缺失'}）→ "
        f"今收 {item.get('close_price') or '缺失'}（{item.get('close_date') or '日期缺失'}）\n"
        f"参考价 {item.get('reference_price') or '缺失'}（{item.get('reference_date') or '日期未记录'}）· "
        f"较参考价 {percent(item.get('reference_return_pct'))}\n"
        f"T+1 {status} · 次日调整：{correction}"
    )
    if item.get("data_reason"):
        text += f"\n数据说明：{item['data_reason']}"
    return text


def _status(ret: Optional[float]) -> str:
    if ret is None:
        return "pending"
    if ret > 0:
        return "hit"
    if ret < 0:
        return "miss"
    return "neutral"


def build_post_market_review(
    report: Mapping[str, Any],
    *,
    prices: Optional[Mapping[str, Iterable[float]]] = None,
    benchmark_return_pct: Optional[float] = None,
    direction_outcomes: Optional[Mapping[str, Mapping[str, Any]]] = None,
    observations: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create review rows from close prices.

    ``prices`` maps a code to a sequence whose first value is the entry/preview
    close and last value is the post-market close. It is deliberately injectable
    so live data and historical verification use the same logic.
    """
    rows: List[Dict[str, Any]] = []
    prices = prices or {}
    for pick in report.get("picks") or []:
        code = str(pick.get("code") or "")
        series = list(prices.get(code) or [])
        returns: Dict[int, Optional[float]] = {}
        if series and positive_price(series[0]) is not None:
            entry = positive_price(series[0])
            for horizon in HORIZONS:
                if len(series) > horizon and positive_price(series[horizon]) is not None:
                    returns[horizon] = round((float(series[horizon]) / entry - 1) * 100, 3)
                else:
                    returns[horizon] = None
        else:
            returns = {horizon: None for horizon in HORIZONS}
        ret = returns.get(1)
        status = _status(ret)
        outcomes = [
            {"horizon": horizon, "return_pct": returns[horizon], "status": _status(returns[horizon])}
            for horizon in HORIZONS
        ]
        rows.append(
            {
                "prediction_id": f"{report.get('as_of', '')}:{code}",
                "code": code,
                "name": pick.get("name", ""),
                "return_pct": ret,
                "outcomes": outcomes,
                "benchmark_return_pct": benchmark_return_pct,
                "excess_return_pct": round(ret - benchmark_return_pct, 3)
                if ret is not None and benchmark_return_pct is not None
                else None,
                "status": status,
                "correction": "keep" if status == "hit" else "downgrade" if status == "miss" else "confirm",
                **dict((observations or {}).get(code) or {}),
            }
        )
    direction_outcomes = direction_outcomes or {}
    direction_review: List[Dict[str, Any]] = []
    for key, label in (
        ("current_attack", "当前主攻"),
        ("medium_term", "未来1~3个月"),
        ("early_positioning", "提前布局"),
        ("avoid_or_exit", "回避/撤退"),
    ):
        for item in (report.get("directions") or {}).get(key) or []:
            direction = str(item.get("direction") or "")
            outcome = dict(direction_outcomes.get(direction) or {})
            direction_review.append({
                "layer": label,
                "direction": direction,
                "premarket_status": item.get("status", "需确认"),
                "review_status": outcome.get("status", "pending"),
                "evidence": outcome.get("evidence", "未匹配到该方向的有效收盘行业数据；占位方向或市场宽度不能由行业涨跌榜验证"),
                "correction": outcome.get("correction", "keep" if outcome.get("status") == "confirmed" else "confirm"),
            })
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    as_of = report.get("as_of") or datetime.now().strftime("%Y-%m-%d")
    return {
        "schema_version": "decision-report-v2",
        "type": "stock_recommend_post_market",
        "as_of": as_of,
        "generated_at": generated_at,
        "run": {
            "run_id": f"{str(as_of).replace('-', '')}-post_market-{generated_at.replace('-', '').replace(':', '').replace(' ', 'T')}",
            "session": "post_market",
            "trade_date": as_of,
            "generated_at": generated_at,
            "status": "partial" if any(r.get("data_status") == "insufficient" for r in rows) or any(r["review_status"] == "pending" for r in direction_review) else "passed",
        },
        "market_review": {
            "premarket_regime": (report.get("market") or {}).get("regime"),
            "premarket_label": (report.get("market") or {}).get("label"),
            "premarket_status": (report.get("market") or {}).get("status"),
        },
        "direction_review": direction_review,
        "items": rows,
        "summary": {
            "pick_count": len(rows),
            "completed_count": sum(r["status"] != "pending" for r in rows),
            "hit_count": sum(r["status"] == "hit" for r in rows),
            "pending_count": sum(r["status"] == "pending" for r in rows),
            "close_count": sum(r.get("close_price") is not None for r in rows),
        },
        "delivery": {"channel": "feishu", "payload_hash": "", "accepted": False},
    }
