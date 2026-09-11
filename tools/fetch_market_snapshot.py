"""Fetch a compact China-market quote snapshot for analysis reports.

The script intentionally keeps data collection separate from judgment. Quote
universes are supplied by config or CLI arguments so industries and stocks can
change without editing code.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


DEFAULT_CONFIG = Path(__file__).with_name("market_snapshot_universe.json")
DEFAULT_STOCK_MAP = Path(__file__).resolve().parents[1] / "docs" / "analyse" / "reference" / "stock_industry_map.jsonl"

THEME_ALIASES = {
    "cpo": "CPO/光通信",
    "光通信": "CPO/光通信",
    "光模块": "CPO/光通信",
    "光模块cpo": "CPO/光通信",
    "通信/cpo/光模块": "CPO/光通信",
    "科技": "科技硬件",
    "科技硬件": "科技硬件",
    "ai硬件": "AI硬件",
    "半导体": "半导体设备",
    "科创芯片": "科创芯片",
    "半导体设备": "半导体设备",
    "光伏": "光伏设备",
    "光伏设备": "光伏设备",
    "电网": "电网设备",
    "电网设备": "电网设备",
    "储能": "储能",
    "储能电池": "储能",
    "动力电池": "新能源",
    "电池": "新能源",
    "创新药": "创新药",
    "医疗": "医疗",
    "港股创新药": "港股创新药",
    "券商": "券商",
    "证券": "券商",
    "经纪成交贝塔": "券商",
}

ROLE_PRIORITY = {
    "情绪龙头/高度龙头": 0,
    "产业龙头/中军": 1,
    "高弹性/低位扩散": 2,
    "防御锚/对冲锚": 3,
    "观察锚": 4,
}


@dataclass
class Quote:
    code: str
    configured_name: str
    name: str
    price: float | None
    pct: float | None
    open: float | None
    prev_close: float | None
    high: float | None
    low: float | None
    amount_yi: float | None
    quote_date: str
    quote_time: str
    note: str = ""


@dataclass
class StockCandidate:
    code: str
    name: str
    price: float | None
    pct: float | None
    amount_yi: float | None
    quote_time: str
    source: str
    note: str = ""


def _to_float(value: str) -> float | None:
    try:
        if value == "" or value is None:
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def parse_code_specs(specs: list[str] | None) -> dict[str, str]:
    codes: dict[str, str] = {}
    for raw_spec in specs or []:
        for raw_item in raw_spec.split(","):
            item = raw_item.strip()
            if not item:
                continue
            code, separator, name = item.partition("=")
            codes[code.strip()] = name.strip() if separator else ""
    return codes


def parse_words(specs: list[str] | None) -> list[str]:
    words: list[str] = []
    for raw_spec in specs or []:
        for raw_item in raw_spec.split(","):
            item = raw_item.strip()
            if item:
                words.append(item)
    return words


def normalize_plain_code(value: str) -> str:
    return re.sub(r"\D", "", value)


def is_a_share_map_code(value: str) -> bool:
    normalized = value.strip().upper()
    if normalized.endswith((".HK", ".HKG")):
        return False
    plain = normalize_plain_code(normalized)
    return bool(plain) and plain.startswith(("0", "2", "3", "4", "6", "8", "9"))


def normalize_theme(value: str) -> str:
    key = value.strip().lower()
    return THEME_ALIASES.get(key, value.strip())


def expand_themes(themes: list[str]) -> list[str]:
    expanded: list[str] = []
    for raw_theme in themes:
        for token in re.split(r"[、,，/+\s]+", raw_theme):
            if not token.strip():
                continue
            normalized = normalize_theme(token)
            if normalized not in expanded:
                expanded.append(normalized)
    return expanded


def load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def role_priority(row: dict[str, Any], matched_themes: list[str]) -> int:
    role_by_theme = row.get("role_by_theme") or {}
    for theme in matched_themes:
        role = str(role_by_theme.get(theme, ""))
        if role in ROLE_PRIORITY:
            return ROLE_PRIORITY[role]
    return ROLE_PRIORITY.get(str(row.get("default_role") or "观察锚"), 9)


def select_mapped_stock_candidates(
    themes: list[str],
    stock_map_path: Path = DEFAULT_STOCK_MAP,
    max_stocks: int = 12,
) -> list[dict[str, Any]]:
    """Select deterministic, theme-fit stock candidates from the local mapping.

    This is a safe fallback for analysis runs where dynamic board discovery fails.
    It only selects direct theme matches, never indirect or excluded matches.
    """
    normalized_themes = expand_themes(themes)
    if not normalized_themes or max_stocks <= 0:
        return []

    selected: list[dict[str, Any]] = []
    for row in load_jsonl_rows(stock_map_path):
        code = str(row.get("code", ""))
        if not is_a_share_map_code(code):
            continue
        direct = [str(theme) for theme in row.get("direct_themes") or []]
        excluded = {str(theme) for theme in row.get("excluded_themes") or []}
        matched = [theme for theme in normalized_themes if theme in direct and theme not in excluded]
        if not matched:
            continue
        selected.append(
            {
                "code": code,
                "name": str(row.get("name", "")),
                "sub_industry": str(row.get("sub_industry", "")),
                "matched_themes": matched,
                "role": str(row.get("default_role") or "观察锚"),
                "execution_status": "开盘后确认候选",
                "notes": str(row.get("notes") or ""),
                "_priority": role_priority(row, matched),
            }
        )

    selected.sort(key=lambda item: (item["_priority"], normalize_plain_code(item["code"]), item["name"]))
    for item in selected:
        item.pop("_priority", None)
    return selected[:max_stocks]


def hydrate_mapped_stock_candidates(
    mapped_candidates: list[dict[str, Any]],
    max_stocks: int,
) -> tuple[list[StockCandidate], str | None]:
    if not mapped_candidates:
        return [], None

    quote_sources: dict[str, dict[str, Any]] = {}
    for candidate in mapped_candidates[:max_stocks]:
        quote_sources[to_sina_a_code(normalize_plain_code(candidate["code"]))] = candidate

    quotes, quote_error = fetch_sina_quotes({code: item["name"] for code, item in quote_sources.items()}, "a")
    quote_by_code = {quote.code: quote for quote in quotes}
    stock_candidates: list[StockCandidate] = []

    for code, mapped in quote_sources.items():
        quote = quote_by_code.get(code)
        themes = "/".join(mapped["matched_themes"])
        note_parts = [
            mapped["execution_status"],
            f"真实归属={mapped['sub_industry']}",
            f"角色={mapped['role']}",
        ]
        if mapped.get("notes"):
            note_parts.append(mapped["notes"])
        stock_candidates.append(
            StockCandidate(
                code=code,
                name=(quote.name if quote else mapped["name"]) or mapped["name"],
                price=quote.price if quote else None,
                pct=quote.pct if quote else None,
                amount_yi=quote.amount_yi if quote else None,
                quote_time=" ".join(part for part in [quote.quote_date, quote.quote_time] if part) if quote else "",
                source=f"映射库fallback：{themes}",
                note="；".join(note_parts),
            )
        )

    return stock_candidates, quote_error


def load_universe(config_path: Path | None) -> dict[str, dict[str, str]]:
    if config_path is None:
        return {"a_quotes": {}, "hk_quotes": {}}
    if not config_path.exists():
        return {"a_quotes": {}, "hk_quotes": {}}

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return {
        "a_quotes": normalize_quote_map(payload.get("a_quotes", {})),
        "hk_quotes": normalize_quote_map(payload.get("hk_quotes", {})),
    }


def normalize_quote_map(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(code): str(name) for code, name in value.items()}
    if isinstance(value, list):
        normalized: dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict) or "code" not in item:
                continue
            normalized[str(item["code"])] = str(item.get("name", ""))
        return normalized
    return {}


def fetch_sina_quotes(codes: dict[str, str], market: str) -> tuple[list[Quote], str | None]:
    if not codes:
        return [], None

    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        return [], f"Sina quote request failed: {type(exc).__name__}: {exc}"

    response.encoding = "gbk"
    quotes: list[Quote] = []
    for line in response.text.splitlines():
        match = re.match(r'var hq_str_([^=]+)="(.*)";', line)
        if not match:
            continue
        code, payload = match.groups()
        fields = payload.split(",")
        configured_name = codes.get(code, "")
        if market == "hk":
            quote = parse_hk_quote(code, configured_name, fields)
        else:
            quote = parse_a_quote(code, configured_name, fields)
        if quote:
            quotes.append(quote)

    missing = sorted(set(codes) - {quote.code for quote in quotes})
    if missing:
        return quotes, f"Sina returned no parsable quote for: {', '.join(missing)}"
    return quotes, None


def parse_a_quote(code: str, configured_name: str, fields: list[str]) -> Quote | None:
    if len(fields) < 4 or not fields[0]:
        return None

    name = fields[0].strip('"')
    open_price = _to_float(fields[1])
    prev_close = _to_float(fields[2])
    price = _to_float(fields[3])
    high = _to_float(fields[4]) if len(fields) > 4 else None
    low = _to_float(fields[5]) if len(fields) > 5 else None
    amount = _to_float(fields[9]) if len(fields) > 9 else None
    quote_date = fields[30] if len(fields) > 30 else ""
    quote_time = fields[31] if len(fields) > 31 else ""
    note = ""

    if price is not None and price <= 0:
        note = "尚无有效最新成交价，通常为开盘前或停牌/无报价"
        price = None

    pct = None
    if price is not None and prev_close and prev_close > 0:
        pct = (price - prev_close) / prev_close * 100

    return Quote(
        code=code,
        configured_name=configured_name,
        name=name,
        price=price,
        pct=pct,
        open=open_price,
        prev_close=prev_close,
        high=high,
        low=low,
        amount_yi=amount / 100_000_000 if amount is not None else None,
        quote_date=quote_date,
        quote_time=quote_time,
        note=note,
    )


def parse_hk_quote(code: str, configured_name: str, fields: list[str]) -> Quote | None:
    if len(fields) < 9 or not fields[1]:
        return None


    name = fields[1].strip('"')
    return Quote(
        code=code,
        configured_name=configured_name,
        name=name,
        price=_to_float(fields[6]),
        pct=_to_float(fields[8]),
        open=_to_float(fields[2]),
        prev_close=_to_float(fields[3]),
        high=_to_float(fields[4]),
        low=_to_float(fields[5]),
        amount_yi=(_to_float(fields[11]) or 0) / 100_000_000 if len(fields) > 11 else None,
        quote_date="",
        quote_time="",
    )


def fetch_akshare_boards(top: int) -> dict[str, Any]:
    result: dict[str, Any] = {"industry_error": None, "concept_error": None}
    try:
        import akshare as ak

        industry = ak.stock_board_industry_name_em()
        result["industry_top"] = industry.head(top).to_dict(orient="records")
        result["industry_bottom"] = industry.tail(top).to_dict(orient="records")
    except Exception as exc:  # noqa: BLE001 - source failures are evidence, not fatal errors.
        result["industry_top"] = []
        result["industry_bottom"] = []
        result["industry_error"] = f"{type(exc).__name__}: {exc}"

    try:
        import akshare as ak

        concept = ak.stock_board_concept_name_em()
        result["concept_top"] = concept.head(top).to_dict(orient="records")
    except Exception as exc:  # noqa: BLE001
        result["concept_top"] = []
        result["concept_error"] = f"{type(exc).__name__}: {exc}"

    return result


def fetch_stock_candidates(
    boards: dict[str, Any],
    keywords: list[str],
    max_stocks: int,
    top_boards: int,
    mode: str,
) -> tuple[list[StockCandidate], str | None]:
    if mode == "off" or max_stocks <= 0:
        return [], None
    has_board_rows = bool(boards.get("industry_top") or boards.get("concept_top"))
    if mode == "auto" and not keywords and not has_board_rows:
        return [], None

    source_note = None
    try:
        import akshare as ak

        spot = ak.stock_zh_a_spot()
    except Exception as exc:  # noqa: BLE001 - quote source instability should be visible.
        spot = None
        source_note = f"A-share spot source failed, using code-name fallback: {type(exc).__name__}: {exc}"

    candidates: list[StockCandidate] = []
    seen_codes: set[str] = set()

    if spot is None:
        return fetch_stock_candidates_from_code_names(boards, keywords, max_stocks, top_boards, mode, source_note)

    by_name = {str(row.get("名称", "")).strip(): row for _, row in spot.iterrows()}

    def add_candidate(row: Any, source: str, note: str = "") -> None:
        code = str(row.get("代码", "")).strip()
        if not code or code in seen_codes:
            return
        seen_codes.add(code)
        candidates.append(
            StockCandidate(
                code=code,
                name=str(row.get("名称", "")).strip(),
                price=_to_float(str(row.get("最新价", ""))),
                pct=_to_float(str(row.get("涨跌幅", ""))),
                amount_yi=(_to_float(str(row.get("成交额", ""))) or 0) / 100_000_000,
                quote_time=str(row.get("时间戳", "")),
                source=source,
                note=note,
            )
        )

    for board_type, rows in [("行业", boards.get("industry_top", [])), ("概念", boards.get("concept_top", []))]:
        for board in rows[:top_boards]:
            leader = str(board.get("领涨股票", "")).strip()
            if not leader or leader not in by_name:
                continue
            board_name = str(board.get("板块名称", "")).strip()
            source = f"{board_type}板块领涨：{board_name}"
            note = "板块涨幅=" + str(board.get("涨跌幅", "")) + "%"
            add_candidate(by_name[leader], source, note)

    if keywords:
        keyword_rows = []
        for _, row in spot.iterrows():
            name = str(row.get("名称", ""))
            if any(keyword in name for keyword in keywords):
                keyword_rows.append(row)
        keyword_rows.sort(key=lambda row: _to_float(str(row.get("涨跌幅", ""))) or -999, reverse=True)
        for row in keyword_rows[:max_stocks]:
            add_candidate(row, "关键词匹配：" + "/".join(keywords))

    if mode == "all" and len(candidates) < max_stocks:
        market_rows = list(spot.iterrows())
        market_rows.sort(key=lambda item: _to_float(str(item[1].get("涨跌幅", ""))) or -999, reverse=True)
        for _, row in market_rows:
            add_candidate(row, "全A涨幅前列")
            if len(candidates) >= max_stocks:
                break

    return candidates[:max_stocks], source_note


def fetch_stock_candidates_from_code_names(
    boards: dict[str, Any],
    keywords: list[str],
    max_stocks: int,
    top_boards: int,
    mode: str,
    source_note: str | None,
) -> tuple[list[StockCandidate], str | None]:
    try:
        import akshare as ak

        code_names = ak.stock_info_a_code_name()
    except Exception as exc:  # noqa: BLE001
        note = source_note or "A-share spot source failed"
        return [], f"{note}; code-name fallback failed: {type(exc).__name__}: {exc}"

    by_name = {str(row.get("name", "")).strip(): row for _, row in code_names.iterrows()}
    quote_sources: dict[str, tuple[str, str]] = {}

    def add_code_name(row: Any, source: str, note: str = "") -> None:
        raw_code = str(row.get("code", "")).strip()
        if not raw_code:
            return
        quote_sources.setdefault(to_sina_a_code(raw_code), (source, note))

    for board_type, rows in [("行业", boards.get("industry_top", [])), ("概念", boards.get("concept_top", []))]:
        for board in rows[:top_boards]:
            leader = str(board.get("领涨股票", "")).strip()
            if not leader or leader not in by_name:
                continue
            board_name = str(board.get("板块名称", "")).strip()
            source = f"{board_type}板块领涨：{board_name}"
            note = "板块涨幅=" + str(board.get("涨跌幅", "")) + "%"
            add_code_name(by_name[leader], source, note)

    if keywords:
        matched = []
        for _, row in code_names.iterrows():
            name = str(row.get("name", ""))
            if any(keyword in name for keyword in keywords):
                matched.append(row)
        for row in matched[: max(max_stocks * 6, max_stocks)]:
            add_code_name(row, "关键词匹配：" + "/".join(keywords))

    if not quote_sources:
        return [], source_note

    quote_names = {code: code for code in quote_sources}
    quotes, quote_error = fetch_sina_quotes(quote_names, "a")
    quotes.sort(key=lambda quote: quote.pct if quote.pct is not None else -999, reverse=True)
    candidates = []
    for quote in quotes[:max_stocks]:
        source, note = quote_sources.get(quote.code, ("动态发现", ""))
        candidates.append(
            StockCandidate(
                code=quote.code,
                name=quote.name or quote.configured_name,
                price=quote.price,
                pct=quote.pct,
                amount_yi=quote.amount_yi,
                quote_time=" ".join(part for part in [quote.quote_date, quote.quote_time] if part),
                source=source,
                note=note,
            )
        )

    notes = [note for note in [source_note, quote_error] if note]
    if mode == "all":
        notes.append("Fallback mode cannot rank full-market leaders without A-share spot data.")
    return candidates, "; ".join(notes) if notes else None


def to_sina_a_code(code: str) -> str:
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("0", "2", "3")):
        return "sz" + code
    if code.startswith(("4", "8", "9")):
        return "bj" + code
    return code


def fmt_number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def quote_table(quotes: list[Quote]) -> str:
    lines = [
        "| 代码 | 名称 | 最新价 | 涨跌幅 | 成交额(亿元) | 报价时间 | 备注 |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for quote in quotes:
        quote_time = " ".join(part for part in [quote.quote_date, quote.quote_time] if part)
        lines.append(
            "| "
            + " | ".join(
                [
                    quote.code,
                    quote.name or quote.configured_name,
                    fmt_number(quote.price, 3),
                    "N/A" if quote.pct is None else f"{quote.pct:.2f}%",
                    fmt_number(quote.amount_yi, 2),
                    quote_time or "N/A",
                    quote.note,
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def stock_candidate_table(candidates: list[StockCandidate]) -> str:
    if not candidates:
        return "无可用数据。"
    lines = [
        "| 代码 | 名称 | 最新价 | 涨跌幅 | 成交额(亿元) | 报价时间 | 候选来源 | 备注 |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for candidate in candidates:
        lines.append(
            "| "
            + " | ".join(
                [
                    candidate.code,
                    candidate.name,
                    fmt_number(candidate.price, 3),
                    "N/A" if candidate.pct is None else f"{candidate.pct:.2f}%",
                    fmt_number(candidate.amount_yi, 2),
                    candidate.quote_time or "N/A",
                    candidate.source,
                    candidate.note,
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def board_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "无可用数据。"
    wanted = ["排名", "板块名称", "涨跌幅", "换手率", "上涨家数", "下跌家数", "领涨股票", "领涨股票-涨跌幅"]
    lines = [
        "| " + " | ".join(wanted) + " |",
        "| " + " | ".join(["---"] * len(wanted)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key, "")) for key in wanted) + " |")
    return "\n".join(lines)


def build_snapshot(
    a_codes: dict[str, str],
    hk_codes: dict[str, str],
    top: int,
    skip_boards: bool,
    include_hk: bool,
    stock_keywords: list[str],
    max_stocks: int,
    top_stock_boards: int,
    stock_candidate_mode: str,
    fallback_themes: list[str] | None = None,
    stock_map_path: Path = DEFAULT_STOCK_MAP,
) -> dict[str, Any]:
    a_quotes, a_error = fetch_sina_quotes(a_codes, "a")
    hk_quotes: list[Quote] = []
    hk_error = None
    if include_hk:
        hk_quotes, hk_error = fetch_sina_quotes(hk_codes, "hk")

    boards = {} if skip_boards else fetch_akshare_boards(top)
    stock_candidates, stock_candidate_error = fetch_stock_candidates(
        boards=boards,
        keywords=stock_keywords,
        max_stocks=max_stocks,
        top_boards=top_stock_boards,
        mode=stock_candidate_mode,
    )
    fallback_note = None
    if not stock_candidates and stock_candidate_mode != "off" and fallback_themes:
        try:
            mapped = select_mapped_stock_candidates(
                themes=fallback_themes,
                stock_map_path=stock_map_path,
                max_stocks=max_stocks,
            )
            stock_candidates, fallback_quote_error = hydrate_mapped_stock_candidates(mapped, max_stocks)
            if stock_candidates:
                fallback_note = "mapped theme-fit fallback used because dynamic stock_candidates were empty"
            if fallback_quote_error:
                fallback_note = "; ".join(part for part in [fallback_note, fallback_quote_error] if part)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            fallback_note = f"mapped theme-fit fallback failed: {type(exc).__name__}: {exc}"
    stock_candidate_notes = [note for note in [stock_candidate_error, fallback_note] if note]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sources": ["Sina realtime quotes", "EastMoney board data via AkShare"],
        "universe": {"a_quotes": a_codes, "hk_quotes": hk_codes if include_hk else {}},
        "a_quotes": [asdict(quote) for quote in a_quotes],
        "a_quote_error": a_error,
        "hk_quotes": [asdict(quote) for quote in hk_quotes],
        "hk_quote_error": hk_error,
        "boards": boards,
        "stock_candidates": [asdict(candidate) for candidate in stock_candidates],
        "stock_candidate_error": "; ".join(stock_candidate_notes) if stock_candidate_notes else None,
    }


def render_markdown(snapshot: dict[str, Any]) -> str:
    a_quotes = [Quote(**item) for item in snapshot["a_quotes"]]
    hk_quotes = [Quote(**item) for item in snapshot["hk_quotes"]]
    stock_candidates = [StockCandidate(**item) for item in snapshot.get("stock_candidates", [])]
    boards = snapshot.get("boards") or {}
    parts = [
        f"# Market Snapshot {snapshot['generated_at']}",
        "",
        "## A股指数与ETF",
        quote_table(a_quotes) if a_quotes else "无可用数据。",
    ]
    if snapshot.get("a_quote_error"):
        parts.extend(["", f"A股行情错误: {snapshot['a_quote_error']}"])

    if hk_quotes or snapshot.get("hk_quote_error"):
        parts.extend(["", "## 港股指数与重点股", quote_table(hk_quotes) if hk_quotes else "无可用数据。"])
        if snapshot.get("hk_quote_error"):
            parts.extend(["", f"港股行情错误: {snapshot['hk_quote_error']}"])

    if stock_candidates or snapshot.get("stock_candidate_error"):
        parts.extend(["", "## 动态个股候选", stock_candidate_table(stock_candidates)])
        if snapshot.get("stock_candidate_error"):
            parts.extend(["", f"个股候选提示: {snapshot['stock_candidate_error']}"])

    if boards:
        parts.extend(["", "## 行业板块涨幅前列", board_table(boards.get("industry_top", []))])
        if boards.get("industry_error"):
            parts.extend(["", f"行业板块错误: {boards['industry_error']}"])
        parts.extend(["", "## 行业板块跌幅前列", board_table(boards.get("industry_bottom", []))])
        parts.extend(["", "## 概念板块涨幅前列", board_table(boards.get("concept_top", []))])
        if boards.get("concept_error"):
            parts.extend(["", f"概念板块错误: {boards['concept_error']}"])

    return "\n".join(parts) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch compact market quote and board snapshot.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", type=Path, help="Optional output path.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Quote universe JSON file.")
    parser.add_argument("--no-config", action="store_true", help="Ignore config and use only CLI quote codes.")
    parser.add_argument("--a-code", action="append", help="A-share/SZ/SH quote as CODE=NAME. Can repeat or use commas.")
    parser.add_argument("--hk-code", action="append", help="HK quote as CODE=NAME. Can repeat or use commas.")
    parser.add_argument("--stock-keyword", action="append", help="Discover A-share candidates by name keyword. Can repeat or use commas.")
    parser.add_argument(
        "--fallback-theme",
        action="append",
        help="Use stock_industry_map.jsonl to build safe fallback candidates when dynamic discovery is empty. Can repeat or use commas.",
    )
    parser.add_argument("--stock-map", type=Path, default=DEFAULT_STOCK_MAP, help="Fallback stock theme map JSONL file.")
    parser.add_argument("--stock-candidate-mode", choices=["auto", "all", "off"], default="auto")
    parser.add_argument("--max-stocks", type=int, default=12, help="Maximum dynamic stock candidates to render.")
    parser.add_argument("--top-stock-boards", type=int, default=8, help="Top board rows used to discover leader stocks.")
    parser.add_argument("--top", type=int, default=15, help="Number of top/bottom board rows to include.")
    parser.add_argument("--skip-boards", action="store_true", help="Skip AkShare industry/concept board calls.")
    parser.add_argument("--no-hk", action="store_true", help="Skip Hong Kong quotes.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    universe = load_universe(None if args.no_config else args.config)
    a_codes = {**universe["a_quotes"], **parse_code_specs(args.a_code)}
    hk_codes = {**universe["hk_quotes"], **parse_code_specs(args.hk_code)}
    stock_keywords = parse_words(args.stock_keyword)
    fallback_themes = parse_words(args.fallback_theme)
    snapshot = build_snapshot(
        a_codes=a_codes,
        hk_codes=hk_codes,
        top=args.top,
        skip_boards=args.skip_boards,
        include_hk=not args.no_hk,
        stock_keywords=stock_keywords,
        max_stocks=args.max_stocks,
        top_stock_boards=args.top_stock_boards,
        stock_candidate_mode=args.stock_candidate_mode,
        fallback_themes=fallback_themes,
        stock_map_path=args.stock_map,
    )
    if args.format == "json":
        output = json.dumps(snapshot, ensure_ascii=False, indent=2)
    else:
        output = render_markdown(snapshot)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
