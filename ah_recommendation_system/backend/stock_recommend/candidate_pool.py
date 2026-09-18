"""Candidate pool builder.

Inputs: CollectedSnapshot (fundamental + capital + events)
Output: top 20-30 candidate codes with composite score.

Scoring is intentionally simple and explainable:
  fundamental_score: PE 分位 + 60日动量 + 市值过滤
  capital_score:     主力净流入 + 北向背景
  event_score:       是否出现在最近新闻里（标题包含代码/简称）

Composite uses versioned trend, price/volume, value/quality, capital,
benchmark-relative strength and event weights, plus an explicit risk penalty.
Missing benchmark or financial evidence is never replaced by synthetic quality.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from loguru import logger
from ah_recommendation_system.backend.stock_recommend.quality_factors import assess_quality

from ah_recommendation_system.backend.stock_recommend.data_collector import (
    CollectedSnapshot,
)
from ah_recommendation_system.backend.stock_recommend.local_store import quote_date_from_value


DEFAULT_WEIGHTS = {
    "trend": 0.25,
    "price_volume": 0.20,
    "value_quality": 0.15,
    "capital": 0.15,
    "relative_strength": 0.15,
    "event": 0.10,
}

# 排除：ST、停牌、明显仙股、异常 PE
EXCLUDE_NAME_PATTERNS = ("ST", "退", "暂停", "B股")


def _date_value(*values: Any) -> Optional[str]:
    for value in values:
        parsed = quote_date_from_value(value)
        if parsed:
            return parsed
    return None


@dataclass
class Candidate:
    code: str
    name: str
    price: Optional[float] = None
    price_as_of: Optional[str] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    market_cap: Optional[float] = None
    change_pct: Optional[float] = None
    change_60d_pct: Optional[float] = None
    return_20d_pct: Optional[float] = None
    drawdown_from_60d_high_pct: Optional[float] = None
    main_net: Optional[float] = None
    fundamental_score: float = 0.0
    capital_score: float = 0.0
    event_score: Optional[float] = None
    event_score_rule: Optional[float] = None
    event_score_llm: Optional[float] = None
    event_score_status: str = "no_relevant_news"
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
    llm_review: str = ""
    llm_catalysts: List[str] = field(default_factory=list)
    llm_risks: List[str] = field(default_factory=list)
    llm_evidence_refs: List[str] = field(default_factory=list)
    hotspot_themes: List[str] = field(default_factory=list)
    hotspot_score: float = 0.0
    hotspot_evidence: List[str] = field(default_factory=list)
    hotspot_industries: List[str] = field(default_factory=list)
    hotspot_match_level: str = "none"
    hotspot_mapping_sources: List[str] = field(default_factory=list)
    hotspot_matches: List[Dict[str, Any]] = field(default_factory=list)
    hotspot_mapping_verified: bool = False
    quality_evidence: Dict[str, Any] = field(default_factory=dict)



def _turnover_pct(amount: Optional[float], market_cap: Optional[float]) -> Optional[float]:
    if amount is None or market_cap is None or market_cap <= 0:
        return None
    return amount / market_cap * 100.0


def _relative_capital_score(
    *,
    main_net: Optional[float],
    amount: Optional[float],
    market_cap: Optional[float],
    main_net_5d: Optional[float] = None,
) -> float:
    if main_net is None:
        return 0.0
    flow = main_net_5d if main_net_5d is not None else main_net
    share_of_amount = (flow / amount) if amount and amount > 0 else None
    share_of_cap = (flow / market_cap) if market_cap and market_cap > 0 else None
    if share_of_amount is not None:
        amount_score = max(0.0, min(1.0, 0.5 + share_of_amount / 0.4))
    else:
        amount_score = max(0.0, min(1.0, (flow / 300_000_000 + 1.0) / 2.0))
    if share_of_cap is not None:
        cap_score = max(0.0, min(1.0, 0.5 + share_of_cap / 0.02))
        return 0.65 * amount_score + 0.35 * cap_score
    return amount_score


def _path_adjusted_trend(chg60: Optional[float], return_20d: Optional[float], drawdown_60d: Optional[float], base: Optional[float] = None) -> float:
    if chg60 is None and base is None:
        return 0.0
    trend = base if base is not None else max(0.0, min(1.0, ((chg60 or 0.0) + 30.0) / 60.0))
    if return_20d is not None and return_20d < 0:
        trend = min(trend, 0.55)
        trend -= min(0.15, abs(return_20d) / 100.0)
    if drawdown_60d is not None and drawdown_60d <= -8:
        trend = min(trend, 0.6)
        trend -= min(0.2, (abs(drawdown_60d) - 8.0) / 50.0)
    return max(0.0, min(1.0, trend))


def _path_adjusted_relative_strength(relative_excess: Optional[float], return_20d: Optional[float], drawdown_60d: Optional[float]) -> float:
    if relative_excess is None:
        return 0.0
    score = max(0.0, min(1.0, 0.5 + relative_excess / 40.0))
    if return_20d is not None and return_20d < 0:
        score = min(score, 0.55)
    if drawdown_60d is not None and drawdown_60d <= -8:
        score = min(score, 0.6)
    return score

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
        for key in ("main_net_5d", "positive_days_5d", "capital_days"):
            value = _safe_float(r.get(key))
            if value is not None:
                existing[key] = value

    cands: List[Candidate] = []
    for code, r in fund_map.items():
        name = str(r.get("name") or "")
        pe = _safe_float(r.get("pe"))
        pb = _safe_float(r.get("pb"))
        mc = _safe_float(r.get("market_cap"))
        price = _safe_float(r.get("price"))
        chg = _safe_float(r.get("change_pct"))
        chg60 = _safe_float(r.get("change_60d_pct"))
        return_20d = _safe_float(r.get("return_20d_pct"))
        drawdown_60d = _safe_float(r.get("drawdown_from_60d_high_pct"))
        main_net = _safe_float((cap_map.get(code) or {}).get("main_net"))

        c = Candidate(
            code=code,
            name=name,
            price=price,
            price_as_of=_date_value(r.get("price_as_of"), r.get("quote_date"), r.get("price_date")),
            pe=pe,
            pb=pb,
            market_cap=mc,
            change_pct=chg,
            change_60d_pct=chg60,
            return_20d_pct=return_20d,
            drawdown_from_60d_high_pct=drawdown_60d,
            main_net=main_net,
            candidate_sources=list(r.get("candidate_sources") or []),
            focus_industries=list(r.get("focus_industries") or []),
            atr=_safe_float(r.get("atr")),
            support=_safe_float(r.get("support")),
            resistance=_safe_float(r.get("resistance")),
            hotspot_themes=list(r.get("hotspot_themes") or []),
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

        amount = _safe_float(r.get("amount"))
        volume_ratio = _safe_float(r.get("volume_ratio") or r.get("volume_ratio_20d"))
        turnover = _turnover_pct(amount, mc)
        cap_row = cap_map.get(code) or {}
        main_net_5d = _safe_float(cap_row.get("main_net_5d"))
        positive_days_5d = _safe_float(cap_row.get("positive_days_5d"))
        capital_days = _safe_float(cap_row.get("capital_days"))

        # capital: relative net flow, not raw yesterday yuan.
        if main_net is not None:
            c.capital_score = round(_relative_capital_score(
                main_net=main_net, amount=amount, market_cap=mc, main_net_5d=main_net_5d,
            ), 4)
            if main_net > 1e7:
                c.reasons.append(f"主力净流入 {main_net/1e8:+.2f} 亿")
        else:
            c.capital_score = 0.0
        if turnover is not None and mc is not None and mc >= 100_000_000_000 and turnover < 1.0:
            c.reasons.append(f"低换手 {turnover:.2f}%")

        # Build auditable evidence dimensions. Missing values remain missing.
        if chg60 is not None:
            trend_bits = [f"60日动量 {chg60:+.1f}%"]
            if return_20d is not None:
                trend_bits.append(f"近20日 {return_20d:+.1f}%")
            if drawdown_60d is not None:
                trend_bits.append(f"距60日高点 {drawdown_60d:+.1f}%")
            trend_ok = chg60 > 0 and (return_20d is None or return_20d >= 0) and (drawdown_60d is None or drawdown_60d > -8)
            if trend_ok:
                c.valid_dimensions.add("trend")
            c.evidence.append({"factor": "trend", "statement": "，".join(trend_bits), "value": chg60, "source": r.get("source") or "snapshot", "as_of": _date_value(r.get("trend_as_of"), r.get("price_as_of"), r.get("quote_date")), "supports": trend_ok, "falsifier": "近20日转负或距60日高点回撤超过8%"})
        if main_net is not None:
            if main_net > 0:
                c.valid_dimensions.add("capital")
            capital_bits = [f"主力净流入 {main_net / 1e8:+.2f}亿"]
            if amount is not None and amount > 0:
                capital_bits.append(f"占成交 {main_net / amount * 100:.1f}%")
            if main_net_5d is not None:
                capital_bits.append(f"5日净流入 {main_net_5d / 1e8:+.2f}亿")
                if positive_days_5d is not None:
                    capital_bits.append(f"5日{int(positive_days_5d)}日为正")
            can_label_accumulation = (
                main_net_5d is not None
                and (capital_days or 0) >= 5
                and (positive_days_5d or 0) >= 3
                and (main_net_5d or 0) > 0
                and r.get("new_high_20d") is not True
            )
            capital_bits.append("疑似吸筹" if can_label_accumulation else "无法判断吸筹")
            c.evidence.append({"factor": "capital", "statement": "，".join(capital_bits), "value": main_net_5d if main_net_5d is not None else main_net, "source": "capital", "as_of": _date_value(r.get("capital_as_of"), r.get("flow_as_of")), "supports": main_net > 0, "falsifier": "主力资金连续转为净流出"})
        else:
            c.evidence.append({"factor": "capital", "statement": "资金流数据缺失，资金分未评估", "value": None, "source": "capital_unavailable", "as_of": None, "supports": False, "falsifier": "资金流数据恢复后可重新评估"})
        if pe is not None and pe > 0:
            if pe <= max_pe:
                c.valid_dimensions.add("value")
            c.evidence.append({"factor": "value", "statement": f"PE {pe:.1f}", "value": pe, "source": r.get("source") or "snapshot", "as_of": _date_value(r.get("valuation_as_of")), "supports": pe <= max_pe, "falsifier": "估值升至筛选上限或盈利预期下修"})
        # A completed daily bar is the liquidity reference during pre-market;
        # a ratio around 0.8 still represents normal tradability and should
        # not be rejected as if it were an illiquid security. Stronger
        # expansion remains a separate scanner tag (>=1.5).
        if amount is not None and amount >= 100_000_000 and (volume_ratio is None or volume_ratio >= 0.8):
            c.valid_dimensions.add("price_volume")
            pv_bits = [f"成交额 {amount / 1e8:.2f}亿"]
            if turnover is not None:
                pv_bits.append(f"换手 {turnover:.2f}%")
            c.evidence.append({"factor": "price_volume", "statement": "，".join(pv_bits), "value": amount, "source": r.get("source") or "snapshot", "as_of": _date_value(r.get("amount_as_of"), c.price_as_of), "supports": amount >= 100_000_000, "falsifier": "成交额跌破1亿或量价背离"})
        # Own-price momentum is already in trend. Relative strength needs an
        # independently aligned benchmark return, never a second copy of it.
        relative_excess = _safe_float(r.get("benchmark_excess_60d_pct"))
        try:
            if not str(r.get("benchmark_end") or "") or str(r["benchmark_end"]) >= snapshot.date:
                relative_excess = None
        except (TypeError, KeyError):
            relative_excess = None
        if relative_excess is not None and r.get("benchmark_source"):
            if relative_excess > 0:
                c.valid_dimensions.add("relative_strength")
            c.evidence.append({"factor": "relative_strength", "value": relative_excess,
                               "statement": f"60日相对基准超额 {relative_excess:+.2f}%",
                               "source": r["benchmark_source"], "as_of": _date_value(r.get("benchmark_end")),
                               "supports": relative_excess > 0, "falsifier": "相对基准超额转负"})
        c.data_quality = round(len(c.valid_dimensions) / 5.0, 3)
        c.quality_grade = "A" if len(c.valid_dimensions) >= 4 else "B" if len(c.valid_dimensions) >= 3 else "C"
        if not amount or amount < 100_000_000:
            c.rejection_reasons.append("quality:成交额缺失或低于1亿")
        if chg60 is None:
            c.rejection_reasons.append("quality:缺少60日趋势")
        if pe is None:
            c.rejection_reasons.append("quality:估值缺失或无效")
        elif pe <= 0:
            c.rejection_reasons.append("quality:亏损估值")
        if mc is None or mc < min_market_cap_yi * 1e8:
            c.rejection_reasons.append("quality:市值缺失或低于50亿")
        if price is None or not 3 <= price <= 300:
            c.rejection_reasons.append("quality:价格缺失" if price is None else "risk:价格超出3至300元范围")
        if chg is None or not -4 <= chg <= 8.5:
            c.rejection_reasons.append("quality:涨跌幅缺失" if chg is None else "risk:当日涨跌幅超出安全范围")
        if bool(r.get("stale")):
            c.rejection_reasons.append("stale:仅有最近一次有效快照，不得正式推荐")
        history_days = _safe_float(r.get("history_days"))
        if history_days is None:
            c.rejection_reasons.append("quality:历史日线覆盖未知")
        elif history_days < 60:
            c.rejection_reasons.append("quality:历史日线不足60个交易日")
        matched_event_scores: List[float] = []
        events_payload = snapshot.events or {}
        provider_failed = str(events_payload.get("status") or events_payload.get("event_status") or "") in {"provider_failed", "failed"}
        for event_index, news in enumerate(events_payload.get("stock_news") or []):
            news_text = f"{news.get('title', '')} {news.get('content', '')}"
            # News providers may return body text mentioning a custody bank or
            # supplier.  Treat an item as this company's catalyst only when
            # the title/explicit subject identifies the candidate.
            title = str(news.get("title") or "")
            subject = " ".join(str(news.get(k) or "") for k in ("subject", "stock_code", "symbol", "code"))
            title_hit = bool(code and code in title) or bool(name and name in title)
            subject_hit = bool(subject and ((code and code in subject) or (name and name in subject)))
            if not (title_hit or subject_hit):
                continue
            p0_negative = any(word in news_text for word in ("立案", "调查", "重大处罚", "财务造假", "退市风险", "重大违约", "业绩暴雷"))
            ordinary_negative = any(word in news_text for word in ("减持", "诉讼", "亏损", "低于预期"))
            negative = p0_negative or ordinary_negative
            major_positive = any(word in news_text for word in (chr(0x7b7e)+chr(0x8ba2), chr(0x91cd)+chr(0x5927)+chr(0x5408)+chr(0x540c), chr(0x4e2d)+chr(0x6807), chr(0x91cd)+chr(0x7ec4), chr(0x5e76)+chr(0x8d2d), chr(0x56de)+chr(0x8d2d), chr(0x589e)+chr(0x6301)))
            event_score = 0.15 if ordinary_negative and not p0_negative else 0.0 if p0_negative else 1.0 if major_positive else 0.8
            matched_event_scores.append(event_score)
            evidence = {
                "factor": "event",
                "event_id": str(news.get("event_id") or f"event-{code}-{event_index}"),
                "statement": str(news.get("title") or "近期公告/新闻覆盖"),
                "value": event_score,
                "source": news.get("source") or "news",
                "url": news.get("url"),
                # Do not manufacture a news date from the report date. An
                # undated item may still affect the broad candidate score, but
                # cannot independently verify a current observation.
                "as_of": _date_value(news.get("published_at"), news.get("date")),
                "supports": not negative,
                "falsifier": "后续公告澄清或催化失效",
            }
            c.evidence.append(evidence)
            if not negative:
                c.valid_dimensions.add("event")
            if p0_negative:
                c.rejection_reasons.append("p0:重大负面公告/新闻风险否决")
        if matched_event_scores:
            c.event_score_rule = round(max(0.0, min(1.0, sum(matched_event_scores) / len(matched_event_scores))), 4)
            c.event_score = c.event_score_rule
            c.event_score_status = "available"
        elif provider_failed:
            c.event_score = None
            c.event_score_rule = None
            c.event_score_status = "provider_failed"
        else:
            c.event_score = 0.5
            c.event_score_rule = 0.5
            c.event_score_status = "no_relevant_news"
        if len(c.valid_dimensions) < 3:
            c.rejection_reasons.append("evidence:有效证据维度少于3个")
        c.data_quality = round(min(1.0, len(c.valid_dimensions) / 6.0), 3)
        c.quality_grade = "A" if len(c.valid_dimensions) >= 4 and history_days is not None and history_days >= 120 else "B" if len(c.valid_dimensions) >= 3 and history_days is not None and history_days >= 60 else "C"

        trend_factor = max(0.0, min(1.0, ((chg60 or 0.0) + 30.0) / 60.0)) if chg60 is not None else 0.0
        if r.get("above_ma20") is True:
            trend_factor = min(1.0, trend_factor + 0.1)
        if r.get("above_ma60") is True:
            trend_factor = min(1.0, trend_factor + 0.1)
        trend_factor = _path_adjusted_trend(chg60, return_20d, drawdown_60d, base=trend_factor if chg60 is not None else None)
        liquidity_factor = min(1.0, (amount or 0.0) / 500_000_000)
        if volume_ratio is not None:
            liquidity_factor = min(1.0, liquidity_factor * min(1.0, volume_ratio / 1.5))
        if turnover is not None and mc is not None and mc >= 100_000_000_000 and turnover < 1.0:
            liquidity_factor = min(liquidity_factor, 0.6)
        value_factor = max(0.0, min(1.0, 1.0 - (pe or max_pe) / max_pe)) if pe is not None and pe > 0 else 0.0
        industry = str(r.get("industry") or " ".join(c.focus_industries))
        if not industry:
            # Some upstream financial rows omit industry. Infer only the
            # unambiguous Chinese company-name classes so bank metrics are not
            # scored with industrial debt/cash heuristics.
            n = str(r.get("name") or "")
            if any(x in n for x in ("银行", "证券", "券商", "保险")):
                industry = n
        c.quality_evidence = assess_quality(r.get("financial_records") or [], as_of=snapshot.date,
                                            industry=industry)
        quality_score = c.quality_evidence.get("score")
        if quality_score is not None:
            # Keep the quality contribution proportional to actual coverage.
            quality_share = 0.5 * c.quality_evidence["metric_count"] / 4
            value_factor = value_factor * (1 - quality_share) + quality_score * quality_share
            c.evidence.append({"factor": "quality", "value": quality_score,
                               "statement": f"财报质量 {quality_score:.2f}，覆盖{c.quality_evidence['metric_count']}/4项",
                               "source": c.quality_evidence["source"], "as_of": c.quality_evidence["published_at"],
                               "supports": quality_score >= .5, "falsifier": "盈利质量或现金转换恶化"})
        capital_factor = _relative_capital_score(
            main_net=main_net, amount=amount, market_cap=mc, main_net_5d=main_net_5d,
        ) if main_net is not None else 0.0
        relative_factor = _path_adjusted_relative_strength(relative_excess, return_20d, drawdown_60d) if relative_excess is not None and r.get("benchmark_source") else 0.0
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
            "event": c.event_score,
            "risk": round(risk_penalty, 4),
        }
        event_factor = c.event_score if c.event_score is not None else 0.0
        c.composite = round(
            weights.get("trend", 0.25) * trend_factor
            + weights.get("price_volume", 0.20) * liquidity_factor
            + weights.get("value_quality", 0.15) * value_factor
            + weights.get("capital", 0.15) * capital_factor
            + weights.get("relative_strength", 0.15) * relative_factor
            + weights.get("event", 0.10) * event_factor
            + risk_penalty,
            4,
        )
        if (c.event_score or 0) >= 0.95:
            c.composite = round(min(1.0, c.composite + 0.05), 4)
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
                "price_as_of": c.price_as_of,
                "pe": c.pe,
                "pb": c.pb,
                "market_cap_yi": round(c.market_cap / 1e8, 1) if c.market_cap else None,
                "change_pct": c.change_pct,
                "change_60d_pct": c.change_60d_pct,
                "main_net_yi": round(c.main_net / 1e8, 3) if c.main_net else None,
                "fundamental_score": c.fundamental_score,
                "capital_score": c.capital_score,
                "event_score": c.event_score,
                "event_score_rule": c.event_score_rule,
                "event_score_llm": c.event_score_llm,
                "event_score_status": c.event_score_status,
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
                "quality_evidence": c.quality_evidence,
                "llm_review": getattr(c, "llm_review", ""),
                "llm_catalysts": list(getattr(c, "llm_catalysts", []) or []),
                "llm_risks": list(getattr(c, "llm_risks", []) or []),
                "llm_evidence_refs": list(getattr(c, "llm_evidence_refs", []) or []),
                "hotspot_themes": list(getattr(c, "hotspot_themes", []) or []),
                "hotspot_score": round(float(getattr(c, "hotspot_score", 0.0) or 0.0), 4),
                "hotspot_evidence": list(getattr(c, "hotspot_evidence", []) or []),
                "hotspot_industries": list(getattr(c, "hotspot_industries", []) or []),
                "hotspot_match_level": getattr(c, "hotspot_match_level", "none") or "none",
                "hotspot_mapping_sources": list(getattr(c, "hotspot_mapping_sources", []) or []),
                "hotspot_mapping_verified": bool(getattr(c, "hotspot_mapping_verified", False)),
            }
        )
    return out
