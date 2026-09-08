from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass(frozen=True)
class RssSource:
    name: str
    url: str


_DEFAULT_SOURCES: List[RssSource] = [
    # JRJ feeds are GBK encoded but include actual <item> entries.
    RssSource(name="金融界-大盘资讯", url="https://rss.jrj.com.cn/stock/673.xml"),
    RssSource(name="金融界-综合", url="https://rss.jrj.com.cn/stock/734.xml"),
    RssSource(name="金融界-行业新闻", url="https://rss.jrj.com.cn/stock/740.xml"),
    # Keep other providers as best-effort (some feeds may be empty depending on region/network).
    RssSource(name="凤凰-股市要闻", url="https://finance.ifeng.com/rss/stocknews.xml"),
    RssSource(name="凤凰-基金要闻", url="https://finance.ifeng.com/rss/fundnews.xml"),
]


def _fetch_bytes(url: str, timeout_seconds: float = 12.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AHRecommendationSystem/1.0)",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        return resp.read()


def _parse_rss_datetime(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return s


def _decode_xml_bytes(xml_bytes: bytes) -> str:
    head = bytes(xml_bytes[:200]).decode("ascii", errors="ignore")
    m = re.search(r"encoding=['\"]([^'\"]+)['\"]", head, re.IGNORECASE)
    enc = (m.group(1) if m else "utf-8").strip().lower()
    if enc in ("gbk", "gb2312", "gb18030"):
        return bytes(xml_bytes).decode(enc, errors="replace")
    return bytes(xml_bytes).decode("utf-8", errors="replace")


def _extract_items(xml_bytes: bytes) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        text = _decode_xml_bytes(xml_bytes)
        root = ET.fromstring(text)
    except Exception as e:
        logger.warning(f"RSS parse failed: {e}")
        return items

    # RSS 2.0: channel/item
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = _parse_rss_datetime(item.findtext("pubDate") or "")
        desc = (item.findtext("description") or "").strip()
        if not title or not link:
            continue
        items.append(
            {
                "title": title,
                "url": link,
                "published_at": pub,
                "summary": desc,
            }
        )

    # Atom: entry
    if not items:
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = (link_el.get("href") if link_el is not None else "") or ""
            updated = (
                entry.findtext("{http://www.w3.org/2005/Atom}updated") or ""
            ).strip()
            summary = (
                entry.findtext("{http://www.w3.org/2005/Atom}summary") or ""
            ).strip()
            if not title or not link:
                continue
            items.append(
                {
                    "title": title,
                    "url": link,
                    "published_at": updated,
                    "summary": summary,
                }
            )

    return items


_CN_WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def _hot_keywords(titles: List[str], limit: int = 20) -> List[Dict[str, Any]]:
    stop = {
        "今日",
        "最新",
        "市场",
        "财经",
        "公司",
        "基金",
        "股票",
        "行业",
        "板块",
        "数据",
        "中国",
        "A股",
        "港股",
        "ETF",
    }
    counts: Dict[str, int] = {}
    for t in titles:
        for w in _CN_WORD_RE.findall(t or ""):
            if w in stop:
                continue
            counts[w] = counts.get(w, 0) + 1
    sorted_items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [{"keyword": k, "count": v} for k, v in sorted_items[:limit]]


def _parse_datetime_value(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    patterns = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"]
    for pattern in patterns:
        try:
            dt = datetime.strptime(text, pattern)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone()
        except Exception:
            continue
    return None


def fetch_news_digest(
    *,
    sources: Optional[List[RssSource]] = None,
    max_items: int = 120,
    max_age_days: int = 7,
) -> Dict[str, Any]:
    used = sources or _DEFAULT_SOURCES
    all_items: List[Dict[str, Any]] = []

    for src in used:
        try:
            xml_bytes = _fetch_bytes(src.url)
            items = _extract_items(xml_bytes)
            for it in items:
                it["source"] = src.name
                all_items.append(it)
        except Exception as e:
            logger.warning(f"RSS fetch failed ({src.name}): {e}")

    # Dedupe by URL
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for it in all_items:
        url = str(it.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(it)
        if len(deduped) >= max_items:
            break

    cutoff = datetime.now().astimezone() - timedelta(
        days=max(1, int(max_age_days or 7))
    )
    fresh_items = []
    stale_count = 0
    latest_published_at = None
    for it in deduped:
        parsed = _parse_datetime_value(it.get("published_at"))
        if parsed and (latest_published_at is None or parsed > latest_published_at):
            latest_published_at = parsed
        if parsed and parsed >= cutoff:
            fresh_items.append(it)
        else:
            stale_count += 1

    titles = [str(it.get("title") or "") for it in fresh_items]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(fresh_items),
        "items": fresh_items,
        "hot_keywords": _hot_keywords(titles),
        "freshness": {
            "max_age_days": max(1, int(max_age_days or 7)),
            "stale_count": stale_count,
            "is_stale": len(fresh_items) == 0 and len(deduped) > 0,
            "latest_published_at": latest_published_at.strftime("%Y-%m-%d %H:%M:%S")
            if latest_published_at
            else None,
            "status": "stale_filtered"
            if len(fresh_items) == 0 and len(deduped) > 0
            else "ok",
        },
    }
