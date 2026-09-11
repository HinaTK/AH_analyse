"""LLM-based stock selector.

Takes candidate pool (top 20-30) + macro news context, asks LLM to pick
top 3-5 with rationale, buy zone, stop loss, target, risks.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from ah_recommendation_system.backend.stock_recommend.candidate_pool import (
    Candidate,
    to_dict_list,
)
from ah_recommendation_system.backend.stock_recommend.llm_client import (
    LLMClient,
    get_llm_client,
)


SYSTEM_PROMPT = (
    "你是一名 A 股量化研究员。请基于提供的候选池和宏观/新闻上下文，"
    "挑选 3-5 只**短线关注股**（1~2 周视角），并给出每只的结构化建议：\n"
    "- code: 6 位代码\n"
    "- name: 中文简称\n"
    "- action: BUY / WATCH\n"
    "- confidence: 0~1 浮点\n"
    "- buy_zone: 建议买入价区间（字符串，例 '10.00-10.20'）\n"
    "- stop_loss: 止损价（字符串，例 '9.40'）\n"
    "- target: 目标价（字符串，例 '11.50'）\n"
    "- holding_days: 建议持有天数（字符串）\n"
    "- rationale: 一句话选股理由（≤ 80 字）\n"
    "- key_risks: 2-3 个核心风险点（数组）\n"
    "- factors: { fundamental_score, capital_score, event_score } 直接采用输入分数\n\n"
    "请同时输出：\n"
    "- summary: 当日盘前一句话总结（≤ 60 字）\n"
    "- market_view: 当日大盘看法（≤ 80 字）\n"
    "- falsification: 1-2 条整体证伪/降级信号（数组）\n\n"
    "严格只输出 JSON，字段名使用英文，不要解释。"
)


def _user_prompt(
    candidates: List[Candidate],
    *,
    macro_context: Optional[Dict[str, Any]] = None,
    top_n_pick: int = 5,
    as_of: Optional[str] = None,
) -> str:
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    rows = to_dict_list(candidates)

    macro_lines: List[str] = []
    if macro_context:
        for it in (macro_context.get("items") or [])[:8]:
            title = str(it.get("title") or "").strip()
            if title:
                macro_lines.append(f"- {title}")
    macro_text = "\n".join(macro_lines) if macro_lines else "（无可用宏观新闻）"

    cand_table = json.dumps(rows, ensure_ascii=False, indent=2)
    return (
        f"## 候选池（{as_of}，已按 composite 排序）\n"
        f"```json\n{cand_table}\n```\n\n"
        f"## 近期宏观/政策新闻\n{macro_text}\n\n"
        f"## 任务\n从候选池中选 {top_n_pick} 只最值得短线关注的 A 股，"
        f"严格按 schema 输出 JSON。"
    )


def select_with_llm(
    candidates: List[Candidate],
    *,
    macro_context: Optional[Dict[str, Any]] = None,
    top_n_pick: int = 5,
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """Run LLM-based selection. Returns structured dict (see SYSTEM_PROMPT schema)."""
    llm = llm or get_llm_client()
    user = _user_prompt(
        candidates,
        macro_context=macro_context,
        top_n_pick=top_n_pick,
    )
    if not candidates:
        return {
            "summary": "候选池为空，未给出推荐。",
            "picks": [],
            "market_view": "—",
            "falsification": [],
            "as_of": datetime.now().strftime("%Y-%m-%d"),
            "llm_mock": llm.is_mock,
        }

    result = llm.chat_json(system=SYSTEM_PROMPT, user=user)

    # Normalize output
    picks = result.get("picks") or []
    if not isinstance(picks, list):
        picks = []

    # Filter & enrich each pick with candidate scores if available
    cand_map = {c.code: c for c in candidates}
    normalized: List[Dict[str, Any]] = []
    for p in picks[:top_n_pick]:
        if not isinstance(p, dict):
            continue
        code = str(p.get("code") or "").strip().zfill(6)
        if not code or len(code) != 6:
            continue
        c = cand_map.get(code)
        if c:
            p.setdefault("name", c.name)
            p["factors"] = {
                "fundamental_score": c.fundamental_score,
                "capital_score": c.capital_score,
                "event_score": c.event_score,
                "composite": c.composite,
            }
        normalized.append(p)

    return {
        "summary": result.get("summary") or "",
        "picks": normalized,
        "market_view": result.get("market_view") or "",
        "falsification": result.get("falsification") or [],
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "llm_mock": llm.is_mock,
        "candidate_count": len(candidates),
    }
