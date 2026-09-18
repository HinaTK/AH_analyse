"""Report builder for daily stock recommendations.

Produces a structured dict (stored as JSON) and a human-readable Markdown report.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from loguru import logger

from ah_recommendation_system.backend.stock_recommend.market_hotspots import build_market_hotspots, summarize_hotspot_mapping
from ah_recommendation_system.backend.stock_recommend.decision_engine import build_market_decision
from ah_recommendation_system.backend.stock_recommend.cross_market import build_cross_market_conclusion
from ah_recommendation_system.backend.stock_recommend.quality_gate import evaluate_report_quality


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _format_factor_line(pick: Dict[str, Any]) -> str:
    factors = dict(pick.get("factor_scores") or {})
    factors.update(pick.get("factors") or {})
    labels = (
        ("trend", "趋势"),
        ("price_volume", "量价"),
        ("value_quality", "估值质量"),
        ("capital", "资金"),
        ("relative_strength", "相对强度"),
        ("event", "消息催化"),
    )

    def score(key: str) -> str:
        try:
            return f"{float(factors.get(key)) * 100:.0f}"
        except (TypeError, ValueError):
            return "-"

    try:
        composite = f"{float(factors.get('composite')) * 100:.1f}/100"
    except (TypeError, ValueError):
        composite = "-"
    return "综合评分 " + composite + "｜" + "｜".join(
        f"{label} {score(key)}" for key, label in labels
    )


def _format_etf_factor_line(etf: Dict[str, Any]) -> str:
    factors = dict(etf.get("factor_scores") or {})
    labels = (
        ("trend", "趋势"),
        ("relative_strength", "相对强度"),
        ("liquidity", "流动性"),
        ("risk_control", "风险控制"),
        ("theme_match", "主题匹配"),
    )

    def score(key: str) -> str:
        try:
            return f"{float(factors.get(key)):.0f}"
        except (TypeError, ValueError):
            return "-"

    try:
        total = f"{float(etf.get('score', etf.get('composite_score'))):.1f}"
    except (TypeError, ValueError):
        total = "-"
    return f"{etf.get('position', '观察')}｜综合 {total}｜" + "｜".join(
        f"{label} {score(key)}" for key, label in labels
    )


def _format_pick_md(p: Dict[str, Any], idx: int) -> str:
    factors = p.get("factors") or {}
    lines: List[str] = []
    lines.append(f"### {idx}. {p.get('name', '?')} ({p.get('code', '?')})")
    lines.append("")
    lines.append(f"- **建议动作**: `{p.get('action', 'WATCH')}`  信心度: `{p.get('confidence', 0)}`")
    buy = p.get("buy_zone") or "—"
    sl = p.get("stop_loss") or "—"
    tgt = p.get("target") or "—"
    hd = p.get("holding_days") or "—"
    lines.append(f"- **买入区间**: {buy}    **止损**: {sl}    **目标**: {tgt}    **持有**: {hd}")
    rat = p.get("rationale") or "（无说明）"
    lines.append(f"- **选股理由**: {rat}")
    llm_review = str(p.get("llm_review") or "").strip()
    if llm_review:
        lines.append(f"- **AI消息复核**: {llm_review}")
    evidence = p.get("evidence") or []
    if evidence:
        lines.append("- **可追溯证据**:")
        for item in evidence[:5]:
            lines.append(
                f"  - {item.get('statement', '')}（{item.get('as_of', '-')}, {item.get('source', '-')})"
            )
    risks = p.get("key_risks") or []
    if risks:
        lines.append("- **核心风险**:")
        for r in risks:
            lines.append(f"  - {r}")
    if factors:
        comp = factors.get("composite")
        if comp is not None:
            lines.append(
                f"- **评分**: {_format_factor_line(p)}"
            )
    lines.append("")
    return "\n".join(lines)


_EMPTY_REASON_TEXT = {
    "data_insufficient": "今日无正式个股推荐：数据不足，未完成有效筛选。",
    "awaiting_confirmation": "今日无正式个股推荐：候选仍待价格、成交或证据确认。",
    "screened_out": "今日无正式个股推荐：数据覆盖与评估充分，但没有候选通过正式门槛。",
}


def _presentation_failed(report: Mapping[str, Any]) -> bool:
    return (report.get("data_status") == "failed"
            or (report.get("run") or {}).get("status") == "failed"
            or (report.get("quality_gate") or {}).get("passed") is False)


def _screening_complete(report: Mapping[str, Any]) -> bool:
    diagnostics = report.get("selection_diagnostics") or {}
    coverage = report.get("coverage") or {}
    try:
        scanned = int(diagnostics.get("scanned_count"))
        universe = int(coverage.get("universe_size"))
        seeds = int(diagnostics.get("candidate_count"))
        evaluated = int(diagnostics.get("evaluated_count"))
        eligible = int(diagnostics.get("eligible_count"))
    except (TypeError, ValueError):
        return False
    gaps_known = "mapping_gaps" in diagnostics
    rejections_known = "rejection_summary" in diagnostics
    return (diagnostics.get("coverage_mode") == "full_market"
            and universe > 0 and scanned / universe >= 0.8
            and seeds > 0 and evaluated >= seeds and eligible == 0
            and coverage.get("fresh_data_available") is True
            and not coverage.get("stale") and report.get("data_status") == "ok"
            and not report.get("blocking_sections") and gaps_known
            and not diagnostics.get("mapping_gaps") and rejections_known)


def empty_stock_message(report: Mapping[str, Any]) -> str:
    """Explain an empty formal list without treating missing coverage as a clean screen."""
    if _presentation_failed(report):
        return _EMPTY_REASON_TEXT["data_insufficient"]
    requested_code = report.get("empty_reason_code")
    code = requested_code
    if code == "screened_out" and not _screening_complete(report):
        code = "data_insufficient"
    if code not in _EMPTY_REASON_TEXT:
        if report.get("data_status") == "degraded":
            code = "data_insufficient"
        elif presentation_observations(report):
            code = "awaiting_confirmation"
        elif _screening_complete(report):
            code = "screened_out"
        else:
            code = "data_insufficient"
    supplied = str(report.get("empty_reason") or "").strip()
    if supplied and code == requested_code:
        canonical = _EMPTY_REASON_TEXT[code]
        return supplied if supplied == canonical else f"{canonical} 补充：{supplied}"
    return _EMPTY_REASON_TEXT[code]


def _code_key(value: Any) -> str:
    code = str(value or "").strip().upper()
    return code.zfill(6) if code.isdigit() and len(code) <= 6 else code


def presentation_observations(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Only a producer-verified, distinct list can appear as watch names."""
    if report.get("observation_pool_verified") is not True or _presentation_failed(report):
        return []
    picks = (report.get("recommendations") or {}).get("stocks") or report.get("picks") or []
    seen = {_code_key(item.get("code")) for item in picks if isinstance(item, Mapping)}
    rows: List[Dict[str, Any]] = []
    for item in report.get("observation_pool") or []:
        if not isinstance(item, Mapping):
            continue
        code = _code_key(item.get("code"))
        if not code or not str(item.get("name") or "").strip() or code in seen:
            continue
        rows.append(dict(item))
        seen.add(code)
        if len(rows) == 6:
            break
    return rows


def _observation_pool_for_report(
    selection: Mapping[str, Any],
    *,
    picks: List[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Normalize only the producer-approved pool; legacy candidates stay internal."""
    if selection.get("observation_pool_verified") is not True:
        return []
    return presentation_observations({
        "observation_pool_verified": True,
        "observation_pool": selection.get("observation_pool") or [],
        "picks": picks,
    })


def _display(value: Any) -> str:
    return str(value).strip() if value is not None and str(value).strip() else "未知"


def _display_list(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if item is not None and str(item).strip()]
        return "、".join(parts) if parts else "未知"
    return _display(value)


def _evidence_text(value: Any) -> str:
    if not value:
        return "未知"
    rows = value if isinstance(value, (list, tuple)) else [value]
    statements = []
    for item in rows[:2]:
        if isinstance(item, Mapping):
            statement = item.get("statement") or item.get("summary") or item.get("title")
        else:
            statement = item
        if statement:
            statements.append(str(statement).strip())
    return "；".join(statements) if statements else "未知"


def format_observation(item: Mapping[str, Any], index: int, *, session: str = "") -> str:
    """Shared wording for the Markdown report and Feishu card."""
    themes = _display_list(item.get("hotspot_themes"))
    level = str(item.get("hotspot_match_level") or "").strip()
    match = {
        "direct": "直接关联", "alias": "别名关联", "industry": "行业关联",
        "indirect": "间接关联", "none": "未匹配",
    }.get(level, "待确认")
    trigger = _display(item.get("trigger"))
    if session == "pre_market" and trigger != "未知":
        trigger = f"{trigger}（盘中待确认）"
    return (
        f"- **{index}. {_display(item.get('name'))} ({_display(item.get('code'))}) · 待确认**\n"
        f"  关联热点：{themes}（{match}）；热点依据：{_evidence_text(item.get('hotspot_evidence'))}\n"
        f"  入选理由：{_display(item.get('inclusion_reason'))}；候选证据：{_evidence_text(item.get('evidence'))}\n"
        f"  待确认项：{_display(item.get('pending_confirmation'))}；未进入正式推荐：{_display_list(item.get('rejection_reasons'))}\n"
        f"  触发：{trigger}；失效：{_display(item.get('invalidation'))}\n"
        f"  行情日：{_display(item.get('price_as_of'))}；候选来源：{_display_list(item.get('candidate_sources'))}"
    )


def presentation_diagnostics(report: Mapping[str, Any]) -> List[str]:
    """Keep market coverage and rule-evaluation counts on separate denominators."""
    diagnostics = report.get("selection_diagnostics") or {}
    coverage = report.get("coverage") or {}
    status = report.get("data_status")
    if _presentation_failed(report):
        state = "数据不足或质量未通过，未完成有效筛选"
    elif status == "degraded":
        state = "有限数据源或部分数据降级，不能视为完整筛选"
    elif status == "ok" and coverage.get("fresh_data_available") is True:
        state = "数据可用；具体覆盖以扫描分母为准"
    elif status == "ok":
        state = "行情新鲜度未确认，不能确认筛选完整性"
    else:
        state = "数据状态未提供，不能确认筛选完整性"
    mode = diagnostics.get("coverage_mode") or coverage.get("mode")
    scanned = diagnostics.get("scanned_count")
    if scanned is None:
        scanned = coverage.get("scanned_count")
    universe = coverage.get("universe_size")
    quote_basis = str(coverage.get("quote_basis") or coverage.get("source") or "")
    quote_note = "；昨收行情" if quote_basis == "previous_close" else ""
    lines = [
        f"- 数据状态：{state}；扫描模式：{_display(mode)}{quote_note}",
        f"- 扫描时间：{_display(diagnostics.get('scan_as_of'))}；行情日：{_display(diagnostics.get('price_as_of'))}；"
        f"行情扫描：{_display(scanned)}/{_display(universe)}（原始行情分母，非候选评估数）",
        "- 筛选进度：" + "；".join(
            f"{label} {_display(diagnostics.get(key))}" for key, label in (
                ("candidate_count", "规则种子"), ("evaluated_count", "实际评估"),
                ("eligible_count", "规则合格"), ("selected_count", "正式选出"),
                ("observation_count", "经核验观察"),
            )
        ),
    ]
    if report.get("observation_pool_verified") is not True:
        lines[-1] = lines[-1].replace(
            f"经核验观察 {_display(diagnostics.get('observation_count'))}", "经核验观察 未确认"
        )
    if "mapping_gaps" in diagnostics:
        lines.append(f"- 映射缺口：{_display_list(diagnostics['mapping_gaps']) if diagnostics['mapping_gaps'] else '无已报告缺口'}")
    else:
        lines.append("- 映射缺口：未提供")
    if "rejection_summary" in diagnostics:
        reasons = diagnostics["rejection_summary"] or {}
        text = "；".join(f"{reason} {count}" for reason, count in reasons.items()) if isinstance(reasons, Mapping) else ""
        lines.append(f"- 未入选原因（实际评估样本）：{text or '无已报告原因'}")
    else:
        lines.append("- 未入选原因（实际评估样本）：未提供")
    warnings = list(report.get("data_warnings") or [])
    degraded = list(report.get("degraded_sections") or [])
    blocked = list(report.get("blocking_sections") or [])
    if degraded:
        lines.append("- 降级模块：" + "、".join(map(str, degraded)))
    if blocked:
        lines.append("- 阻断模块：" + "、".join(map(str, blocked)))
    if warnings:
        lines.append("- 数据告警：" + "；".join(map(str, warnings)))
    if (report.get("run") or {}).get("session") == "pre_market":
        if quote_basis == "previous_close" and diagnostics.get("price_as_of"):
            lines.append("- 盘前仅使用已完成日行情及最新催化；盘中触发待确认，消息热点不等于买入建议。")
        else:
            lines.append("- 盘前行情是否为已完成日数据待核对；盘中触发待确认，消息热点不等于买入建议。")
    return lines


def build_report(
    *,
    selection: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    snapshot_errors: Optional[List[str]] = None,
    coverage: Optional[Dict[str, Any]] = None,
    llm_context: Optional[Dict[str, Any]] = None,
    decision: Optional[Dict[str, Any]] = None,
    cross_market: Optional[Dict[str, Any]] = None,
    session: str = "pre_market",
) -> Dict[str, Any]:
    """Build full report dict (JSON-ready)."""
    snap_errors = list(snapshot_errors or [])
    etf_picks = list(selection.get("etf_picks") or [])
    news_hotspots = list((llm_context or {}).get("hotspots") or [])
    market_hotspots = build_market_hotspots(
        news_hotspots=news_hotspots,
        market_signals=list((llm_context or {}).get("market_signals") or []),
        picks=selection.get("picks") or candidates,
        etf_picks=etf_picks[:3],
        limit=5,
    )
    hotspot_mapping_summary = summarize_hotspot_mapping(
        news_hotspots,
        candidate_mappings=dict((llm_context or {}).get("candidate_hotspot_mappings") or {}),
        picks=selection.get("picks") or [],
    )
    coverage = dict(coverage or {})
    provider_health = dict(coverage.get("provider_health") or {})
    degraded_sections: list[str] = []
    blocking_sections: list[str] = []
    fallback_quotes_ok = str(coverage.get("mode") or "") in {"focused_fallback", "limited_sample"} and bool(coverage.get("fresh_data_available"))
    previous_close_ok = str(coverage.get("source") or "") == "previous_close" or str(coverage.get("quote_basis") or "") == "previous_close"
    for section, health in provider_health.items():
        if isinstance(health, Mapping):
            status = str(health.get("collection_status") or health.get("status") or "").lower()
            freshness = str(health.get("freshness_status") or "").lower()
            if status in {"timeout_pending", "capacity_exhausted", "failed", "degraded", "unavailable"} or freshness in {"stale", "expired"} or health.get("cache_stale"):
                degraded_sections.append(str(section))
            if (coverage.get("mode") != "mock_sample" and
                    status in {"failed", "unavailable", "timeout_pending", "degraded"} and
                    str(section) in {"fundamental", "market_data", "history"}):
                blocking_sections.append(str(section))
            if (coverage.get("mode") != "mock_sample" and not fallback_quotes_ok and not previous_close_ok and
                    status in {"failed", "unavailable", "timeout_pending", "degraded"} and
                    str(section) == "hithink_financial_api"):
                blocking_sections.append(str(section))
        elif str(health).lower() in {"degraded", "failed", "unavailable", "stale", "timeout_pending"}:
            degraded_sections.append(str(section))
            # Scalar provider-health entries (e.g. hithink_financial_api:
            # "degraded") must participate in the same core-data quality
            # gate as mapping-shaped entries.
            if (coverage.get("mode") != "mock_sample" and
                    str(health).lower() in {"degraded", "failed", "unavailable", "timeout_pending"} and
                    str(section) in {"fundamental", "market_data", "history"}):
                blocking_sections.append(str(section))
            if (coverage.get("mode") != "mock_sample" and not fallback_quotes_ok and not previous_close_ok and
                    str(health).lower() in {"degraded", "failed", "unavailable", "timeout_pending"} and
                    str(section) == "hithink_financial_api"):
                blocking_sections.append(str(section))
    coverage["degraded_sections"] = sorted(set(coverage.get("degraded_sections") or degraded_sections))
    coverage["blocking_sections"] = sorted(set(coverage.get("blocking_sections") or blocking_sections))
    if coverage["blocking_sections"]:
        coverage["core_data_blocked"] = True
    universe = int(coverage.get("universe_size") or 0)
    scanned = int(coverage.get("scanned_count") or 0)
    coverage["ratio"] = round(scanned / universe, 4) if universe else None
    if previous_close_ok:
        coverage["label"] = "昨收全市场观察池"
    elif coverage.get("mode") == "focused_fallback":
        coverage["label"] = "重点行业+龙虎榜有限观察池"
    else:
        coverage["label"] = "全市场观察池" if universe and scanned / universe >= 0.8 else "有限样本观察池"
    if coverage.get("fresh_data_available") is False:
        data_status = "failed"
    elif coverage.get("stale") or coverage.get("mode") == "limited_sample":
        data_status = "degraded" if scanned else "failed"
    elif coverage.get("mode") == "focused_fallback":
        data_status = "degraded" if scanned else "failed"
    else:
        data_status = "ok" if scanned else "failed"
    internal_observation_pool = selection.get("observation_pool") or [
        item for item in candidates if item.get("observation_only")
    ][:6]
    picks_for_report = list(selection.get("picks") or [])
    verified = selection.get("observation_pool_verified") is True
    observation_pool = _observation_pool_for_report(selection, picks=picks_for_report)
    diagnostics = dict(selection.get("selection_diagnostics") or {})
    for key, value in (("coverage_mode", coverage.get("mode")),
                       ("scanned_count", coverage.get("scanned_count")),
                       ("eligible_count", selection.get("eligible_count"))):
        if key not in diagnostics and value is not None:
            diagnostics[key] = value
    if "picks" in selection:
        diagnostics["selected_count"] = len(selection["picks"] or [])
    if verified:
        diagnostics["observation_count"] = len(observation_pool)
    rejection_reasons: Dict[str, int] = {}
    for item in candidates:
        for reason in item.get("rejection_reasons") or []:
            key = str(reason).split(":", 1)[0]
            rejection_reasons[key] = rejection_reasons.get(key, 0) + 1
    as_of = selection.get("as_of") or _today_str()
    decision = dict(decision or build_market_decision(
        as_of=as_of,
        market_signals=list((llm_context or {}).get("market_signals") or []),
        hotspots=market_hotspots,
        coverage=coverage,
    ))
    directions = dict(decision.get("directions") or {})
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cross_market_data = dict(cross_market or {})
    if not cross_market_data:
        cross_market_data = {
            "status": "unavailable",
            "risk_level": "unknown",
            "markets": {},
            "conclusion": build_cross_market_conclusion({"status": "unavailable"}),
        }
    else:
        cross_market_data.setdefault("conclusion", build_cross_market_conclusion(cross_market_data))
    report = {
        "schema_version": "decision-report-v2",
        "generated_at": generated_at,
        "as_of": as_of,
        "type": "stock_recommend_pre_market",
        "summary": selection.get("summary", ""),
        "market_view": selection.get("market_view", ""),
        "empty_reason": selection.get("empty_reason"),
        "empty_reason_code": selection.get("empty_reason_code") if not selection.get("picks") else None,
        "falsification": selection.get("falsification", []),
        "picks": selection.get("picks", []),
        "observation_pool_verified": verified,
        "observation_pool": observation_pool,
        "selection_diagnostics": diagnostics,
        "etf_picks": etf_picks[:3],
        "etf_rejections": list(selection.get("etf_rejections") or []),
        "etf_deduplicated": list(selection.get("etf_deduplicated") or []),
        "etf_portfolio_summary": dict(selection.get("etf_portfolio_summary") or {}),
        "etf_selection": {
            "selected_count": len(etf_picks[:3]),
            "rejected_count": len(selection.get("etf_rejections") or []),
            "deduplicated_count": len(selection.get("etf_deduplicated") or []),
            "selection_mode": "rule_quality_diversified",
        },
        "candidate_count": selection.get("candidate_count", len(candidates)),
        "candidates_top": candidates[:10],
        "llm_mock": selection.get("llm_mock", True),
        "data_warnings": snap_errors,
        "coverage": coverage,
        "provider_health": provider_health,
        "degraded_sections": list(coverage.get("degraded_sections") or []),
        "blocking_sections": list(coverage.get("blocking_sections") or []),
        "fallback_chain": list(coverage.get("fallback_chain") or []),
        "circuit_breakers": list(coverage.get("circuit_breakers") or []),
        "data_status": data_status,
        "quality": {
            "eligible_count": int(selection.get("eligible_count", len(selection.get("picks") or []))),
            "recommended_count": len(selection.get("picks") or []),
            "rejected_count": max(0, len(candidates) - len(selection.get("picks") or [])),
            "rejection_reasons": rejection_reasons,
        },
        "factor_version": selection.get("factor_version", "evidence-v1"),
        "hotspots": news_hotspots,
        "market_hotspots": market_hotspots,
        "hotspot_mapping_summary": hotspot_mapping_summary,
        "llm": dict((llm_context or {}).get("llm") or {}),
        "market": {key: value for key, value in decision.items() if key != "directions"},
        "directions": directions,
        "recommendations": {
            "stocks": list(selection.get("picks") or []),
            "etfs": etf_picks[:3],
        },
        "internal_observation_pool": internal_observation_pool,
        "data_quality": {
            "coverage_mode": coverage.get("mode"),
            "providers": dict(coverage.get("provider_health") or {}),
            "freshness": {
                "fresh_data_available": coverage.get("fresh_data_available"),
                "stale": bool(coverage.get("stale")),
            },
            "coverage": coverage,
            "errors": snap_errors,
        },
        "cross_market": cross_market_data,
        "research_audit": {
            "market_data": dict(coverage.get("provider_health") or {}),
            "news": dict((coverage.get("provider_health") or {}).get("news") or {}),
            "x_twitter": "X早期信号已按用户偏好禁用，未调用X/Twitter工具",
        },
    }
    report["quality_gate"] = evaluate_report_quality(report)
    if not report["quality_gate"]["passed"]:
        run_status = "failed"
    elif data_status == "degraded":
        run_status = "degraded"
    else:
        run_status = "passed"
    report["run"] = {
        "run_id": f"{as_of.replace('-', '')}-{session}-{generated_at.replace('-', '').replace(':', '').replace(' ', 'T')}",
        "session": session,
        "trade_date": as_of,
        "generated_at": generated_at,
        "status": run_status,
    }
    if not report["picks"]:
        if _presentation_failed(report):
            report["empty_reason_code"] = "data_insufficient"
        elif report["empty_reason_code"] not in _EMPTY_REASON_TEXT:
            report["empty_reason_code"] = (
                "awaiting_confirmation" if observation_pool else
                "screened_out" if _screening_complete(report) else "data_insufficient"
            )
        elif report["empty_reason_code"] == "screened_out" and not _screening_complete(report):
            report["empty_reason_code"] = "data_insufficient"
        report["empty_reason"] = empty_stock_message(report)
    report["delivery"] = {
        "channel": "feishu",
        "payload_hash": "",
        "accepted": False,
    }
    return report


def build_markdown(report: Dict[str, Any]) -> str:
    """Render report as Markdown for push to IM / files."""
    as_of = report.get("as_of", _today_str())
    lines: List[str] = []
    lines.append(f"# A股盘前决策 · {as_of}")
    lines.append("")
    lines.append(f"> {report.get('summary', '')}")
    lines.append("")
    market = dict(report.get("market") or {})
    if market:
        lines.append("## 大盘环境判断")
        lines.append("")
        lines.append(
            f"- **姿态**：{market.get('label', market.get('regime', '待确认'))}"
            f"｜状态 `{market.get('status', '需确认')}`｜环境分 {market.get('score', '-')}"
            f"｜{market.get('position_guidance', '仓位待定')}"
        )
        for item in market.get("evidence") or []:
            lines.append(f"- 证据：{item.get('statement', '')}（{item.get('source', '-')}，{item.get('as_of', '-') }）")
        lines.append("")

    directions = dict(report.get("directions") or {})
    if directions:
        lines.append("## 提前布局判断 / 可埋伏方向")
        lines.append("")
        for key, label in (
            ("current_attack", "当前主攻"),
            ("medium_term", "未来1~3个月主投"),
            ("early_positioning", "可小仓底仓 / 可埋伏 / 等待触发"),
            ("avoid_or_exit", "回避 / 撤退"),
        ):
            rows = directions.get(key) or []
            if not rows:
                lines.append(f"- **{label}**：无合格方向，等待触发")
                continue
            for item in rows:
                position = item.get("trial_position_limit")
                position_text = f"；试错仓上限：{position}" if position else ""
                lines.append(
                    f"- **{label}**：{item.get('direction', '待确认')}｜{item.get('action', '等待')}"
                    f"｜{item.get('status', '需确认')}｜窗口：{item.get('window', '-')}"
                    f"；触发：{item.get('trigger', '等待价格确认')}；失效：{item.get('invalidation', '待定义')}"
                    f"{position_text}"
                )
        lines.append("")

    cross_market = dict(report.get("cross_market") or {})
    if cross_market:
        lines.append("## 跨市场环境")
        lines.append("")
        lines.append(
            f"- 状态：{cross_market.get('status', '待确认')}｜风险等级：{cross_market.get('risk_level', 'unknown')}"
            f"｜时间：{cross_market.get('observed_at', '-')}"
        )
        if cross_market.get("conclusion"):
            lines.append(f"- **对A股结论**：{cross_market['conclusion']}")
        lines.append("")
    if report.get("market_view"):
        lines.append(f"**大盘看法**: {report['market_view']}")
        lines.append("")
    audit = report.get("evidence_audit") or {}
    if audit:
        regime = audit.get("market_regime") or {}
        lines.append(f"**证据覆盖**：财务 {audit.get('financial_count', 0)}/{audit.get('attempted_count', 0)}；"
                     f"相对基准 {audit.get('relative_strength_count', 0)}/{audit.get('attempted_count', 0)}。"
                     f"基准状态：{regime.get('regime', 'unknown')}，行情截止 {regime.get('price_as_of', '缺失')}。")
        lines.append("财务覆盖为候选子集年报；历史接口不是修订版本档案。权重晋级需通过滚动样本外及组合风险验证。")
        lines.append("")
    market_hotspots = report.get("market_hotspots") or []
    lines.append("## 市场热点目录（非个股建议）")
    lines.append("")
    if market_hotspots:
        for item in market_hotspots[:5]:
            status = item.get("status_label") or item.get("status") or "需确认"
            drivers = "、".join(item.get("drivers") or []) or "暂无明确驱动"
            industries = "、".join(item.get("industries") or []) or "待映射"
            reps = "、".join(item.get("representatives") or []) or item.get("mapping_gap") or "行业成员数据缺失"
            lines.append(f"- **{item.get('theme', '未知')}**｜{status}｜驱动：{drivers}｜行业：{industries}｜代表：{reps}")
    else:
        lines.append("> 暂无已验证市场热点（新闻与盘面信号均不足）")
    lines.append("> 目录中的行业代表仅用于说明热点映射，不属于正式推荐或观察名单。")
    lines.append("")
    hotspots = report.get("hotspots") or []
    if hotspots:
        lines.append("**消息热点/产业链**:")
        for item in hotspots[:5]:
            industries = "、".join(item.get("industries") or []) or "待映射"
            lines.append(f"- {item.get('theme', '未知')}：{industries}（{item.get('status', '需确认')}）")
        lines.append("")
    fals = report.get("falsification") or []
    if fals:
        lines.append("**整体证伪信号**:")
        for f in fals:
            lines.append(f"- {f}")
        lines.append("")
    picks = (report.get("recommendations") or {}).get("stocks") or report.get("picks") or []
    lines.append("## 正式个股推荐")
    lines.append("")
    if not picks:
        lines.append(f"> {empty_stock_message(report)}")
    else:
        for i, p in enumerate(picks, 1):
            lines.append(_format_pick_md(p, i))
    observation_pool = presentation_observations(report)
    if observation_pool:
        lines.append("## 待确认个股观察（非正式推荐）")
        lines.append("")
        lines.append("> 仅作条件观察；未达到正式推荐门槛，不构成买入建议。")
        for index, item in enumerate(observation_pool, 1):
            lines.append(format_observation(
                item, index, session=str((report.get("run") or {}).get("session") or "")
            ))
    else:
        lines.extend([
            "## 待确认个股观察（非正式推荐）",
            "",
            "> 本次无经核验观察名单。旧观察池与热点目录代表不直接沿用。",
        ])
    etf_picks = report.get("etf_picks") or []
    if etf_picks:
        lines.extend(["", "## ETF观察", ""])
        for e in etf_picks[:3]:
            lines.append(
                f"- {e.get('name', '')} ({e.get('code', '')})：{_format_etf_factor_line(e)}；{e.get('rationale', '')}"
            )
    lines.extend(["", "## 数据缺口 / 筛选概况", ""])
    lines.extend(presentation_diagnostics(report))
    audit = dict(report.get("research_audit") or {})
    if audit:
        lines.append("")
        lines.append("## 搜索与数据通道审计")
        lines.append("")
        lines.append(f"- 行情/数据源：{audit.get('market_data', {})}")
        lines.append(f"- 新闻源：{audit.get('news', {})}")
        lines.append(f"- {audit.get('x_twitter', 'X早期信号已按用户偏好禁用，未调用X/Twitter工具')}")
    lines.append("")
    lines.append(f"_生成时间: {report.get('generated_at', '')}_  ·  LLM mock: {report.get('llm_mock', False)}")
    return "\n".join(lines)


def save_report(report: Dict[str, Any], root_dir: Path) -> Dict[str, str]:
    """Write report to disk.

    Returns dict with `json_path` and `md_path`.
    """
    target_dir = root_dir / "data" / "stock_recommend"
    target_dir.mkdir(parents=True, exist_ok=True)
    as_of = report.get("as_of") or _today_str()
    json_path = target_dir / f"recommend_{as_of.replace('-', '')}.json"
    md_path = target_dir / f"recommend_{as_of.replace('-', '')}.md"
    latest_json = target_dir / "latest.json"
    latest_md = target_dir / "latest.md"

    import json

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = build_markdown(report)
    md_path.write_text(md, encoding="utf-8")

    run_id = str((report.get("run") or {}).get("run_id") or as_of.replace("-", ""))
    archive_dir = target_dir / "premarket_runs"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_json = archive_dir / f"{run_id}.json"
    archive_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    archive_md = archive_dir / f"{run_id}.md"
    archive_md.write_text(md, encoding="utf-8")
    # Mock/test runs must never replace the live latest pointer.
    is_mock = str((report.get("coverage") or {}).get("mode") or "") == "mock_sample"
    if not is_mock:
        latest_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        latest_md.write_text(md, encoding="utf-8")
    logger.info(f"report saved: json={json_path} md={md_path} archive={archive_json}")
    return {"json_path": str(json_path), "md_path": str(md_path), "latest_json": str(latest_json), "latest_md": str(latest_md), "archive_json": str(archive_json), "archive_md": str(archive_md)}


def save_review_report(review: Dict[str, Any], root_dir: Path) -> Dict[str, str]:
    """Persist a post-market review next to recommendation reports."""
    target_dir = root_dir / "data" / "stock_recommend"
    target_dir.mkdir(parents=True, exist_ok=True)
    as_of = str(review.get("as_of") or _today_str()).replace("-", "")
    json_path = target_dir / f"review_{as_of}.json"
    md_path = target_dir / f"review_{as_of}.md"
    import json

    lines = [f"# A股盘后复盘 · {review.get('as_of', '')}", ""]
    summary = review.get("summary") or {}
    lines.append(
        f"收盘数据 {summary.get('close_count', 0)}/{summary.get('pick_count', 0)}；"
        f"T+1已验证 {summary.get('completed_count', 0)}/{summary.get('pick_count', 0)}，"
        f"待验证 {summary.get('pending_count', 0)}。"
    )
    lines.append("")
    from ah_recommendation_system.backend.stock_recommend.post_market import format_review_item, format_direction_review
    direction_rows = review.get("direction_review") or []
    if direction_rows:
        lines.extend(["## 方向复盘", ""])
        for item in direction_rows:
            lines.append(format_direction_review(item))
        lines.append("")
    lines.append("当日涨跌与后续验证分别展示；观察价格表现不等于交易收益。")
    for item in review.get("items") or []:
        lines.append(format_review_item(item))
    markdown = "\n".join(lines) + "\n"
    payload = json.dumps(review, ensure_ascii=False, indent=2)
    json_path.write_text(payload, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    (target_dir / "latest_review.json").write_text(payload, encoding="utf-8")
    (target_dir / "latest_review.md").write_text(markdown, encoding="utf-8")
    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "latest_json": str(target_dir / "latest_review.json"),
        "latest_md": str(target_dir / "latest_review.md"),
    }
