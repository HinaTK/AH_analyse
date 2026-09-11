"""Data collectors for stock recommendation.

Three channels:
- fundamental:  PE/PB/ROE/营收增速/行业景气 (AKShare stock_zh_a_spot_em + financial indicators)
- capital:      主力净流入 / 北向 / 融资融券 (AKShare)
- events:       个股新闻 / 公告 / RSS 宏观 (AKShare news_em + rss_fetcher)

Each collector degrades gracefully: returns {} on failure and logs a warning.
"""
from __future__ import annotations

import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

try:
    import akshare as ak  # type: ignore
except Exception:  # pragma: no cover
    ak = None  # type: ignore

from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager, SnapshotResult
from ah_recommendation_system.backend.etf_sector.rss_fetcher import (
    fetch_news_digest,
)
from ah_recommendation_system.backend.stock_recommend.news_ranker import classify_query_bucket


# ---------- helpers ----------

def _safe_call(fn, *, attempts: int = 2, sleep_s: float = 0.4):
    last_exc: Optional[Exception] = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            time.sleep(sleep_s * (i + 1))
    logger.warning(f"AKShare call failed after {attempts} attempts: {last_exc}")
    return None


def _df_to_records(df: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    df = df.replace({pd.NA: None})
    return df.to_dict(orient="records")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _is_recent_timestamp(value: Any, *, max_age_days: int = 4) -> bool:
    try:
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        observed = datetime.fromtimestamp(numeric)
    except (TypeError, ValueError, OSError):
        try:
            observed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
            return False
    return datetime.now() - observed <= timedelta(days=max_age_days)


def _snapshot_is_usable(rows: List[Dict[str, Any]]) -> bool:
    """Reject a fresh-but-empty pre-market snapshot before fallback routing."""
    if not rows:
        return False
    def present(row: Dict[str, Any], key: str) -> bool:
        value = row.get(key)
        return value is not None and value != "" and value != 0
    # Keep the single-row unit/integration probe useful; real market pages
    # must have broad price and activity coverage to enter the pipeline.
    if len(rows) == 1:
        return present(rows[0], "price")
    price_ratio = sum(present(row, "price") for row in rows) / len(rows)
    activity_ratio = sum(
        present(row, "change_pct") or present(row, "amount") for row in rows
    ) / len(rows)
    return price_ratio >= 0.6 and activity_ratio >= 0.4


# ---------- mock data (used when price_fetcher.use_mock_data is True) ----------

_MOCK_FUND_ROWS: List[Dict[str, Any]] = [
    {"code": "600519", "name": "贵州茅台", "price": 1620.5, "change_pct": 0.8,  "change_60d_pct": 4.2,  "pe": 22.5, "pb": 8.1,  "market_cap": 2.04e12, "float_cap": 2.04e12, "turnover_pct": 0.45},
    {"code": "000858", "name": "五粮液",   "price": 158.3,  "change_pct": 1.2,  "change_60d_pct": 6.5,  "pe": 18.2, "pb": 4.3,  "market_cap": 6.14e11, "float_cap": 6.14e11, "turnover_pct": 0.62},
    {"code": "300750", "name": "宁德时代", "price": 215.4,  "change_pct": 2.1,  "change_60d_pct": 12.8, "pe": 24.6, "pb": 5.2,  "market_cap": 9.48e11, "float_cap": 8.30e11, "turnover_pct": 1.35},
    {"code": "600036", "name": "招商银行", "price": 38.6,   "change_pct": 0.5,  "change_60d_pct": 3.1,  "pe": 6.8,  "pb": 0.95, "market_cap": 9.72e11, "float_cap": 9.72e11, "turnover_pct": 0.31},
    {"code": "601318", "name": "中国平安", "price": 51.2,   "change_pct": 0.3,  "change_60d_pct": 1.2,  "pe": 8.5,  "pb": 0.88, "market_cap": 9.34e11, "float_cap": 6.71e11, "turnover_pct": 0.28},
    {"code": "000333", "name": "美的集团", "price": 76.4,   "change_pct": 0.9,  "change_60d_pct": 5.4,  "pe": 13.1, "pb": 2.4,  "market_cap": 5.34e11, "float_cap": 5.31e11, "turnover_pct": 0.55},
    {"code": "601899", "name": "紫金矿业", "price": 18.7,   "change_pct": 1.8,  "change_60d_pct": 9.2,  "pe": 16.4, "pb": 3.1,  "market_cap": 4.92e11, "float_cap": 4.72e11, "turnover_pct": 1.12},
    {"code": "600276", "name": "恒瑞医药", "price": 47.5,   "change_pct": 0.4,  "change_60d_pct": -1.5, "pe": 42.1, "pb": 5.8,  "market_cap": 3.04e11, "float_cap": 3.04e11, "turnover_pct": 0.42},
    {"code": "002594", "name": "比亚迪",   "price": 248.6,  "change_pct": 1.5,  "change_60d_pct": 8.7,  "pe": 21.3, "pb": 4.2,  "market_cap": 7.23e11, "float_cap": 3.55e11, "turnover_pct": 0.95},
    {"code": "600900", "name": "长江电力", "price": 29.4,   "change_pct": 0.2,  "change_60d_pct": 2.8,  "pe": 18.4, "pb": 2.9,  "market_cap": 7.20e11, "float_cap": 7.20e11, "turnover_pct": 0.18},
    {"code": "601166", "name": "兴业银行", "price": 18.2,   "change_pct": 0.1,  "change_60d_pct": 0.5,  "pe": 4.6,  "pb": 0.55, "market_cap": 4.04e11, "float_cap": 3.92e11, "turnover_pct": 0.21},
    {"code": "600028", "name": "中国石化", "price": 6.5,    "change_pct": 0.3,  "change_60d_pct": 1.8,  "pe": 8.9,  "pb": 0.78, "market_cap": 7.43e11, "float_cap": 6.50e11, "turnover_pct": 0.15},
    {"code": "601398", "name": "工商银行", "price": 6.8,    "change_pct": 0.0,  "change_60d_pct": 1.2,  "pe": 5.2,  "pb": 0.62, "market_cap": 2.04e12, "float_cap": 2.04e12, "turnover_pct": 0.08},
    {"code": "300059", "name": "东方财富", "price": 18.4,   "change_pct": 2.8,  "change_60d_pct": 14.6, "pe": 32.5, "pb": 3.8,  "market_cap": 1.45e11, "float_cap": 1.39e11, "turnover_pct": 2.45},
    {"code": "002475", "name": "立讯精密", "price": 42.1,   "change_pct": 1.6,  "change_60d_pct": 11.2, "pe": 19.8, "pb": 3.4,  "market_cap": 3.02e11, "float_cap": 2.93e11, "turnover_pct": 1.12},
]

_MOCK_CAP_ROWS: List[Dict[str, Any]] = [
    {"code": "600519", "name": "贵州茅台", "main_net": 1.8e9,  "super_net": 1.2e9,  "big_net": 6.0e8},
    {"code": "000858", "name": "五粮液",   "main_net": 5.2e8,  "super_net": 3.0e8,  "big_net": 2.2e8},
    {"code": "300750", "name": "宁德时代", "main_net": 2.4e9,  "super_net": 1.5e9,  "big_net": 9.0e8},
    {"code": "600036", "name": "招商银行", "main_net": 8.0e8,  "super_net": 5.0e8,  "big_net": 3.0e8},
    {"code": "601318", "name": "中国平安", "main_net": -3.0e8, "super_net": -1.0e8, "big_net": -2.0e8},
    {"code": "000333", "name": "美的集团", "main_net": 6.0e8,  "super_net": 4.0e8,  "big_net": 2.0e8},
    {"code": "601899", "name": "紫金矿业", "main_net": 1.2e9,  "super_net": 7.0e8,  "big_net": 5.0e8},
    {"code": "600276", "name": "恒瑞医药", "main_net": -1.5e8, "super_net": -5.0e7, "big_net": -1.0e8},
    {"code": "002594", "name": "比亚迪",   "main_net": 1.5e9,  "super_net": 8.0e8,  "big_net": 7.0e8},
    {"code": "600900", "name": "长江电力", "main_net": 2.0e8,  "super_net": 1.0e8,  "big_net": 1.0e8},
    {"code": "601166", "name": "兴业银行", "main_net": 1.0e8,  "super_net": 5.0e7,  "big_net": 5.0e7},
    {"code": "600028", "name": "中国石化", "main_net": 1.5e8,  "super_net": 8.0e7,  "big_net": 7.0e7},
    {"code": "601398", "name": "工商银行", "main_net": 5.0e7,  "super_net": 3.0e7,  "big_net": 2.0e7},
    {"code": "300059", "name": "东方财富", "main_net": 2.2e9,  "super_net": 1.4e9,  "big_net": 8.0e8},
    {"code": "002475", "name": "立讯精密", "main_net": 1.6e9,  "super_net": 9.0e8,  "big_net": 7.0e8},
]

_MOCK_NEWS_ITEMS: List[Dict[str, Any]] = [
    {"title": "宁德时代 300750 公布新一代固态电池路线图", "content": "宁德时代发布新电池技术，300750 关注度提升", "source": "财联社", "url": "https://example.com/1"},
    {"title": "紫金矿业 601899 海外金矿扩产获批", "content": "601899 紫金矿业产能扩张", "source": "证券时报", "url": "https://example.com/2"},
    {"title": "东方财富 300059 旗下基金代销规模创新高", "content": "300059 业绩超预期", "source": "上海证券报", "url": "https://example.com/3"},
    {"title": "央行：稳健货币政策灵活适度", "content": "宏观流动性环境", "source": "央行", "url": "https://example.com/4"},
]

_MOCK_HSGT: Dict[str, Any] = {
    "rows": [
        {"名称": "沪股通", "成交净买额": 3.2e9},
        {"名称": "深股通", "成交净买额": 2.8e9},
    ]
}


def _is_mock_mode() -> bool:
    try:
        return bool(get_price_fetcher().use_mock_data)
    except Exception:
        return False


# ---------- fundamental ----------

def _collect_a_share_spot(limit: int = 200) -> List[Dict[str, Any]]:
    """全市场实时行情（带 PE/PB/市值/换手/涨跌幅）。

    盘后才能稳定；盘前返回空列表（调用方需 fallback）。
    """
    if _is_mock_mode():
        rows = [dict(row, amount=row.get("amount", 300_000_000), volume_ratio=row.get("volume_ratio", 1.6), history_days=120, source="mock") for row in _MOCK_FUND_ROWS]
        return rows[:limit] if limit else rows
    manager = MarketDataManager(akshare_module=ak)
    result = manager.fetch_snapshot(limit=limit)
    if not result.rows:
        logger.warning(f"market snapshot unavailable: {result.error}")
        return []
    health = {
        "market_data": result.health(),
        "market_stats": result.stats,
        "attempted_sources": list(result.attempted),
        "skipped_sources": list(result.skipped),
    }
    return [dict(row, provider_health=health) for row in result.rows]



def collect_fundamental(limit: int = 6000) -> Dict[str, Any]:
    """基本面数据汇总。"""
    rows = _collect_a_share_spot(limit=limit)
    detected_source = "mock" if _is_mock_mode() else "akshare.stock_zh_a_spot_em"
    if rows and rows[0].get("source"):
        detected_source = str(rows[0]["source"])
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": detected_source,
        "rows": rows,
        "count": len(rows),
        "universe_size": 5300 if _is_mock_mode() else len(rows),
        "fields": ["code", "name", "price", "change_pct", "pe", "pb",
                   "turnover_pct", "market_cap", "change_60d_pct"],
        "provider_health": (rows[0].get("provider_health") if rows else {}) or {},
    }
    logger.info(f"fundamental rows={len(rows)}")
    return payload


# ---------- capital ----------

def _collect_individual_fund_flow(date_str: Optional[str] = None) -> List[Dict[str, Any]]:
    """个股主力/超大单/大单净流入。date_str: YYYYMMDD。"""
    if _is_mock_mode():
        return list(_MOCK_CAP_ROWS)
    if ak is None:
        return []
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    def _go():
        # AKShare's rank endpoint is the market-wide daily table.  The
        # per-symbol endpoint requires a stock code plus market and cannot
        # accept a YYYYMMDD date.
        return ak.stock_individual_fund_flow_rank(indicator="今日")

    df = _safe_call(_go, attempts=2)
    if df is None or df.empty:
        return []
    rename = {
        "代码": "code",
        "名称": "name",
        "今日主力净流入-净额": "main_net",
        "今日超大单净流入-净额": "super_net",
        "今日大单净流入-净额": "big_net",
        "今日中单净流入-净额": "mid_net",
        "今日小单净流入-净额": "small_net",
        "股票代码": "code",
        "股票简称": "name",
        "主力净流入-净额": "main_net",
        "超大单净流入-净额": "super_net",
        "大单净流入-净额": "big_net",
        "中单净流入-净额": "mid_net",
        "小单净流入-净额": "small_net",
    }
    df = df.rename(columns=rename)
    keep = [c for c in rename.values() if c in df.columns]
    df = df[keep]
    if "code" in df.columns:
        df["code"] = df["code"].astype(str).str.zfill(6)
    return _df_to_records(df)


def _collect_hsgt_fund_flow() -> Dict[str, Any]:
    """北向资金当日净流入。"""
    if _is_mock_mode():
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "mock",
            "rows": list(_MOCK_HSGT.get("rows") or []),
        }
    if ak is None:
        return {}
    def _go():
        return ak.stock_hsgt_fund_flow_summary_em()
    df = _safe_call(_go, attempts=2)
    if df is None or df.empty:
        return {}

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "akshare.stock_hsgt_fund_flow_summary_em",
        "rows": _df_to_records(df.head(40)),
    }


def collect_capital() -> Dict[str, Any]:
    """资金面汇总：主力 + 北向。融资融券因接口频率低、可选接入。"""
    rows = _collect_individual_fund_flow()
    hsgt = _collect_hsgt_fund_flow()
    try:
        from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient
        client = HithinkClient()
        if client.enabled:
            for board_type, source in (("org", "lhb_institution"), ("hot_money", "lhb_trader")):
                try:
                    for item in client.dragon_tiger(board_type=board_type):
                        code = str(item.get("thscode") or item.get("code") or "").split(".")[0].zfill(6)
                        if board_type == "org":
                            net = item.get("org_net_value") or item.get("net_value")
                        else:
                            net = item.get("hot_money_net_value") or item.get("net_value")
                        if len(code) == 6 and float(net or 0) > 0:
                            rows.append({"code": code, "name": item.get("name") or code, "main_net": net, "net_buy": net, "source": source})
                except Exception as exc:
                    logger.warning(f"Financial-API {board_type} unavailable: {exc}")
    except Exception:
        pass
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "akshare.fund_flow",
        "rows": rows,
        "count": len(rows),
        "hsgt": hsgt,
    }
    logger.info(f"capital rows={len(rows)} hsgt_keys={list(hsgt.keys())}")
    return payload


# ---------- events ----------


def select_macro_news_by_bucket(items, *, limit: int = 80, per_bucket: int = 20):
    """Keep policy/price/industry news even if they arrive after a global tape."""
    buckets = {
        "policy": [],
        "price_supply": [],
        "industry": [],
        "foreign_capital": [],
        "company": [],
        "macro_tape": [],
    }
    seen: set[str] = set()
    for raw in items or []:
        item = dict(raw)
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        key = str(item.get("url") or "") or f"{title}|{item.get('published_at') or ''}"
        if key in seen:
            continue
        seen.add(key)
        bucket = str(item.get("query_bucket") or "") or classify_query_bucket(item)
        item["query_bucket"] = bucket
        buckets.setdefault(bucket, []).append(item)
    output: list[dict] = []
    for bucket in ("policy", "price_supply", "industry", "foreign_capital", "company", "macro_tape"):
        output.extend(buckets.get(bucket, [])[:per_bucket])
        if len(output) >= limit:
            return output[:limit]
    return output[:limit]


def _collect_news_em(limit: int = 100, codes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if _is_mock_mode():
        return list(_MOCK_NEWS_ITEMS)[:limit] if limit else list(_MOCK_NEWS_ITEMS)
    if ak is None:
        return []
    rename = {
        "新闻标题": "title",
        "新闻内容": "content",
        "发布时间": "published_at",
        "来源": "source",
        "文章来源": "source",
        "网址": "url",
        "新闻链接": "url",
    }
    records: List[Dict[str, Any]] = []
    for code in (codes or [])[: max(1, limit)]:
        def fetch_news(symbol: str = str(code)):
            with pd.option_context("future.infer_string", False):
                return ak.stock_news_em(symbol=symbol)

        df = _safe_call(fetch_news, attempts=2)
        if df is None or df.empty:
            continue
        df = df.rename(columns=rename)
        keep = [column for column in dict.fromkeys(rename.values()) if column in df.columns]
        records.extend(_df_to_records(df[keep])[:5])
        if len(records) >= limit:
            break
    return records[:limit]


def _collect_notice_news(
    limit: int = 100,
    codes: Optional[List[str]] = None,
    *,
    ak_module: Any = None,
) -> List[Dict[str, Any]]:
    """Collect dated company announcements as a candidate-news fallback."""
    provider = ak if ak_module is None else ak_module
    if provider is None:
        return []
    today = datetime.now().strftime("%Y%m%d")
    df = _safe_call(
        lambda: provider.stock_notice_report(symbol="全部", date=today),
        attempts=2,
    )
    if df is None or df.empty:
        return []
    wanted = {str(code).zfill(6) for code in (codes or []) if str(code)}
    output: List[Dict[str, Any]] = []
    for raw in df.head(max(limit * 10, limit)).to_dict("records"):
        code = str(raw.get("代码") or raw.get("股票代码") or raw.get("code") or "").zfill(6)
        if wanted and code not in wanted:
            continue
        title = str(raw.get("公告标题") or raw.get("标题") or raw.get("title") or "").strip()
        if not title:
            continue
        output.append({
            "code": code,
            "name": raw.get("名称") or raw.get("股票简称") or "",
            "title": title,
            "content": raw.get("公告类型") or raw.get("类型") or "",
            "published_at": str(raw.get("公告日期") or raw.get("日期") or ""),
            "source": "上市公司公告聚合",
            "url": raw.get("网址") or raw.get("链接") or raw.get("url") or "",
        })
        if len(output) >= limit:
            break
    return output


def _collect_macro_news_fallback(
    limit: int = 80,
    *,
    ak_module: Any = None,
) -> List[Dict[str, Any]]:
    """Collect non-RSS macro/global news from independent AKShare adapters."""
    provider = ak if ak_module is None else ak_module
    if provider is None:
        return []
    today = datetime.now().strftime("%Y%m%d")
    sources = (
        ("东方财富全球财经", "stock_info_global_em", {}),
        ("新浪全球财经", "stock_info_global_sina", {}),
        ("百度宏观资讯", "news_economic_baidu", {"date": today}),
    )
    output: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for source_name, method_name, kwargs in sources:
        method = getattr(provider, method_name, None)
        if method is None:
            continue

        def fetch(method=method, kwargs=kwargs):
            try:
                return method(**kwargs)
            except TypeError:
                return method()

        df = _safe_call(fetch, attempts=2)
        if df is None or df.empty:
            continue
        for raw in df.head(max(limit * 5, limit)).to_dict("records"):
            title = str(raw.get("标题") or raw.get("新闻标题") or raw.get("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            output.append({
                "title": title,
                "summary": raw.get("摘要") or raw.get("内容") or raw.get("新闻内容") or "",
                "published_at": str(raw.get("发布时间") or raw.get("时间") or raw.get("日期") or ""),
                "source": source_name,
                "url": raw.get("链接") or raw.get("网址") or raw.get("url") or "",
            })
    return select_macro_news_by_bucket(output, limit=limit)


def collect_events(limit: int = 100, codes: Optional[List[str]] = None) -> Dict[str, Any]:
    """事件面汇总：个股新闻、公告、RSS和非RSS宏观兜底。"""
    news = _collect_news_em(limit=limit, codes=codes)
    notices = _collect_notice_news(limit=limit, codes=codes) if codes and not _is_mock_mode() else []
    existing_news = {(str(item.get("title") or ""), str(item.get("published_at") or "")) for item in news}
    news.extend(
        item for item in notices
        if (str(item.get("title") or ""), str(item.get("published_at") or "")) not in existing_news
    )
    stock_cap = 50 if codes else limit
    news = news[: min(limit, stock_cap)]
    macro: Dict[str, Any] = {"source": "mock", "items": []} if _is_mock_mode() else {}
    if not _is_mock_mode() and not codes:
        try:
            macro = fetch_news_digest(max_items=80)
        except Exception as e:
            logger.warning(f"rss digest failed: {e}")
        fallback_macro = _collect_macro_news_fallback(limit=80)
        macro = dict(macro or {})
        macro_items = list(macro.get("items") or [])
        seen_macro = {str(item.get("title") or "") for item in macro_items}
        macro_items.extend(item for item in fallback_macro if str(item.get("title") or "") not in seen_macro)
        macro["items"] = select_macro_news_by_bucket(macro_items, limit=80)
        macro["count"] = len(macro["items"])
        macro["source"] = "rss+akshare_global_macro"

    def with_event_id(item: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        value = dict(item)
        raw = f"{value.get('url', '')}|{value.get('title', '')}|{value.get('published_at', '')}"
        value.setdefault("event_id", f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}")
        return value

    news = [with_event_id(item, "stock") for item in news]
    if macro.get("items"):
        macro = dict(macro)
        macro["items"] = [with_event_id(item, "macro") for item in macro.get("items") or []]
    status = "available" if news or macro.get("items") else "provider_failed" if ak is None and not _is_mock_mode() else "no_relevant_news"

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "akshare.stock_news_em+announcements+rss+global_macro",
        "stock_news": news,
        "macro_news": macro,
        "count": len(news),
        "status": status,
        "provider_health": {
            "akshare_stock_news": "healthy" if news else ("disabled" if ak is None else "empty"),
            "company_notices": "healthy" if notices else "empty",
            "rss": "healthy" if macro.get("count", 0) else "empty",
            "macro_fallback": "healthy" if not codes and macro.get("source") == "rss+akshare_global_macro" and macro.get("count", 0) else "empty",
        },
    }
    logger.info(f"events stock_news={len(news)} macro_count={macro.get('count', 0)}")
    return payload


# ---------- orchestrator ----------

@dataclass
class CollectedSnapshot:
    date: str
    fundamental: Dict[str, Any] = field(default_factory=dict)
    capital: Dict[str, Any] = field(default_factory=dict)
    events: Dict[str, Any] = field(default_factory=dict)
    cross_market: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "fundamental": self.fundamental,
            "capital": self.capital,
            "events": self.events,
            "cross_market": self.cross_market,
            "errors": self.errors,
        }


def collect_all(limit: int = 6000) -> CollectedSnapshot:
    """一键采集三路。任一失败不影响其他。"""
    snap = CollectedSnapshot(date=_today_str())

    try:
        snap.fundamental = collect_fundamental(limit=limit)
    except Exception as e:
        snap.errors.append(f"fundamental:{e}")
        logger.warning(f"collect_fundamental failed: {e}")

    try:
        snap.capital = collect_capital()
    except Exception as e:
        snap.errors.append(f"capital:{e}")
        logger.warning(f"collect_capital failed: {e}")

    try:
        snap.events = collect_events()
    except Exception as e:
        snap.errors.append(f"events:{e}")
        logger.warning(f"collect_events failed: {e}")

    if not _is_mock_mode():
        try:
            from ah_recommendation_system.backend.stock_recommend.cross_market import collect_cross_market

            snap.cross_market = collect_cross_market()
            if snap.cross_market.get("status") == "failed":
                snap.errors.append("cross_market:all_sources_failed")
        except Exception as e:
            snap.errors.append(f"cross_market:{type(e).__name__}")
            logger.warning(f"collect_cross_market failed: {type(e).__name__}")

    return snap


def get_price_fetcher_singleton():
    return get_price_fetcher()
