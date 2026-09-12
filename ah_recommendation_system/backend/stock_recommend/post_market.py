"""Build a deterministic post-market review for the pre-market picks."""
from __future__ import annotations

from datetime import datetime
import math
import re
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
        "reference_source": pick.get("reference_source") or "未记录",
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
    observation_date = as_of
    if today.empty:
        # A provider may lag the current calendar date. Keep the latest
        # completed close visible, but do not treat it as T+1 validation.
        if bars.empty:
            return row
        today = bars.iloc[[-1]]
        observation_date = str(today.iloc[-1]["date"])
    close = positive_price(today.iloc[-1]["close"])
    if close is None:
        return row
    stale = observation_date != as_of
    row.update(close_price=close, close_date=observation_date,
               data_status="stale_close" if stale else "available",
               data_reason=(f"当日收盘尚未提供，使用最新已完成交易日 {observation_date}；T+1仍待验证" if stale else ""))
    previous = bars.loc[bars["date"] < observation_date]
    if not previous.empty:
        previous_close = positive_price(previous.iloc[-1]["close"])
        if previous_close is not None:
            row.update(previous_close=previous_close, previous_close_date=previous.iloc[-1]["date"],
                       daily_return_pct=round((close / previous_close - 1) * 100, 3))
    # A same-day reference equal to the observed close is just the baseline.
    # A distinct same-day pre-market price, or an explicitly dated earlier
    # reference, is real movement since the recommendation snapshot.
    prior_reference_date = str(pick.get("reference_date") or "")[:10]
    dated_prior_reference = bool(prior_reference_date) and prior_reference_date < observation_date
    has_prior_bar = not previous.empty
    same_day_distinct_price = (
        not prior_reference_date and not has_prior_bar
        and observation_date == as_of and reference != close
    )
    if reference is not None and (dated_prior_reference or same_day_distinct_price):
        row["reference_return_pct"] = round((close / reference - 1) * 100, 3)
    if row["daily_return_pct"] is None:
        row.update(data_status="insufficient", data_reason="缺少有效昨收，无法计算当日涨跌")
    return row


def format_review_item(item: Mapping[str, Any]) -> str:
    status = {"pending": "待验证", "hit": "上涨", "miss": "下跌", "neutral": "平盘"}.get(item.get("status"), "待验证")
    correction = {"keep": "保留观察", "downgrade": "降级观察", "confirm": "等待确认"}.get(item.get("correction"), "等待确认")
    change = item.get("daily_return_pct")
    label = "最近交易日涨跌" if item.get("data_status") == "stale_close" else "当日涨跌"
    performance = f"{label} {change:+.2f}%" if change is not None else "未取得可核验的当日涨跌"
    lines = [f"**{item.get('name', '')} ({item.get('code', '')})** · {performance}"]
    if item.get("close_price") is not None:
        if item.get("previous_close") is not None:
            lines.append(f"前收 {item['previous_close']}（{item.get('previous_close_date')}）→ "
                         f"收盘 {item['close_price']}（{item.get('close_date')}）")
        else:
            lines.append(f"收盘 {item['close_price']}（{item.get('close_date')}）")
    if item.get("reference_price") is not None:
        value = item.get("reference_return_pct")
        reference = f"原报告参考价 {item['reference_price']}"
        if value is None:
            reference += "；时点未核验，不计算相对收益。"
        else:
            reference += f"；较参考价 {value:+.2f}%（观察价格变化，非交易收益）。"
        lines.append(reference)
    if item.get("status", "pending") == "pending":
        lines.append("T+1 待验证；不据此调整观察结论。")
    else:
        lines.append(f"T+1 {status}；{correction}。")
    if item.get("data_reason"):
        lines.append(f"数据说明：{item['data_reason']}")
    return "\n".join(lines)


def format_direction_review(item: Mapping[str, Any]) -> str:
    status = {"failed": "当日走弱", "confirmed": "当日得到支持", "neutral": "当日表现中性", "pending": "尚未验证"}.get(
        item.get("review_status"), str(item.get("review_status") or "尚未验证"))
    correction = {"downgrade": "降级观察", "keep": "保留观察", "confirm": "继续观察"}.get(
        item.get("correction"), str(item.get("correction") or "继续观察"))
    evidence = str(item.get("evidence") or "尚无可核验依据")
    evidence = evidence.replace("（来源：ths）", "（来源：同花顺行业行情）")
    return (f"- **{item.get('layer', '方向')}·{item.get('direction', '未指定')}**｜{status}｜{correction}\n"
            f"  {evidence}")


def audit_review_card(report: Mapping[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate content before delivery, including strings hidden by formatting."""
    def strings(value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, Mapping):
            for child in value.values():
                yield from strings(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from strings(child)

    errors = []
    if any(re.search(r"\?{2,}|\ufffd", value) for value in strings(report)):
        errors.append("报告含连续问号或非法替换字符")
    visible = "\n".join(strings(payload))
    if re.search(r"\?{2,}|\ufffd", visible):
        errors.append("推送文本含乱码")
    if re.search(r"\b(?:failed|pending|confirm|downgrade|premarket_candidate_snapshot)\b", visible):
        errors.append("推送文本含未翻译的内部字段")
    if "None%" in visible or "nan%" in visible:
        errors.append("推送文本含非法收益值")
    return {"passed": not errors, "errors": errors, "version": "post-market-content-v1"}


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
            if key in {"medium_term", "early_positioning"} and outcome.get("status") in {"failed", "confirmed"}:
                outcome["status"] = "pending"
                outcome["correction"] = "confirm"
                outcome["evidence"] = "单日行业涨跌不足以验证未来1~3个月方向；需结合分红兑现、盈利与持续走势评估。"
            direction_review.append({
                "layer": label,
                "direction": direction,
                "premarket_status": item.get("status", "需确认"),
                "review_status": outcome.get("status", "pending"),
                "evidence": outcome.get("evidence", "本次未采集全市场上涨/下跌家数，不能判断市场宽度。" if "宽度" in direction else "本次未匹配到该方向的收盘数据，不作有效或失效判断。"),
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
            "status": "partial" if any(r.get("data_status") in {"insufficient", "stale_close"} for r in rows) or any(r["review_status"] == "pending" for r in direction_review) or any(r["status"] == "pending" for r in rows) else "passed",
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
            "close_count": sum(r.get("close_price") is not None and r.get("close_date") == as_of for r in rows),
        },
        "delivery": {"channel": "feishu", "payload_hash": "", "accepted": False},
    }
