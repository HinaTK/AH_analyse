# AH股票列表和基本信息
# ======================

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import akshare as ak
import pandas as pd
from loguru import logger


# Static fallback mapping (used when AKShare list fetch is unavailable).
# Keep this set small and high-confidence to avoid mismatched pairs.
AH_STOCK_PAIRS: Dict[str, str] = {
    # 银行
    "601398.SH": "1398.HK",  # 工商银行
    "601939.SH": "0939.HK",  # 建设银行
    "601288.SH": "1288.HK",  # 农业银行
    "601988.SH": "3988.HK",  # 中国银行
    # 券商/保险
    "600030.SH": "6030.HK",  # 中信证券
    "601318.SH": "2318.HK",  # 中国平安
    "601628.SH": "2628.HK",  # 中国人寿
    # 能源/制造
    "600028.SH": "0386.HK",  # 中国石化
    "601857.SH": "0857.HK",  # 中国石油
    "002594.SZ": "1211.HK",  # 比亚迪
    "601088.SH": "1088.HK",  # 中国神华
}


_A_CODE_RE = re.compile(r"\d{6}\.(SH|SZ)$", re.IGNORECASE)
_H_CODE_RE = re.compile(r"\d{1,5}\.HK$", re.IGNORECASE)


def _normalize_a_code(code: str) -> str:
    s = (code or "").strip().upper()
    if not s:
        return ""

    if _A_CODE_RE.match(s):
        return s

    m = re.search(r"(\d{6})", s)
    if not m:
        return ""

    digits = m.group(1)
    market = "SH" if digits.startswith("6") else "SZ"
    return f"{digits}.{market}"


def _normalize_h_code(code: str) -> str:
    s = (code or "").strip().upper()
    if not s:
        return ""

    if _H_CODE_RE.match(s):
        return s

    m = re.search(r"(\d{1,5})", s)
    if not m:
        return ""

    digits = m.group(1)
    if len(digits) < 4:
        digits = digits.zfill(4)

    return f"{digits}.HK"


def _pairs_and_names_from_df(df: pd.DataFrame) -> Tuple[Dict[str, str], Dict[str, str]]:
    if df is None or df.empty:
        return {}, {}

    a_col = "A股代码" if "A股代码" in df.columns else None
    h_col = "H股代码" if "H股代码" in df.columns else None
    name_col = "A股简称" if "A股简称" in df.columns else None

    if not a_col or not h_col:
        return {}, {}

    pairs: Dict[str, str] = {}
    a_names: Dict[str, str] = {}

    for _, row in df.iterrows():
        a_code = _normalize_a_code(str(row.get(a_col, "")))
        h_code = _normalize_h_code(str(row.get(h_col, "")))
        if not a_code or not h_code:
            continue

        if a_code not in pairs:
            pairs[a_code] = h_code

        if name_col and a_code not in a_names:
            name = str(row.get(name_col, ""))
            if name and name != "nan":
                a_names[a_code] = name

    return pairs, a_names


@dataclass
class _AhListCache:
    ts: float
    df: pd.DataFrame
    pairs: Dict[str, str]
    a_names: Dict[str, str]


_ah_list_cache: Optional[_AhListCache] = None
_AH_LIST_TTL_SECONDS = 6 * 3600


def get_ah_stock_list() -> pd.DataFrame:
    """Fetch AH list via AKShare (Eastmoney). Cached in-process."""

    global _ah_list_cache
    if _ah_list_cache and (time.time() - _ah_list_cache.ts) < _AH_LIST_TTL_SECONDS:
        return _ah_list_cache.df

    # Dynamic fetch is opt-in because upstream can be slow/flaky.
    dyn_enabled = (os.environ.get("AH_DYNAMIC_AH_LIST") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not dyn_enabled:
        _ah_list_cache = _AhListCache(
            ts=time.time(), df=pd.DataFrame(), pairs={}, a_names={}
        )
        return _ah_list_cache.df

    try:
        fetch_fn = getattr(ak, "stock_zh_ah_spot_em", None) or getattr(
            ak, "stock_zh_ah_spot", None
        )
        if fetch_fn is None:
            return pd.DataFrame()

        df_any = fetch_fn()
        if not isinstance(df_any, pd.DataFrame):
            return pd.DataFrame()

        df = df_any

        pairs, names = _pairs_and_names_from_df(df)
        _ah_list_cache = _AhListCache(ts=time.time(), df=df, pairs=pairs, a_names=names)
        return df
    except Exception as e:
        # Network failures are common; callers should tolerate empty results.
        logger.warning(f"Failed to fetch AH list from AKShare: {e}")
        _ah_list_cache = _AhListCache(
            ts=time.time(), df=pd.DataFrame(), pairs={}, a_names={}
        )
        return pd.DataFrame()


def get_ah_pairs() -> Dict[str, str]:
    """Return {A_code: H_code}.

    Prefer official list from AKShare; fallback to static mapping when unavailable.
    """

    df = get_ah_stock_list()
    if not df.empty and _ah_list_cache and _ah_list_cache.pairs:
        return _ah_list_cache.pairs.copy()

    return AH_STOCK_PAIRS.copy()


def get_stock_name(a_code: str) -> str:
    """Get A-share short name."""

    norm = _normalize_a_code(a_code)

    df = get_ah_stock_list()
    if not df.empty and _ah_list_cache and _ah_list_cache.a_names:
        name = _ah_list_cache.a_names.get(norm)
        if name:
            return name

    stock_names = {
        "601398.SH": "工商银行",
        "601939.SH": "建设银行",
        "601288.SH": "农业银行",
        "601988.SH": "中国银行",
        "600030.SH": "中信证券",
        "601318.SH": "中国平安",
        "601628.SH": "中国人寿",
        "600028.SH": "中国石化",
        "601857.SH": "中国石油",
        "002594.SZ": "比亚迪",
        "601088.SH": "中国神华",
    }
    return stock_names.get(norm, "")


def filter_by_market_cap(
    stock_list: pd.DataFrame,
    market_cap_col: str = "总市值",
    threshold: float = 500,
) -> pd.DataFrame:
    """按市值筛选股票"""

    if stock_list.empty:
        return stock_list
    if market_cap_col not in stock_list.columns:
        return stock_list

    mask = stock_list[market_cap_col] >= threshold
    return stock_list.loc[mask].copy()


def get_active_ah_stocks() -> List[Dict[str, object]]:
    """Return a list of active AH stocks for UI."""

    ah_list = get_ah_stock_list()

    if ah_list.empty:
        pairs = get_ah_pairs()
        return [
            {"a_code": k, "h_code": v, "name": get_stock_name(k)}
            for k, v in pairs.items()
        ]

    stocks: List[Dict[str, object]] = []
    for _, row in ah_list.iterrows():
        a_code = _normalize_a_code(str(row.get("A股代码", "")))
        h_code = _normalize_h_code(str(row.get("H股代码", "")))
        if not a_code or not h_code:
            continue

        stock: Dict[str, object] = {
            "a_code": a_code,
            "h_code": h_code,
            "name": str(row.get("A股简称", "")),
            "a_price": row.get("A股收盘价", 0),
            "h_price": row.get("H股收盘价", 0),
            "premium": row.get("溢价率", 0),
            "market_cap": row.get("总市值", 0),
        }
        stocks.append(stock)

    return stocks


# AH股票行业分类
AH_INDUSTRY_MAPPING = {
    "601398.SH": "银行",
    "601988.SH": "银行",
    "601939.SH": "银行",
    "601288.SH": "银行",
    "600030.SH": "证券",
    "600015.SH": "银行",
    "601336.SH": "保险",
    "601601.SH": "保险",
    "601318.SH": "保险",
    "601628.SH": "保险",
    "002594.SZ": "汽车",
    "600028.SH": "石油石化",
    "601857.SH": "石油石化",
    "601088.SH": "煤炭",
    "600362.SH": "有色金属",
    "600547.SH": "黄金",
}


def get_stock_industry(a_code: str) -> str:
    """获取股票行业分类"""

    return AH_INDUSTRY_MAPPING.get(_normalize_a_code(a_code), "其他")
