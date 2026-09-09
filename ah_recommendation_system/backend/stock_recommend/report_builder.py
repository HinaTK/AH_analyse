"""Report builder for daily stock recommendations.

Produces a structured dict (stored as JSON) and a human-readable Markdown report.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ah_recommendation_system.backend.stock_recommend.market_hotspots import build_market_hotspots
from ah_recommendation_system.backend.stock_recommend.decision_engine import build_market_decision
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
    coverage = dict(coverage or {})
    universe = int(coverage.get("universe_size") or 0)
    scanned = int(coverage.get("scanned_count") or 0)
    coverage["ratio"] = round(scanned / universe, 4) if universe else None
    if coverage.get("mode") == "focused_fallback":
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
    observation_pool = selection.get("observation_pool") or [
        item for item in candidates if item.get("observation_only")
    ][:6]
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
    report = {
        "schema_version": "decision-report-v2",
        "generated_at": generated_at,
        "as_of": as_of,
        "type": "stock_recommend_pre_market",
        "summary": selection.get("summary", ""),
        "market_view": selection.get("market_view", ""),
        "falsification": selection.get("falsification", []),
        "picks": selection.get("picks", []),
        "observation_pool": observation_pool,
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
        "provider_health": dict(coverage.get("provider_health") or {}),
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
        "llm": dict((llm_context or {}).get("llm") or {}),
        "market": {key: value for key, value in decision.items() if key != "directions"},
        "directions": directions,
        "recommendations": {
            "stocks": list(selection.get("picks") or []),
            "etfs": etf_picks[:3],
        },
        "internal_observation_pool": observation_pool,
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
        "cross_market": dict(cross_market or {}),
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
    lines.append(f"# A 股盘前推荐 · {as_of}")
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
        lines.append("")
    if report.get("market_view"):
        lines.append(f"**大盘看法**: {report['market_view']}")
        lines.append("")
    market_hotspots = report.get("market_hotspots") or []
    lines.append("## 市场热点")
    lines.append("")
    if market_hotspots:
        for item in market_hotspots[:5]:
            status = item.get("status_label") or item.get("status") or "需确认"
            drivers = "、".join(item.get("drivers") or []) or "暂无明确驱动"
            industries = "、".join(item.get("industries") or []) or "待映射"
            reps = "、".join(item.get("representatives") or []) or "暂无代表标的"
            lines.append(f"- **{item.get('theme', '未知')}**｜{status}｜驱动：{drivers}｜行业：{industries}｜代表：{reps}")
    else:
        lines.append("> 暂无已验证市场热点（新闻与盘面信号均不足）")
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
    picks = report.get("picks") or []
    if not picks:
        lines.append("> ⚠️ 今日无正式个股推荐：没有标的同时通过数据质量、证据数量和趋势/量价确认门槛。")
    else:
        for i, p in enumerate(picks, 1):
            lines.append(_format_pick_md(p, i))
    etf_picks = report.get("etf_picks") or []
    if etf_picks:
        lines.append("## ETF观察")
        lines.append("")
        for e in etf_picks[:3]:
            lines.append(
                f"- {e.get('name', '')} ({e.get('code', '')})：{_format_etf_factor_line(e)}；{e.get('rationale', '')}"
            )
    observation_pool = report.get("observation_pool") or []
    if observation_pool:
        lines.append("## 观察池（未达正式推荐门槛）")
        lines.append("")
        for item in observation_pool[:6]:
            reasons = "；".join(item.get("rejection_reasons") or []) or "等待更多证据"
            lines.append(f"- {item.get('name', '')} ({item.get('code', '')})：{reasons}")
    warns = report.get("data_warnings") or []
    if warns:
        lines.append("---")
        lines.append("**数据告警**:")
        for w in warns:
            lines.append(f"- {w}")
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

    # Stable latest pointer
    latest_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    latest_md.write_text(md, encoding="utf-8")

    logger.info(f"report saved: json={json_path} md={md_path}")
    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "latest_json": str(latest_json),
        "latest_md": str(latest_md),
    }


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
        f"完成 {summary.get('completed_count', 0)} / {summary.get('pick_count', 0)}，"
        f"命中 {summary.get('hit_count', 0)}。"
    )
    lines.append("")
    direction_rows = review.get("direction_review") or []
    if direction_rows:
        lines.extend(["## 方向复盘 / Direction review", ""])
        for item in direction_rows:
            lines.append(
                f"- {item.get('layer', '方向')} · {item.get('direction', '待确认')}："
                f"{item.get('review_status', 'pending')}；修正 {item.get('correction', 'confirm')}"
            )
            evidence = str(item.get("evidence") or "").strip()
            if evidence:
                lines.append(f"  - 证据：{evidence}")
        lines.append("")
    for item in review.get("items") or []:
        lines.append(
            f"- {item.get('name', '')} ({item.get('code', '')})："
            f"{item.get('status', 'pending')}，收益 {item.get('return_pct', '-') }%，"
            f"修正 {item.get('correction', 'confirm')}"
        )
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
