"""Rank collected news into a compact hotspot evidence pack."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
import os
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_HOTSPOT_EVIDENCE_LIMIT = 36

POLICY_TERMS = ("政策", "监管", "发改委", "证监会", "国务院", "关税", "制裁", "价格监督检查", "查处")
PRICE_SUPPLY_TERMS = ("价格", "涨价", "回落", "供应", "库存", "检修", "限电", "气价", "油价")
INDUSTRY_TERMS = ("半导体", "新能源", "军工", "有色", "航运", "银行", "券商", "医药", "工业硅", "多晶硅", "硅料", "卫星", "芯片")
FOREIGN_TERMS = ("北向", "外资", "ETF份额", "ETF 份额")
KEYWORD_TERMS = POLICY_TERMS + PRICE_SUPPLY_TERMS + ("北向", "ETF份额")
QUALITY_SOURCES = ("证券时报", "财联社", "上证报", "中证报", "新华", "人民日报")
COMPANY_ONLY_TERMS = ("回购", "增持", "减持", "分红")

_HANZI_RE = re.compile(r"[一-鿿]+")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _blob(item: Mapping[str, Any]) -> str:
    return " ".join(_text(item.get(key)) for key in ("title", "summary", "content"))


def classify_query_bucket(item: Mapping[str, Any]) -> str:
    blob = _blob(item)
    if any(term in blob for term in POLICY_TERMS):
        return "policy"
    if any(term in blob for term in PRICE_SUPPLY_TERMS):
        return "price_supply"
    if any(term in blob for term in INDUSTRY_TERMS):
        return "industry"
    if any(term in blob for term in FOREIGN_TERMS):
        return "foreign_capital"
    if any(term in blob for term in COMPANY_ONLY_TERMS):
        return "company"
    return "macro_tape"


def _parse_published_at(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:19] if len(text) >= 19 else text, pattern)
        except ValueError:
            continue
    return None


def _cluster_key(item: Mapping[str, Any]) -> str:
    title = _text(item.get("title"))
    hanzi = "".join(_HANZI_RE.findall(title))
    if len(hanzi) >= 8:
        return f"title:{hanzi[:24]}"
    if title:
        return f"title:{title.casefold()[:80]}"
    url = _text(item.get("url")).split("?", 1)[0]
    return f"url:{url}" if url else ""


def score_news_item(item: Mapping[str, Any], *, candidates: Sequence[Mapping[str, Any]] = (), now: datetime | None = None) -> float:
    blob = _blob(item)
    bucket = _text(item.get("query_bucket")) or classify_query_bucket(item)
    score = {"policy": 5.0, "price_supply": 5.0, "industry": 4.0, "foreign_capital": 3.0, "company": 1.0}.get(bucket, 0.0)
    score += sum(1.0 for term in KEYWORD_TERMS if term in blob)
    source = _text(item.get("source"))
    if any(name in source for name in QUALITY_SOURCES):
        score += 2.0
    candidate_bits: list[str] = []
    for row in candidates:
        candidate_bits.extend(_text(row.get(key)) for key in ("name", "code"))
        for key in ("focus_industries", "industries"):
            value = row.get(key) or []
            if isinstance(value, (list, tuple, set)):
                candidate_bits.extend(_text(part) for part in value)
            else:
                candidate_bits.append(_text(value))
    if any(bit and len(bit) >= 2 and bit in blob for bit in candidate_bits):
        score += 3.0
    published = _parse_published_at(item.get("published_at"))
    current = now or datetime.now()
    if published and published.date() == current.date():
        score += 1.0
    return score




def hotspot_evidence_limit(limit: int | None = None) -> int:
    if limit is not None:
        return max(8, min(int(limit), 60))
    raw = os.environ.get("AH_HOTSPOT_EVIDENCE_LIMIT", str(DEFAULT_HOTSPOT_EVIDENCE_LIMIT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_HOTSPOT_EVIDENCE_LIMIT
    return max(8, min(value, 60))

def select_hotspot_evidence(news_items: Iterable[Mapping[str, Any]], *, candidates: Sequence[Mapping[str, Any]] = (), limit: int | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    limit = hotspot_evidence_limit(limit)
    current = now or datetime.now()
    cutoff = current - timedelta(days=7)
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for index, raw in enumerate(news_items or []):
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        title = _text(item.get("title"))
        if not title:
            continue
        published = _parse_published_at(item.get("published_at"))
        if published and published < cutoff:
            continue
        item["query_bucket"] = _text(item.get("query_bucket")) or classify_query_bucket(item)
        ranked.append((score_news_item(item, candidates=candidates, now=current), -index, item))
    ranked.sort(reverse=True)
    selected: list[dict[str, Any]] = []
    clusters: dict[str, dict[str, Any]] = {}
    for _score, _order, item in ranked:
        key = _cluster_key(item)
        if not key:
            continue
        existing = clusters.get(key)
        if existing is None:
            row = dict(item)
            row["reprint_count"] = 1
            row["reprint_urls"] = [_text(item.get("url"))] if _text(item.get("url")) else []
            clusters[key] = row
            selected.append(row)
            if len(selected) >= max(0, int(limit)):
                break
            continue
        existing["reprint_count"] = int(existing.get("reprint_count") or 1) + 1
        url = _text(item.get("url"))
        if url and url not in (existing.get("reprint_urls") or []):
            existing.setdefault("reprint_urls", []).append(url)
    return selected

