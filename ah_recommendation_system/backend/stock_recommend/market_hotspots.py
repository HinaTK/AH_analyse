"""Build auditable market-hotspot summaries for reports and notifications."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

PLACEHOLDER_THEMES = {"\u65b0\u95fb\u9a71\u52a8\u5f85\u786e\u8ba4", "\u70ed\u70b9\u5f85\u786e\u8ba4"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _items(value: Any, limit: int = 5) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [_text(item) for item in value if _text(item)][:limit]
    value = _text(value)
    return [value] if value else []


def _status_label(status: str) -> str:
    return {"confirmed": "消息验证", "early_signal": "消息待确认"}.get(status, "消息待确认")


def build_market_hotspots(
    *,
    news_hotspots: Iterable[Mapping[str, Any]] = (),
    market_signals: Iterable[Mapping[str, Any]] = (),
    picks: Iterable[Mapping[str, Any]] = (),
    etf_picks: Iterable[Mapping[str, Any]] = (),
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Prioritize validated news, then sector breadth signals.

    ETF trends and stock rankings are deliberately not market hotspots by
    themselves. Market-derived rows require explicit breadth evidence.
    """
    # ETF trends alone are not sufficient evidence. Stock candidates may be
    # used only as an explicitly labelled fallback direction when no news or
    # breadth hotspot is available.
    limit = max(0, min(int(limit), 5))
    output: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in news_hotspots:
        if not isinstance(raw, Mapping):
            continue
        theme = _text(raw.get("theme"))
        status = _text(raw.get("status"))
        if not theme or status == "discarded" or theme in PLACEHOLDER_THEMES or theme in seen:
            continue
        seen.add(theme)
        refs = _items(raw.get("evidence_refs"), 10)
        reprints = int(raw.get("reprint_count") or raw.get("evidence_count") or len(refs) or 0)
        independent = raw.get("independent_source_count")
        evidence_grade = _text(raw.get("evidence_grade")) or _status_label(status)
        output.append({
            "theme": theme,
            "drivers": _items(raw.get("drivers"), 3),
            "industries": _items(raw.get("industries"), 5),
            "representatives": _items(raw.get("representatives"), 5),
            "mapping_gap": _text(raw.get("mapping_gap")) or None,
            "source_type": "news",
            "status": status or "early_signal",
            "status_label": _status_label(status),
            "evidence_grade": evidence_grade,
            "confidence": raw.get("confidence"),
            "evidence_refs": refs,
            "evidence_count": reprints or len(refs),
            "independent_source_count": independent,
            "horizon": _text(raw.get("horizon")) or "short",
        })
        if len(output) >= limit:
            return output

    for raw in market_signals:
        if not isinstance(raw, Mapping):
            continue
        theme = _text(raw.get("theme")) or _text(raw.get("name"))
        change = raw.get("change_pct") if raw.get("change_pct") is not None else raw.get("chg_pct")
        try:
            change_value = float(change)
            advance_value, total_value = int(raw.get("advance_count")), int(raw.get("total_count"))
        except (TypeError, ValueError):
            continue
        if not theme or theme in seen or total_value < 5 or advance_value / total_value < 0.6 or change_value < 1.0:
            continue
        seen.add(theme)
        driver = f"涨幅 {change_value:.1f}%；上涨{advance_value}/{total_value}"
        try:
            driver += f"；成交额 {float(raw.get('turnover_yi')):.1f}亿"
        except (TypeError, ValueError):
            pass
        leader = _text(raw.get("leader"))
        output.append({
            "theme": theme,
            "drivers": [driver],
            "industries": [theme],
            "representatives": [leader] if leader else [],
            "source_type": "market",
            "status": "market_confirmed",
            "status_label": "盘面确认",
            "confidence": None,
            "evidence_refs": [],
            "evidence_count": 0,
            "horizon": "short",
        })
        if len(output) >= limit:
            return output

    candidate_groups: dict[str, list[Mapping[str, Any]]] = {}
    for raw in picks:
        if not isinstance(raw, Mapping):
            continue
        for industry in raw.get("focus_industries") or []:
            key = _text(industry)
            if key:
                candidate_groups.setdefault(key, []).append(raw)
    for theme, members in sorted(candidate_groups.items(), key=lambda item: -len(item[1])):
        if theme in seen or len(members) < 2:
            continue
        seen.add(theme)
        representatives = [_text(row.get("name")) for row in members[:5] if _text(row.get("name"))]
        output.append({
            "theme": theme,
            "drivers": [f"候选池 {len(members)} 只标的同向出现，等待行业宽度与成交确认"],
            "industries": [theme],
            "representatives": representatives,
            "source_type": "candidate",
            "status": "early_signal",
            "status_label": "候选方向待确认",
            "confidence": None,
            "evidence_refs": [],
            "evidence_count": 0,
            "horizon": "short",
        })
        if len(output) >= limit:
            return output

    return output[:limit]
