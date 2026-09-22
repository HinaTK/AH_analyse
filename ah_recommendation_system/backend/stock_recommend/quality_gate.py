"""Pre-delivery report quality checks."""
from __future__ import annotations

from typing import Any, Dict, Mapping


def evaluate_report_quality(report: Mapping[str, Any]) -> Dict[str, Any]:
    coverage = dict(report.get("coverage") or report.get("data_quality", {}).get("coverage") or {})
    recommendations = dict(report.get("recommendations") or {})
    stocks = list(recommendations.get("stocks") or report.get("picks") or [])
    etfs = list(recommendations.get("etfs") or report.get("etf_picks") or [])
    panel = list(report.get("candidate_panel") or report.get("candidates_top") or [])
    market = dict(report.get("market") or {})
    directions = dict(report.get("directions") or {})
    blockers = []
    warnings = []
    checks = []

    blocking_sections = list(report.get("blocking_sections") or coverage.get("blocking_sections") or [])
    checks.append({"name": "core_provider_health", "passed": not blocking_sections})
    if blocking_sections:
        blockers.append("核心数据源降级或超时：" + "、".join(str(item) for item in blocking_sections))

    stock_count_valid = len(stocks) <= 5
    checks.append({"name": "stock_count_limit", "passed": stock_count_valid})
    if not stock_count_valid:
        blockers.append("正式股票超过5只")

    etf_count_valid = len(etfs) <= 3
    checks.append({"name": "etf_count_limit", "passed": etf_count_valid})
    if not etf_count_valid:
        blockers.append("正式ETF超过3只")

    fresh = coverage.get("fresh_data_available")
    source = str(coverage.get("source") or "")
    live_source = bool(source) and source not in {"mock", ""}
    stale_only = (
        fresh is False
        or source == "last_good_snapshot"
        or bool(coverage.get("stale"))
        or (live_source and fresh is not True)
    )
    checks.append({"name": "fresh_market_data", "passed": not stale_only})
    if stale_only:
        blockers.append("仅有旧缓存或无法确认当日有效行情")

    mode = str(coverage.get("mode") or "")
    ratio = coverage.get("ratio")
    full_market_valid = not (mode == "full_market" and ratio is not None and float(ratio) < 0.8)
    checks.append({"name": "coverage_label_truthful", "passed": full_market_valid})
    if not full_market_valid:
        blockers.append("全市场覆盖不足80%却标记为全市场")
    elif mode in {"focused_fallback", "limited_sample"}:
        warnings.append("本次为有限样本，结论已降级")

    fallback_errors = [str(item) for item in (coverage.get("circuit_breakers") or []) if str(item)]
    if fallback_errors:
        warnings.append(
            "部分数据源异常，兜底链路已接管：" + "、".join(fallback_errors[:5])
        )

    history_target = coverage.get("history_target_count")
    history_count = coverage.get("history_count")
    # Never substitute candidate_count. Missing both fields means this report
    # did not run the live history cohort, so there is nothing to measure.
    if history_target is None and history_count is None:
        history_complete = True
    else:
        history_complete = (
            type(history_target) is int and type(history_count) is int
            and history_target > 0 and 0 <= history_count <= history_target
            and history_count / history_target >= 0.8
        )
    checks.append({"name": "candidate_history_completeness", "passed": history_complete})
    if not history_complete:
        message = "候选历史行情完整率低于80%"
        replay = source in {"previous_close", "disk_cache"} or str(coverage.get("quote_basis") or "") == "previous_close"
        if replay:
            warnings.append(message + "（昨收回放，不阻断正式观察）")
        else:
            blockers.append(message)

    decision_complete = bool(market.get("regime") and market.get("status")) and all(
        key in directions
        for key in ("current_attack", "medium_term", "early_positioning", "avoid_or_exit")
    )
    checks.append({"name": "decision_complete", "passed": decision_complete})
    if not decision_complete:
        blockers.append("缺少市场姿态或方向分层")
    regime = str(market.get("regime") or "").strip().lower()
    status = str(market.get("status") or "").strip().lower()
    regime_evidence = dict(market.get("regime_evidence") or {})
    evidence_status = str(regime_evidence.get("status") or "").strip().lower()
    usable_posture = True
    if regime in {"unknown", "unavailable", ""} or status in {"unknown", "unavailable", ""} or evidence_status in {"unavailable", "unknown"}:
        usable_posture = False
        blockers.append("缺少可用市场姿态证据")
    checks.append({"name": "market_posture_usable", "passed": usable_posture})

    stock_reasons_valid = all(str(item.get("rationale") or "").strip() for item in stocks)
    checks.append({"name": "stock_rationales_traceable", "passed": stock_reasons_valid})
    if not stock_reasons_valid:
        blockers.append("正式股票存在空白入选理由")
    stock_evidence_valid = all(
        any(str(evidence.get("statement") or "").strip() for evidence in (item.get("evidence") or []))
        for item in stocks
    )
    checks.append({"name": "stock_evidence_present", "passed": stock_evidence_valid})
    if not stock_evidence_valid:
        blockers.append("正式股票缺少可追溯证据")

    etf_fields_valid = all(
        item.get("code")
        and item.get("factor_scores")
        and (item.get("score") is not None or item.get("composite_score") is not None)
        for item in etfs
    )
    checks.append({"name": "etf_quality_evidence", "passed": etf_fields_valid})
    if not etf_fields_valid:
        blockers.append("正式ETF缺少真实评分或行情质量证据")

    valuation_missing = 0
    for item in panel:
        reasons = [str(reason) for reason in (item.get("rejection_reasons") or [])]
        if item.get("pe") is None or any("估值缺失" in reason for reason in reasons):
            valuation_missing += 1
    valuation_complete = True
    if len(panel) >= 5 and valuation_missing / len(panel) >= 0.8:
        valuation_complete = False
        blockers.append("候选估值字段大面积缺失，数据不完整，推荐结论受限")
    checks.append({"name": "candidate_valuation_coverage", "passed": valuation_complete})

    quote_missing = 0
    for item in panel:
        reasons = [str(reason) for reason in (item.get("rejection_reasons") or [])]
        if item.get("price") is None or any("价格缺失" in reason or "涨跌幅缺失" in reason for reason in reasons):
            quote_missing += 1
    quote_complete = True
    if len(panel) >= 5 and quote_missing / len(panel) >= 0.8:
        quote_complete = False
        blockers.append("候选价格或涨跌幅大面积缺失，数据不完整，推荐结论受限")
    checks.append({"name": "candidate_quote_coverage", "passed": quote_complete})

    llm = dict(report.get("llm") or {})
    if llm.get("hotspot_status") == "failed":
        detail = str(llm.get("hotspot_error") or "未知错误")
        warnings.append(f"LLM热点分析失败，已降级使用规则与价格证据：{detail}")
    if llm.get("event_status") == "failed":
        detail = str(llm.get("event_error") or "未知错误")
        warnings.append(f"LLM候选消息复核失败，已保留规则消息分：{detail}")

    return {
        "passed": not blockers,
        "checks": checks,
        "blocking_reasons": blockers,
        "warnings": warnings,
    }
