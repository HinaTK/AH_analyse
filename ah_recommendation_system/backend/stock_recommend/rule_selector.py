"""Free, deterministic final selection for the daily candidate pool."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate


def _price_plan(candidate: Candidate) -> Dict[str, str]:
    price = candidate.price
    if (
        not price
        or candidate.support is None
        or candidate.resistance is None
        or candidate.support > price
        or candidate.resistance <= price
    ):
        return {"buy_zone": "等待支撑位确认", "stop_loss": "等待风险边界确认", "target": "等待压力位确认"}
    support = float(candidate.support)
    stop = support - float(candidate.atr or price * 0.05) * 1.25
    return {
        "buy_zone": f"{support:.2f}-{float(price):.2f}",
        "stop_loss": f"{max(0.01, stop):.2f}",
        "target": f"{float(candidate.resistance):.2f}",
    }


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
    defensive = bool(market_regime and market_regime.get("regime") == "defense" and market_regime.get("status") == "available")
    if defensive:
        top_n_pick = min(top_n_pick, 2)
    for candidate in candidates:
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
        picks.append(
            {
                "code": candidate.code,
                "name": candidate.name,
                "reference_price": candidate.price,
                "reference_date": getattr(candidate, "price_as_of", None),
                "reference_source": "candidate_snapshot",
                "action": "WATCH",
                "confidence": round(0.45 + candidate.composite * 0.4, 2),
                **plan,
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
                "focus_industries": list(candidate.focus_industries),
                "score": round(candidate.composite * 100, 2),
                "quality_grade": candidate.quality_grade,
                "quality_evidence": candidate.quality_evidence,
                "factor_scores": candidate.factor_scores,
                "evidence": candidate.evidence,
                "risk_flags": candidate.rejection_reasons,
            }
        )
        selected_industries.update(industries)
    selected_codes = {pick["code"] for pick in picks}
    observation_candidates = [candidate for candidate in candidates if candidate.code not in selected_codes][:6]
    role_labels = ("龙头", "弹性", "中军", "验证", "防御", "避雷")
    observation_pool = [
        {
            "code": candidate.code,
            "name": candidate.name,
            "role": role_labels[index] if index < len(role_labels) else "观察",
            "score": round(candidate.composite * 100, 2),
            "quality_grade": candidate.quality_grade,
            "evidence": candidate.evidence,
            "rejection_reasons": candidate.rejection_reasons or ["ranking:未进入当日前三"],
            "candidate_sources": candidate.candidate_sources,
            "focus_industries": candidate.focus_industries,
        }
        for index, candidate in enumerate(observation_candidates)
    ]
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
        "llm_used": False,
        "llm_mock": False,
        "coverage_mode": coverage_mode,
        "market_regime": market_regime or {"regime": "unknown", "status": "unavailable"},
    }
