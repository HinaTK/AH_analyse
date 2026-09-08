"""Report builder for daily stock recommendations.

Produces a structured dict (stored as JSON) and a human-readable Markdown report.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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
                f"- **因子**: fundamental={factors.get('fundamental_score', '?')} "
                f"capital={factors.get('capital_score', '?')} "
                f"event={factors.get('event_score', '?')} "
                f"composite={comp}"
            )
    lines.append("")
    return "\n".join(lines)


def build_report(
    *,
    selection: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    snapshot_errors: Optional[List[str]] = None,
    coverage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build full report dict (JSON-ready)."""
    snap_errors = list(snapshot_errors or [])
    etf_picks = selection.get("etf_picks") or [
        {
            "code": "510300",
            "name": "沪深300ETF",
            "action": "WATCH",
            "rationale": "宽基基准，用于观察市场风险偏好与候选超额。",
            "trigger": "指数站稳短期均线且成交额回升",
            "invalidation": "跌破阶段低点并持续弱于中证全指",
        },
        {
            "code": "159915",
            "name": "创业板ETF",
            "action": "WATCH",
            "rationale": "成长风格代表，用于观察科技与新能源风险偏好。",
            "trigger": "放量突破并获得行业扩散确认",
            "invalidation": "冲高回落且行业宽度持续收窄",
        },
    ]
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
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "as_of": selection.get("as_of") or _today_str(),
        "type": "stock_recommend_pre_market",
        "summary": selection.get("summary", ""),
        "market_view": selection.get("market_view", ""),
        "falsification": selection.get("falsification", []),
        "picks": selection.get("picks", []),
        "observation_pool": observation_pool,
        "etf_picks": etf_picks[:2],
        "candidate_count": selection.get("candidate_count", len(candidates)),
        "candidates_top": candidates[:10],
        "llm_mock": selection.get("llm_mock", True),
        "data_warnings": snap_errors,
        "coverage": coverage,
        "data_status": data_status,
        "quality": {
            "eligible_count": int(selection.get("eligible_count", len(selection.get("picks") or []))),
            "recommended_count": len(selection.get("picks") or []),
            "rejected_count": max(0, len(candidates) - len(selection.get("picks") or [])),
            "rejection_reasons": rejection_reasons,
        },
        "factor_version": selection.get("factor_version", "evidence-v1"),
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
    if report.get("market_view"):
        lines.append(f"**大盘看法**: {report['market_view']}")
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
        for e in etf_picks[:2]:
            lines.append(f"- {e.get('name', '')} ({e.get('code', '')})：{e.get('rationale', '')}")
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
