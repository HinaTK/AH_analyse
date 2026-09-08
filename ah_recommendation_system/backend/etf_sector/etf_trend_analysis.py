from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
from loguru import logger


@dataclass(frozen=True)
class EtfUniverseItem:
    code: str
    name: str
    category: str
    style: str
    is_defensive: bool = False
    is_overseas: bool = False


@dataclass(frozen=True)
class TrendAnalysisParameters:
    lookback_short: int = 20
    lookback_mid: int = 60
    lookback_long: int = 120
    breakout_window: int = 60


DEFAULT_ETF_UNIVERSE: List[EtfUniverseItem] = [
    EtfUniverseItem("510300", "沪深300ETF", "宽基", "大盘核心"),
    EtfUniverseItem("510050", "上证50ETF", "宽基", "蓝筹价值"),
    EtfUniverseItem("510500", "中证500ETF", "宽基", "中盘成长"),
    EtfUniverseItem("512100", "中证1000ETF", "宽基", "小盘弹性"),
    EtfUniverseItem("159915", "创业板ETF", "成长", "科技成长"),
    EtfUniverseItem("512880", "证券ETF", "行业", "高贝塔"),
    EtfUniverseItem("512010", "医药ETF", "行业", "防御成长", is_defensive=True),
    EtfUniverseItem("515180", "红利ETF", "防御", "高股息", is_defensive=True),
    EtfUniverseItem("518880", "黄金ETF", "商品", "避险资产", is_defensive=True),
    EtfUniverseItem("513100", "纳指ETF", "海外", "美股科技", is_overseas=True),
]

DEFAULT_PARAMETERS = TrendAnalysisParameters()
_ETF_CODE_PATTERN = re.compile(r"\d{6}")
_DEFAULT_ETF_MAP = {item.code: item for item in DEFAULT_ETF_UNIVERSE}
_HISTORY_FETCH_RETRY_DELAYS = (0.35, 0.8)

RECOMMENDATION_PRIORITY = {
    "优先关注": 0,
    "持有观察": 1,
    "暂不关注": 2,
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if not text or text in {"--", "None", "nan", "NaN"}:
                return None
            return float(text)
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            return int(float(text))
        return int(value)
    except Exception:
        return None


def _sanitize_period(
    value: Any, default: int, *, min_value: int = 5, max_value: int = 250
) -> int:
    parsed = _to_int(value)
    if parsed is None:
        return default
    return max(min_value, min(max_value, parsed))


def sanitize_trend_analysis_parameters(
    *,
    lookback_short: Any = None,
    lookback_mid: Any = None,
    lookback_long: Any = None,
    breakout_window: Any = None,
) -> TrendAnalysisParameters:
    short = _sanitize_period(lookback_short, DEFAULT_PARAMETERS.lookback_short)
    mid = _sanitize_period(lookback_mid, DEFAULT_PARAMETERS.lookback_mid)
    long = _sanitize_period(lookback_long, DEFAULT_PARAMETERS.lookback_long)
    breakout = _sanitize_period(
        breakout_window,
        DEFAULT_PARAMETERS.breakout_window,
        min_value=10,
        max_value=250,
    )

    if not (short < mid < long):
        short = DEFAULT_PARAMETERS.lookback_short
        mid = DEFAULT_PARAMETERS.lookback_mid
        long = DEFAULT_PARAMETERS.lookback_long

    return TrendAnalysisParameters(
        lookback_short=short,
        lookback_mid=mid,
        lookback_long=long,
        breakout_window=breakout,
    )


def resolve_etf_universe(
    codes: Optional[str] = None,
    universe_items: Optional[List[Dict[str, Any]]] = None,
) -> List[EtfUniverseItem]:
    if isinstance(universe_items, list) and universe_items:
        seen = set()
        universe: List[EtfUniverseItem] = []
        for raw in universe_items:
            if not isinstance(raw, dict):
                continue
            code = _to_text_code(raw.get("code"))
            if not code or code in seen:
                continue
            seen.add(code)
            universe.append(
                EtfUniverseItem(
                    code=code,
                    name=str(raw.get("name") or f"ETF {code}"),
                    category=str(raw.get("category") or "自动筛选"),
                    style=str(raw.get("style") or "主题候选"),
                    is_defensive=bool(raw.get("is_defensive")),
                    is_overseas=bool(raw.get("is_overseas")),
                )
            )
        if universe:
            return universe

    if not isinstance(codes, str) or not codes.strip():
        return list(DEFAULT_ETF_UNIVERSE)

    seen = set()
    universe: List[EtfUniverseItem] = []
    raw_items = re.split(r"[,，;；\s]+", codes.strip())
    for raw in raw_items:
        if not raw:
            continue
        match = _ETF_CODE_PATTERN.search(raw)
        if not match:
            continue
        code = match.group(0)
        if code in seen:
            continue
        seen.add(code)

        known_item = _DEFAULT_ETF_MAP.get(code)
        if known_item:
            universe.append(known_item)
        else:
            universe.append(
                EtfUniverseItem(
                    code=code,
                    name=f"ETF {code}",
                    category="自定义",
                    style="未分类",
                )
            )

    return universe or list(DEFAULT_ETF_UNIVERSE)


def _to_text_code(value: Any) -> Optional[str]:
    match = _ETF_CODE_PATTERN.search(str(value or ""))
    return match.group(0) if match else None


def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "close", "high"])

    date_col = next(
        (c for c in df.columns if str(c) in {"日期", "净值日期", "交易日期", "date"}),
        df.columns[0],
    )
    close_col = next(
        (
            c
            for c in df.columns
            if str(c) in {"收盘", "收盘价", "单位净值", "最新价", "close"}
        ),
        df.columns[2] if len(df.columns) > 2 else df.columns[-1],
    )
    high_col = next(
        (c for c in df.columns if str(c) in {"最高", "最高价", "high"}),
        df.columns[3] if len(df.columns) > 3 else close_col,
    )

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "high": pd.to_numeric(df[high_col], errors="coerce"),
        }
    )
    out = (
        out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    )
    if "high" not in out or out["high"].isna().all():
        out["high"] = out["close"]
    else:
        out["high"] = out["high"].fillna(out["close"])
    return out


def _filter_history_window(
    hist: pd.DataFrame, start_date: str, end_date: str
) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame(columns=["date", "close", "high"])

    start = pd.to_datetime(start_date, format="%Y%m%d", errors="coerce")
    end = pd.to_datetime(end_date, format="%Y%m%d", errors="coerce")
    out = hist
    if pd.notna(start):
        out = out[out["date"] >= start]
    if pd.notna(end):
        out = out[out["date"] <= end]
    return out.reset_index(drop=True)


def fetch_etf_hist_em(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak

    return ak.fund_etf_hist_em(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )


def fetch_etf_hist_em_unadjusted(
    symbol: str, start_date: str, end_date: str
) -> pd.DataFrame:
    import akshare as ak

    return ak.fund_etf_hist_em(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="",
    )


def _normalize_sina_etf_symbol(symbol: str) -> str:
    code = str(symbol or "").strip()
    if code.startswith(("sh", "sz")):
        return code
    if not _ETF_CODE_PATTERN.fullmatch(code):
        return code
    if code.startswith(("1", "3")):
        return f"sz{code}"
    return f"sh{code}"


def fetch_etf_hist_sina(symbol: str) -> pd.DataFrame:
    import akshare as ak

    return ak.fund_etf_hist_sina(symbol=_normalize_sina_etf_symbol(symbol))


def _is_non_empty_history(df: Optional[pd.DataFrame]) -> bool:
    return df is not None and not df.empty


def _fetch_history_with_retries(
    fetcher: Callable[..., pd.DataFrame],
    *args: Any,
    source_name: str,
    retry_delays: Tuple[float, ...] = _HISTORY_FETCH_RETRY_DELAYS,
    **kwargs: Any,
) -> pd.DataFrame:
    attempts = len(retry_delays) + 1
    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            df = fetcher(*args, **kwargs)
            if _is_non_empty_history(df):
                return df
            last_error = ValueError("empty_history")
        except Exception as exc:
            last_error = exc
        if attempt < len(retry_delays):
            delay = retry_delays[attempt]
            logger.warning(
                f"etf_history_retry source={source_name} attempt={attempt + 1}/{attempts}: {last_error}"
            )
            time.sleep(delay)
    if last_error:
        raise last_error
    return pd.DataFrame()


def fetch_etf_history_with_fallback(
    symbol: str, start_date: str, end_date: str
) -> Tuple[pd.DataFrame, str]:
    errors: List[str] = []
    fetch_plan = [
        (
            "eastmoney_qfq",
            fetch_etf_hist_em,
            {"symbol": symbol, "start_date": start_date, "end_date": end_date},
        ),
        (
            "eastmoney_raw",
            fetch_etf_hist_em_unadjusted,
            {"symbol": symbol, "start_date": start_date, "end_date": end_date},
        ),
        (
            "sina",
            fetch_etf_hist_sina,
            {"symbol": symbol},
        ),
    ]

    for source_name, fetcher, kwargs in fetch_plan:
        try:
            df = _fetch_history_with_retries(
                fetcher,
                source_name=source_name,
                **kwargs,
            )
            if _is_non_empty_history(df):
                return df, source_name
        except Exception as exc:
            errors.append(f"{source_name}:{exc}")

    raise RuntimeError("; ".join(errors) or "empty_history")


def _calc_return(series: pd.Series, lookback: int) -> Optional[float]:
    if series is None or lookback <= 0 or len(series) <= lookback:
        return None
    prev = _to_float(series.iloc[-(lookback + 1)])
    last = _to_float(series.iloc[-1])
    if prev in (None, 0) or last is None:
        return None
    return round((last / prev - 1.0) * 100.0, 2)


def _round_or_none(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _clip_score(value: Optional[float], scale: float, weight: float) -> float:
    if value is None or scale <= 0:
        return 0.0
    ratio = max(-1.0, min(1.0, float(value) / scale))
    return ratio * weight


def _metric_aliases(
    params: TrendAnalysisParameters, metrics: Dict[str, Any]
) -> Dict[str, Any]:
    aliases: Dict[str, Any] = {}
    if params.lookback_short == 20:
        aliases["ret_20d"] = metrics.get("ret_shortd")
        aliases["ma20"] = metrics.get("ma_short")
        aliases["above_ma20"] = metrics.get("above_ma_short")
        aliases["volatility_20d_pct"] = metrics.get("volatility_shortd_pct")
    if params.lookback_mid == 60:
        aliases["ret_60d"] = metrics.get("ret_midd")
        aliases["ma60"] = metrics.get("ma_mid")
        aliases["above_ma60"] = metrics.get("above_ma_mid")
    if params.lookback_long == 120:
        aliases["ret_120d"] = metrics.get("ret_longd")
    if params.lookback_short == 20 and params.lookback_mid == 60:
        aliases["ma20_above_ma60"] = metrics.get("ma_short_above_ma_mid")
    if params.breakout_window == 60:
        aliases["breakout_gap_60d_pct"] = metrics.get("breakout_gap_pct")
    return aliases


def _build_reasons(
    metrics: Dict[str, Any], history_days: int, params: TrendAnalysisParameters
) -> List[str]:
    reasons: List[str] = []
    ret_short = metrics.get("ret_shortd")
    ret_mid = metrics.get("ret_midd")
    if ret_short is not None and ret_mid is not None:
        reasons.append(
            f"{params.lookback_short}/{params.lookback_mid}日收益为 {ret_short:.1f}% / {ret_mid:.1f}%"
        )
    elif ret_short is not None:
        reasons.append(f"{params.lookback_short}日收益为 {ret_short:.1f}%")

    above_ma_short = metrics.get("above_ma_short")
    above_ma_mid = metrics.get("above_ma_mid")
    ma_short_above_ma_mid = metrics.get("ma_short_above_ma_mid")
    if above_ma_short and above_ma_mid:
        reasons.append(f"价格站上 MA{params.lookback_short} 与 MA{params.lookback_mid}")
    elif above_ma_mid is False:
        reasons.append(f"价格仍位于 MA{params.lookback_mid} 下方")
    elif above_ma_short is False:
        reasons.append(f"短线回落至 MA{params.lookback_short} 下方")

    if ma_short_above_ma_mid is True:
        reasons.append(
            f"MA{params.lookback_short} 高于 MA{params.lookback_mid}，中期趋势偏强"
        )
    elif ma_short_above_ma_mid is False:
        reasons.append(
            f"MA{params.lookback_short} 低于 MA{params.lookback_mid}，中期修复仍待确认"
        )

    breakout_gap = metrics.get("breakout_gap_pct")
    if breakout_gap is not None:
        if breakout_gap >= 0:
            reasons.append(f"已突破近{params.breakout_window}日高点")
        elif breakout_gap >= -3:
            reasons.append(f"距离近{params.breakout_window}日高点较近")
        elif breakout_gap <= -12:
            reasons.append(f"距离近{params.breakout_window}日高点仍较远")

    volatility = metrics.get("volatility_shortd_pct")
    if volatility is not None and volatility >= 2.8:
        reasons.append(f"{params.lookback_short}日波动率 {volatility:.1f}%，波动偏大")
    elif volatility is not None and volatility <= 1.2:
        reasons.append(f"{params.lookback_short}日波动率 {volatility:.1f}%，波动较稳")

    if history_days < params.lookback_long:
        reasons.append(
            f"历史样本 {history_days} 日，{params.lookback_long}日指标参考有限"
        )

    deduped: List[str] = []
    for item in reasons:
        if item not in deduped:
            deduped.append(item)
    return deduped[:4]


def _trend_label(score: float) -> str:
    if score >= 78:
        return "强势上涨"
    if score >= 63:
        return "震荡偏强"
    if score >= 45:
        return "震荡"
    if score >= 30:
        return "震荡偏弱"
    return "弱势下行"


def _recommendation(score: float, metrics: Dict[str, Any]) -> str:
    ret_short = metrics.get("ret_shortd")
    above_ma_mid = metrics.get("above_ma_mid")
    if score >= 70 and (ret_short or 0) > 0 and above_ma_mid is True:
        return "优先关注"
    if score >= 45:
        return "持有观察"
    return "暂不关注"


def _empty_result(
    item: EtfUniverseItem, *, status: str, reasons: List[str], error: str
) -> Dict[str, Any]:
    return {
        "code": item.code,
        "name": item.name,
        "category": item.category,
        "style": item.style,
        "is_defensive": item.is_defensive,
        "is_overseas": item.is_overseas,
        "status": status,
        "trend_label": "数据缺失",
        "recommendation": "持有观察",
        "recommendation_priority": RECOMMENDATION_PRIORITY["持有观察"],
        "reasons": reasons,
        "error": error,
    }


def _build_one_etf(
    item: EtfUniverseItem,
    start_date: str,
    end_date: str,
    params: TrendAnalysisParameters,
) -> Dict[str, Any]:
    try:
        raw, history_source = fetch_etf_history_with_fallback(
            item.code, start_date, end_date
        )
        hist = _filter_history_window(
            _normalize_history(raw), start_date=start_date, end_date=end_date
        )
        if hist.empty:
            return _empty_result(
                item,
                status="fetch_failed",
                reasons=["未获取到有效日线数据"],
                error="empty_history",
            )

        history_days = int(len(hist))
        close = hist["close"]
        daily_ret = close.pct_change()
        ma_short = (
            close.rolling(params.lookback_short).mean().iloc[-1]
            if history_days >= params.lookback_short
            else None
        )
        ma_mid = (
            close.rolling(params.lookback_mid).mean().iloc[-1]
            if history_days >= params.lookback_mid
            else None
        )
        breakout_high = (
            hist["high"].rolling(params.breakout_window).max().iloc[-1]
            if history_days >= params.breakout_window
            else None
        )
        last_close = _to_float(close.iloc[-1])
        last_date = hist["date"].iloc[-1].strftime("%Y-%m-%d")
        volatility = (
            _to_float(daily_ret.tail(params.lookback_short).std(ddof=0)) * 100.0
            if history_days >= params.lookback_short + 1
            and daily_ret.tail(params.lookback_short).notna().sum()
            >= max(10, int(params.lookback_short * 0.7))
            else None
        )
        breakout_gap = (
            ((last_close / breakout_high) - 1.0) * 100.0
            if last_close not in (None, 0) and breakout_high not in (None, 0)
            else None
        )

        metrics = {
            "ret_shortd": _calc_return(close, params.lookback_short),
            "ret_midd": _calc_return(close, params.lookback_mid),
            "ret_longd": _calc_return(close, params.lookback_long),
            "ma_short": _round_or_none(_to_float(ma_short)),
            "ma_mid": _round_or_none(_to_float(ma_mid)),
            "above_ma_short": None
            if ma_short is None or last_close is None
            else bool(last_close >= ma_short),
            "above_ma_mid": None
            if ma_mid is None or last_close is None
            else bool(last_close >= ma_mid),
            "ma_short_above_ma_mid": None
            if ma_short is None or ma_mid is None
            else bool(ma_short >= ma_mid),
            "volatility_shortd_pct": _round_or_none(volatility),
            "breakout_gap_pct": _round_or_none(breakout_gap),
            "returns_pct": {
                "short": _calc_return(close, params.lookback_short),
                "mid": _calc_return(close, params.lookback_mid),
                "long": _calc_return(close, params.lookback_long),
            },
            "moving_averages": {
                "short": _round_or_none(_to_float(ma_short)),
                "mid": _round_or_none(_to_float(ma_mid)),
            },
        }
        metrics.update(_metric_aliases(params, metrics))

        score = 50.0
        score += _clip_score(metrics["ret_shortd"], 8.0, 14.0)
        score += _clip_score(metrics["ret_midd"], 15.0, 16.0)
        score += _clip_score(metrics["ret_longd"], 25.0, 14.0)
        score += (
            8.0
            if metrics["above_ma_short"] is True
            else -8.0
            if metrics["above_ma_short"] is False
            else 0.0
        )
        score += (
            12.0
            if metrics["above_ma_mid"] is True
            else -12.0
            if metrics["above_ma_mid"] is False
            else 0.0
        )
        score += (
            6.0
            if metrics["ma_short_above_ma_mid"] is True
            else -6.0
            if metrics["ma_short_above_ma_mid"] is False
            else 0.0
        )
        if metrics["breakout_gap_pct"] is not None:
            if metrics["breakout_gap_pct"] >= 0:
                score += 8.0
            elif metrics["breakout_gap_pct"] >= -3:
                score += 4.0
            elif metrics["breakout_gap_pct"] <= -12:
                score -= 6.0
        if metrics["volatility_shortd_pct"] is not None:
            if metrics["volatility_shortd_pct"] >= 2.8:
                score -= 4.0
            elif metrics["volatility_shortd_pct"] <= 1.2:
                score += 2.0
        score = max(0.0, min(100.0, score))
        score = round(score, 1)

        insufficient_threshold = max(40, params.lookback_short * 2)
        if history_days < insufficient_threshold:
            trend_label = "样本不足"
            recommendation = "持有观察"
            status = "insufficient_history"
        else:
            trend_label = _trend_label(score)
            recommendation = _recommendation(score, metrics)
            status = "history_limited" if history_days < params.lookback_long else "ok"

        return {
            "code": item.code,
            "name": item.name,
            "category": item.category,
            "style": item.style,
            "is_defensive": item.is_defensive,
            "is_overseas": item.is_overseas,
            "source": history_source,
            "status": status,
            "history_days": history_days,
            "last_date": last_date,
            "last_close": _round_or_none(last_close, 3),
            **metrics,
            "trend_score": score,
            "trend_label": trend_label,
            "recommendation": recommendation,
            "recommendation_priority": RECOMMENDATION_PRIORITY[recommendation],
            "reasons": _build_reasons(metrics, history_days, params),
        }
    except Exception as exc:
        logger.warning(
            f"etf_trend_fetch_failed code={item.code} name={item.name}: {exc}"
        )
        return _empty_result(
            item,
            status="fetch_failed",
            reasons=["数据抓取失败，建议参考存量报告"],
            error=str(exc),
        )


def _market_regime(
    valid_rows: List[Dict[str, Any]], params: TrendAnalysisParameters
) -> Dict[str, Any]:
    if not valid_rows:
        return {
            "regime_label": "数据不足",
            "market_summary": "ETF 趋势样本不足，建议等待数据恢复后再判断。",
            "market_tags": ["样本不足"],
        }

    avg_score = round(
        sum(float(r.get("trend_score") or 0.0) for r in valid_rows) / len(valid_rows),
        1,
    )
    above_ma60_count = sum(1 for r in valid_rows if r.get("above_ma_mid") is True)
    focus_count = sum(1 for r in valid_rows if r.get("recommendation") == "优先关注")
    breadth = above_ma60_count / len(valid_rows)

    if avg_score >= 68 and breadth >= 0.6:
        regime_label = "偏强轮动"
        market_summary = "多数 ETF 站上中期均线，趋势偏强，适合优先跟踪强势方向。"
    elif avg_score >= 56 and breadth >= 0.45:
        regime_label = "结构偏强"
        market_summary = "市场仍以结构性机会为主，强势ETF可继续跟踪，弱势方向不宜追。"
    elif avg_score >= 44 and breadth >= 0.3:
        regime_label = "震荡分化"
        market_summary = "不同方向分化明显，宜精选趋势更清晰的ETF，避免全面加仓。"
    else:
        regime_label = "风险偏弱"
        market_summary = "整体趋势偏弱，建议以防守观察为主，等待广度改善。"

    tags = [
        regime_label,
        f"站上MA{params.lookback_mid} {above_ma60_count}/{len(valid_rows)}",
        f"优先关注 {focus_count}只",
    ]
    return {
        "regime_label": regime_label,
        "avg_score": avg_score,
        "market_summary": market_summary,
        "market_tags": tags,
    }


def generate_etf_trend_recommendation_block(
    *,
    codes: Optional[str] = None,
    universe_items: Optional[List[Dict[str, Any]]] = None,
    lookback_short: Any = None,
    lookback_mid: Any = None,
    lookback_long: Any = None,
    breakout_window: Any = None,
) -> Dict[str, Any]:
    params = sanitize_trend_analysis_parameters(
        lookback_short=lookback_short,
        lookback_mid=lookback_mid,
        lookback_long=lookback_long,
        breakout_window=breakout_window,
    )
    universe = resolve_etf_universe(codes, universe_items=universe_items)

    max_window = max(
        params.lookback_short,
        params.lookback_mid,
        params.lookback_long,
        params.breakout_window,
    )
    history_days = max(540, max_window * 4)
    end = datetime.now()
    start = end - timedelta(days=history_days)
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")

    recommendations = [
        _build_one_etf(item, start_date=start_date, end_date=end_date, params=params)
        for item in universe
    ]
    recommendations.sort(
        key=lambda r: (
            int(r.get("recommendation_priority", 9)),
            -float(r.get("trend_score") or 0.0),
            str(r.get("code") or ""),
        )
    )

    valid_rows = [
        r for r in recommendations if r.get("status") in {"ok", "history_limited"}
    ]
    failed_rows = [r for r in recommendations if r.get("status") == "fetch_failed"]
    insufficient_rows = [
        r for r in recommendations if r.get("status") == "insufficient_history"
    ]
    regime = _market_regime(valid_rows, params)

    strongest = [
        {
            "code": r.get("code"),
            "name": r.get("name"),
            "category": r.get("category"),
            "trend_label": r.get("trend_label"),
            "recommendation": r.get("recommendation"),
            "trend_score": r.get("trend_score"),
        }
        for r in valid_rows[:3]
    ]
    defensive_candidates = [
        {
            "code": r.get("code"),
            "name": r.get("name"),
            "category": r.get("category"),
            "trend_label": r.get("trend_label"),
            "recommendation": r.get("recommendation"),
            "trend_score": r.get("trend_score"),
        }
        for r in sorted(
            [r for r in valid_rows if r.get("is_defensive")],
            key=lambda r: (
                int(r.get("recommendation_priority", 9)),
                -float(r.get("trend_score") or 0.0),
            ),
        )[:3]
    ]

    return {
        "generated_at": _now_str(),
        "source": "eastmoney",
        "parameters": {
            "lookback_short": params.lookback_short,
            "lookback_mid": params.lookback_mid,
            "lookback_long": params.lookback_long,
            "breakout_window": params.breakout_window,
        },
        "analysis_window": {
            "start_date": start_date,
            "end_date": end_date,
            "adjust": "qfq",
            "lookbacks": [
                params.lookback_short,
                params.lookback_mid,
                params.lookback_long,
            ],
            "breakout_window": params.breakout_window,
            "parameters": {
                "lookback_short": params.lookback_short,
                "lookback_mid": params.lookback_mid,
                "lookback_long": params.lookback_long,
                "breakout_window": params.breakout_window,
            },
        },
        "coverage": {
            "universe_count": len(universe),
            "success_count": len(valid_rows),
            "history_limited_count": len(
                [r for r in recommendations if r.get("status") == "history_limited"]
            ),
            "insufficient_count": len(insufficient_rows),
            "failed_count": len(failed_rows),
            "custom_universe": bool(
                (isinstance(codes, str) and codes.strip())
                or (isinstance(universe_items, list) and len(universe_items) > 0)
            ),
        },
        "summary": {
            **regime,
            "recommended_count": sum(
                1 for r in recommendations if r.get("recommendation") == "优先关注"
            ),
            "watch_count": sum(
                1 for r in recommendations if r.get("recommendation") == "持有观察"
            ),
            "avoid_count": sum(
                1 for r in recommendations if r.get("recommendation") == "暂不关注"
            ),
            "strongest_etfs": strongest,
            "defensive_etfs": defensive_candidates,
            "errors": [
                {
                    "code": r.get("code"),
                    "name": r.get("name"),
                    "error": r.get("error") or "fetch_failed",
                }
                for r in failed_rows
            ],
        },
        "universe": [
            {
                "code": item.code,
                "name": item.name,
                "category": item.category,
                "style": item.style,
                "is_defensive": item.is_defensive,
                "is_overseas": item.is_overseas,
            }
            for item in universe
        ],
        "recommendations": recommendations,
    }
