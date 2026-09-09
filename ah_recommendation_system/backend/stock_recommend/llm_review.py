"""LLM event review and second-pass candidate reranking.

The model is deliberately scoped to the event dimension.  All other factor
values and all hard risk gates remain deterministic.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate, DEFAULT_WEIGHTS
from ah_recommendation_system.backend.stock_recommend.codex_cli_client import CodexCliClient

MAX_EVENTS_PER_CANDIDATE = 5


def _review_events(candidate: Candidate) -> List[Dict[str, Any]]:
    return [
        item for item in candidate.evidence if item.get("factor") == "event"
    ][:MAX_EVENTS_PER_CANDIDATE]


def normalize_llm_reviews(payload: Mapping[str, Any], *, valid_event_ids: Set[str]) -> Dict[str, Dict[str, Any]]:
    reviews: Dict[str, Dict[str, Any]] = {}
    for raw in payload.get("reviews") or []:
        if not isinstance(raw, Mapping):
            continue
        code = str(raw.get("code") or "").strip().zfill(6)
        try:
            score = float(raw.get("overall_score"))
        except (TypeError, ValueError):
            continue
        if len(code) != 6 or not 0.0 <= score <= 1.0:
            continue
        refs = {str(item) for item in (raw.get("evidence_refs") or []) if str(item)}
        if refs and not refs.issubset(valid_event_ids):
            continue
        if not refs and valid_event_ids:
            continue
        item = dict(raw)
        item["code"] = code
        item["overall_score"] = score
        item["evidence_refs"] = sorted(refs)
        reviews[code] = item
    return reviews


def apply_llm_event_scores(
    candidates: Iterable[Candidate],
    reviews: Mapping[str, Mapping[str, Any]],
    *,
    weights: Optional[Mapping[str, float]] = None,
    llm_share: float = 0.3,
) -> List[Candidate]:
    """Blend rule/LLM event scores and rerank without changing other factors."""
    weights = weights or DEFAULT_WEIGHTS
    llm_share = max(0.0, min(0.5, float(llm_share)))
    rows = list(candidates)
    for candidate in rows:
        review = reviews.get(candidate.code)
        if not review or candidate.event_score_rule is None and candidate.event_score is None:
            continue
        try:
            llm_score = float(review.get("overall_score"))
        except (TypeError, ValueError):
            continue
        if not 0.0 <= llm_score <= 1.0:
            continue
        rule_score = candidate.event_score_rule if candidate.event_score_rule is not None else candidate.event_score
        if rule_score is None:
            continue
        candidate.event_score_rule = float(rule_score)
        candidate.event_score_llm = llm_score
        candidate.event_score = round((1.0 - llm_share) * float(rule_score) + llm_share * llm_score, 4)
        candidate.event_score_status = "available"
        candidate.factor_scores["event"] = candidate.event_score
        candidate.factor_scores["event_score_rule"] = candidate.event_score_rule
        candidate.factor_scores["event_score_llm"] = candidate.event_score_llm
        candidate.factor_scores["event_llm_share"] = llm_share
        candidate.llm_review = str(review.get("reason") or "")
        candidate.llm_catalysts = list(review.get("catalysts") or [])
        candidate.llm_risks = list(review.get("risks") or [])
        candidate.llm_evidence_refs = list(review.get("evidence_refs") or [])

        risk_penalty = float(candidate.factor_scores.get("risk") or 0.0)
        candidate.composite = round(
            weights.get("trend", 0.25) * float(candidate.factor_scores.get("trend") or 0.0)
            + weights.get("price_volume", 0.20) * float(candidate.factor_scores.get("price_volume") or 0.0)
            + weights.get("value_quality", 0.15) * float(candidate.factor_scores.get("value_quality") or 0.0)
            + weights.get("capital", 0.15) * float(candidate.factor_scores.get("capital") or 0.0)
            + weights.get("relative_strength", 0.15) * float(candidate.factor_scores.get("relative_strength") or 0.0)
            + weights.get("event", 0.10) * candidate.event_score
            + risk_penalty,
            4,
        )
    rows.sort(key=lambda item: (item.observation_only, -item.composite))
    return rows


def build_event_review_prompt(candidates: Iterable[Candidate], *, as_of: str) -> str:
    rows = []
    valid_event_ids: List[str] = []
    for candidate in candidates:
        events = _review_events(candidate)
        if not events:
            continue
        for event in events:
            valid_event_ids.append(str(event.get("event_id") or ""))
        rows.append({
            "code": candidate.code,
            "name": candidate.name,
            "event_score_rule": candidate.event_score_rule,
            "events": events,
            "factor_scores": {key: value for key, value in candidate.factor_scores.items() if key != "risk"},
        })
    return (
        "你是消息面复核分析师。只分析输入中已有的事件，不得联网、编造新闻、日期、来源或股票代码。"
        "只输出JSON。overall_score必须是0到1；没有有效事件时不要输出该股票。"
        "重大负面风险不得被正面叙述抵消。字段：reviews=[{code,overall_score,confidence,reason,catalysts,risks,evidence_refs}]。\n"
        f"分析日期：{as_of}\n事件ID白名单：{json.dumps(sorted(set(valid_event_ids)), ensure_ascii=False)}\n"
        f"候选事件：{json.dumps(rows, ensure_ascii=False)}"
    )


def review_candidate_events(candidates: List[Candidate], *, as_of: str, client: Optional[CodexCliClient] = None) -> Dict[str, Any]:
    """Review only the supplied ranked candidates; never scans the market."""
    submitted_codes = {
        candidate.code
        for candidate in candidates
        if any(
            event.get("event_id")
            for event in _review_events(candidate)
        )
    }
    event_ids = {
        str(event.get("event_id"))
        for candidate in candidates
        for event in _review_events(candidate)
        if event.get("event_id")
    }
    if not event_ids:
        return {
            "status": "no_relevant_news",
            "reviews": {},
            "output_valid": False,
            "input_candidate_count": len(candidates),
            "submitted_count": 0,
            "reviewed_count": 0,
        }
    client = client or CodexCliClient()
    result = client.analyze(build_event_review_prompt(candidates, as_of=as_of))
    payload = result.get("data") if result.get("status") == "used" else None
    reviews = normalize_llm_reviews(payload or {}, valid_event_ids=event_ids) if isinstance(payload, Mapping) else {}
    if result.get("status") == "used" and not reviews:
        result = dict(result)
        result["status"] = "failed"
        result["error"] = "no_valid_event_reviews"
    result["reviews"] = reviews
    result["input_candidate_count"] = len(candidates)
    result["submitted_count"] = len(submitted_codes)
    result["reviewed_count"] = len(reviews)
    return result
