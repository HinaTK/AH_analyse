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

from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot


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
}


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
                rows.append(
                    {
                        "code": parts[2].zfill(6),
                        "name": parts[1],
                        "price": float(parts[3] or 0),
                        "change_pct": float(parts[32] or 0),
                        "volume": float(parts[6] or 0),
                        "amount": float(parts[37] or 0),
                        "quote_time": parts[30],
                    }
                )
            except (TypeError, ValueError):
                continue
    return rows


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
    quoted = {str(row.get("code") or "").zfill(6): row for row in quote_fetcher(list(by_code))}
    for code, row in by_code.items():
        row.update(quoted.get(code) or {})
    rows = [row for row in by_code.values() if _number(row.get("price")) > 0]
    errors = [] if rows else ["focused_quotes_unavailable"]
    return CollectedSnapshot(
        date=datetime.now().strftime("%Y-%m-%d"),
        fundamental={"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": "focused_tencent_quotes", "rows": rows, "count": len(rows), "universe_size": requested_count, "requested_count": requested_count},
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
    return build_focused_snapshot(focus_universe=focus_universe or DEFAULT_FOCUS_UNIVERSE, activity_rows=collect_lhb_activity())
