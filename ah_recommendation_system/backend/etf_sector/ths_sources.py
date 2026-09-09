from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from loguru import logger


_SUSPICIOUS_MOJIBAKE_CHARS = set(
    "ÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿŒœŠšŸŽž€‚ƒ„…†‡ˆ‰‹›™"
)


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, str):
            s = x.strip().replace(",", "")
            if not s or s in ("--", "nan", "None"):
                return None
            return float(s)
        return float(x)
    except Exception:
        return None


def _to_int(x: Any) -> Optional[int]:
    try:
        v = _to_float(x)
        return int(v) if v is not None else None
    except Exception:
        return None


def _safe_head(df: pd.DataFrame, n: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    return df.head(n).copy()


def _is_missing_value(value: Any) -> bool:
    try:
        return value is None or bool(pd.isna(value))
    except Exception:
        return value is None


def _count_cjk_chars(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _count_suspicious_chars(text: str) -> int:
    return sum(
        1 for ch in text if ch in _SUSPICIOUS_MOJIBAKE_CHARS or 0x80 <= ord(ch) <= 0x9F
    )


def normalize_display_text(value: Any) -> str:
    """Conservatively repair common UTF-8 mojibake in display text."""
    if _is_missing_value(value):
        return ""

    text = str(value).replace("\x00", "").replace("\xa0", " ").strip()
    if not text:
        return ""

    if "�" in text:
        return text

    base_cjk = _count_cjk_chars(text)
    base_suspicious = _count_suspicious_chars(text)
    if base_suspicious == 0 and base_cjk > 0:
        return text

    best = text
    best_cjk = base_cjk
    best_suspicious = base_suspicious

    for source_encoding in ("latin1", "cp1252"):
        try:
            candidate = text.encode(source_encoding).decode("utf-8")
        except Exception:
            continue
        candidate = candidate.replace("\x00", "").replace("\xa0", " ").strip()
        if not candidate or "�" in candidate:
            continue
        candidate_cjk = _count_cjk_chars(candidate)
        candidate_suspicious = _count_suspicious_chars(candidate)
        if candidate_cjk <= 0:
            continue
        if candidate_cjk < best_cjk:
            continue
        if candidate_cjk == best_cjk and candidate_suspicious >= best_suspicious:
            continue
        if candidate_cjk == best_cjk and best_cjk == base_cjk:
            continue
        best = candidate
        best_cjk = candidate_cjk
        best_suspicious = candidate_suspicious

    if best_cjk > base_cjk and best_suspicious <= base_suspicious:
        return best
    if best_cjk == base_cjk and best_cjk > 0 and best_suspicious < base_suspicious:
        return best
    return text


def fetch_etf_spot_ths() -> pd.DataFrame:
    import akshare as ak

    # doc: fund_etf_spot_ths(date="")
    return ak.fund_etf_spot_ths(date="")


def fetch_etf_spot_sina() -> pd.DataFrame:
    import akshare as ak

    # doc: fund_etf_category_sina(symbol="ETF基金")
    return ak.fund_etf_category_sina(symbol="ETF基金")


def fetch_stock_a_spot_sina() -> pd.DataFrame:
    import akshare as ak

    # doc: stock_zh_a_spot (sina)
    return ak.stock_zh_a_spot()


def fetch_industry_summary_ths() -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_industry_summary_ths()


def fetch_concept_name_ths() -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_concept_name_ths()


def fetch_industry_name_ths() -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_industry_name_ths()


def fetch_concept_summary_ths() -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_concept_summary_ths()


def fetch_concept_info_ths(symbol: str) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_concept_info_ths(symbol=symbol)


def fetch_concept_index_ths(
    symbol: str, start_date: str, end_date: str
) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_concept_index_ths(
        symbol=symbol, start_date=start_date, end_date=end_date
    )


def fetch_industry_info_ths(symbol: str) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_industry_info_ths(symbol=symbol)


def fetch_industry_index_ths(
    symbol: str, start_date: str, end_date: str
) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_industry_index_ths(
        symbol=symbol, start_date=start_date, end_date=end_date
    )


def normalize_etf_spot_ths(
    df: pd.DataFrame, *, limit: int = 60
) -> List[Dict[str, Any]]:
    """Normalize THS ETF spot data.

    THS columns are stable but can appear garbled in some consoles; map by position.
    Expected order (from AKShare docs):
    [序号, 基金代码, 基金名称, 当前-单位净值, 当前-累计净值, 前一日-单位净值, 前一日-累计净值, 增长值, 增长率, 赎回状态, 申购状态, 最新-交易日, 最新-单位净值, 最新-累计净值, 基金类型, 查询日期]
    """
    if df is None or df.empty:
        return []

    out: List[Dict[str, Any]] = []
    df2 = _safe_head(df, max(limit, 10))
    for _, row in df2.iterrows():
        code = str(row.iloc[1])
        name = normalize_display_text(row.iloc[2])
        growth_pct = _to_float(row.iloc[8])
        unit_nav = _to_float(row.iloc[3])
        fund_type = normalize_display_text(row.iloc[14]) if len(row) > 14 else ""
        out.append(
            {
                "code": code,
                "name": name,
                "chg_pct": growth_pct,
                "unit_nav": unit_nav,
                "fund_type": fund_type,
                "source": "ths",
            }
        )

    # Sort by chg_pct desc if present
    out.sort(key=lambda r: (r.get("chg_pct") is None, -(r.get("chg_pct") or 0.0)))
    return out[:limit]


def normalize_etf_spot_sina(
    df: pd.DataFrame, *, limit: int = 100
) -> List[Dict[str, Any]]:
    """Normalize Sina ETF list/spot.

    Expected order (AKShare docs):
    [代码, 名称, 最新价, 涨跌额, 涨跌幅, 买入, 卖出, 昨收, 今开, 最高, 最低, 成交量, 成交额]
    """
    if df is None or df.empty:
        return []
    rows: List[Dict[str, Any]] = []
    df2 = _safe_head(df, max(limit, 10))
    for _, row in df2.iterrows():
        code_raw = str(row.iloc[0])
        name = normalize_display_text(row.iloc[1])
        price = _to_float(row.iloc[2])
        chg_pct = _to_float(row.iloc[4])
        vol = _to_int(row.iloc[11])
        amt = _to_float(row.iloc[12])
        # code like sh510300/sz159915
        code = code_raw
        rows.append(
            {
                "code": code,
                "name": name,
                "price": price,
                "chg_pct": chg_pct,
                "volume": vol,
                "turnover": amt,
                "source": "sina",
            }
        )

    # Keep ETF only (rough filter)
    rows = [r for r in rows if str(r.get("code") or "").startswith(("sh", "sz"))]
    # Sort by turnover if available
    rows.sort(key=lambda r: (r.get("turnover") is None, -(r.get("turnover") or 0.0)))
    return rows[:limit]


def normalize_industry_summary_ths(
    df: pd.DataFrame, *, limit: int = 20
) -> Dict[str, List[Dict[str, Any]]]:
    """Normalize THS industry summary.

    Returns top_gainers/top_losers based on pct change.
    """
    if df is None or df.empty:
        return {"top_gainers": [], "top_losers": []}
    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        name = normalize_display_text(row.iloc[1])
        chg_pct = _to_float(row.iloc[2])
        turnover_yi = _to_float(row.iloc[3])
        leader = normalize_display_text(row.iloc[9]) if len(row) > 9 else ""
        leader_chg = _to_float(row.iloc[10]) if len(row) > 10 else None
        rows.append(
            {
                "name": name,
                "chg_pct": chg_pct,
                "turnover_yi": turnover_yi,
                "leader": leader,
                "leader_chg_pct": leader_chg,
                "source": "ths",
            }
        )
    rows_ok = [r for r in rows if r.get("chg_pct") is not None]
    advance_count = sum(1 for row in rows_ok if float(row.get("chg_pct") or 0.0) > 0)
    total_count = len(rows_ok)
    for row in rows_ok:
        row["advance_count"] = advance_count
        row["total_count"] = total_count
    rows_ok.sort(key=lambda r: float(r.get("chg_pct") or 0.0), reverse=True)
    top = rows_ok[:limit]
    bottom = list(reversed(rows_ok[-limit:]))
    return {"top_gainers": top, "top_losers": bottom}


def normalize_board_index_ths(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Normalize THS board index data (industry/concept) by position.

    AKShare returns 7 columns like:
    [日期, 开盘价, 最高价, 最低价, 收盘价, 成交量, 成交额]

    Column names may appear garbled in some consoles; map by position.
    """
    if df is None or df.empty:
        return []

    out: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        dt = str(row.iloc[0])
        close = _to_float(row.iloc[4]) if len(row) > 4 else None
        out.append({"date": dt, "close": close})
    return out


def normalize_concept_summary_ths(
    df: pd.DataFrame, *, limit: int = 50
) -> List[Dict[str, Any]]:
    """Normalize THS concept summary text for ETF sector pages."""
    if df is None or df.empty:
        return []

    items: List[Dict[str, Any]] = []
    df2 = _safe_head(df, max(limit, 10))
    for _, row in df2.iterrows():
        items.append(
            {
                "date": str(row.iloc[0]).strip(),
                "concept": normalize_display_text(row.iloc[1]),
                "headline": normalize_display_text(row.iloc[2]),
                "leader": normalize_display_text(row.iloc[3]) if len(row) > 3 else "",
                "constituents": _to_int(row.iloc[4]) if len(row) > 4 else None,
            }
        )
    return items[:limit]


def compute_index_trend(
    points: List[Dict[str, Any]], *, lookbacks: List[int]
) -> Dict[str, Any]:
    closes: List[float] = [
        float(p["close"]) for p in points if p.get("close") is not None
    ]
    if not closes:
        return {"last_close": None, "returns": {}}

    last_close = float(closes[-1])
    returns: Dict[str, Optional[float]] = {}
    for n in lookbacks:
        key = f"ret_{int(n)}d"
        if len(closes) <= n:
            returns[key] = None
            continue
        prev = float(closes[-(n + 1)])
        if prev == 0:
            returns[key] = None
            continue
        returns[key] = (last_close / prev - 1.0) * 100.0

    return {"last_close": last_close, "returns": returns}


def fetch_board_trend_items_ths(
    *,
    kind: str,
    names: List[str],
    lookbacks: List[int],
    start_date: str,
    end_date: str,
    per_item_delay_s: float = 0.0,
) -> List[Dict[str, Any]]:
    """Fetch trend metrics for THS industry/concept boards by name."""
    if not names:
        return []

    out: List[Dict[str, Any]] = []
    fetcher = (
        fetch_industry_index_ths if kind == "industry" else fetch_concept_index_ths
    )

    for nm in names:
        nm2 = normalize_display_text(nm) or str(nm).strip()
        if not nm2:
            continue
        try:
            df = fetcher(nm2, start_date, end_date)
            points = normalize_board_index_ths(df)
            tr = compute_index_trend(points, lookbacks=lookbacks)
            out.append(
                {
                    "name": nm2,
                    "kind": kind,
                    "source": "ths",
                    "start_date": start_date,
                    "end_date": end_date,
                    "last_date": points[-1]["date"] if points else None,
                    "last_close": tr.get("last_close"),
                    **(tr.get("returns") or {}),
                }
            )
        except Exception as e:
            logger.warning(f"board_index_fetch_failed kind={kind} name={nm2}: {e}")
            out.append(
                {
                    "name": nm2,
                    "kind": kind,
                    "source": "ths",
                    "start_date": start_date,
                    "end_date": end_date,
                    "error": str(e),
                }
            )
        if per_item_delay_s and per_item_delay_s > 0:
            time.sleep(per_item_delay_s)

    return out
