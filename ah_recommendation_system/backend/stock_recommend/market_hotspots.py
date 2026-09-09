"""Build auditable market-hotspot summaries for reports and notifications."""
from __future__ import annotations

from typing import Any, Iterable, Mapping


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
    del picks, etf_picks  # retained for backwards-compatible call sites
    limit = max(0, min(int(limit), 5))
    output: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in news_hotspots:
        if not isinstance(raw, Mapping):
            continue
        theme = _text(raw.get("theme"))
        status = _text(raw.get("status"))
        if not theme or status == "discarded" or theme in seen:
            continue
        seen.add(theme)
        refs = _items(raw.get("evidence_refs"), 10)
        output.append({
            "theme": theme,
            "drivers": _items(raw.get("drivers"), 3),
            "industries": _items(raw.get("industries"), 5),
            "representatives": _items(raw.get("representatives"), 5),
            "source_type": "news",
            "status": status or "early_signal",
            "status_label": _status_label(status),
            "confidence": raw.get("confidence"),
            "evidence_refs": refs,
            "evidence_count": len(refs),
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

    return output[:limit]
