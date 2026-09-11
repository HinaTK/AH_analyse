"""Quality scoring and diversified portfolio selection for ETFs.

The module is deliberately deterministic.  LLM/hotspot output may only
contribute to the theme-match dimension supplied through ``hotspots``; hard
gates and all price/liquidity/risk dimensions remain rule based.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


ETF_WEIGHTS = {
    "trend": 0.30,
    "relative_strength": 0.20,
    "liquidity": 0.15,
    "risk_control": 0.20,
    "theme_match": 0.15,
}

MIN_TURNOVER = 100_000_000.0
MIN_TREND_SCORE = 60.0
MIN_HISTORY_DAYS = 60

_THEME_ALIASES = {
    "农业粮食": ("粮食", "农业", "农产品", "种植", "豆粕"),
    "能源化工": ("能源", "化工", "油气", "石油", "煤炭"),
    "黄金": ("黄金", "贵金属"),
    "半导体科技": ("半导体", "芯片", "科创", "创业板", "科技", "算力"),
    "新能源": ("新能源", "光伏", "储能", "锂电", "电池"),
    "证券金融": ("证券", "券商", "银行", "金融"),
    "医药医疗": ("医药", "医疗", "创新药"),
    "红利防御": ("红利", "高股息", "价值"),
    "宽基核心": ("沪深300", "上证50", "中证500", "中证1000", "宽基"),
    "海外科技": ("纳指", "纳斯达克", "恒生科技", "港股"),
    "债券防御": ("债券", "国债", "地方债", "信用债", "短融", "货币", "现金"),
}


def _float(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() in {"", "--", "None", "nan", "NaN"}:
            return None
        number = float(str(value).replace(",", ""))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _percentile(values: Sequence[float], value: Optional[float]) -> float:
    if value is None or not values:
        return 50.0
    if len(values) == 1:
        return 50.0
    below = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    return round((below + equal * 0.5) / len(values) * 100.0, 1)


def _name_text(row: Mapping[str, Any]) -> str:
    return "".join(str(row.get(key) or "") for key in ("name", "style", "category", "theme_group")).lower()


def _canonical_theme(text: Any) -> str:
    value = str(text or "")
    for canonical, aliases in _THEME_ALIASES.items():
        if any(alias.lower() in value.lower() for alias in aliases):
            return canonical
    return "unknown"


def classify_etf_exposure(row: Mapping[str, Any]) -> Dict[str, str]:
    """Return deterministic index/theme/exposure groups used for de-duplication."""
    underlying = str(row.get("underlying_index") or "").strip()
    if underlying:
        index_key = re.sub(r"\s+", "", underlying).lower()
    else:
        index_key = ""
    theme = str(row.get("theme_group") or "").strip() or _canonical_theme(_name_text(row))
    text = _name_text(row)
    if not index_key:
        index_key = f"theme:{theme}"
    if theme == "宽基核心":
        exposure = "broad_core"
    elif theme in {"农业粮食", "能源化工", "黄金"}:
        exposure = f"commodity_{theme}"
    elif theme in {"红利防御", "债券防御"} or bool(row.get("is_defensive")):
        exposure = "defensive"
    elif theme == "海外科技":
        exposure = "overseas"
    elif theme == "unknown" and "行业" in text:
        exposure = "industry_unknown"
    else:
        exposure = theme
    return {
        "underlying_index": index_key,
        "theme_group": theme,
        "exposure_group": exposure,
    }


def _hotspot_text(hotspots: Iterable[Mapping[str, Any]]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for item in hotspots
        for key in ("theme", "drivers", "industries")
        if item.get(key)
    ).lower()


def _theme_match_score(row: Mapping[str, Any], hotspots: Iterable[Mapping[str, Any]]) -> tuple[float, List[str]]:
    reasons: List[str] = []
    text = _name_text(row)
    matched = list(row.get("matched_themes") or [])
    rule_match = bool(matched) or _canonical_theme(text) != "unknown"
    score = 50.0
    if rule_match:
        score += 15.0
        reasons.append("规则主题映射有效")
    hotspot_blob = _hotspot_text(hotspots)
    if hotspot_blob and any(alias.lower() in hotspot_blob for alias in _THEME_ALIASES.get(_canonical_theme(text), ())):
        score += 30.0
        reasons.append("已验证消息热点匹配")
    elif hotspot_blob and any(token.lower() in hotspot_blob for token in ("能源", "油气", "农业", "粮食", "半导体", "医药", "证券")) and rule_match:
        score += 15.0
        reasons.append("消息热点与 ETF 主题部分匹配")
    return _clamp(score), reasons


def _gate(row: Mapping[str, Any], *, min_turnover: float = MIN_TURNOVER) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    status = str(row.get("status") or "")
    if status not in {"ok", "history_limited"}:
        reasons.append(f"status:{status or 'missing'}")
    history = _float(row.get("history_days"))
    if history is None or history < MIN_HISTORY_DAYS:
        reasons.append("history:<60d")
    turnover = _float(row.get("turnover"))
    if turnover is None or turnover < min_turnover:
        reasons.append(f"liquidity:<{min_turnover:g}")
    trend = _float(row.get("trend_score"))
    if trend is None or trend < MIN_TREND_SCORE:
        reasons.append("trend:<60")
    if row.get("above_ma60") is not True and row.get("above_ma_mid") is not True:
        reasons.append("ma60:not_above")
    if _float(row.get("ret_60d")) is None and _float(row.get("ret_midd")) is None:
        reasons.append("ret60:missing")
    if _float(row.get("volatility_20d_pct")) is None and _float(row.get("volatility_shortd_pct")) is None:
        reasons.append("volatility:missing")
    if _float(row.get("max_drawdown_60d_pct")) is None:
        reasons.append("drawdown:missing")
    return not reasons, reasons


def build_etf_quality_scores(
    rows: Iterable[Mapping[str, Any]],
    *,
    benchmark: Optional[Mapping[str, Any]] = None,
    hotspots: Optional[Iterable[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Attach five scores and gate diagnostics to ETF trend rows."""
    source = [dict(row) for row in rows]
    turnovers = [value for value in (_float(row.get("turnover")) for row in source) if value is not None]
    benchmark = benchmark or {}
    hotspot_rows = list(hotspots or [])
    output: List[Dict[str, Any]] = []
    for row in source:
        trend = _clamp(_float(row.get("trend_score")) if _float(row.get("trend_score")) is not None else 50.0)
        ret20 = _float(row.get("ret_20d") if row.get("ret_20d") is not None else row.get("ret_shortd"))
        ret60 = _float(row.get("ret_60d") if row.get("ret_60d") is not None else row.get("ret_midd"))
        ret120 = _float(row.get("ret_120d") if row.get("ret_120d") is not None else row.get("ret_longd"))
        diffs = []
        for value, key in ((ret20, "ret_20d"), (ret60, "ret_60d"), (ret120, "ret_120d")):
            base = _float(benchmark.get(key))
            if value is not None and base is not None:
                diffs.append(value - base)
        relative = _clamp(50.0 + (sum(diffs) / len(diffs) * 4.0 if diffs else 0.0))
        liquidity = _percentile(turnovers, _float(row.get("turnover")))
        drawdown = _float(row.get("max_drawdown_60d_pct"))
        volatility = _float(row.get("volatility_20d_pct") if row.get("volatility_20d_pct") is not None else row.get("volatility_shortd_pct"))
        drawdown_score = _clamp(100.0 + (drawdown or -30.0) * 3.0)
        volatility_score = _clamp(100.0 - ((volatility or 5.0) * 15.0))
        crowding_flags = 0
        if ret20 is not None and ret20 > 15:
            crowding_flags += 1
        gap = _float(row.get("breakout_gap_60d_pct") if row.get("breakout_gap_60d_pct") is not None else row.get("breakout_gap_pct"))
        if gap is not None and gap >= -2:
            crowding_flags += 1
        vol_values = [v for v in (_float(item.get("volatility_20d_pct")) for item in source) if v is not None]
        if volatility is not None and vol_values and volatility >= sorted(vol_values)[max(0, int(len(vol_values) * 0.75) - 1)]:
            crowding_flags += 1
        crowding_penalty = 20.0 if crowding_flags >= 3 else 10.0 if crowding_flags == 2 else 0.0
        risk_control = _clamp((drawdown_score * 0.6 + volatility_score * 0.4) - crowding_penalty)
        theme_match, theme_reasons = _theme_match_score(row, hotspot_rows)
        scores = {
            "trend": round(trend, 1),
            "relative_strength": round(relative, 1),
            "liquidity": round(liquidity, 1),
            "risk_control": round(risk_control, 1),
            "theme_match": round(theme_match, 1),
        }
        composite = round(sum(scores[key] * weight for key, weight in ETF_WEIGHTS.items()), 1)
        enriched = dict(row)
        enriched.update(classify_etf_exposure(enriched))
        enriched.update({
            "trend_score": trend,
            "relative_strength_score": scores["relative_strength"],
            "liquidity_score": scores["liquidity"],
            "risk_control_score": scores["risk_control"],
            "theme_match_score": scores["theme_match"],
            "composite_score": composite,
            "factor_scores": scores,
            "risk_flags": (["crowding_penalty"] if crowding_penalty else []),
            "theme_match_reasons": theme_reasons,
        })
        output.append(enriched)
    return output


def select_etf_portfolio(
    rows: Iterable[Mapping[str, Any]],
    *,
    limit: int = 3,
    min_score: float = 60.0,
    min_turnover: float = MIN_TURNOVER,
) -> Dict[str, Any]:
    """Select a small diversified ETF portfolio without filling weak slots."""
    limit = max(0, min(int(limit), 3))
    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    deduplicated: List[Dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        if "composite_score" not in row:
            row["composite_score"] = _float(row.get("score")) or _float(row.get("trend_score")) or 0.0
        row.update(classify_etf_exposure(row))
        passed, reasons = _gate(row, min_turnover=max(0.0, float(min_turnover)))
        if not passed or float(row.get("composite_score") or 0.0) < min_score:
            row["selection_status"] = "rejected"
            row["rejection_reasons"] = reasons or [f"score:<{min_score:g}"]
            rejected.append(row)
        else:
            row["selection_status"] = "candidate"
            candidates.append(row)
    candidates.sort(key=lambda item: (-float(item.get("composite_score") or 0.0), str(item.get("code") or "")))
    selected: List[Dict[str, Any]] = []
    seen_index: set[str] = set()
    seen_exposure: set[str] = set()
    for row in candidates:
        if len(selected) >= limit:
            break
        duplicate_kind = None
        if row["underlying_index"] in seen_index:
            duplicate_kind = "underlying_index"
        elif row["exposure_group"] in seen_exposure:
            duplicate_kind = "exposure_group"
        if duplicate_kind:
            row["selection_status"] = "deduplicated"
            row["rejection_reasons"] = [f"duplicate:{duplicate_kind}"]
            deduplicated.append(row)
            continue
        row["selection_status"] = "selected"
        row["position"] = (
            "防御"
            if row.get("is_defensive") or row.get("exposure_group") == "defensive"
            else "核心"
            if row.get("exposure_group") == "broad_core"
            else "主线"
        )
        row["selection_reasons"] = list(row.get("theme_match_reasons") or []) + [
            f"综合分 {float(row['composite_score']):.1f}"
        ]
        selected.append(row)
        seen_index.add(row["underlying_index"])
        seen_exposure.add(row["exposure_group"])
    available = len(selected)
    missing_reason = ""
    if available < limit:
        missing_reason = f"可用 ETF 数量不足 {limit} 只（当前 {available} 只），未为凑数补入低质量标的"
    return {
        "selected": selected,
        "rejected": rejected,
        "deduplicated": deduplicated,
        "portfolio_summary": {
            "count": available,
            "missing_slots_reason": missing_reason,
            "diversification_score": round(min(100.0, 40.0 + len(seen_exposure) * 20.0), 1),
            "exposure_groups": sorted(seen_exposure),
        },
    }
