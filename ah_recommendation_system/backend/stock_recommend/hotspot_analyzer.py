"""Local-Codex hotspot extraction from already collected market evidence."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from ah_recommendation_system.backend.stock_recommend.codex_cli_client import CodexCliClient
from ah_recommendation_system.backend.stock_recommend.news_ranker import hotspot_evidence_limit, select_hotspot_evidence

PLACEHOLDER_THEMES = {"\u65b0\u95fb\u9a71\u52a8\u5f85\u786e\u8ba4", "\u70ed\u70b9\u5f85\u786e\u8ba4"}
CONFIDENCE_LABELS = {
    "high": 0.8,
    "\u9ad8": 0.8,
    "medium": 0.55,
    "\u4e2d": 0.55,
    "low": 0.35,
    "\u4f4e": 0.35,
}


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def collect_news_items(macro_news: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = list(macro_news.get("items") or []) + list(macro_news.get("stock_news") or [])
    output: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        row.setdefault("event_id", f"macro-{index}")
        output.append(row)
    return output


def selected_evidence(macro_news: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]] = (), limit: int | None = None) -> list[dict[str, Any]]:
    return select_hotspot_evidence(collect_news_items(macro_news), candidates=list(candidates), limit=hotspot_evidence_limit(limit))


def build_hotspot_prompt(*, macro_news: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]], as_of: str, evidence_items: Sequence[Mapping[str, Any]] | None = None) -> str:
    news_items = list(evidence_items) if evidence_items is not None else selected_evidence(macro_news, candidates)
    titles = []
    packed = list(news_items[:hotspot_evidence_limit()])
    for index, item in enumerate(packed):
        titles.append({
            "event_id": item.get("event_id") or f"macro-{index}",
            "title": _bounded_text(item.get("title"), 120),
            "summary": _bounded_text(item.get("summary") or item.get("content"), 300),
            "source": _bounded_text(item.get("source"), 40),
            "published_at": _bounded_text(item.get("published_at"), 32),
            "query_bucket": _bounded_text(item.get("query_bucket"), 24),
        })
    rows = [
        {"code": row.get("code"), "name": row.get("name"), "change_pct": row.get("change_pct"), "amount": row.get("amount"), "candidate_sources": row.get("candidate_sources"), "focus_industries": row.get("focus_industries")}
        for row in list(candidates)[:20]
    ]
    event_ids = [item["event_id"] for item in titles]
    return (
        "\u4f60\u662fA\u80a1\u76d8\u524d\u70ed\u70b9\u7814\u7a76\u5458\u3002\u53ea\u80fd\u7528\u4e0b\u9762\u65b0\u95fb\u3001\u884c\u4e1a\u548c\u5019\u9009\u80a1\u8bc6\u522b\u81f3\u591a5\u4e2a\u70ed\u70b9\uff0c"
        "\u4e0d\u8981\u7f16\u9020\u6ca1\u6709\u4e0a\u5e02\u516c\u53f8\u8bc1\u636e\u3002\u6bcf\u4e2a\u70ed\u70b9\u81f3\u5c112\u6761evidence_refs\u3002\u53ea\u8f93JSON\u3002"
        "{hotspots:[{theme,drivers,industries,direction,confidence,horizon,evidence_refs}],market_regime,falsification}\n"
        "\u7ea6\u675f\uff1aconfidence \u5fc5\u987b\u662f 0 \u5230 1 \u7684\u5c0f\u6570\uff0c\u6570\u5b57\u8d8a\u5927\u8868\u793a\u7f6e\u4fe1\u5ea6\u8d8a\u9ad8\uff1b\u7981\u6b62 high/medium/low\u3002"
        "drivers \u5fc5\u987b\u662f\u5b57\u7b26\u4e32\u6570\u7ec4\u3002evidence_refs \u53ea\u80fd\u4f7f\u7528\u4e0b\u5217 event_id\u3002\n"
        f"\u5206\u6790\u65e5\u671f\uff1a{as_of}\n\u53ef\u7528event_id\uff1a{json.dumps(event_ids, ensure_ascii=False)}\n"
        f"\u65b0\u95fb\uff1a{json.dumps(titles, ensure_ascii=False)}\n\u5019\u9009\u80a1\u4e0a\u4e0b\u6587\uff1a{json.dumps(rows, ensure_ascii=False)}"
    )


def coerce_confidence(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if 0.0 <= number <= 1.0:
            return number
        if 1.0 < number <= 100.0:
            return round(number / 100.0, 4)
        return None
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in CONFIDENCE_LABELS:
        return CONFIDENCE_LABELS[text]
    match = re.search(r"(\d+(?:\.\d+)?)\s*%?", text)
    if not match:
        return None
    number = float(match.group(1))
    if text.endswith("%") or number > 1.0:
        number = number / 100.0
    if 0.0 <= number <= 1.0:
        return round(number, 4)
    return None


def coerce_drivers(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[\uff1b;\u3001,/|]", value)
        return [part.strip() for part in parts if part.strip()][:5]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()][:5]
    return []


def normalize_hotspots(payload: Mapping[str, Any], *, valid_refs: set[str]) -> list[Dict[str, Any]]:
    output: list[Dict[str, Any]] = []
    discards: list[dict[str, Any]] = []
    for item in payload.get("hotspots") or []:
        if not isinstance(item, Mapping):
            continue
        theme = str(item.get("theme") or "").strip()
        refs = {str(ref) for ref in (item.get("evidence_refs") or []) if str(ref)}
        confidence = coerce_confidence(item.get("confidence"))
        reason = None
        if not theme or theme in PLACEHOLDER_THEMES:
            reason = "missing_theme"
        elif confidence is None:
            reason = "confidence_unusable"
        elif len(refs) < 2:
            reason = "refs_lt_2"
        elif not refs.issubset(valid_refs):
            reason = "unknown_ref"
        if reason:
            discards.append({"theme": theme, "reason": reason, "evidence_refs": sorted(refs)})
            continue
        output.append({
            "theme": theme,
            "drivers": coerce_drivers(item.get("drivers")),
            "industries": [str(x) for x in item.get("industries") or []][:8],
            "direction": str(item.get("direction") or "mixed"),
            "confidence": confidence,
            "horizon": str(item.get("horizon") or "short"),
            "evidence_refs": sorted(refs),
            "status": "early_signal",
        })
        if len(output) >= 5:
            break
    if isinstance(payload, dict):
        payload["_discarded"] = discards
    return output


def analyze_hotspots(*, macro_news: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]], as_of: str, client: Optional[CodexCliClient] = None) -> Dict[str, Any]:
    candidate_rows = list(candidates)
    evidence = selected_evidence(macro_news, candidate_rows)
    valid_refs = {str(item.get("event_id") or f"macro-{index}") for index, item in enumerate(evidence)}
    if len(valid_refs) < 2:
        return {"status": "unavailable", "hotspots": [], "output_valid": False, "prompt_news": evidence, "valid_refs": sorted(valid_refs)}
    client = client or CodexCliClient(timeout_seconds=float(os.environ.get("AH_CODEX_HOTSPOT_TIMEOUT_SECONDS", "240")))
    prompt = build_hotspot_prompt(macro_news=macro_news, candidates=candidate_rows, as_of=as_of, evidence_items=evidence)
    result = client.analyze(prompt)
    payload = result.get("data") if result.get("status") == "used" else None
    hotspots = normalize_hotspots(payload or {}, valid_refs=valid_refs) if isinstance(payload, Mapping) else []
    evidence_by_id = {str(item.get("event_id") or f"macro-{index}"): item for index, item in enumerate(evidence)}
    for hotspot in hotspots:
        refs = list(hotspot.get("evidence_refs") or [])
        reprints = 0
        sources = set()
        for ref in refs:
            item = evidence_by_id.get(str(ref)) or {}
            reprints += int(item.get("reprint_count") or 1)
            source = str(item.get("source") or "").strip()
            if source:
                sources.add(source)
        hotspot["evidence_count"] = reprints or len(refs)
        hotspot["independent_source_count"] = len(sources) if sources else None
    result["hotspots"] = hotspots
    result["prompt_news"] = evidence
    result["valid_refs"] = sorted(valid_refs)
    if isinstance(payload, Mapping):
        result["discarded"] = list(payload.get("_discarded") or [])
    if not hotspots and result.get("status") == "used":
        result["status"] = "failed"
        result["error"] = "no_valid_hotspots"
    return result

