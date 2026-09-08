"""Candidate pool builder.

Inputs: CollectedSnapshot (fundamental + capital + events)
Output: top 20-30 candidate codes with composite score.

Scoring is intentionally simple and explainable:
  fundamental_score: PE 分位 + 60日动量 + 市值过滤
  capital_score:     主力净流入 + 北向背景
  event_score:       是否出现在最近新闻里（标题包含代码/简称）

Composite = 0.4 * fundamental + 0.35 * capital + 0.25 * event
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from loguru import logger

from ah_recommendation_system.backend.stock_recommend.data_collector import (
    CollectedSnapshot,
)


DEFAULT_WEIGHTS = {
    "trend": 0.25,
    "price_volume": 0.20,
    "value_quality": 0.15,
    "capital": 0.15,
    "relative_strength": 0.15,
}

# 排除：ST、停牌、明显仙股、异常 PE
EXCLUDE_NAME_PATTERNS = ("ST", "退", "暂停", "B股")


@dataclass
class Candidate:
    code: str
    name: str
    price: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    market_cap: Optional[float] = None
    change_pct: Optional[float] = None
    change_60d_pct: Optional[float] = None
    main_net: Optional[float] = None
    fundamental_score: float = 0.0
    capital_score: float = 0.0
    event_score: float = 0.0
    composite: float = 0.0
    reasons: List[str] = field(default_factory=list)
    candidate_sources: List[str] = field(default_factory=list)
    focus_industries: List[str] = field(default_factory=list)
    observation_only: bool = False
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    valid_dimensions: set[str] = field(default_factory=set)
    rejection_reasons: List[str] = field(default_factory=list)
    atr: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None
    quality_grade: str = "C"
    data_quality: float = 0.0
    factor_scores: Dict[str, float] = field(default_factory=dict)


def _safe_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def _is_excluded(name: str) -> bool:
    if not name:
        return True
    return any(pat in name for pat in EXCLUDE_NAME_PATTERNS)


def _percentile_rank(values: List[float], v: Optional[float]) -> float:
    """Lower-is-better percentile for PE (0=best, 1=worst)."""
    if v is None or not values:
        return 0.5
    arr = sorted(values)
    if v <= arr[0]:
        return 0.0
    if v >= arr[-1]:
        return 1.0
    # binary search insertion point
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < v:
            lo = mid + 1
        else:
            hi = mid
    return lo / len(arr)


def _cap_filter(market_cap: Optional[float], min_cap_yi: float = 50.0) -> bool:
    if market_cap is None:
        return True  # 不强过滤
    # market_cap 单位通常是 元；阈值 50 亿 = 5e9
    return market_cap >= min_cap_yi * 1e8


def _pe_filter(pe: Optional[float], max_pe: float = 200.0) -> bool:
    if pe is None:
        return True
    if pe <= 0 or pe > max_pe:
        return False
    return True


def build_candidates(
    snapshot: CollectedSnapshot,
    *,
    top_n: int = 30,
    weights: Optional[Dict[str, float]] = None,
    min_market_cap_yi: float = 50.0,
    max_pe: float = 80.0,
) -> List[Candidate]:
    weights = weights or DEFAULT_WEIGHTS
    fund_rows = snapshot.fundamental.get("rows") or []
    cap_rows = snapshot.capital.get("rows") or []
    if not fund_rows:
        logger.warning("fundamental rows empty; candidate pool may be empty")

    # Build lookups
    pe_values: List[float] = []
    fund_map: Dict[str, Dict[str, Any]] = {}
    for r in fund_rows:
        code = str(r.get("code") or "").strip()
        name = str(r.get("name") or "").strip()
        if not code or len(code) != 6:
            continue
        if _is_excluded(name):
            continue
        pe = _safe_float(r.get("pe"))
        mc = _safe_float(r.get("market_cap"))
        if not _cap_filter(mc, min_market_cap_yi):
            continue
        if not _pe_filter(pe, max_pe):
            continue
        fund_map[code] = r
        if pe is not None:
            pe_values.append(pe)

    cap_map: Dict[str, Dict[str, Any]] = {}
    for r in cap_rows:
        code = str(r.get("code") or "").strip()
        if len(code) != 6:
            continue
        existing = cap_map.setdefault(code, {"code": code, "main_net": 0.0})
        existing["main_net"] = (_safe_float(existing.get("main_net")) or 0.0) + (_safe_float(r.get("main_net")) or 0.0)
        for key in ("name", "source"):
            if r.get(key) and not existing.get(key):
                existing[key] = r[key]

    cands: List[Candidate] = []
    for code, r in fund_map.items():
        name = str(r.get("name") or "")
        pe = _safe_float(r.get("pe"))
        pb = _safe_float(r.get("pb"))
        mc = _safe_float(r.get("market_cap"))
        price = _safe_float(r.get("price"))
        chg = _safe_float(r.get("change_pct"))
        chg60 = _safe_float(r.get("change_60d_pct"))
        main_net = _safe_float((cap_map.get(code) or {}).get("main_net"))

        c = Candidate(
            code=code,
            name=name,
            price=price,
            pe=pe,
            pb=pb,
            market_cap=mc,
            change_pct=chg,
            change_60d_pct=chg60,
            main_net=main_net,
            candidate_sources=list(r.get("candidate_sources") or []),
            focus_industries=list(r.get("focus_industries") or []),
            atr=_safe_float(r.get("atr")),
            support=_safe_float(r.get("support")),
            resistance=_safe_float(r.get("resistance")),
        )

        # Industry membership is provenance only; it is never an investment reason.
        if "lhb_institution" in c.candidate_sources:
            c.reasons.append("机构席位净买入")
        if "lhb_trader" in c.candidate_sources:
            c.reasons.append("活跃营业部净买入")

        # fundamental: PE 分位低 + 60 日正动量 + 合理市值
        pe_rank = _percentile_rank(pe_values, pe)  # 0=最低
        pe_score = 1.0 - pe_rank  # PE 越低越好
        mom_score = 0.0
        if chg60 is not None:
            # clip 到 [-30, +30] 之间线性映射
            mom_score = max(-0.3, min(0.3, chg60 / 100.0)) / 0.3 * 0.5 + 0.5
        cap_score = 0.5
        if mc is not None:
            # 市值 50~5000 亿：0.5~0.9；>5000 亿：0.9；<50 亿：0.4
            yi = mc / 1e8
            if yi < 50:
                cap_score = 0.3
            elif yi < 5000:
                cap_score = 0.5 + min(0.4, (yi - 50) / 5000.0)
            else:
                cap_score = 0.9
        c.fundamental_score = round(0.5 * pe_score + 0.3 * mom_score + 0.2 * cap_score, 4)

        if pe is not None and pe_rank <= 0.3:
            c.reasons.append(f"PE 分位偏低 ({pe:.1f})")
        if chg60 is not None and chg60 > 0:
            c.reasons.append(f"60 日动量 {chg60:+.1f}%")

        # capital: 主力净流入
        if main_net is not None:
            # 1 亿=1e8 算 1.0；负值扣分
            score = max(-0.3, min(0.3, main_net / 1e8)) / 0.3 * 0.5 + 0.5
            c.capital_score = round(score, 4)
            if main_net > 1e7:
                c.reasons.append(f"主力净流入 {main_net/1e8:+.2f} 亿")
        else:
            c.capital_score = 0.0

        # Build auditable evidence dimensions. Missing values remain missing.
        if chg60 is not None:
            if chg60 > 0:
                c.valid_dimensions.add("trend")
            c.evidence.append({"factor": "trend", "statement": f"60日动量 {chg60:+.1f}%", "value": chg60, "source": r.get("source") or "snapshot", "as_of": snapshot.date, "supports": chg60 > 0, "falsifier": "60日动量转负或跌破MA60"})
        if main_net is not None:
            if main_net > 0:
                c.valid_dimensions.add("capital")
            c.evidence.append({"factor": "capital", "statement": f"主力净流入 {main_net / 1e8:+.2f}亿", "value": main_net, "source": "capital", "as_of": snapshot.date, "supports": main_net > 0, "falsifier": "主力资金连续转为净流出"})
        if pe is not None and pe > 0:
            if pe <= max_pe:
                c.valid_dimensions.add("value")
            c.evidence.append({"factor": "value", "statement": f"PE {pe:.1f}", "value": pe, "source": r.get("source") or "snapshot", "as_of": snapshot.date, "supports": pe <= max_pe, "falsifier": "估值升至筛选上限或盈利预期下修"})
        amount = _safe_float(r.get("amount"))
        volume_ratio = _safe_float(r.get("volume_ratio") or r.get("volume_ratio_20d"))
        if amount is not None and amount >= 100_000_000 and (volume_ratio is None or volume_ratio >= 1.0):
            c.valid_dimensions.add("price_volume")
            c.evidence.append({"factor": "price_volume", "statement": f"成交额 {amount / 1e8:.2f}亿", "value": amount, "source": r.get("source") or "snapshot", "as_of": snapshot.date, "supports": amount >= 100_000_000, "falsifier": "成交额跌破1亿或量价背离"})
        if chg is not None and chg >= 0 and chg60 is not None and chg60 > 0:
            c.valid_dimensions.add("relative_strength")
        c.data_quality = round(len(c.valid_dimensions) / 5.0, 3)
        c.quality_grade = "A" if len(c.valid_dimensions) >= 4 else "B" if len(c.valid_dimensions) >= 3 else "C"
        if not amount or amount < 100_000_000:
            c.rejection_reasons.append("quality:成交额缺失或低于1亿")
        if chg60 is None:
            c.rejection_reasons.append("quality:缺少60日趋势")
        if pe is None or pe <= 0:
            c.rejection_reasons.append("quality:估值缺失或无效")
        if mc is None or mc < min_market_cap_yi * 1e8:
            c.rejection_reasons.append("quality:市值缺失或低于50亿")
        if price is None or not 3 <= price <= 300:
            c.rejection_reasons.append("risk:价格超出3至300元范围")
        if chg is None or not -4 <= chg <= 8.5:
            c.rejection_reasons.append("risk:当日涨跌幅超出安全范围")
        if bool(r.get("stale")):
            c.rejection_reasons.append("stale:仅有最近一次有效快照，不得正式推荐")
        history_days = _safe_float(r.get("history_days"))
        if history_days is None:
            c.rejection_reasons.append("quality:历史日线覆盖未知")
        elif history_days < 60:
            c.rejection_reasons.append("quality:历史日线不足60个交易日")
        for news in snapshot.events.get("stock_news") or []:
            news_text = f"{news.get('title', '')} {news.get('content', '')}"
            if code not in news_text and name not in news_text:
                continue
            negative = any(word in news_text for word in ("立案", "调查", "处罚", "减持", "违约", "退市", "亏损"))
            c.event_score = 0.0 if negative else 0.8
            evidence = {
                "factor": "event",
                "statement": str(news.get("title") or "近期公告/新闻覆盖"),
                "value": 0.0 if negative else 1.0,
                "source": news.get("source") or "news",
                "url": news.get("url"),
                "as_of": news.get("published_at") or snapshot.date,
                "supports": not negative,
                "falsifier": "后续公告澄清或催化失效",
            }
            c.evidence.append(evidence)
            if not negative:
                c.valid_dimensions.add("event")
            if negative:
                c.rejection_reasons.append("p0:负面公告/新闻风险否决")
        if len(c.valid_dimensions) < 3:
            c.rejection_reasons.append("evidence:有效证据维度少于3个")
        c.data_quality = round(min(1.0, len(c.valid_dimensions) / 5.0), 3)
        c.quality_grade = "A" if len(c.valid_dimensions) >= 4 and history_days is not None and history_days >= 120 else "B" if len(c.valid_dimensions) >= 3 and history_days is not None and history_days >= 60 else "C"

        trend_factor = max(0.0, min(1.0, ((chg60 or 0.0) + 30.0) / 60.0)) if chg60 is not None else 0.0
        if r.get("above_ma20") is True:
            trend_factor = min(1.0, trend_factor + 0.1)
        if r.get("above_ma60") is True:
            trend_factor = min(1.0, trend_factor + 0.1)
        liquidity_factor = min(1.0, (amount or 0.0) / 500_000_000)
        if volume_ratio is not None:
            liquidity_factor = min(1.0, liquidity_factor * min(1.0, volume_ratio / 1.5))
        value_factor = max(0.0, min(1.0, 1.0 - (pe or max_pe) / max_pe)) if pe is not None and pe > 0 else 0.0
        capital_factor = max(0.0, min(1.0, ((main_net or 0.0) / 100_000_000 + 1.0) / 2.0)) if main_net is not None else 0.0
        relative_factor = max(0.0, min(1.0, 0.5 + ((chg or 0.0) / 20.0) + ((chg60 or 0.0) / 100.0))) if chg is not None and chg60 is not None else 0.0
        risk_penalty = 0.0
        volatility = _safe_float(r.get("volatility_20d_pct"))
        drawdown = _safe_float(r.get("max_drawdown_pct"))
        if volatility is not None and volatility > 45:
            risk_penalty -= min(0.08, (volatility - 45) / 1000.0)
        if drawdown is not None and drawdown < -20:
            risk_penalty -= min(0.08, abs(drawdown + 20) / 500.0)
        c.factor_scores = {
            "trend": round(trend_factor, 4),
            "price_volume": round(liquidity_factor, 4),
            "value_quality": round(value_factor, 4),
            "capital": round(capital_factor, 4),
            "relative_strength": round(relative_factor, 4),
            "risk": round(risk_penalty, 4),
        }
        c.composite = round(
            weights.get("trend", 0.25) * trend_factor
            + weights.get("price_volume", 0.20) * liquidity_factor
            + weights.get("value_quality", 0.15) * value_factor
            + weights.get("capital", 0.15) * capital_factor
            + weights.get("relative_strength", 0.15) * relative_factor
            + risk_penalty,
            4,
        )
        has_focus = "focus_industry" in c.candidate_sources
        has_lhb = bool({"lhb_trader", "lhb_institution"} & set(c.candidate_sources))
        if has_focus and has_lhb:
            c.reasons.append("行业归属与席位资金交集（仅作候选来源）")
        # 龙虎榜/机构席位 alone is a lead, not trend confirmation.  Keep it
        # visible in the candidate pool but prevent it from becoming a pick
        # until it intersects the configured focus industries.
        c.observation_only = bool(has_lhb and not has_focus)
        if c.observation_only:
            c.reasons.append("仅资金异动，行业/价格未确认")
        if c.rejection_reasons:
            c.observation_only = True
        cands.append(c)

    cands.sort(key=lambda c: (c.observation_only, -c.composite))
    return cands[:top_n]


def to_dict_list(cands: Iterable[Candidate]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in cands:
        out.append(
            {
                "code": c.code,
                "name": c.name,
                "price": c.price,
                "pe": c.pe,
                "pb": c.pb,
                "market_cap_yi": round(c.market_cap / 1e8, 1) if c.market_cap else None,
                "change_pct": c.change_pct,
                "change_60d_pct": c.change_60d_pct,
                "main_net_yi": round(c.main_net / 1e8, 3) if c.main_net else None,
                "fundamental_score": c.fundamental_score,
                "capital_score": c.capital_score,
                "event_score": c.event_score,
                "composite": c.composite,
                "reasons": c.reasons,
                "candidate_sources": c.candidate_sources,
                "focus_industries": c.focus_industries,
                "observation_only": c.observation_only,
                "evidence": c.evidence,
                "valid_dimensions": sorted(c.valid_dimensions),
                "rejection_reasons": c.rejection_reasons,
                "quality_grade": c.quality_grade,
                "data_quality": c.data_quality,
                "atr": c.atr,
                "support": c.support,
                "resistance": c.resistance,
                "factor_scores": c.factor_scores,
            }
        )
    return out
