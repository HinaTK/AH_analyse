from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from loguru import logger


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
        name = str(row.iloc[2])
        growth_pct = _to_float(row.iloc[8])
        unit_nav = _to_float(row.iloc[3])
        fund_type = str(row.iloc[14]) if len(row) > 14 else ""
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
        name = str(row.iloc[1])
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
        name = str(row.iloc[1])
        chg_pct = _to_float(row.iloc[2])
        turnover_yi = _to_float(row.iloc[3])
        leader = str(row.iloc[9]) if len(row) > 9 else ""
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
    rows_ok.sort(key=lambda r: float(r.get("chg_pct") or 0.0), reverse=True)
    top = rows_ok[:limit]
    bottom = list(reversed(rows_ok[-limit:]))
    return {"top_gainers": top, "top_losers": bottom}
