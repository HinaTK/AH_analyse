"""Focused, low-volume fallback collector.

It intentionally avoids the fragile all-market AKShare pagination path.  The
universe is assembled from configured focus-industry symbols plus recent
龙虎榜/机构席位 activity, then quotes are fetched in small batches from
Tencent's public quote endpoint.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence

import requests
from loguru import logger

from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot
from ah_recommendation_system.backend.stock_recommend.data_source_router import parse_sina_quotes
from ah_recommendation_system.backend.stock_recommend.local_store import quote_date_from_value


DEFAULT_FOCUS_UNIVERSE: Dict[str, List[Dict[str, str]]] = {
    "科技": [
        {"code": "300750", "name": "宁德时代"},
        {"code": "300059", "name": "东方财富"},
        {"code": "002475", "name": "立讯精密"},
        {"code": "688981", "name": "中芯国际"},
    ],
    "新能源": [
        {"code": "300750", "name": "宁德时代"},
        {"code": "002594", "name": "比亚迪"},
        {"code": "601012", "name": "隆基绿能"},
    ],
    "券商": [
        {"code": "600030", "name": "中信证券"},
        {"code": "300059", "name": "东方财富"},
        {"code": "601688", "name": "华泰证券"},
    ],
    "医疗": [
        {"code": "600276", "name": "恒瑞医药"},
        {"code": "300760", "name": "迈瑞医疗"},
        {"code": "603259", "name": "药明康德"},
    ],
    "银行": [
        {"code": "002142", "name": "宁波银行"},
        {"code": "600036", "name": "招商银行"},
    ],
    "油轮运输": [
        {"code": "601872", "name": "招商轮船"},
        {"code": "600026", "name": "中远海能"},
    ],
    "油运": [
        {"code": "601872", "name": "招商轮船"},
        {"code": "600026", "name": "中远海能"},
    ],
    "集装箱航运": [
        {"code": "601919", "name": "中远海控"},
        {"code": "601866", "name": "中远海发"},
    ],
    "石油开采": [
        {"code": "600028", "name": "中国石化"},
        {"code": "601857", "name": "中国石油"},
    ],
    "功率半导体": [
        {"code": "600584", "name": "长电科技"},
        {"code": "603501", "name": "韦尔股份"},
    ],
    "玻纤": [
        {"code": "600176", "name": "中国巨石"},
    ],
    "电子布": [
        {"code": "600176", "name": "中国巨石"},
    ],
    "人形机器人": [
        {"code": "002050", "name": "三花智控"},
        {"code": "002008", "name": "大族激光"},
    ],
}



def attach_industry_tags(
    rows: Iterable[Dict[str, Any]],
    focus_universe: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
) -> List[Dict[str, Any]]:
    """Copy exact industry membership onto quote rows without inventing aliases."""
    memberships: Dict[str, List[str]] = {}
    for industry, members in (focus_universe or {}).items():
        label = str(industry or "").strip()
        if not label:
            continue
        for member in members or []:
            code = str((member or {}).get("code") or "").zfill(6)
            if len(code) == 6:
                bucket = memberships.setdefault(code, [])
                if label not in bucket:
                    bucket.append(label)
    tagged: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        code = str(item.get("code") or "").zfill(6)
        industries = list(item.get("focus_industries") or item.get("industries") or [])
        for label in memberships.get(code, []):
            if label not in industries:
                industries.append(label)
        if industries:
            item["focus_industries"] = industries
            item["industries"] = industries
            if not str(item.get("industry") or "").strip():
                item["industry"] = industries[0]
        tagged.append(item)
    return tagged


def industry_tag_coverage(rows) -> float:
    """Share of snapshot rows that already carry an explicit industry tag."""
    items = list(rows or [])
    if not items:
        return 0.0
    tagged = 0
    for row in items:
        labels = list(row.get("focus_industries") or row.get("industries") or [])
        if not labels and row.get("industry"):
            labels = [row.get("industry")]
        if any(str(item or "").strip() for item in labels):
            tagged += 1
    return tagged / len(items)


def _normalize_industry_universe(raw) -> Dict[str, List[Dict[str, str]]]:
    if not isinstance(raw, Mapping):
        return {}
    result: Dict[str, List[Dict[str, str]]] = {}
    for industry, members in raw.items():
        label = str(industry or "").strip()
        if not label or not isinstance(members, Iterable) or isinstance(members, (str, bytes)):
            continue
        cleaned: List[Dict[str, str]] = []
        seen = set()
        for member in members:
            if not isinstance(member, Mapping):
                continue
            code = str(member.get("code") or "").zfill(6)
            if len(code) != 6 or code in seen:
                continue
            seen.add(code)
            cleaned.append({"code": code, "name": str(member.get("name") or code)})
        if cleaned:
            result[label] = cleaned
    return result


def resolve_industry_universe(
    *,
    fetch_live,
    store_root,
    as_of: str,
    errors: List[str] | None = None,
    prefer_cache: bool = False,
) -> Dict[str, List[Dict[str, str]]]:
    """Prefer a full-market industry catalog; never silently fall back to the tiny static map."""
    from ah_recommendation_system.backend.stock_recommend.local_store import (
        load_industry_universe,
        persist_industry_universe,
    )

    notes = errors if errors is not None else []
    cached = _normalize_industry_universe(load_industry_universe(store_root, as_of=as_of))
    if prefer_cache:
        if cached:
            notes.append("industry_universe:cached")
            return cached
        notes.append("industry_universe:unavailable")
        return {}
    try:
        live = _normalize_industry_universe(fetch_live())
        if live:
            persist_industry_universe(live, store_root, as_of=as_of)
            return live
        notes.append("industry_universe:empty_live")
    except Exception as exc:
        notes.append(f"industry_universe_live:{type(exc).__name__}")
    if cached:
        notes.append("industry_universe:cached")
        return cached
    notes.append("industry_universe:unavailable")
    return {}


def _quote_tencent(codes: Sequence[str], *, batch_size: int = 50) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    size = max(1, int(batch_size))
    for start in range(0, len(codes), size):
        batch = codes[start : start + size]
        symbols = ",".join(("sh" if code.startswith(("5", "6", "9")) else "sz") + code for code in batch)
        response = requests.get(
            "https://qt.gtimg.cn/q=" + symbols,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://stockapp.finance.qq.com/"},
            timeout=15,
        )
        response.raise_for_status()
        text = response.content.decode("gbk", errors="replace")
        for raw in re.findall(r'v_\w+="([^"]*)"', text):
            parts = raw.split("~")
            if len(parts) < 38:
                continue
            try:
                def _optional_float(index: int):
                    if index >= len(parts):
                        return None
                    raw_value = str(parts[index] or "").strip()
                    if not raw_value or raw_value in {"-", "--"}:
                        return None
                    number = float(raw_value)
                    return None if number == 0 else number

                pe = _optional_float(39)
                pb = _optional_float(46)
                market_cap_yi = _optional_float(44)
                float_cap_yi = _optional_float(45)
                rows.append(
                    {
                        "code": parts[2].zfill(6),
                        "name": parts[1],
                        "price": float(parts[3] or 0),
                        "change_pct": float(parts[32] or 0),
                        "volume": float(parts[6] or 0),
                        "amount": float(parts[37] or 0),
                        "quote_time": parts[30],
                        "quote_date": quote_date_from_value(parts[30]),
                        "quote_source": "tencent",
                        "pe": pe,
                        "pb": pb,
                        "market_cap": None if market_cap_yi is None else round(market_cap_yi * 1e8),
                        "float_cap": None if float_cap_yi is None else round(float_cap_yi * 1e8),
                        "pe_kind": "dynamic" if pe is not None else None,
                        "pe_source": "tencent" if pe is not None else None,
                    }
                )
            except (TypeError, ValueError):
                continue
    return rows


def _quote_sina(codes: Sequence[str], *, batch_size: int = 50) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for start in range(0, len(codes), max(1, int(batch_size))):
        batch = codes[start : start + max(1, int(batch_size))]
        symbols = ",".join(("sh" if code.startswith(("5", "6", "9")) else "sz") + code for code in batch)
        response = requests.get(
            "https://hq.sinajs.cn/list=" + symbols,
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        response.raise_for_status()
        for row in parse_sina_quotes(response.content):
            row["quote_source"] = "sina"
            rows.append(row)
    return rows


def _quote_with_fallback(codes: Sequence[str]) -> List[Dict[str, Any]]:
    try:
        rows = _quote_tencent(codes)
        if rows:
            return rows
    except Exception as exc:
        logger.warning(f"Tencent quote fallback unavailable: {exc}")
    try:
        rows = _quote_sina(codes)
        if rows:
            return rows
    except Exception as exc:
        logger.warning(f"Sina quote fallback unavailable: {exc}")
    return []


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _select_lhb_activity(
    trader_rows: Iterable[Mapping[str, Any]],
    institution_rows: Iterable[Mapping[str, Any]],
    *,
    top_n_per_source: int = 60,
) -> List[Dict[str, Any]]:
    """Keep auditable positive-net-buy activity, aggregated by stock/source."""
    selected: List[Dict[str, Any]] = []
    for source, source_rows in (
        ("lhb_trader", trader_rows),
        ("lhb_institution", institution_rows),
    ):
        grouped: Dict[str, Dict[str, Any]] = {}
        for raw in source_rows:
            code = str(raw.get("code") or raw.get("股票代码") or "").zfill(6)
            net_buy = _number(raw.get("net_buy") if "net_buy" in raw else raw.get("净额"))
            if len(code) != 6 or net_buy <= 0:
                continue
            row = grouped.setdefault(
                code,
                {
                    "code": code,
                    "name": raw.get("name") or raw.get("股票名称") or code,
                    "net_buy": 0.0,
                    "source": source,
                    "listing_count": 0,
                },
            )
            row["net_buy"] += net_buy
            row["listing_count"] += int(_number(raw.get("listing_count") or raw.get("上榜次数")))
        ranked = sorted(
            grouped.values(),
            key=lambda row: (row["net_buy"], row["listing_count"]),
            reverse=True,
        )
        selected.extend(ranked[: max(0, int(top_n_per_source))])
    return selected


def build_focused_snapshot(
    *,
    focus_universe: Mapping[str, Sequence[Mapping[str, Any]]],
    activity_rows: Iterable[Mapping[str, Any]] = (),
    quote_fetcher: Callable[[Sequence[str]], List[Dict[str, Any]]] = _quote_tencent,
) -> CollectedSnapshot:
    activity_rows = list(activity_rows)
    by_code: Dict[str, Dict[str, Any]] = {}
    for industry, items in focus_universe.items():
        for item in items:
            code = str(item.get("code") or "").zfill(6)
            if len(code) != 6:
                continue
            row = by_code.setdefault(code, {"code": code, "name": item.get("name") or code, "candidate_sources": [], "focus_industries": []})
            if "focus_industry" not in row["candidate_sources"]:
                row["candidate_sources"].append("focus_industry")
            if industry not in row["focus_industries"]:
                row["focus_industries"].append(industry)
    for item in activity_rows:
        code = str(item.get("code") or item.get("股票代码") or "").zfill(6)
        if len(code) != 6:
            continue
        row = by_code.setdefault(code, {"code": code, "name": item.get("name") or item.get("股票名称") or code, "candidate_sources": [], "focus_industries": []})
        source = str(item.get("source") or "lhb_trader")
        if source not in row["candidate_sources"]:
            row["candidate_sources"].append(source)
        row["lhb_net_buy"] = item.get("net_buy") or item.get("净额")
    requested_count = len(by_code)
    quoted_rows = list(quote_fetcher(list(by_code)))
    quoted = {str(row.get("code") or "").zfill(6): row for row in quoted_rows}
    observed_dates = [
        parsed
        for row in quoted_rows
        for parsed in [quote_date_from_value(row.get("price_as_of") or row.get("quote_date") or row.get("price_date") or row.get("quote_time"))]
        if parsed
    ]
    price_as_of = max(observed_dates) if observed_dates and len(set(observed_dates)) == 1 else None
    for code, row in by_code.items():
        row.update(quoted.get(code) or {})
        if price_as_of and not any(row.get(key) for key in ("price_as_of", "quote_date", "price_date")):
            row["price_as_of"] = price_as_of
    rows = [row for row in by_code.values() if _number(row.get("price")) > 0]
    errors = [] if rows else ["focused_quotes_unavailable"]
    quote_source = next(
        (str(row.get("quote_source")) for row in rows if row.get("quote_source")),
        "tencent",
    )
    cross_market: Dict[str, Any] = {}
    try:
        from ah_recommendation_system.backend.stock_recommend.cross_market import collect_cross_market
        cross_market = collect_cross_market()
    except Exception as exc:
        errors.append(f"cross_market:{type(exc).__name__}")
    snapshot_date = price_as_of or None
    return CollectedSnapshot(
        date=snapshot_date or datetime.now().strftime("%Y-%m-%d"),
        fundamental={"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": f"focused_{quote_source}_quotes", "rows": rows, "count": len(rows), "universe_size": requested_count, "requested_count": requested_count, "price_as_of": price_as_of},
        capital={
            "source": "sina_lhb",
            "rows": [
                {
                    **dict(item),
                    "code": str(item.get("code") or item.get("股票代码") or "").zfill(6),
                    "main_net": item.get("net_buy") or item.get("净额"),
                }
                for item in activity_rows
            ],
        },
        events={"source": "focused", "stock_news": [], "macro_news": {}},
        cross_market=cross_market,
        errors=errors,
    )


def collect_lhb_activity() -> List[Dict[str, Any]]:
    """Return recent 龙虎榜 statistics and institution席位 rows when available."""
    import akshare as ak

    trader_rows: List[Dict[str, Any]] = []
    institution_rows: List[Dict[str, Any]] = []
    try:
        for _, item in ak.stock_lhb_ggtj_sina("5").iterrows():
            trader_rows.append({"code": str(item.get("股票代码") or "").zfill(6), "name": item.get("股票名称"), "net_buy": item.get("净额"), "listing_count": item.get("上榜次数")})
    except Exception as exc:
        trader_rows = []
    try:
        for _, item in ak.stock_lhb_jgmx_sina().iterrows():
            institution_rows.append({"code": str(item.get("股票代码") or "").zfill(6), "name": item.get("股票名称"), "net_buy": _number(item.get("机构席位买入额")) - _number(item.get("机构席位卖出额")), "交易日期": item.get("交易日期")})
    except Exception as exc:
        institution_rows = []
    return _select_lhb_activity(trader_rows, institution_rows)


def collect_focused_market(*, focus_universe: Mapping[str, Sequence[Mapping[str, Any]]] | None = None) -> CollectedSnapshot:
    return build_focused_snapshot(
        focus_universe=focus_universe or DEFAULT_FOCUS_UNIVERSE,
        activity_rows=collect_lhb_activity(),
        quote_fetcher=_quote_with_fallback,
    )
