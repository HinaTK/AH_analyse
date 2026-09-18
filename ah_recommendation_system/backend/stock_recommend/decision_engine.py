"""Deterministic market posture and direction synthesis.

This module converts already-collected market evidence into an actionable
decision.  It never calls an LLM and never discovers securities by itself.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_confirmed(hotspot: Mapping[str, Any]) -> bool:
    return str(hotspot.get("status") or hotspot.get("status_label") or "").lower() in {
        "confirmed",
        "有效",
    }


def _medium_term_qualified(hotspot: Mapping[str, Any], positive_signals: list[Mapping[str, Any]]) -> bool:
    """Only promote a theme to the 1--3 month bucket after real confirmation."""
    status = str(hotspot.get("status") or "").lower()
    refs = hotspot.get("evidence_refs") or []
    try:
        independent = int(hotspot.get("independent_source_count") or 0)
    except (TypeError, ValueError):
        independent = 0
    drivers = " ".join(str(x) for x in (hotspot.get("drivers") or []))
    slow_variable = any(token in drivers for token in ("\u8ba2\u5355", "\u76c8\u5229", "\u4f9b\u9700", "\u653f\u7b56", "\u4ea7\u80fd", "\u4e1a\u7ee9", "\u5e93\u5b58", "\u4ef7\u683c"))
    price_confirmed = status in {"confirmed", "market_confirmed", "\u6709\u6548", "\u5e02\u573a\u786e\u8ba4"}
    breadth_confirmed = any(str(signal.get("theme") or "") == str(hotspot.get("theme") or "") for signal in positive_signals)
    return independent >= 2 and len(refs) >= 2 and slow_variable and (price_confirmed or breadth_confirmed)


def _direction_item(
    direction: str,
    *,
    action: str,
    status: str,
    evidence: Iterable[str],
    window: str,
    trigger: str,
    invalidation: str,
    trial_position_limit: Optional[str] = None,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "direction": direction,
        "action": action,
        "status": status,
        "evidence": [item for item in evidence if item],
        "window": window,
        "trigger": trigger,
        "invalidation": invalidation,
    }
    if trial_position_limit:
        item["trial_position_limit"] = trial_position_limit
    return item


def build_market_decision(
    *,
    as_of: str,
    market_signals: Optional[Iterable[Mapping[str, Any]]] = None,
    hotspots: Optional[Iterable[Mapping[str, Any]]] = None,
    coverage: Optional[Mapping[str, Any]] = None,
    cross_market: Optional[Mapping[str, Any]] = None,
    previous_medium_term: Optional[str] = None,
    market_regime: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a deterministic market decision from verified evidence."""
    signals = [dict(item) for item in (market_signals or []) if isinstance(item, Mapping)]
    hotspot_rows = [dict(item) for item in (hotspots or []) if isinstance(item, Mapping)]
    coverage_row = dict(coverage or {})

    score = 45.0
    ratio = _number(coverage_row.get("ratio"))
    if ratio >= 0.8:
        score += 10.0
    elif coverage_row.get("mode") in {"focused_fallback", "limited_sample", "stale_only"}:
        score -= 10.0

    positive_signals = []
    negative_signals = []
    for item in signals:
        change = _number(item.get("change_pct"))
        advance = _number(item.get("advance_count"))
        total = _number(item.get("total_count"))
        breadth = advance / total if total > 0 else 0.0
        if change >= 1.0 and (breadth >= 0.6 or total == 0):
            positive_signals.append(item)
        if change <= -1.0 or (total > 0 and breadth < 0.35):
            negative_signals.append(item)
    score += min(20.0, len(positive_signals) * 5.0)
    score -= min(20.0, len(negative_signals) * 5.0)

    confirmed_hotspots = [item for item in hotspot_rows if _is_confirmed(item)]
    score += min(10.0, len(confirmed_hotspots) * 3.0)

    risk_level = str((cross_market or {}).get("risk_level") or "").lower()
    if risk_level in {"high", "p0", "高"}:
        score -= 15.0
    score = round(max(0.0, min(100.0, score)), 1)
    if score >= 65:
        regime, label, status = "offense", "结构性进攻", "有效"
    elif score >= 45:
        regime, label, status = "balanced", "震荡等待确认", "需确认"
    else:
        regime, label, status = "defense", "防守", "降级观察"

    benchmark = dict(market_regime or {})
    benchmark_regime = str(benchmark.get("regime") or "").lower()
    if benchmark.get("status") == "available" and benchmark_regime in {"offense", "balanced", "defense"}:
        regime = benchmark_regime
        if regime == "defense":
            label, status = "防守", "降级观察"
        elif regime == "offense":
            label, status = "结构性进攻", "有效"
        else:
            label, status = "震荡等待确认", "需确认"

    if regime == "offense":
        position_guidance = "进攻仓位 60%-80%；主线确认后分批加仓，跌破失效位减仓"
    elif regime == "balanced":
        position_guidance = "均衡仓位 40%-60%；仅在触发条件确认后加仓，未确认不追涨"
    else:
        position_guidance = "轻仓 20%-30%；不主动加仓，等待市场修复后再提高仓位"

    actionable_hotspots = [item for item in hotspot_rows if str(item.get("status") or "").lower() in {"confirmed", "有效", "early_signal", "消息待确认"}]
    ranked_themes = []
    for hotspot in actionable_hotspots:
        theme = str(hotspot.get("theme") or "").strip()
        if theme and theme not in ranked_themes:
            ranked_themes.append(theme)
    for signal in positive_signals:
        # Market-wide breadth describes the trading environment; it is not an
        # investable industry/theme and must never become a direction pick.
        if str(signal.get("source") or "") == "a_share_full_snapshot":
            continue
        theme = str(signal.get("theme") or signal.get("name") or "").strip()
        if theme and theme not in ranked_themes:
            ranked_themes.append(theme)

    primary = ranked_themes[0] if ranked_themes else "暂无价格确认主线"
    primary_status = (
        "有效"
        if ranked_themes and positive_signals and score >= 65 and regime == "offense"
        else "需确认"
    )
    if regime == "defense" and ranked_themes:
        primary_action = "主题存在，等待指数确认"
    elif primary_status == "有效":
        primary_action = "回踩确认后参与，不追无量高开"
    else:
        primary_action = "等待开盘后价格、成交和宽度确认"
    primary_evidence = [
        f"行业盘面正向信号{len(positive_signals)}项",
        f"已交叉验证热点{len(confirmed_hotspots)}项",
    ]

    qualified_medium = next((item for item in actionable_hotspots if _medium_term_qualified(item, positive_signals)), None)
    prior = str(previous_medium_term or "").strip()
    # Never promote or blindly carry forward a prior theme. It must pass the
    # current run's independent-source, slow-variable and price/breadth gates.
    medium = str((qualified_medium or {}).get("theme") or "暂无通过慢变量门槛的中期主线")
    medium_action = "分批观察，等待慢变量和价格结构继续确认" if qualified_medium else "等待确认"
    early = []
    if confirmed_hotspots and positive_signals:
        early.append(
            _direction_item(
                medium,
                action="可小仓试错",
                status="需确认",
                evidence=["催化与盘面方向一致", "价格结构未被否定"],
                window="T+5至1~3个月",
                trigger="相对强度继续改善且回踩有成交承接",
                invalidation="跌破阶段支撑且行业宽度持续收窄，或出现P0证伪事件",
                trial_position_limit="目标方向最终计划仓位的10%-30%",
            )
        )

    avoid_name = str(
        (negative_signals[0].get("theme") or negative_signals[0].get("name"))
        if negative_signals
        else "利好不涨、趋势破坏或无成交确认的方向"
    )
    directions = {
        "current_attack": [
            _direction_item(
                primary,
                action=primary_action,
                status=primary_status,
                evidence=primary_evidence,
                window="开盘前至早盘确认",
                trigger="行业指数、成交和上涨宽度同步确认",
                invalidation="高开回落且宽度收窄，或指数与主线同步跌破关键支撑",
            )
        ],
        "medium_term": [
            _direction_item(
                medium,
                action=medium_action,
                status="需确认",
                evidence=(["已满足独立来源、慢变量和价格/宽度确认门槛"] if qualified_medium else ["当前仅有早期信号或证据不足，未满足独立来源、慢变量和价格/宽度确认门槛"]),
                window="1~3个月",
                trigger="慢变量改善且趋势、相对强度转正",
                invalidation="慢变量证伪或价格结构持续破坏",
            )
        ],
        "early_positioning": early,
        "avoid_or_exit": [
            _direction_item(
                avoid_name,
                action="回避/撤退",
                status="有效" if negative_signals else "需确认",
                evidence=["价格确认优先于催化叙事"],
                window="至价格结构修复",
                trigger="重新放量站回关键均线后再分析",
                invalidation="行业宽度和相对强度恢复",
            )
        ],
    }
    previous = str(previous_medium_term or "").strip()
    if not previous:
        direction_change_reason = "首次建立方向"
    elif not qualified_medium:
        direction_change_reason = "本次中期证据门槛未满足，旧方向和新热点均降为等待确认"
    else:
        direction_change_reason = "证据门槛通过后切换方向" if previous != medium else "方向未变化"
    return {
        "as_of": as_of,
        "score": score,
        "regime": regime,
        "label": label,
        "status": status,
        "position_guidance": position_guidance,
        "evidence": [
            {"statement": text, "source": "deterministic_market_engine", "as_of": as_of}
            for text in primary_evidence
        ],
        "invalidation": [
            "指数、成交与上涨宽度同时转弱",
            "已验证主线出现利好不涨并跌破阶段支撑",
            "出现改变风险偏好的P0事件",
        ],
        "directions": directions,
        "direction_audit": {
            "previous_medium_term": previous or None,
            "current_medium_term": medium,
            "direction_change_reason": direction_change_reason,
            "medium_term_qualified": bool(qualified_medium),
        },
    }
