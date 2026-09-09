"""Local-Codex hotspot extraction from already collected market evidence."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Mapping, Optional

from ah_recommendation_system.backend.stock_recommend.codex_cli_client import CodexCliClient


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def build_hotspot_prompt(*, macro_news: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]], as_of: str) -> str:
    titles = []
    news_items = list(macro_news.get("items") or []) + list(macro_news.get("stock_news") or [])
    for index, item in enumerate(news_items[:24]):
        titles.append({
            "event_id": item.get("event_id") or f"macro-{index}",
            "title": _bounded_text(item.get("title"), 120),
            "summary": _bounded_text(item.get("summary") or item.get("content"), 300),
            "source": _bounded_text(item.get("source"), 40),
            "published_at": _bounded_text(item.get("published_at"), 32),
        })
    rows = [
        {"code": row.get("code"), "name": row.get("name"), "change_pct": row.get("change_pct"), "amount": row.get("amount"), "candidate_sources": row.get("candidate_sources"), "focus_industries": row.get("focus_industries")}
        for row in list(candidates)[:20]
    ]
    return (
        "你是A股盘前热点研究员。只能基于输入的新闻、行业和候选数据识别最多5个热点，"
        "不得联网、编造股票代码或证据。每个热点至少引用2个evidence_refs。只输出JSON："
        "{hotspots:[{theme,drivers,industries,direction,confidence,horizon,evidence_refs}],market_regime,falsification}。\n"
        f"分析日期：{as_of}\n新闻：{json.dumps(titles, ensure_ascii=False)}\n候选与行情：{json.dumps(rows, ensure_ascii=False)}"
    )


def normalize_hotspots(payload: Mapping[str, Any], *, valid_refs: set[str]) -> list[Dict[str, Any]]:
    output: list[Dict[str, Any]] = []
    for item in payload.get("hotspots") or []:
        if not isinstance(item, Mapping):
            continue
        theme = str(item.get("theme") or "").strip()
        refs = {str(ref) for ref in (item.get("evidence_refs") or []) if str(ref)}
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            continue
        if not theme or len(refs) < 2 or not refs.issubset(valid_refs) or not 0 <= confidence <= 1:
            continue
        output.append({
            "theme": theme,
            "drivers": [str(x) for x in item.get("drivers") or []][:5],
            "industries": [str(x) for x in item.get("industries") or []][:8],
            "direction": str(item.get("direction") or "mixed"),
            "confidence": confidence,
            "horizon": str(item.get("horizon") or "short"),
            "evidence_refs": sorted(refs),
            "status": "early_signal",
        })
        if len(output) >= 5:
            break
    return output


def analyze_hotspots(*, macro_news: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]], as_of: str, client: Optional[CodexCliClient] = None) -> Dict[str, Any]:
    # Both macro RSS and collected stock news are valid hotspot evidence.
    # Keep the original ``macro_news`` argument name for API compatibility.
    news_items = list(macro_news.get("items") or []) + list(macro_news.get("stock_news") or [])
    valid_refs = {str(item.get("event_id") or f"macro-{index}") for index, item in enumerate(news_items)}
    if len(valid_refs) < 2:
        return {"status": "unavailable", "hotspots": [], "output_valid": False}
    client = client or CodexCliClient()
    result = client.analyze(build_hotspot_prompt(macro_news=macro_news, candidates=candidates, as_of=as_of))
    payload = result.get("data") if result.get("status") == "used" else None
    hotspots = normalize_hotspots(payload or {}, valid_refs=valid_refs) if isinstance(payload, Mapping) else []
    result["hotspots"] = hotspots
    if result.get("status") == "used" and not hotspots:
        result["status"] = "failed"
        result["error"] = "no_valid_hotspots"
    return result
