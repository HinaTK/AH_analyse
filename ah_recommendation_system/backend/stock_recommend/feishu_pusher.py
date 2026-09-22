"""Feishu (Lark) webhook pusher for daily stock recommendation.

Sends an interactive card via incoming webhook.
Configure via env: AH_FEISHU_WEBHOOK (required), AH_FEISHU_SECRET (optional, for signing).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from loguru import logger


from ah_recommendation_system.backend.stock_recommend.market_hotspots import build_market_hotspots
from ah_recommendation_system.backend.stock_recommend.report_builder import (
    empty_stock_message,
    format_observation,
    presentation_diagnostics,
    presentation_observations,
)


def resolve_webhook(value: Optional[str] = None) -> str:
    raw = (value if value is not None else os.environ.get("AH_FEISHU_WEBHOOK") or "").strip()
    if not raw:
        for path in (
            Path(r"C:\Users\Administrator\Downloads\feishu_key.txt"),
            Path.home() / "Downloads" / "feishu_key.txt",
        ):
            try:
                raw = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if raw:
                break
    match = re.search(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9-]+", raw)
    return match.group(0) if match else raw


def _format_factor_line(pick: Dict[str, Any]) -> str:
    factors = dict(pick.get("factor_scores") or {})
    factors.update(pick.get("factors") or {})
    # 资金流数据缺失时，资金维度显示"-"而不是0分
    has_capital_evidence = False
    for item in pick.get("evidence") or []:
        if item.get("factor") == "capital":
            has_capital_evidence = True
            if item.get("source") == "capital_unavailable":
                factors["capital"] = None
            break
    if not has_capital_evidence and float(factors.get("capital") or 0) == 0.0:
        # 旧数据没有资金evidence，资金分恰好为0视为未评估
        factors["capital"] = None
    labels = (
        ("trend", "趋势"),
        ("price_volume", "量价"),
        ("value_quality", "估值质量"),
        ("capital", "资金"),
        ("relative_strength", "相对强度"),
        ("event", "消息催化"),
    )

    def score(key: str) -> str:
        value = factors.get(key)
        try:
            return f"{float(value) * 100:.0f}"
        except (TypeError, ValueError):
            return "-"

    composite = factors.get("composite")
    try:
        composite_text = f"{float(composite) * 100:.1f}/100"
    except (TypeError, ValueError):
        composite_text = "-"
    dimensions = "｜".join(f"{label} {score(key)}" for key, label in labels)
    rule = factors.get("event_score_rule")
    ai = factors.get("event_score_llm")
    event_detail = ""
    if rule is not None or ai is not None:
        def _event_score(value: Any) -> str:
            try:
                return f"{float(value) * 100:.0f}"
            except (TypeError, ValueError):
                return "-"
        event_detail = f"｜规则 {_event_score(rule)}｜AI {_event_score(ai)}"
    return f"综合评分 {composite_text}｜{dimensions}{event_detail}"


def _format_capital_evidence(pick: Dict[str, Any]) -> str:
    for item in pick.get("evidence") or []:
        if item.get("factor") == "capital":
            return str(item.get("statement") or "资金分未评估")
    return "资金分未评估"


def _format_etf_line(etf: Dict[str, Any]) -> str:
    factors = dict(etf.get("factor_scores") or {})
    labels = (
        ("trend", "趋势"),
        ("relative_strength", "相对强度"),
        ("liquidity", "流动性"),
        ("risk_control", "风险控制"),
        ("theme_match", "主题匹配"),
    )

    def score(key: str) -> str:
        value = factors.get(key)
        try:
            return f"{float(value):.0f}"
        except (TypeError, ValueError):
            return "-"

    total = etf.get("score", etf.get("composite_score"))
    try:
        total_text = f"{float(total):.1f}"
    except (TypeError, ValueError):
        total_text = "-"
    dimensions = "｜".join(f"{label} {score(key)}" for key, label in labels)
    theme = str(etf.get("theme_group") or "未分类")
    return f"{etf.get('position', '观察')}·{theme}｜综合 {total_text}｜{dimensions}"


def _sign(secret: str, timestamp: str) -> str:
    """Compute Feishu sign for incoming webhook."""
    string_to_sign = f"{timestamp}\n{secret}"
    h = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(h).decode("utf-8")


def build_card(report: Dict[str, Any]) -> Dict[str, Any]:
    """Build Feishu interactive card payload."""
    as_of = report.get("as_of", "")
    if report.get("type") == "stock_recommend_post_market":
        summary = dict(report.get("summary") or {})
        elements: list[Any] = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**收盘数据**：{summary.get('close_count', 0)}/{summary.get('pick_count', 0)}；"
                        f"T+1已验证 {summary.get('completed_count', 0)}/{summary.get('pick_count', 0)}，"
                        f"上涨 {summary.get('hit_count', 0)}；待验证 {summary.get('pending_count', 0)}"
                    ),
                },
            }
        ]
        closing_market = dict(report.get("closing_market") or {})
        strongest = []
        weakest = []
        for item in closing_market.get("top_gainers") or []:
            try:
                strongest.append(f"{item.get('name', '')} {float(item.get('chg_pct')):+.2f}%")
            except (TypeError, ValueError):
                continue
        for item in closing_market.get("top_losers") or []:
            try:
                weakest.append(f"{item.get('name', '')} {float(item.get('chg_pct')):+.2f}%")
            except (TypeError, ValueError):
                continue
        if strongest or weakest:
            close_lines = []
            if strongest:
                close_lines.append("**收盘最强**：" + "、".join(strongest[:5]))
            if weakest:
                close_lines.append("**收盘最弱**：" + "、".join(weakest[:5]))
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n".join(close_lines)},
            })
        from ah_recommendation_system.backend.stock_recommend.post_market import format_review_item, format_direction_review
        for item in report.get("items") or []:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": format_review_item(item)},
            })
        direction_rows = report.get("direction_review") or []
        if direction_rows:
            lines = []
            for item in direction_rows[:8]:
                lines.append(format_direction_review(item))
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "**方向复盘**\n" + "\n".join(lines)},
            })
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": f"A股盘后复盘 · {as_of}"},
                    "template": "green",
                },
                "elements": elements,
            },
        }
    quality_gate = dict(report.get("quality_gate") or {})
    run = dict(report.get("run") or {})
    if report.get("schema_version") == "decision-report-v2" and (
        quality_gate.get("passed") is False or run.get("status") == "failed"
    ):
        reasons = quality_gate.get("blocking_reasons") or report.get("data_warnings") or ["未知质量异常"]
        content = "**任务状态**\n数据采集失败或内容质量未通过，本次未生成正常推荐。\n" + "\n".join(
            f"- {reason}" for reason in reasons
        )
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": f"A股分析任务异常 · {as_of}"},
                    "template": "red",
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                    {"tag": "hr"},
                    {"tag": "div", "text": {"tag": "lark_md", "content":
                        f"**正式个股推荐**\n{empty_stock_message(report)}"}},
                    {"tag": "hr"},
                    {"tag": "div", "text": {"tag": "lark_md", "content":
                        "**待确认个股观察（非正式推荐）**\n本次无经核验观察名单。"}},
                    {"tag": "hr"},
                    {"tag": "div", "text": {"tag": "lark_md", "content":
                        "**数据缺口 / 筛选概况**\n" + "\n".join(presentation_diagnostics(report))}},
                    {"tag": "div", "text": {"tag": "lark_md", "content": "系统已保留运行审计，下次任务将重新探测数据源。"}},
                ],
            },
        }
    summary = report.get("summary", "")
    market_view = report.get("market_view", "")
    recommendations = dict(report.get("recommendations") or {})
    picks = recommendations.get("stocks") or report.get("picks") or []
    etf_picks = recommendations.get("etfs") or report.get("etf_picks") or []
    elements: list[Any] = []
    status = report.get("data_status")
    coverage_label = (report.get("coverage") or {}).get("label")
    if status in {"degraded", "failed"} or (coverage_label and coverage_label != "全市场观察池"):
        status_text = {
            "degraded": "⚠️ 部分数据降级，请结合数据范围与缺口查看结果",
            "failed": "⚠️ 数据采集失败：本次不生成策略结论",
        }.get(status, "")
        if coverage_label and status != "failed":
            status_text = f"{status_text + ' · ' if status_text else ''}范围：{coverage_label}"
        if status_text:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": status_text}})
    static_summary = "仅保留具备可追溯趋势/量价及至少三类独立证据的候选；证据不足时不生成个股推荐。"
    if summary and summary.strip() != static_summary:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**盘前总结**: {summary}"},
            }
        )
    if market_view:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**大盘**: {market_view}"},
            }
        )

    market = dict(report.get("market") or {})
    if market:
        market_score = market.get("score", "-")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**市场姿态**：{market.get('label', market.get('regime', '待确认'))}"
                    f"｜{market.get('status', '需确认')}｜环境分 {market_score}"
                    f"｜{market.get('position_guidance', '仓位待定')}"
                ),
            },
        })

    cross_market = dict(report.get("cross_market") or {})
    if cross_market:
        market_groups = dict(cross_market.get("markets") or {})
        cross_lines = []
        for key, label in (("united_states", "美股隔夜"), ("hong_kong", "港股"), ("fx", "汇率"), ("rates", "利率")):
            rows = market_groups.get(key) or []
            if not rows:
                continue
            values = []
            for item in rows[:3]:
                metric = item.get("change_pct", item.get("value"))
                suffix = "%" if item.get("change_pct") is not None else ""
                values.append(f"{item.get('name', '')} {metric if metric is not None else '-'}{suffix}")
            cross_lines.append(f"- **{label}**：" + "、".join(values))
        if cross_lines or cross_market.get("conclusion"):
            body = "\n".join(cross_lines) if cross_lines else "- 外部市场可用数值不足"
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**跨市场环境**｜风险 {cross_market.get('risk_level', 'unknown')}"
                        f"｜{cross_market.get('observed_at', '-')}\n" + body
                        + (f"\n**对A股结论**：{cross_market.get('conclusion')}" if cross_market.get('conclusion') else "")
                    ),
                },
            })

    directions = dict(report.get("directions") or {})
    if directions:
        labels = (
            ("current_attack", "当前主攻"),
            ("medium_term", "未来1~3个月"),
            ("early_positioning", "提前布局"),
            ("avoid_or_exit", "回避/撤退"),
        )
        direction_lines = []
        for key, label in labels:
            rows = directions.get(key) or []
            if not rows:
                direction_lines.append(f"- **{label}**：无合格方向，等待触发")
                continue
            for item in rows[:2]:
                position = item.get("trial_position_limit")
                position_text = f"｜试错仓 {position}" if position else ""
                direction_lines.append(
                    f"- **{label}**：{item.get('direction', '待确认')}｜{item.get('action', '等待')}"
                    f"｜{item.get('status', '需确认')}{position_text}\n"
                    f"  触发：{item.get('trigger', '等待价格确认')}｜失效：{item.get('invalidation', '待定义')}"
                )
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**方向与行动**\n" + "\n".join(direction_lines)},
        })

    market_hotspots = report.get("market_hotspots")
    if market_hotspots is None:
        market_hotspots = build_market_hotspots(
            news_hotspots=report.get("hotspots") or [],
            picks=picks,
            etf_picks=etf_picks,
            limit=5,
        )
    hotspot_lines = []
    for item in market_hotspots[:5]:
        grade = item.get("evidence_grade") or item.get("status_label") or "消息待确认"
        reprints = int(item.get("evidence_count") or 0)
        independent = item.get("independent_source_count")
        evidence_text = ""
        if item.get("source_type") == "news":
            if independent is not None:
                evidence_text = f"·报道{reprints}篇｜独立来源{int(independent)}个"
            elif reprints:
                evidence_text = f"·报道{reprints}篇｜独立性未知"
        industries = "、".join(item.get("industries") or []) or "待映射"
        reps = "、".join(item.get("representatives") or []) or item.get("mapping_gap") or "行业成员数据缺失"
        hotspot_lines.append(
            f"- **{item.get('theme', '未知')}**｜{grade}{evidence_text}\n"
            f"  行业：{industries}｜代表：{reps}"
        )
    hotspot_content = "**市场热点目录（非个股建议）**\n" + ("\n".join(hotspot_lines) if hotspot_lines else "暂无已验证市场热点（新闻与盘面信号均不足）")
    hotspot_content += "\n目录中的行业代表仅用于说明热点映射，不属于正式推荐或观察名单。"
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": hotspot_content}})

    elements.append({"tag": "hr"})
    if picks:
        heading = "**正式个股推荐**"
        if str(report.get("type") or "") == "stock_recommend_open_confirm":
            heading = "**开盘确认（可下单或取消）**"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": heading}})
        for i, p in enumerate(picks, 1):
            code = p.get("code", "?")
            name = p.get("name", "?")
            action = p.get("action", "WATCH")
            trigger = p.get("trigger") or "未给出"
            invalidation = p.get("invalidation") or "未给出"
            md = (
                f"**{i}. {name} ({code})** · `{action}`\n"
                f"触发：{trigger}\n"
                f"否定：{invalidation}"
            )
            if action == "CONDITIONAL_BUY":
                md += (
                    f"\n条件买入 {p.get('buy_zone') or '待确认'}｜止损 {p.get('stop_loss') or '待确认'}"
                    f"｜目标 {p.get('target') or '待确认'}"
                    f"\n仓位：{p.get('position_text') or '未给出'}"
                    f"\n{p.get('fill_constraint') or '开盘确认前不得成交'}"
                )
            elif action == "BUY":
                md += (
                    f"\n可下单｜买入 {p.get('buy_zone') or '待确认'}"
                    f"｜止损 {p.get('stop_loss') or '待确认'}"
                    f"\n仓位：{p.get('position_text') or '未给出'}"
                )
            elif action == "CANCEL":
                md += f"\n当日取消：{p.get('cancel_reason') or p.get('fill_constraint') or '未确认'}"
            llm_review = str(p.get("llm_review") or "").strip()
            if "hotspot_match_level" in p:
                themes = "、".join(p.get("hotspot_themes") or [])
                bonus_points = float(p.get("hotspot_bonus") or 0) * 100
                if themes:
                    md += f"\n热点：{themes}｜排序加分 {bonus_points:.2f}/100"
                else:
                    md += "\n热点：未匹配当前热点，基础因子入选"
            if llm_review:
                md += f"\nAI复核: {llm_review}"
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": md}})
    else:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**正式个股推荐**\n{empty_stock_message(report)}"},
            }
        )

    observations = presentation_observations(report)
    elements.append({"tag": "hr"})
    if observations:
        observation_text = (
            "**待确认个股观察（非正式推荐）**\n"
            "仅作条件观察；未达到正式推荐门槛，不构成买入建议。\n"
            + "\n".join(
                format_observation(item, index, session=str(run.get("session") or ""))
                for index, item in enumerate(observations, 1)
            )
        )
    else:
        observation_text = (
            "**待确认个股观察（非正式推荐）**\n"
            "本次无经核验观察名单。旧观察池与热点目录代表不直接沿用。"
        )
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": observation_text}})

    if etf_picks:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content":
            "**ETF观察**\n" + "\n".join(
                f"- {e.get('name', '')} ({e.get('code', '')}) · {_format_etf_line(e)}\n"
                f"  理由：{e.get('rationale', '')}"
                for e in etf_picks[:3]
            )
        }})
    else:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**ETF观察**: 今日无合格ETF"}})

    fals = report.get("falsification") or []
    if fals:
        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**证伪信号**: " + "; ".join(fals),
                },
            }
        )

    elements.append({"tag": "hr"})
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": "**数据缺口 / 筛选概况**\n" + "\n".join(presentation_diagnostics(report)),
        },
    })

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": (f"功能预览 · {as_of}" if report.get("is_preview")
                                else f"A/H市场盘前决策 · {as_of}" if report.get("schema_version") == "decision-report-v2"
                                else f"A 股盘前推荐 · {as_of}"),
                },
                "template": "blue",
            },
            "elements": elements,
        },
    }


def push_to_feishu(
    report: Dict[str, Any],
    *,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
    timeout: float = 10.0,
    retries: int = 3,
    backoff_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Push report to Feishu webhook. Returns response info."""
    if isinstance(report, dict) and "msg_type" in report and isinstance(report.get("card"), dict):
        raise TypeError(
            "push_to_feishu expects the source report, not a prebuilt card. "
            "Call push_to_feishu(report) and let it build the card internally."
        )
    coverage = dict(report.get("coverage") or {})
    run = dict(report.get("run") or {})
    is_mock = (
        str(coverage.get("mode") or "") == "mock_sample"
        or str(coverage.get("source") or "") == "mock"
        or str(run.get("source") or "") == "mock"
    )
    if is_mock:
        return {"ok": False, "skipped": True, "reason": "mock_delivery_blocked"}
    quality_failed = (
        report.get("quality_gate", {}).get("passed") is False
        or str(run.get("status") or "") == "failed"
    )
    if quality_failed:
        return {"ok": False, "skipped": True, "reason": "quality_gate_failed"}
    hook = resolve_webhook(webhook)
    if not hook:
        return {"ok": False, "skipped": True, "reason": "AH_FEISHU_WEBHOOK not set"}

    sec = (secret if secret is not None else os.environ.get("AH_FEISHU_SECRET") or "").strip()

    payload = build_card(report)
    payload_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    content_audit = None
    if report.get("type") == "stock_recommend_post_market":
        from ah_recommendation_system.backend.stock_recommend.post_market import audit_review_card
        content_audit = audit_review_card(report, payload)
        if not content_audit["passed"]:
            logger.error("Post-market content check blocked delivery: {}", content_audit["errors"])
            return {"ok": False, "skipped": True, "reason": "post_market_content_check_failed",
                    "content_audit": content_audit, "payload_hash": payload_hash}
    elif str(report.get("type") or "").startswith("stock_recommend"):
        from ah_recommendation_system.backend.stock_recommend.card_content_audit import audit_pre_market_card
        content_audit = audit_pre_market_card(report, payload)
        if not content_audit["passed"]:
            logger.error("Pre-market content check blocked delivery: {}", content_audit["errors"])
            return {"ok": False, "skipped": True, "reason": "pre_market_content_check_failed",
                    "content_audit": content_audit, "payload_hash": payload_hash}
    if sec:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(sec, ts)

    attempts = max(1, int(retries))
    last_error: Optional[str] = None
    last_status: Optional[int] = None
    last_data: Any = None
    attempts_made = 0
    for attempt in range(1, attempts + 1):
        attempts_made = attempt
        try:
            resp = requests.post(hook, json=payload, timeout=timeout)
            last_status = resp.status_code
            try:
                last_data = resp.json()
            except Exception:
                last_data = {"raw": resp.text[:500]}
            business_code = last_data.get("code") if isinstance(last_data, dict) else None
            ok = resp.status_code == 200 and business_code in (None, 0, "0")
            if ok:
                logger.info(f"feishu push status={resp.status_code} ok=True")
                return {
                    "ok": True,
                    "status": resp.status_code,
                    "response": last_data,
                    "retry_count": attempt,
                    "payload_hash": payload_hash,
                    "content_audit": content_audit,
                }
            last_error = f"business_{business_code}" if resp.status_code == 200 else f"http_{resp.status_code}"
            retryable = resp.status_code >= 500 or resp.status_code == 429
            if not retryable:
                break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            logger.warning("feishu delivery state is ambiguous after transport error: {}", exc)
            return {
                "ok": False,
                "status": last_status,
                "response": last_data,
                "error": str(exc),
                "retry_count": attempt,
                "payload_hash": payload_hash,
                "delivery_ambiguous": True,
            }
        except Exception as e:
            last_error = str(e)
            break
        if attempt < attempts and backoff_seconds > 0:
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
    logger.warning(f"feishu push failed after {attempts_made} attempts: {last_error}")
    return {
        "ok": False,
        "status": last_status,
        "response": last_data,
        "error": last_error,
        "retry_count": attempts_made,
        "payload_hash": payload_hash,
        "delivery_ambiguous": False,
    }


def push_failure_alert(
    report: Dict[str, Any],
    *,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Send a failure notice without treating it as a formal recommendation."""
    coverage = dict(report.get("coverage") or {})
    run = dict(report.get("run") or {})
    is_mock = (
        str(coverage.get("mode") or "") == "mock_sample"
        or str(coverage.get("source") or "") == "mock"
        or str(run.get("source") or "") == "mock"
    )
    if is_mock:
        return {"ok": False, "skipped": True, "reason": "mock_delivery_blocked"}
    hook = resolve_webhook(webhook)
    if not hook:
        return {"ok": False, "skipped": True, "reason": "AH_FEISHU_WEBHOOK not set"}
    as_of = report.get("as_of", "")
    quality_gate = dict(report.get("quality_gate") or {})
    reasons = quality_gate.get("blocking_reasons") or report.get("data_warnings") or ["未知质量异常"]
    content = (
        "**任务状态**\n数据采集失败或内容质量未通过，本次未生成正式观察。\n"
        + "\n".join(f"- {reason}" for reason in reasons)
        + "\n\n这不是买入建议，也不是当日正式推荐卡。"
    )
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"A股分析任务异常 · {as_of}"},
                "template": "red",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            ],
        },
    }
    sec = (secret if secret is not None else os.environ.get("AH_FEISHU_SECRET") or "").strip()
    if sec:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(sec, ts)
    try:
        resp = requests.post(hook, json=payload, timeout=timeout)
        business = resp.json() if resp.text else {}
        code = business.get("code") if isinstance(business, dict) else None
        ok = resp.status_code == 200 and code in (None, 0, "0")
        return {
            "ok": ok,
            "status": resp.status_code,
            "response": business,
            "reason": "alert_sent" if ok else f"http_{resp.status_code}",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "reason": "alert_transport_error"}


def push_markdown_simple(
    text: str,
    *,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Push plain text (Markdown) - use when interactive card not desired."""
    hook = resolve_webhook(webhook)
    if not hook:
        return {"ok": False, "skipped": True, "reason": "AH_FEISHU_WEBHOOK not set"}

    sec = (secret if secret is not None else os.environ.get("AH_FEISHU_SECRET") or "").strip()
    payload: Dict[str, Any] = {"msg_type": "markdown", "content": {"text": text}}
    if sec:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(sec, ts)

    try:
        resp = requests.post(hook, json=payload, timeout=timeout)
        return {
            "ok": resp.status_code == 200,
            "status": resp.status_code,
            "response": (resp.json() if resp.text else {}),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
