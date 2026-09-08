from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ah_recommendation_system.backend.etf_sector.etf_sector_report import (
    generate_etf_sector_block,
)
from ah_recommendation_system.backend.etf_sector.etf_trend_analysis import (
    fetch_etf_hist_em,
)
from ah_recommendation_system.backend.reporting.report_store import ReportStore


BENCHMARK_CODE = "510300"
DEFAULT_HORIZONS = (5, 20)

STATUS_META = {
    "hit": {"status_cn": "命中", "label": "明显兑现"},
    "weak_hit": {"status_cn": "基本命中", "label": "方向基本对"},
    "neutral": {"status_cn": "中性", "label": "优势不明显"},
    "miss": {"status_cn": "偏离", "label": "与判断不一致"},
    "pending": {"status_cn": "待复盘", "label": "样本未完成"},
}

ERROR_TAG_META = {
    "sample_not_ready": {
        "label": "样本未到期",
        "note": "后续报告窗口还没走完，先保留原判断。",
    },
    "mapping_missing": {
        "label": "缺少ETF映射",
        "note": "当前主题没有可回看的ETF映射，暂时无法用价格验证。",
    },
    "market_data_gap": {
        "label": "行情缺口",
        "note": "复盘区间缺少完整行情数据，本次结果仅保留观察。",
    },
    "underperformed_benchmark": {
        "label": "跑输基准",
        "note": "方向判断偏乐观，后续相对沪深300表现落后。",
    },
    "crowding_too_early": {
        "label": "预警偏早",
        "note": "提示过热后仍继续走强，节奏上偏保守。",
    },
    "edge_not_clear": {
        "label": "优势不明显",
        "note": "方向没有明显出错，但超额收益不够突出。",
    },
    "risk_not_confirmed": {
        "label": "风险未证实",
        "note": "回避信号没有明显兑现，热度仍需继续观察。",
    },
}

CONFIDENCE_META = {
    "high": {
        "label": "高置信",
        "note": "信号较集中，可优先跟踪。",
    },
    "medium": {
        "label": "中置信",
        "note": "方向较清晰，适合继续观察。",
    },
    "low": {
        "label": "低置信",
        "note": "更偏试探，需要更多后续验证。",
    },
}

LABEL_NOTES = {
    "potential_breakout": "寻找可能启动的强势主题",
    "confirmed_leader": "跟踪已经走出来的主线",
    "crowded_risk": "提醒热度偏高，避免追涨",
    "priority_watch": "趋势评分靠前，适合优先观察",
    "watch": "方向尚可，保持跟踪",
    "avoid": "趋势偏弱，暂不关注",
}

BEARISH_LABELS = {"crowded_risk", "avoid"}


@dataclass(frozen=True)
class StoredReportItem:
    path: Path
    date_str: str
    report: Dict[str, Any]


def _parse_report_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y%m%d")
    except Exception:
        return None


def _report_date_from_path(path: Path) -> Optional[str]:
    stem = path.stem
    if stem.startswith("report_"):
        date_str = stem.replace("report_", "", 1)
        return date_str if len(date_str) == 8 and date_str.isdigit() else None
    return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _fmt_signed_pct(value: Optional[float], digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:+.{digits}f}%"


def _fmt_ratio_pct(value: Optional[float], digits: int = 1) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value * 100:.{digits}f}%"


def _format_cn_date(value: Optional[str]) -> str:
    parsed = _parse_report_date(str(value or ""))
    return parsed.strftime("%Y年%m月%d日") if parsed else str(value or "-")


def _month_key(date_str: Optional[str]) -> Optional[str]:
    text = str(date_str or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}"
    return None


def _month_label(month_key: Optional[str]) -> str:
    text = str(month_key or "")
    if len(text) == 7 and text[4] == "-":
        return f"{text[:4]}年{text[5:7]}月"
    return text or "未知月份"


def _horizon_label(horizon: int) -> str:
    return f"T+{int(horizon)}"


def _confidence_bucket(confidence: Any) -> str:
    value = _safe_float(confidence)
    if value is None:
        return "medium"
    if value >= 0.67:
        return "high"
    if value >= 0.4:
        return "medium"
    return "low"


def _join_parts(parts: List[str], sep: str = "；") -> str:
    cleaned = [str(part).strip() for part in parts if str(part or "").strip()]
    return sep.join(cleaned)


def _reason_dimension_summaries(data: Any) -> List[str]:
    if isinstance(data, dict):
        output: List[str] = []
        summary = data.get("summary")
        if isinstance(summary, str) and summary.strip():
            output.append(summary.strip())
        for value in data.values():
            output.extend(_reason_dimension_summaries(value))
        deduped: List[str] = []
        for item in output:
            if item not in deduped:
                deduped.append(item)
        return deduped
    if isinstance(data, list):
        output: List[str] = []
        for value in data:
            output.extend(_reason_dimension_summaries(value))
        return output
    return []


def _make_error_tag(code: str) -> Dict[str, str]:
    meta = ERROR_TAG_META.get(code, {})
    return {
        "code": code,
        "label": str(meta.get("label") or code),
        "note": str(meta.get("note") or ""),
    }


def list_stored_reports(store: ReportStore, limit: int = 120) -> List[StoredReportItem]:
    items: List[StoredReportItem] = []
    for path in sorted(store.reports_dir.glob("report_*.json"))[-max(1, int(limit or 120)) :]:
        date_str = _report_date_from_path(path)
        if not date_str:
            continue
        try:
            report = store.load_path(path)
        except Exception:
            continue
        items.append(StoredReportItem(path=path, date_str=date_str, report=report))
    items.sort(key=lambda item: item.date_str)
    return items


def _extract_prediction_rows(report_item: StoredReportItem) -> List[Dict[str, Any]]:
    blk = (report_item.report or {}).get("etf_sector") or {}
    rows: List[Dict[str, Any]] = []
    mapping = [
        ("potential_breakouts", "potential_breakout", "潜在突破"),
        ("confirmed_leaders", "confirmed_leader", "已确认主线"),
        ("crowded_risks", "crowded_risk", "过热谨慎"),
    ]
    for key, label, label_cn in mapping:
        for item in blk.get(key) or []:
            if not isinstance(item, dict):
                continue
            theme = str(item.get("theme") or "").strip()
            if not theme:
                continue
            rows.append(
                {
                    "prediction_id": f"{report_item.date_str}:{label}:{theme}",
                    "report_date": report_item.date_str,
                    "generated_at": blk.get("generated_at") or report_item.date_str,
                    "entity_type": "theme",
                    "entity_name": theme,
                    "entity_code": None,
                    "label": label,
                    "label_cn": label_cn,
                    "confidence": item.get("confidence"),
                    "score": item.get("score"),
                    "reasons": item.get("reasons") or [],
                    "reason_dimensions": item.get("reason_dimensions") or {},
                    "related_etfs": item.get("related_etfs") or [],
                    "snapshot_payload": item,
                    "version": "review_v1",
                    "benchmark": BENCHMARK_CODE,
                    "horizons": list(DEFAULT_HORIZONS),
                }
            )

    trend_block = blk.get("etf_trend") or {}
    label_map = {
        "优先关注": ("priority_watch", "ETF优先关注"),
        "持有观察": ("watch", "ETF持有观察"),
        "暂不关注": ("avoid", "ETF暂不关注"),
    }
    for item in trend_block.get("recommendations") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        label, label_cn = label_map.get(
            str(item.get("recommendation") or ""),
            ("watch", "ETF观察"),
        )
        rows.append(
            {
                "prediction_id": f"{report_item.date_str}:{label}:{code}",
                "report_date": report_item.date_str,
                "generated_at": blk.get("generated_at") or report_item.date_str,
                "entity_type": "etf",
                "entity_name": str(item.get("name") or code),
                "entity_code": code,
                "label": label,
                "label_cn": label_cn,
                "confidence": min(
                    1.0,
                    max(0.0, (_safe_float(item.get("trend_score")) or 0.0) / 100.0),
                ),
                "score": item.get("trend_score"),
                "reasons": item.get("reasons") or [],
                "reason_dimensions": {},
                "related_etfs": [{"code": code, "name": str(item.get("name") or code)}],
                "snapshot_payload": item,
                "version": "review_v1",
                "benchmark": BENCHMARK_CODE,
                "horizons": list(DEFAULT_HORIZONS),
            }
        )
    return rows


def _load_close_return(
    cache: Dict[Tuple[str, str, str], Optional[float]],
    code: str,
    start_date: str,
    end_date: str,
) -> Optional[float]:
    key = (code, start_date, end_date)
    if key in cache:
        return cache[key]
    try:
        hist = fetch_etf_hist_em(code, start_date=start_date, end_date=end_date)
        if hist is None or hist.empty:
            cache[key] = None
            return None
        frame = hist.copy()
        if "日期" in frame.columns and "收盘" in frame.columns:
            frame = frame[["日期", "收盘"]].rename(columns={"日期": "date", "收盘": "close"})
        elif {"date", "close"}.issubset(frame.columns):
            frame = frame[["date", "close"]]
        else:
            cache[key] = None
            return None
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).sort_values("date")
        if len(frame) < 2:
            cache[key] = None
            return None
        start_close = float(frame.iloc[0]["close"])
        end_close = float(frame.iloc[-1]["close"])
        result = round((end_close / start_close - 1.0) * 100.0, 3) if start_close > 0 else None
        cache[key] = result
        return result
    except Exception:
        cache[key] = None
        return None


def _decorate_prediction(prediction: Dict[str, Any]) -> Dict[str, Any]:
    bucket = _confidence_bucket(prediction.get("confidence"))
    bucket_meta = CONFIDENCE_META[bucket]
    related = prediction.get("related_etfs") or []
    related_names = []
    for item in related[:2]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("name") or item.get("code") or "").strip()
        if text:
            related_names.append(text)
    related_summary = "、".join(related_names)
    reason_text = _join_parts(
        [
            *[str(x).strip() for x in (prediction.get("reasons") or [])[:2] if str(x).strip()],
            *(_reason_dimension_summaries(prediction.get("reason_dimensions") or {})[:1]),
        ]
    )
    signal_direction_cn = "回避" if prediction.get("label") in BEARISH_LABELS else "看多"
    label_note = LABEL_NOTES.get(str(prediction.get("label") or ""), "记录一次可复盘判断")
    entity_summary = str(prediction.get("entity_name") or "-")
    if related_summary and prediction.get("entity_type") == "theme":
        entity_summary = f"{entity_summary}（关联ETF：{related_summary}）"
    elif prediction.get("entity_code"):
        entity_summary = f"{entity_summary}（{prediction['entity_code']}）"
    human_summary = (
        f"{_format_cn_date(prediction.get('report_date'))}对{entity_summary}给出“{prediction.get('label_cn') or '-'}”判断，"
        f"偏向{signal_direction_cn}；{label_note}。"
    )
    if reason_text:
        human_summary += f"核心依据：{reason_text}。"

    return {
        **prediction,
        "report_month": _month_key(str(prediction.get("report_date") or "")),
        "report_date_label": _format_cn_date(prediction.get("report_date")),
        "confidence_bucket": bucket,
        "confidence_bucket_label": bucket_meta["label"],
        "confidence_note": bucket_meta["note"],
        "signal_direction_cn": signal_direction_cn,
        "related_etf_summary": related_summary or "-",
        "reason_summary": reason_text or "暂无明确触发点",
        "entity_summary": entity_summary,
        "human_summary": human_summary,
    }


def _classify_status(label: str, excess: float) -> Tuple[str, List[str]]:
    if label in BEARISH_LABELS:
        if excess <= -3.0:
            return "hit", []
        if excess < 0:
            return "weak_hit", []
        if excess >= 3.0:
            return "miss", ["crowding_too_early"]
        return "neutral", ["risk_not_confirmed"]
    if excess >= 3.0:
        return "hit", []
    if excess > 0:
        return "weak_hit", []
    if excess <= -3.0:
        return "miss", ["underperformed_benchmark"]
    return "neutral", ["edge_not_clear"]


def _build_pending_sentence(horizon_label: str, tags: List[Dict[str, str]]) -> str:
    labels = "、".join(tag["label"] for tag in tags if tag.get("label"))
    notes = "；".join(tag["note"] for tag in tags if tag.get("note"))
    if labels and notes:
        return f"{horizon_label} 暂未完成复盘：{labels}。{notes}"
    if labels:
        return f"{horizon_label} 暂未完成复盘：{labels}。"
    return f"{horizon_label} 暂无足够样本，先保留原判断。"


def _build_review_notes(status: str, label: str, error_summary: str) -> str:
    if status == "hit":
        return "判断方向与后续相对表现一致，兑现度较高。"
    if status == "weak_hit":
        return "方向基本判断对了，但超额优势不算大。"
    if status == "neutral":
        if label in BEARISH_LABELS:
            return "回避信号暂未明显兑现，热度仍需继续观察。"
        return "后续相对优势不够突出，仍需继续观察。"
    if status == "miss":
        return f"后续走势与原判断不一致，主要问题：{error_summary or '节奏判断偏差'}。"
    if error_summary:
        return f"当前无法形成结论：{error_summary}。"
    return "当前样本不足，待后续复盘。"


def _build_review_sentence(
    horizon_label: str,
    status: str,
    excess: Optional[float],
    error_summary: str,
) -> str:
    if status == "pending":
        return f"{horizon_label} 暂无可用结论。"
    if not isinstance(excess, (int, float)):
        return f"{horizon_label} 暂时无法计算相对表现。"
    label = STATUS_META.get(status, {}).get("label") or status
    sentence = f"{horizon_label} 相对沪深300超额 {_fmt_signed_pct(float(excess))}，{label}。"
    if error_summary:
        sentence += f"标签：{error_summary}。"
    return sentence


def _evaluate_prediction(
    prediction: Dict[str, Any],
    future_report: Optional[StoredReportItem],
    price_cache: Dict[Tuple[str, str, str], Optional[float]],
    horizon: int,
) -> Dict[str, Any]:
    report_date = str(prediction.get("report_date") or "")
    label = str(prediction.get("label") or "")
    related = prediction.get("related_etfs") or []
    primary = related[0] if related else {}
    code = str(primary.get("code") or "").strip()
    horizon_label = _horizon_label(horizon)
    review_date = future_report.date_str if future_report else None

    if not future_report:
        tags = [_make_error_tag("sample_not_ready")]
        error_summary = "、".join(tag["label"] for tag in tags)
        return {
            "status": "pending",
            "status_cn": STATUS_META["pending"]["status_cn"],
            "status_label": STATUS_META["pending"]["label"],
            "horizon": horizon,
            "horizon_label": horizon_label,
            "review_date": review_date,
            "review_date_label": _format_cn_date(review_date),
            "entity_return_pct": None,
            "benchmark_return_pct": None,
            "excess_return_pct": None,
            "error_tags": tags,
            "error_summary": error_summary,
            "review_notes": _build_review_notes("pending", label, error_summary),
            "review_sentence": _build_pending_sentence(horizon_label, tags),
        }

    if not code:
        tags = [_make_error_tag("mapping_missing")]
        error_summary = "、".join(tag["label"] for tag in tags)
        return {
            "status": "pending",
            "status_cn": STATUS_META["pending"]["status_cn"],
            "status_label": STATUS_META["pending"]["label"],
            "horizon": horizon,
            "horizon_label": horizon_label,
            "review_date": review_date,
            "review_date_label": _format_cn_date(review_date),
            "entity_return_pct": None,
            "benchmark_return_pct": None,
            "excess_return_pct": None,
            "error_tags": tags,
            "error_summary": error_summary,
            "review_notes": _build_review_notes("pending", label, error_summary),
            "review_sentence": _build_pending_sentence(horizon_label, tags),
        }

    entity_ret = _load_close_return(price_cache, code, report_date, review_date)
    bench_ret = _load_close_return(price_cache, BENCHMARK_CODE, report_date, review_date)
    excess = None if entity_ret is None or bench_ret is None else round(entity_ret - bench_ret, 3)

    if excess is None:
        tags = [_make_error_tag("market_data_gap")]
        error_summary = "、".join(tag["label"] for tag in tags)
        return {
            "status": "pending",
            "status_cn": STATUS_META["pending"]["status_cn"],
            "status_label": STATUS_META["pending"]["label"],
            "horizon": horizon,
            "horizon_label": horizon_label,
            "review_date": review_date,
            "review_date_label": _format_cn_date(review_date),
            "entity_return_pct": entity_ret,
            "benchmark_return_pct": bench_ret,
            "excess_return_pct": excess,
            "error_tags": tags,
            "error_summary": error_summary,
            "review_notes": _build_review_notes("pending", label, error_summary),
            "review_sentence": _build_pending_sentence(horizon_label, tags),
        }

    status, error_codes = _classify_status(label, float(excess))
    tags = [_make_error_tag(code_item) for code_item in error_codes]
    error_summary = "、".join(tag["label"] for tag in tags)

    return {
        "status": status,
        "status_cn": STATUS_META[status]["status_cn"],
        "status_label": STATUS_META[status]["label"],
        "horizon": horizon,
        "horizon_label": horizon_label,
        "review_date": review_date,
        "review_date_label": _format_cn_date(review_date),
        "entity_return_pct": entity_ret,
        "benchmark_return_pct": bench_ret,
        "excess_return_pct": excess,
        "error_tags": tags,
        "error_summary": error_summary,
        "review_notes": _build_review_notes(status, label, error_summary),
        "review_sentence": _build_review_sentence(horizon_label, status, excess, error_summary),
    }


def _build_monthly_stats(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        month = item.get("report_month") or "unknown"
        bucket = item.get("confidence_bucket")
        row = grouped.setdefault(
            month,
            {
                "month": month,
                "month_label": _month_label(month),
                "prediction_count": 0,
                "review_count": 0,
                "pending_count": 0,
                "hit_like": 0,
                "miss_count": 0,
                "high_confidence_count": 0,
                "excess_values": [],
            },
        )
        row["prediction_count"] += 1
        if bucket == "high":
            row["high_confidence_count"] += 1
        for outcome in item.get("outcomes") or []:
            status = outcome.get("status")
            if status == "pending":
                row["pending_count"] += 1
                continue
            row["review_count"] += 1
            if status in {"hit", "weak_hit"}:
                row["hit_like"] += 1
            if status == "miss":
                row["miss_count"] += 1
            if isinstance(outcome.get("excess_return_pct"), (int, float)):
                row["excess_values"].append(float(outcome["excess_return_pct"]))

    series: List[Dict[str, Any]] = []
    for key in sorted(grouped.keys()):
        row = grouped[key]
        review_count = int(row["review_count"])
        avg_excess = (
            round(sum(row["excess_values"]) / len(row["excess_values"]), 3)
            if row["excess_values"]
            else None
        )
        month_row = {
            "month": row["month"],
            "month_label": row["month_label"],
            "prediction_count": row["prediction_count"],
            "review_count": review_count,
            "pending_count": row["pending_count"],
            "high_confidence_count": row["high_confidence_count"],
            "hit_rate": round(row["hit_like"] / review_count, 3) if review_count else None,
            "avg_excess_return_pct": avg_excess,
            "miss_count": row["miss_count"],
            "headline": (
                f"{row['month_label']}共发出{row['prediction_count']}条判断，已复盘{review_count}个窗口，"
                f"命中率{_fmt_ratio_pct(round(row['hit_like'] / review_count, 3), 1) if review_count else '-'}，"
                f"平均超额{_fmt_signed_pct(avg_excess)}。"
            ),
        }
        series.append(month_row)

    cards = list(reversed(series[-3:]))
    headline = cards[0]["headline"] if cards else "当前样本不足，先等待更多月度复盘。"
    return {"headline": headline, "cards": cards, "series": series[-6:]}


def _build_confidence_stats(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, Any]] = {
        key: {
            "bucket": key,
            "label": meta["label"],
            "note": meta["note"],
            "prediction_count": 0,
            "review_count": 0,
            "pending_count": 0,
            "hit_like": 0,
            "miss_count": 0,
            "excess_values": [],
        }
        for key, meta in CONFIDENCE_META.items()
    }
    for item in items:
        bucket = str(item.get("confidence_bucket") or "medium")
        row = grouped[bucket]
        row["prediction_count"] += 1
        for outcome in item.get("outcomes") or []:
            status = outcome.get("status")
            if status == "pending":
                row["pending_count"] += 1
                continue
            row["review_count"] += 1
            if status in {"hit", "weak_hit"}:
                row["hit_like"] += 1
            if status == "miss":
                row["miss_count"] += 1
            if isinstance(outcome.get("excess_return_pct"), (int, float)):
                row["excess_values"].append(float(outcome["excess_return_pct"]))

    buckets: List[Dict[str, Any]] = []
    for key in ("high", "medium", "low"):
        row = grouped[key]
        review_count = int(row["review_count"])
        avg_excess = (
            round(sum(row["excess_values"]) / len(row["excess_values"]), 3)
            if row["excess_values"]
            else None
        )
        buckets.append(
            {
                "bucket": row["bucket"],
                "label": row["label"],
                "note": row["note"],
                "prediction_count": row["prediction_count"],
                "review_count": review_count,
                "pending_count": row["pending_count"],
                "miss_count": row["miss_count"],
                "hit_rate": round(row["hit_like"] / review_count, 3) if review_count else None,
                "avg_excess_return_pct": avg_excess,
                "headline": (
                    f"{row['label']}判断已复盘{review_count}个窗口，命中率"
                    f"{_fmt_ratio_pct(round(row['hit_like'] / review_count, 3), 1) if review_count else '-'}，"
                    f"平均超额{_fmt_signed_pct(avg_excess)}。"
                ),
            }
        )

    completed_rows = [row for row in buckets if row["review_count"] > 0]
    if completed_rows:
        best_row = max(
            completed_rows,
            key=lambda row: (
                row["hit_rate"] if isinstance(row["hit_rate"], (int, float)) else -1,
                row["avg_excess_return_pct"]
                if isinstance(row["avg_excess_return_pct"], (int, float))
                else -999,
            ),
        )
        headline = (
            f"当前{best_row['label']}判断表现相对更稳，命中率{_fmt_ratio_pct(best_row['hit_rate'])}，"
            f"平均超额{_fmt_signed_pct(best_row['avg_excess_return_pct'])}。"
        )
    else:
        headline = "高/中/低置信判断都还在积累样本，先以趋势方向为主。"
    return {"headline": headline, "buckets": buckets}


def _build_weekly_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    dated_items = [item for item in items if _parse_report_date(str(item.get("report_date") or ""))]
    if not dated_items:
        return {
            "title": "近一周复盘摘要",
            "period_start": None,
            "period_end": None,
            "headline": "暂无可用于周度复盘的样本。",
            "bullets": ["先等待更多日报积累后，再观察一周内判断质量。"],
        }

    latest_date = max(_parse_report_date(str(item.get("report_date") or "")) for item in dated_items)
    window_start = latest_date - timedelta(days=6)
    recent_items = [
        item
        for item in dated_items
        if (_parse_report_date(str(item.get("report_date") or "")) or latest_date) >= window_start
    ]
    recent_outcomes = [
        outcome
        for item in recent_items
        for outcome in (item.get("outcomes") or [])
        if outcome.get("status") != "pending"
    ]
    recent_excess_values = [
        float(outcome["excess_return_pct"])
        for outcome in recent_outcomes
        if isinstance(outcome.get("excess_return_pct"), (int, float))
    ]
    pending_count = sum(
        1
        for item in recent_items
        for outcome in (item.get("outcomes") or [])
        if outcome.get("status") == "pending"
    )
    hit_like = sum(1 for outcome in recent_outcomes if outcome.get("status") in {"hit", "weak_hit"})
    avg_excess = (
        round(sum(recent_excess_values) / len(recent_excess_values), 3)
        if recent_excess_values
        else None
    )

    item_scores: List[Tuple[float, str]] = []
    for item in recent_items:
        values = [
            float(outcome["excess_return_pct"])
            for outcome in (item.get("outcomes") or [])
            if isinstance(outcome.get("excess_return_pct"), (int, float))
        ]
        if values:
            item_scores.append((round(sum(values) / len(values), 3), str(item.get("entity_name") or "-")))

    top_names = [name for score, name in sorted(item_scores, reverse=True) if score > 0][:2]
    weak_names = [name for score, name in sorted(item_scores) if score < 0][:2]
    high_pending = sum(
        1
        for item in recent_items
        if item.get("confidence_bucket") == "high"
        and any(outcome.get("status") == "pending" for outcome in (item.get("outcomes") or []))
    )

    period_start = window_start.strftime("%Y%m%d")
    period_end = latest_date.strftime("%Y%m%d")
    headline = (
        f"近一周新增{len(recent_items)}条ETF/板块判断，已完成{len(recent_outcomes)}个复盘窗口，"
        f"命中率{_fmt_ratio_pct(round(hit_like / len(recent_outcomes), 3), 1) if recent_outcomes else '-'}，"
        f"平均超额{_fmt_signed_pct(avg_excess)}。"
    )
    bullets = [headline]
    if top_names:
        bullets.append(f"本周相对更顺的方向集中在{'、'.join(top_names)}，适合继续跟踪延续性。")
    if weak_names:
        bullets.append(f"偏差主要出现在{'、'.join(weak_names)}，多半是节奏偏慢或追涨过早。")
    if pending_count:
        bullets.append(f"还有{pending_count}个窗口待复盘，其中高置信判断待观察{high_pending}条，可优先盯T+20延续。")
    return {
        "title": "近一周复盘摘要",
        "period_start": period_start,
        "period_end": period_end,
        "headline": headline,
        "bullets": bullets[:4],
    }


def build_etf_sector_review(store: ReportStore, limit_reports: int = 40) -> Dict[str, Any]:
    reports = list_stored_reports(store, limit=limit_reports)
    predictions: List[Dict[str, Any]] = []
    for item in reports:
        predictions.extend(_extract_prediction_rows(item))

    if not predictions:
        try:
            live_block = generate_etf_sector_block()
            live_item = StoredReportItem(
                path=Path("live"),
                date_str=datetime.now().strftime("%Y%m%d"),
                report={"etf_sector": live_block},
            )
            predictions.extend(_extract_prediction_rows(live_item))
        except Exception:
            pass

    predictions = [_decorate_prediction(item) for item in predictions]
    price_cache: Dict[Tuple[str, str, str], Optional[float]] = {}
    report_index = {item.date_str: idx for idx, item in enumerate(reports)}
    review_items: List[Dict[str, Any]] = []
    outcome_counts = {"hit": 0, "weak_hit": 0, "neutral": 0, "miss": 0, "pending": 0}
    excess_values: List[float] = []

    for prediction in predictions:
        base_index = report_index.get(prediction["report_date"])
        outcomes: List[Dict[str, Any]] = []
        if base_index is None:
            for horizon in DEFAULT_HORIZONS:
                outcome = {
                    "status": "pending",
                    "status_cn": STATUS_META["pending"]["status_cn"],
                    "status_label": STATUS_META["pending"]["label"],
                    "horizon": horizon,
                    "horizon_label": _horizon_label(horizon),
                    "review_date": None,
                    "review_date_label": "-",
                    "entity_return_pct": None,
                    "benchmark_return_pct": None,
                    "excess_return_pct": None,
                    "error_tags": [_make_error_tag("sample_not_ready")],
                    "error_summary": ERROR_TAG_META["sample_not_ready"]["label"],
                    "review_notes": "当前预测，待后续报告复盘。",
                    "review_sentence": _build_pending_sentence(
                        _horizon_label(horizon),
                        [_make_error_tag("sample_not_ready")],
                    ),
                }
                outcomes.append(outcome)
                outcome_counts["pending"] = outcome_counts.get("pending", 0) + 1
            review_items.append({**prediction, "outcomes": outcomes})
            continue

        for horizon in DEFAULT_HORIZONS:
            target_index = base_index + horizon
            future = reports[target_index] if target_index < len(reports) else None
            outcome = _evaluate_prediction(prediction, future, price_cache, horizon)
            outcomes.append(outcome)
            outcome_counts[outcome["status"]] = outcome_counts.get(outcome["status"], 0) + 1
            if isinstance(outcome.get("excess_return_pct"), (int, float)):
                excess_values.append(float(outcome["excess_return_pct"]))

        review_items.append({**prediction, "outcomes": outcomes})

    completed = sum(outcome_counts.get(key, 0) for key in ("hit", "weak_hit", "neutral", "miss"))
    hit_like = outcome_counts.get("hit", 0) + outcome_counts.get("weak_hit", 0)
    avg_excess = round(sum(excess_values) / len(excess_values), 3) if excess_values else None
    monthly_stats = _build_monthly_stats(review_items)
    confidence_stats = _build_confidence_stats(review_items)
    weekly_summary = _build_weekly_summary(review_items)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "prediction_count": len(predictions),
            "review_count": completed,
            "pending_count": outcome_counts.get("pending", 0),
            "hit_rate": round(hit_like / completed, 3) if completed else None,
            "avg_excess_return_pct": avg_excess,
            "status_counts": outcome_counts,
            "headline": (
                f"累计记录{len(predictions)}条判断，已完成{completed}个复盘窗口，"
                f"命中率{_fmt_ratio_pct(round(hit_like / completed, 3), 1) if completed else '-'}，"
                f"平均超额{_fmt_signed_pct(avg_excess)}。"
            ),
        },
        "monthly_stats": monthly_stats,
        "confidence_stats": confidence_stats,
        "weekly_summary": weekly_summary,
        "items": list(reversed(review_items[-80:])),
    }
