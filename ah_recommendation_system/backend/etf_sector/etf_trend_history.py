from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ah_recommendation_system.backend.reporting.report_store import ReportStore


_REPORT_DATE_PATTERN = re.compile(r"report_(\d{8})\.json$")


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def normalize_history_limit(value: Any, default: int = 30) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(180, parsed))


def extract_etf_trend_from_report(
    report: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(report, dict):
        return None
    etf_sector = report.get("etf_sector")
    if not isinstance(etf_sector, dict):
        return None
    trend = etf_sector.get("etf_trend")
    return trend if isinstance(trend, dict) else None


def summarize_etf_trend_snapshot(
    trend: Optional[Dict[str, Any]], *, report_date: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    if not isinstance(trend, dict) or not trend:
        return None

    summary = trend.get("summary") if isinstance(trend.get("summary"), dict) else {}
    recommendations = (
        trend.get("recommendations")
        if isinstance(trend.get("recommendations"), list)
        else []
    )

    recommended_count = _safe_int(summary.get("recommended_count"))
    watch_count = _safe_int(summary.get("watch_count"))
    avoid_count = _safe_int(summary.get("avoid_count"))

    if not any((recommended_count, watch_count, avoid_count)) and recommendations:
        recommended_count = sum(
            1 for item in recommendations if item.get("recommendation") == "优先关注"
        )
        watch_count = sum(
            1 for item in recommendations if item.get("recommendation") == "持有观察"
        )
        avoid_count = sum(
            1 for item in recommendations if item.get("recommendation") == "暂不关注"
        )

    strongest = []
    raw_strongest = (
        summary.get("strongest_etfs")
        if isinstance(summary.get("strongest_etfs"), list)
        else []
    )
    for item in raw_strongest[:3]:
        if not isinstance(item, dict):
            continue
        strongest.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "recommendation": item.get("recommendation"),
                "trend_score": _safe_float(item.get("trend_score")),
            }
        )

    generated_at = trend.get("generated_at") or ""
    date_text = (
        generated_at[:10]
        if isinstance(generated_at, str) and len(generated_at) >= 10
        else None
    )
    if not date_text and report_date:
        if len(report_date) == 8:
            date_text = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"
        else:
            date_text = report_date

    strongest_summary = "、".join(
        str(item.get("name") or item.get("code") or "") for item in strongest if item
    )

    return {
        "date": date_text,
        "report_date": report_date,
        "generated_at": generated_at or None,
        "regime_label": summary.get("regime_label") or "数据不足",
        "avg_score": _safe_float(summary.get("avg_score")),
        "recommended_count": recommended_count,
        "watch_count": watch_count,
        "avoid_count": avoid_count,
        "strongest_etfs": strongest,
        "strongest_summary": strongest_summary,
    }


def _extract_report_date(path: Path) -> Optional[str]:
    match = _REPORT_DATE_PATTERN.search(path.name)
    return match.group(1) if match else None


def load_etf_trend_history(store: ReportStore, limit: int = 30) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    normalized_limit = normalize_history_limit(limit)

    paths = sorted(
        store.reports_dir.glob("report_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for path in paths:
        try:
            report = store.load_path(path)
        except Exception:
            continue

        snapshot = summarize_etf_trend_snapshot(
            extract_etf_trend_from_report(report),
            report_date=_extract_report_date(path),
        )
        if not snapshot:
            continue

        items.append(snapshot)
        if len(items) >= normalized_limit:
            break

    return items
