"""Build a deterministic post-market review for the pre-market picks."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional


HORIZONS = (1, 5, 20)


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
        if series and float(series[0]) != 0:
            entry = float(series[0])
            for horizon in HORIZONS:
                if len(series) > horizon:
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
                "evidence": outcome.get("evidence", "等待可靠收盘价量与行业宽度确认"),
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
            "status": "passed",
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
        },
        "delivery": {"channel": "feishu", "payload_hash": "", "accepted": False},
    }
