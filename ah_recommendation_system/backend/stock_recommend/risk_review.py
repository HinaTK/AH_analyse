"""Deterministic candidate risk review inspired by the daily-stock-analysis risk layer."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .candidate_pool import Candidate

P0_TERMS = ("立案", "退市", "财务造假", "重大处罚", "重大诉讼", "暂停上市")
RISK_TERMS = ("减持", "亏损", "业绩预警", "监管", "商誉减值", "债务违约")
SEVERE_TERMS = ("净利润同比下降", "净利润下降", "业绩大幅下滑", "业绩同比下降", "亏损扩大", "重大不确定性")


def review_candidate_risks(candidates: Iterable[Candidate]) -> Dict[str, Any]:
    """Attach auditable risk flags; never upgrades a candidate or changes scores."""
    reviewed = 0
    p0_count = 0
    for candidate in candidates:
        texts = [str(item.get("statement") or "") for item in candidate.evidence if isinstance(item, dict)]
        texts.extend(str(item) for item in (candidate.llm_risks or []))
        joined = "；".join(texts)
        p0 = [term for term in P0_TERMS if term in joined]
        risks = [term for term in RISK_TERMS if term in joined]
        severe = [term for term in SEVERE_TERMS if term in joined]
        if p0:
            candidate.rejection_reasons.append("p0:风险复核发现" + "、".join(p0))
            candidate.llm_risks = sorted(set(candidate.llm_risks or []) | {"；".join(p0)})
            p0_count += 1
        elif risks:
            candidate.llm_risks = sorted(set(candidate.llm_risks or []) | {"；".join(risks)})
        if severe:
            # A severe negative fundamental signal may only downgrade a
            # candidate; it must never be offset by a high technical score.
            candidate.observation_only = True
            candidate.rejection_reasons.append("risk:重大负面基本面，降级观察")
            candidate.llm_risks = sorted(set(candidate.llm_risks or []) | {"；".join(severe)})
        reviewed += 1
    return {"status": "used", "reviewed_count": reviewed, "p0_count": p0_count}
