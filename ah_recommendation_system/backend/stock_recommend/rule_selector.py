"""Free, deterministic final selection for the daily candidate pool."""
from __future__ import annotations

from datetime import datetime
from collections import Counter
from typing import Any, Dict, List

from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate


MIN_REWARD_RISK = 1.5
FILL_CONSTRAINT = "开盘确认前不得成交"


def _price_plan(candidate: Candidate) -> Dict[str, Any]:
    price = candidate.price
    if (
        not price
        or candidate.support is None
        or candidate.resistance is None
        or candidate.support > price
        or candidate.resistance <= price
    ):
        return {
            "buy_zone": "等待支撑位确认",
            "stop_loss": "等待风险边界确认",
            "target": "等待压力位确认",
            "reward_risk": None,
            "entry_price": None,
        }
    support = float(candidate.support)
    entry = float(price)
    stop = support - float(candidate.atr or price * 0.05) * 1.25
    target = float(candidate.resistance)
    risk = entry - stop
    reward_risk = round((target - entry) / risk, 4) if risk > 0 else None
    return {
        "buy_zone": f"{support:.2f}-{entry:.2f}",
        "stop_loss": f"{max(0.01, stop):.2f}",
        "target": f"{target:.2f}",
        "reward_risk": reward_risk,
        "entry_price": entry,
    }


def _position_plan(market_regime: Dict[str, Any] | None) -> Dict[str, Any]:
    defensive = bool(market_regime and market_regime.get("regime") == "defense" and market_regime.get("status") == "available")
    if defensive:
        low, high, cap = 0.05, 0.08, 0.30
    else:
        low, high, cap = 0.05, 0.10, 0.80
    return {
        "position_pct_min": low,
        "position_pct_max": high,
        "account_cap_pct": cap,
        "position_text": f"单票{low:.0%}-{high:.0%}，账户总仓≤{cap:.0%}".replace(".0%", "%"),
    }


EMPTY_REASON_TEXT = {
    "data_insufficient": "今日无正式个股推荐：数据覆盖或关键证据不足，无法完成有效筛选。",
    "awaiting_confirmation": "今日无正式个股推荐：候选已有线索，但仍待价格、成交或热点催化确认。",
    "screened_out": "今日无正式个股推荐：数据覆盖和候选评估充分，但没有候选通过正式门槛。",
}


def _has_p0(candidate: Candidate) -> bool:
    if any(str(reason).lower().startswith("p0") for reason in candidate.rejection_reasons):
        return True
    texts = [
        str(item.get(key) or "")
        for item in (candidate.evidence or [])
        if isinstance(item, dict)
        for key in ("statement", "claim", "title")
    ]
    texts.extend(str(item) for item in (getattr(candidate, "llm_risks", []) or []))
    return any(
        term in " ".join(texts)
        for term in ("立案", "退市", "财务造假", "重大处罚", "重大诉讼", "暂停上市", "重大违约", "业绩暴雷")
    )


def _negative_trend(candidate: Candidate) -> bool:
    score = candidate.factor_scores.get("trend") if candidate.factor_scores else None
    if score is not None and float(score) < 0:
        return True
    if candidate.change_60d_pct is not None and float(candidate.change_60d_pct) < 0:
        return True
    if candidate.return_20d_pct is not None and float(candidate.return_20d_pct) < 0:
        return True
    if (
        candidate.drawdown_from_60d_high_pct is not None
        and float(candidate.drawdown_from_60d_high_pct) <= -8
    ):
        return True
    for evidence in candidate.evidence or []:
        if str(evidence.get("factor") or "") != "trend":
            continue
        if evidence.get("supports") is False:
            return True
        value = evidence.get("value")
        try:
            if float(value) < 0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _negative_catalyst(candidate: Candidate) -> bool:
    negative_terms = (
        "利空", "负面", "减持", "诉讼", "暴雷", "处罚", "调查", "违约",
        "业绩预警", "亏损扩大", "业绩下滑", "低于预期",
    )
    if any(
        any(word in str(risk) for word in negative_terms)
        for risk in (getattr(candidate, "llm_risks", []) or [])
    ):
        return True
    for evidence in candidate.evidence or []:
        if str(evidence.get("factor") or "") != "event":
            continue
        if evidence.get("supports") is False:
            return True
        text = f"{evidence.get('statement') or ''} {evidence.get('claim') or ''}"
        if any(word in text for word in negative_terms):
            return True
    return False


def _current_hotspot_evidence(candidate: Candidate) -> bool:
    if not getattr(candidate, "hotspot_mapping_verified", False):
        return False
    if not getattr(candidate, "hotspot_themes", None) or not getattr(candidate, "hotspot_evidence", None):
        return False
    return any(
        str(match.get("status") or "").lower() in {"market_confirmed", "confirmed"}
        and str(match.get("direction") or "").lower() in {"positive", "bullish", "support", "利好", "看多", "正面"}
        and bool(match.get("evidence_refs"))
        and (
            str(match.get("status") or "").lower() == "confirmed"
            or match.get("price_volume_confirmed") is True
            or int(match.get("independent_source_count") or 0) >= 2
        )
        for match in (getattr(candidate, "hotspot_matches", []) or [])
    )


def _dated_price_evidence(candidate: Candidate) -> bool:
    if not candidate.price or not getattr(candidate, "price_as_of", None):
        return False
    return any(
        str(item.get("factor") or "") in {"trend", "price_volume"}
        and item.get("value") is not None
        and _known_date(item.get("as_of"))
        for item in (candidate.evidence or [])
    )


def _known_date(value: Any) -> bool:
    text = str(value or "").strip()[:10]
    if len(text) != 10:
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return True


def _positive_catalyst_evidence(candidate: Candidate) -> bool:
    for item in candidate.evidence or []:
        if str(item.get("factor") or "") != "event" or item.get("supports", True) is False:
            continue
        if not str(item.get("statement") or item.get("claim") or item.get("title") or "").strip():
            continue
        if _known_date(item.get("as_of")):
            return True
    return False


def _observation_item(candidate: Candidate, *, reason: str) -> Dict[str, Any]:
    pending: list[str] = []
    if not _dated_price_evidence(candidate):
        pending.append("缺少带日期的价格或量价证据")
    if not _current_hotspot_evidence(candidate):
        pending.append("缺少本次可核验热点映射或催化引用")
    if not any(str(item.get("factor") or "") == "event" and item.get("supports", True) for item in candidate.evidence or []):
        pending.append("个股催化尚未完成独立核验")
    trigger = "开盘后确认价格站稳前收并出现成交量/成交额扩张后再评估"
    invalidation = "收盘跌破观察边界，或热点催化转为负向/失效"
    return {
        "code": candidate.code,
        "name": candidate.name,
        "evidence": list(candidate.evidence or []),
        "rejection_reasons": list(candidate.rejection_reasons or [reason]),
        "hotspot_themes": list(getattr(candidate, "hotspot_themes", []) or []),
        "hotspot_match_level": getattr(candidate, "hotspot_match_level", "none") or "none",
        "hotspot_evidence": list(getattr(candidate, "hotspot_evidence", []) or []),
        "candidate_sources": list(candidate.candidate_sources or []),
        "price_as_of": getattr(candidate, "price_as_of", None),
        "inclusion_reason": reason,
        "pending_confirmation": "；".join(pending) if pending else "等待开盘后量价确认",
        "trigger": trigger,
        "invalidation": invalidation,
    }


def _empty_reason(*, candidates: List[Candidate], eligible_count: int, evaluated_count: int, coverage_mode: str, picks: List[Dict[str, Any]], market_regime: Dict[str, Any] | None = None) -> str:
    if not candidates or evaluated_count == 0 or coverage_mode in {"limited_sample", "focused_fallback", "unavailable"}:
        return "data_insufficient"
    if market_regime and market_regime.get("status") != "available":
        return "data_insufficient"
    if not picks and any(_current_hotspot_evidence(candidate) for candidate in candidates):
        return "awaiting_confirmation"
    if eligible_count and not picks:
        return "awaiting_confirmation"
    return "screened_out"


def select_by_rules(
    candidates: List[Candidate],
    *,
    top_n_pick: int = 3,
    minimum_score: float = 0.55,
    coverage_mode: str = "full_market",
    market_regime: Dict[str, Any] | None = None,
    ranking_key: str = "composite",
) -> Dict[str, Any]:
    picks: List[Dict[str, Any]] = []
    eligible = []
    evaluated_count = 0
    defensive = bool(market_regime and market_regime.get("regime") == "defense" and market_regime.get("status") == "available")
    if defensive:
        top_n_pick = min(top_n_pick, 2)
    for candidate in candidates:
        evaluated_count += 1
        if market_regime and market_regime.get("status") != "available":
            candidate.rejection_reasons.append("market:基准状态未知，仅观察")
            continue
        if defensive:
            supported = {str(e.get("factor")) for e in candidate.evidence if e.get("supports") is True}
            if (not {"trend", "relative_strength"}.issubset(supported)
                    or not ({"capital", "event", "quality"} & supported)
                    or float(candidate.factor_scores.get("relative_strength") or 0) <= .5
                    or float(candidate.factor_scores.get("trend") or 0) < .6):
                candidate.rejection_reasons.append("market:防守期缺少逆势强度及独立确认")
                continue
        if candidate.observation_only:
            continue
        if _has_p0(candidate):
            if not any(str(reason).lower().startswith("p0") for reason in candidate.rejection_reasons):
                candidate.rejection_reasons.append("p0:重大负面风险否决")
            continue
        if _negative_catalyst(candidate):
            candidate.rejection_reasons.append("risk:负向催化，不进入正式推荐")
            continue
        if any(str((item or {}).get("source") or "") == "capital_unavailable" for item in (candidate.evidence or [])):
            candidate.rejection_reasons.append("capital:missing_flow_cannot_formal_pick")
            continue
        structured_factors = {
            str(e.get("factor")) for e in candidate.evidence if e.get("factor")
        }
        supported_factors = {
            str(e.get("factor"))
            for e in candidate.evidence
            if e.get("factor") and e.get("supports", True)
        }
        dimensions = (
            set(candidate.valid_dimensions) & supported_factors
            if structured_factors
            else set(candidate.valid_dimensions)
        )
        if len(dimensions) < 3 or not ({"trend", "price_volume"} & dimensions):
            if not any(reason.startswith("evidence") for reason in candidate.rejection_reasons):
                candidate.rejection_reasons.append("evidence:至少需要3个维度且包含趋势或量价")
            continue
        if candidate.quality_grade not in {"A", "B"}:
            candidate.rejection_reasons.append("quality:正式推荐要求质量A或B")
            continue
        model_score = getattr(candidate, "model_score", None)
        if ranking_key == "model_score" and model_score is not None:
            ranking_score = model_score
            if ranking_score < minimum_score:
                candidate.rejection_reasons.append(f"score:模型分低于{minimum_score:.4f}")
                continue
        else:
            ranking_score = candidate.composite
            if candidate.composite < minimum_score:
                candidate.rejection_reasons.append(f"score:综合分低于{minimum_score:.2f}")
                continue
        if coverage_mode in {"focused_fallback", "limited_sample"}:
            # A narrow universe cannot support a formal pick on technical and
            # valuation factors alone. Require an independent event or
            # capital confirmation; otherwise retain it only for observation.
            confirmed = {"event", "capital"} & dimensions
            if not confirmed:
                candidate.rejection_reasons.append("coverage:有限样本缺少消息或资金确认")
                continue
        if any(reason.startswith("p0") or reason.startswith("stale") or reason.startswith("quality:历史") for reason in candidate.rejection_reasons):
            continue
        eligible.append(candidate)
    def _base_ranking_score(candidate: Candidate) -> float:
        if ranking_key == "model_score" and getattr(candidate, "model_score", None) is not None:
            return float(candidate.model_score)
        return float(candidate.composite)

    def _ranking_bonus(candidate: Candidate) -> float:
        # Hotspots affect ordering only, capped at 0.015 (1.5 score points).
        return min(0.015, max(0.0, float(getattr(candidate, "hotspot_score", 0.0) or 0.0) * 0.10))

    eligible.sort(key=lambda item: (item.observation_only, -(_base_ranking_score(item) + _ranking_bonus(item))))
    selected_industries: set[str] = set()
    for candidate in eligible:
        if len(picks) >= max(0, top_n_pick):
            break
        industries = set(candidate.focus_industries)
        if industries and industries & selected_industries:
            candidate.rejection_reasons.append("concentration:同一行业已有更高排名标的")
            continue
        plan = _price_plan(candidate)
        reasons = [e.get("statement") for e in candidate.evidence if e.get("statement") and e.get("supports", True)]
        if not reasons:
            continue
        reward_risk = plan.get("reward_risk")
        if reward_risk is not None and float(reward_risk) < MIN_REWARD_RISK:
            candidate.rejection_reasons.append(
                f"reward_risk:盈亏比{reward_risk}低于{MIN_REWARD_RISK:.1f}，空间不足不得条件买入"
            )
            continue
        position = _position_plan(market_regime)
        picks.append(
            {
                "code": candidate.code,
                "name": candidate.name,
                "reference_price": candidate.price,
                "reference_date": getattr(candidate, "price_as_of", None),
                "reference_source": "candidate_snapshot",
                "action": "CONDITIONAL_BUY",
                "execution_status": "awaiting_open_confirmation",
                "fill_constraint": FILL_CONSTRAINT,
                "confidence": round(0.45 + candidate.composite * 0.4, 2),
                **plan,
                **position,
                "holding_days": "5-20个交易日",
                "rationale": "；".join(reasons[:5]),
                "trigger": "板块不转弱且价格站稳前一交易日收盘，成交额不低于20日均值",
                "invalidation": "收盘跌破观察止损位，或板块与个股相对强度同时转弱",
                "key_risks": ["高开追涨风险", "免费数据源缺口或延迟"],
                "factors": {
                    "fundamental_score": candidate.fundamental_score,
                    "capital_score": candidate.capital_score,
                    "event_score": candidate.event_score,
                    "composite": candidate.composite,
                    **candidate.factor_scores,
                },
                "llm_review": getattr(candidate, "llm_review", ""),
                "llm_catalysts": list(getattr(candidate, "llm_catalysts", []) or []),
                "llm_risks": list(getattr(candidate, "llm_risks", []) or []),
                "hotspot_themes": list(getattr(candidate, "hotspot_themes", []) or []),
                "hotspot_score": round(float(getattr(candidate, "hotspot_score", 0.0) or 0.0), 4),
                "hotspot_evidence": list(getattr(candidate, "hotspot_evidence", []) or []),
                "hotspot_industries": list(getattr(candidate, "hotspot_industries", []) or []),
                "hotspot_match_level": getattr(candidate, "hotspot_match_level", "none") or "none",
                "hotspot_mapping_sources": list(getattr(candidate, "hotspot_mapping_sources", []) or []),
                "focus_industries": list(candidate.focus_industries),
                "score": round(candidate.composite * 100, 2),
                "ranking_score": round(_base_ranking_score(candidate) + _ranking_bonus(candidate), 4),
                "hotspot_bonus": round(_ranking_bonus(candidate), 4),
                "quality_grade": candidate.quality_grade,
                "quality_evidence": candidate.quality_evidence,
                "factor_scores": candidate.factor_scores,
                "evidence": candidate.evidence,
                "risk_flags": candidate.rejection_reasons,
            }
        )
        selected_industries.update(industries)
    selected_codes = {str(pick.get("code") or "").zfill(6) for pick in picks}
    # Observation is a separately verified lane. It never consumes the formal
    # pool's first N rows and never promotes a candidate rejected by P0/trend/
    # catalyst evidence.
    observation_pool: list[Dict[str, Any]] = []
    seen_observations: set[str] = set()
    observation_candidates = sorted(
        candidates,
        key=lambda item: -(_base_ranking_score(item) + _ranking_bonus(item)),
    )
    for candidate in observation_candidates:
        code = str(candidate.code).zfill(6)
        if code in selected_codes or code in seen_observations:
            continue
        if len(observation_pool) >= 6:
            break
        if _has_p0(candidate) or _negative_trend(candidate) or _negative_catalyst(candidate):
            continue
        if (
            not _current_hotspot_evidence(candidate)
            or not _dated_price_evidence(candidate)
            or not _positive_catalyst_evidence(candidate)
        ):
            continue
        reason_parts = ["本次行情存在带日期趋势/量价证据", "已匹配本次热点并有催化引用"]
        if candidate.rejection_reasons:
            reason_parts.append("未满足正式推荐的完整门槛，保留为条件观察")
        observation_pool.append(_observation_item(candidate, reason="；".join(reason_parts)))
        seen_observations.add(code)

    empty_reason_code = _empty_reason(
        candidates=list(candidates),
        eligible_count=len(eligible),
        evaluated_count=evaluated_count,
        coverage_mode=coverage_mode,
        picks=picks,
        market_regime=market_regime,
    )
    rejection_summary: Counter[str] = Counter()
    for candidate in candidates:
        for reason in candidate.rejection_reasons or []:
            rejection_summary[str(reason).split(":", 1)[0]] += 1
    mapping_gaps = sorted({
        "热点映射或催化引用缺失"
        for candidate in candidates
        if not _current_hotspot_evidence(candidate)
    })
    scan_as_of = None
    price_as_of = next((candidate.price_as_of for candidate in candidates if candidate.price_as_of), None)
    evaluated_known = bool(candidates) or evaluated_count == 0
    selection_diagnostics = {
        "scan_as_of": scan_as_of,
        "price_as_of": price_as_of,
        "coverage_mode": coverage_mode,
        "scanned_count": None,
        "candidate_count": len(candidates) if evaluated_known else None,
        "evaluated_count": evaluated_count if evaluated_known else None,
        "eligible_count": len(eligible) if evaluated_known else None,
        "selected_count": len(picks) if evaluated_known else None,
        "observation_count": len(observation_pool) if bool(observation_pool) else None,
        "mapping_gaps": mapping_gaps,
        "rejection_summary": dict(rejection_summary),
    }
    return {
        "summary": "仅保留具备可追溯趋势/量价及至少三类独立证据的候选；证据不足时不生成个股推荐。",
        "market_view": ("基准处于防守状态，仅精选最多2只逆势强势股作条件观察；等待触发确认，控制试错风险。" if defensive
                        else "基准状态未知，等待数据确认。" if market_regime and market_regime.get("status") != "available"
                        else "保持均衡观察；只有触发条件确认后才进入观察或试错。"),
        "falsification": ["沪深300跌破阶段低点", "市场成交额显著萎缩且涨跌家数恶化"],
        "picks": picks,
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "observation_pool": observation_pool,
        "observation_pool_verified": bool(observation_pool),
        "empty_reason_code": empty_reason_code if not picks else None,
        "empty_reason": EMPTY_REASON_TEXT[empty_reason_code] if not picks else None,
        "selection_diagnostics": selection_diagnostics,
        "llm_used": False,
        "llm_mock": False,
        "coverage_mode": coverage_mode,
        "market_regime": market_regime or {"regime": "unknown", "status": "unavailable"},
    }

def finalize_picks_against_hotspots(
    selection: Dict[str, Any],
    *,
    hotspots: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Keep formal picks only when they map onto current themes."""
    result = dict(selection or {})
    picks = list(result.get("picks") or [])
    themes = [
        str(item.get("theme") or "").strip()
        for item in (hotspots or [])
        if str(item.get("theme") or "").strip() and str(item.get("status") or "") != "discarded"
    ]
    # Hotspots are a post-gate ordering signal, never an additional formal
    # eligibility gate.  Keep this compatibility hook so callers can still
    # attach mapping diagnostics without deleting an otherwise valid pick.
    if themes:
        unrelated = [
            {"code": item.get("code"), "name": item.get("name")}
            for item in picks
            if not str(item.get("hotspot_match_level") or "")
            or not list(item.get("hotspot_themes") or [])
        ]
        if unrelated:
            result["unrelated_leaders"] = unrelated
    return result
