from __future__ import annotations

import re
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ah_recommendation_system.backend.etf_sector.etf_trend_analysis import (
    DEFAULT_ETF_UNIVERSE,
)
from ah_recommendation_system.backend.etf_sector.ths_sources import (
    fetch_board_trend_items_ths,
    fetch_concept_summary_ths,
    fetch_etf_spot_sina,
    fetch_etf_spot_ths,
    fetch_industry_summary_ths,
    normalize_concept_summary_ths,
    normalize_display_text,
    normalize_etf_spot_sina,
    normalize_etf_spot_ths,
    normalize_industry_summary_ths,
)


_CODE_PATTERN = re.compile(r"\d{6}")
_NOISE_WORDS = (
    "etf",
    "ETF",
    "指数",
    "主题",
    "行业",
    "概念",
    "基金",
    "联接",
    "增强",
    "龙头",
    "交易型开放式",
    "同花顺",
)
_THEME_ALIASES = {
    "证券": ["证券", "券商", "非银"],
    "半导体": ["半导体", "芯片", "集成电路"],
    "医药": ["医药", "医疗", "创新药", "生物医药", "医药生物"],
    "黄金": ["黄金", "贵金属"],
    "有色": ["有色", "资源", "铜", "稀土", "黄金股"],
    "军工": ["军工", "国防", "航空航天"],
    "消费": ["消费", "白酒", "食品饮料", "家电"],
    "新能源": ["新能源", "光伏", "储能", "锂电", "电池", "新能车"],
    "机器人": ["机器人", "自动化", "智能制造"],
    "人工智能": ["人工智能", "AI", "算力", "数据", "信创", "软件"],
    "红利": ["红利", "高股息"],
    "银行": ["银行", "金融"],
    "港股": ["港股", "恒生", "恒生科技", "互联网"],
    "纳指": ["纳指", "纳斯达克", "美股", "科技"],
    "创业板": ["创业板", "成长"],
}


def _normalize_code(value: Any) -> Optional[str]:
    match = _CODE_PATTERN.search(str(value or ""))
    return match.group(0) if match else None


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text or text in {"--", "nan", "NaN", "None"}:
            return None
        return float(text)
    except Exception:
        return None


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for word in _NOISE_WORDS:
        text = text.replace(word, "")
    return re.sub(r"\s+", "", text)


def _canonical_theme_name(name: Any) -> str:
    text = _clean_text(name)
    if not text:
        return ""
    for canonical, aliases in _THEME_ALIASES.items():
        if any(alias and alias in text for alias in aliases):
            return canonical
    return text


def _theme_keywords(name: Any) -> List[str]:
    canonical = _canonical_theme_name(name)
    if not canonical:
        return []
    keywords = {canonical}
    for key, aliases in _THEME_ALIASES.items():
        if (
            key == canonical
            or canonical in aliases
            or key in canonical
            or canonical in key
        ):
            keywords.update(alias for alias in aliases if alias)
            keywords.add(key)
    return sorted({kw for kw in keywords if len(kw) >= 2}, key=len, reverse=True)


def _extract_concept_payload() -> Dict[str, Any]:
    df = fetch_concept_summary_ths()
    items = normalize_concept_summary_ths(df, limit=20)
    return {"items": items[:20]}


def _extract_theme_names(
    industry_payload: Dict[str, Any], concept_payload: Dict[str, Any]
) -> Dict[str, List[str]]:
    industry_names = [
        normalize_display_text(item.get("name"))
        for item in (industry_payload or {}).get("top_gainers", [])[:8]
        if isinstance(item, dict)
    ]
    concept_names = [
        normalize_display_text(item.get("concept"))
        for item in (concept_payload or {}).get("items", [])[:8]
        if isinstance(item, dict)
    ]
    return {
        "industry": [name for name in industry_names if name.strip()],
        "concept": [name for name in concept_names if name.strip()],
    }


def _fetch_board_trend_payload(
    industry_names: Sequence[str], concept_names: Sequence[str]
) -> Dict[str, Any]:
    lookbacks = [5, 10, 20]
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=200)).strftime("%Y%m%d")
    return {
        "source": "ths",
        "lookbacks": lookbacks,
        "start_date": start_date,
        "end_date": end_date,
        "industry": {
            "items": fetch_board_trend_items_ths(
                kind="industry",
                names=sorted(set(industry_names)),
                lookbacks=lookbacks,
                start_date=start_date,
                end_date=end_date,
                per_item_delay_s=0.0,
            )
        },
        "concept": {
            "items": fetch_board_trend_items_ths(
                kind="concept",
                names=sorted(set(concept_names)),
                lookbacks=lookbacks,
                start_date=start_date,
                end_date=end_date,
                per_item_delay_s=0.0,
            )
        },
    }


def _theme_buckets(
    industry_payload: Dict[str, Any],
    concept_payload: Dict[str, Any],
    trend_payload: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}

    def ensure(theme_name: str) -> Dict[str, Any]:
        key = _canonical_theme_name(theme_name)
        if not key:
            return {}
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "theme": key,
                "source_votes": 0,
                "industry_mentions": [],
                "concept_mentions": [],
                "board_items": [],
                "score": 0.0,
                "stage": "观察",
                "reasons": [],
            }
            buckets[key] = bucket
        return bucket

    for idx, item in enumerate((industry_payload or {}).get("top_gainers", [])[:8]):
        if not isinstance(item, dict):
            continue
        bucket = ensure(item.get("name"))
        if not bucket:
            continue
        bucket["source_votes"] += 1
        bucket["industry_mentions"].append(
            {
                "name": item.get("name"),
                "rank": idx + 1,
                "chg_pct": item.get("chg_pct"),
            }
        )
        bucket["score"] += max(0.0, 16.0 - idx * 1.5)
        bucket["reasons"].append(f"行业强弱榜前列#{idx + 1}")

    for idx, item in enumerate((concept_payload or {}).get("items", [])[:8]):
        if not isinstance(item, dict):
            continue
        bucket = ensure(item.get("concept"))
        if not bucket:
            continue
        bucket["source_votes"] += 1
        bucket["concept_mentions"].append(
            {
                "name": item.get("concept"),
                "rank": idx + 1,
                "headline": item.get("headline"),
            }
        )
        bucket["score"] += max(0.0, 12.0 - idx)
        bucket["reasons"].append(f"热概念摘要入选#{idx + 1}")

    for kind in ("industry", "concept"):
        for item in ((trend_payload or {}).get(kind, {}) or {}).get("items", []):
            if not isinstance(item, dict) or item.get("error"):
                continue
            bucket = ensure(item.get("name"))
            if not bucket:
                continue
            bucket["board_items"].append(item)

    for bucket in buckets.values():
        board_score = 0.0
        accelerating = False
        persistence = False
        for item in bucket.get("board_items") or []:
            ret5 = _to_float(item.get("ret_5d"))
            ret10 = _to_float(item.get("ret_10d"))
            ret20 = _to_float(item.get("ret_20d"))
            if ret5 is not None and ret5 > 0:
                board_score += 8.0
            if ret10 is not None and ret10 > 0:
                board_score += 6.0
            if ret20 is not None and ret20 > 0:
                board_score += 6.0
            if (
                ret5 is not None
                and ret10 is not None
                and ret5 > ret10 * 0.7
                and ret5 > 1.5
            ):
                accelerating = True
            if (
                ret5 is not None
                and ret10 is not None
                and ret20 is not None
                and ret5 > 0
                and ret10 > 0
                and ret20 > 0
            ):
                persistence = True
        bucket["score"] += board_score
        if persistence and accelerating:
            bucket["stage"] = "加速"
            bucket["score"] += 10.0
            bucket["reasons"].append("板块 5/10/20 日动量共振，且短期加速")
        elif persistence:
            bucket["stage"] = "持续走强"
            bucket["score"] += 7.0
            bucket["reasons"].append("板块 5/10/20 日动量共振")
        elif accelerating:
            bucket["stage"] = "准备启动"
            bucket["score"] += 5.0
            bucket["reasons"].append("板块短期动量抬升")
        elif bucket["board_items"]:
            bucket["reasons"].append("板块趋势已纳入观察")

    return buckets


def _candidate_pool_from_sources(
    sina_rows: Sequence[Dict[str, Any]], ths_rows: Sequence[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    pool: Dict[str, Dict[str, Any]] = {}

    def ensure(code: str, name: str) -> Dict[str, Any]:
        item = pool.get(code)
        if item is None:
            item = {
                "code": code,
                "name": name or f"ETF {code}",
                "score": 0.0,
                "reasons": [],
                "matched_themes": [],
                "turnover_rank": None,
                "gainer_rank": None,
            }
            pool[code] = item
        elif name and (
            not item.get("name") or str(item.get("name")).startswith("ETF ")
        ):
            item["name"] = name
        return item

    for item in DEFAULT_ETF_UNIVERSE:
        ensure(item.code, item.name)

    for idx, row in enumerate(sina_rows or []):
        code = _normalize_code(row.get("code"))
        if not code:
            continue
        item = ensure(code, str(row.get("name") or ""))
        item["turnover_rank"] = idx + 1
        item["score"] += max(0.0, 24.0 - idx)
        item["reasons"].append(f"ETF 成交额活跃#{idx + 1}")

    for idx, row in enumerate(ths_rows or []):
        code = _normalize_code(row.get("code"))
        if not code:
            continue
        item = ensure(code, str(row.get("name") or ""))
        item["gainer_rank"] = idx + 1
        item["score"] += max(0.0, 18.0 - idx)
        item["reasons"].append(f"ETF 涨幅热度#{idx + 1}")

    return pool


def _score_etfs_for_themes(
    theme_rows: Sequence[Dict[str, Any]], pool: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    for etf in pool.values():
        clean_name = _clean_text(etf.get("name"))
        for theme in theme_rows:
            theme_name = str(theme.get("theme") or "")
            keywords = _theme_keywords(theme_name)
            if not clean_name or not keywords:
                continue
            strength = 0.0
            if any(keyword and keyword == clean_name for keyword in keywords):
                strength = 16.0
            elif any(keyword and keyword in clean_name for keyword in keywords):
                strength = 10.0
            if strength <= 0:
                continue
            if theme.get("stage") == "加速":
                strength += 5.0
            elif theme.get("stage") == "持续走强":
                strength += 3.0
            strength += min(12.0, float(theme.get("score") or 0.0) / 6.0)
            etf["score"] += strength
            etf["matched_themes"].append(theme_name)
            etf["reasons"].append(f"匹配主题:{theme_name}({theme.get('stage')})")

    ranked = sorted(
        pool.values(),
        key=lambda item: (
            -float(item.get("score") or 0.0),
            len(item.get("matched_themes") or []) == 0,
            int(item.get("turnover_rank") or 999),
            str(item.get("code") or ""),
        ),
    )
    return ranked


def _fill_with_defaults(
    selected: List[Dict[str, Any]], ranked_pool: Sequence[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    seen = {str(item.get("code") or "") for item in selected}
    for item in ranked_pool:
        code = str(item.get("code") or "")
        if not code or code in seen:
            continue
        selected.append(item)
        seen.add(code)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _theme_return_snapshot(
    bucket: Dict[str, Any],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    ret5_values: List[float] = []
    ret10_values: List[float] = []
    ret20_values: List[float] = []
    for item in bucket.get("board_items") or []:
        ret5 = _to_float(item.get("ret_5d"))
        ret10 = _to_float(item.get("ret_10d"))
        ret20 = _to_float(item.get("ret_20d"))
        if ret5 is not None:
            ret5_values.append(ret5)
        if ret10 is not None:
            ret10_values.append(ret10)
        if ret20 is not None:
            ret20_values.append(ret20)
    return (
        max(ret5_values) if ret5_values else None,
        max(ret10_values) if ret10_values else None,
        max(ret20_values) if ret20_values else None,
    )


def _collect_theme_etf_rows(
    etf_payload: Dict[str, Any],
    selection_payload: Optional[Dict[str, Any]],
    etf_trend_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}

    def ensure(code: str, name: str) -> Dict[str, Any]:
        item = rows.get(code)
        if item is None:
            item = {
                "code": code,
                "name": name or f"ETF {code}",
                "turnover_rank": None,
                "gainer_rank": None,
                "selection_score": None,
                "trend_score": None,
                "trend_label": None,
                "recommendation": None,
                "status": None,
            }
            rows[code] = item
        elif name and str(item.get("name") or "").startswith("ETF "):
            item["name"] = name
        return item

    for idx, item in enumerate((etf_payload or {}).get("top_by_turnover") or []):
        if not isinstance(item, dict):
            continue
        code = _normalize_code(item.get("code"))
        if not code:
            continue
        row = ensure(code, str(item.get("name") or ""))
        row["turnover_rank"] = idx + 1

    gainers = list((etf_payload or {}).get("top_gainers") or []) + list(
        (etf_payload or {}).get("top_gainers_nav") or []
    )
    for idx, item in enumerate(gainers):
        if not isinstance(item, dict):
            continue
        code = _normalize_code(item.get("code"))
        if not code:
            continue
        row = ensure(code, str(item.get("name") or ""))
        current_rank = row.get("gainer_rank")
        next_rank = idx + 1
        if current_rank is None or next_rank < current_rank:
            row["gainer_rank"] = next_rank

    for item in (selection_payload or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        code = _normalize_code(item.get("code"))
        if not code:
            continue
        row = ensure(code, str(item.get("name") or ""))
        score = _to_float(item.get("score"))
        if score is not None:
            row["selection_score"] = score

    for item in (etf_trend_payload or {}).get("recommendations") or []:
        if not isinstance(item, dict):
            continue
        code = _normalize_code(item.get("code"))
        if not code:
            continue
        row = ensure(code, str(item.get("name") or ""))
        trend_score = _to_float(item.get("trend_score"))
        if trend_score is not None:
            row["trend_score"] = trend_score
        if item.get("trend_label"):
            row["trend_label"] = item.get("trend_label")
        if item.get("recommendation"):
            row["recommendation"] = item.get("recommendation")
        if item.get("status"):
            row["status"] = item.get("status")

    return rows


def _match_related_etfs(
    theme_name: str, etf_rows: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    keywords = _theme_keywords(theme_name)
    if not keywords:
        return []

    matched: List[Tuple[float, Dict[str, Any]]] = []
    for item in etf_rows.values():
        clean_name = _clean_text(item.get("name"))
        if not clean_name:
            continue
        strength = 0.0
        if any(keyword and keyword == clean_name for keyword in keywords):
            strength = 30.0
        elif any(keyword and keyword in clean_name for keyword in keywords):
            strength = 18.0
        if strength <= 0:
            continue
        selection_score = _to_float(item.get("selection_score"))
        if selection_score is not None:
            strength += min(12.0, selection_score / 10.0)
        trend_score = _to_float(item.get("trend_score"))
        if trend_score is not None:
            strength += min(12.0, max(0.0, trend_score - 50.0) / 2.5)
        turnover_rank = item.get("turnover_rank")
        if turnover_rank:
            strength += max(0.0, 10.0 - min(float(turnover_rank), 10.0))
        gainer_rank = item.get("gainer_rank")
        if gainer_rank:
            strength += max(0.0, 8.0 - min(float(gainer_rank), 8.0))
        matched.append((strength, item))

    matched.sort(
        key=lambda pair: (
            -pair[0],
            int(pair[1].get("turnover_rank") or 999),
            int(pair[1].get("gainer_rank") or 999),
            str(pair[1].get("code") or ""),
        )
    )
    return [
        {
            "code": row.get("code"),
            "name": row.get("name"),
            "turnover_rank": row.get("turnover_rank"),
            "gainer_rank": row.get("gainer_rank"),
            "selection_score": row.get("selection_score"),
            "trend_score": row.get("trend_score"),
            "trend_label": row.get("trend_label"),
            "recommendation": row.get("recommendation"),
            "status": row.get("status"),
            "confirmation": (
                "trend_confirmed"
                if (_to_float(row.get("trend_score")) or 0.0) >= 60.0
                or str(row.get("recommendation") or "") in {"优先关注", "持有观察"}
                else "heat_confirmed"
                if (
                    (
                        row.get("turnover_rank")
                        and int(row.get("turnover_rank") or 999) <= 10
                    )
                    or (
                        row.get("gainer_rank")
                        and int(row.get("gainer_rank") or 999) <= 10
                    )
                )
                else "matched"
            ),
        }
        for _, row in matched[:3]
        if row.get("code")
    ]


def _theme_news_heat(theme_name: str, news_payload: Dict[str, Any]) -> int:
    keywords = _theme_keywords(theme_name)
    if not keywords:
        return 0

    heat = 0
    for item in (news_payload or {}).get("hot_keywords") or []:
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword") or "")
        if any(token and token in keyword for token in keywords):
            heat += int(_to_float(item.get("count")) or 1)

    for item in (news_payload or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        if any(token and token in title for token in keywords):
            heat += 1

    return heat


def _dedupe_texts(values: Sequence[str], limit: int = 4) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _bounded_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _format_pct(value: Optional[float]) -> str:
    return "--" if value is None else f"{value:.1f}%"


def _pick_primary_board_item(bucket: Dict[str, Any]) -> Dict[str, Any]:
    best_item: Dict[str, Any] = {}
    best_score = float("-inf")
    for item in bucket.get("board_items") or []:
        if not isinstance(item, dict):
            continue
        ret5 = _to_float(item.get("ret_5d")) or 0.0
        ret10 = _to_float(item.get("ret_10d")) or 0.0
        ret20 = _to_float(item.get("ret_20d")) or 0.0
        score = ret5 * 1.2 + ret10 + ret20 * 0.8
        if score > best_score:
            best_score = score
            best_item = item
    return best_item


def _build_relative_strength_map(
    theme_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    scored_rows: List[Tuple[str, float]] = []
    for row in theme_rows:
        theme_name = str(row.get("theme") or "").strip()
        if not theme_name:
            continue
        ret5 = _to_float(row.get("ret_5d"))
        ret10 = _to_float(row.get("ret_10d"))
        ret20 = _to_float(row.get("ret_20d"))
        if ret5 is None and ret10 is None and ret20 is None:
            continue
        composite = (ret5 or 0.0) * 1.4 + (ret10 or 0.0) + (ret20 or 0.0) * 0.6
        scored_rows.append((theme_name, composite))

    if not scored_rows:
        return {}

    ordered = sorted(scored_rows, key=lambda item: (-item[1], item[0]))
    total = len(ordered)
    middle = float(median(value for _, value in ordered))
    details: Dict[str, Dict[str, Any]] = {}
    for idx, (theme_name, composite) in enumerate(ordered, start=1):
        percentile = 1.0 if total <= 1 else 1.0 - float(idx - 1) / float(total - 1)
        if total <= 1:
            signal = "peer_unavailable"
            score = 0.0
            summary = "可比主题不足，暂不做强弱排序"
        else:
            if percentile >= 0.75:
                signal = "peer_leader"
                score = 8.0
            elif percentile >= 0.5:
                signal = "above_average"
                score = 5.0
            elif percentile >= 0.25:
                signal = "middle"
                score = 2.0
            else:
                signal = "lagging"
                score = 0.0
            vs_median = composite - middle
            if vs_median >= 1.5:
                delta_text = f"，高于中位 {vs_median:.1f} 分"
            elif vs_median <= -1.5:
                delta_text = f"，低于中位 {abs(vs_median):.1f} 分"
            else:
                delta_text = "，接近中位"
            summary = f"同类强弱第 {idx}/{total}{delta_text}"
        details[theme_name] = {
            "score": round(score, 1),
            "signal": signal,
            "rank": idx,
            "total": total,
            "summary": summary,
            "peer_score": round(composite, 1),
            "vs_median": round(composite - middle, 1),
        }
    return details


def build_theme_breakout_block(
    *,
    industry_payload: Optional[Dict[str, Any]] = None,
    concept_payload: Optional[Dict[str, Any]] = None,
    trend_payload: Optional[Dict[str, Any]] = None,
    news_payload: Optional[Dict[str, Any]] = None,
    etf_payload: Optional[Dict[str, Any]] = None,
    etf_trend_payload: Optional[Dict[str, Any]] = None,
    selection_payload: Optional[Dict[str, Any]] = None,
    limit_per_bucket: int = 3,
) -> Dict[str, Any]:
    """Build staged theme candidates from already-fetched ETF sector payloads."""
    limit = max(1, min(int(limit_per_bucket or 3), 5))
    trend_for_buckets = {
        "industry": ((trend_payload or {}).get("industry") or {}),
        "concept": ((trend_payload or {}).get("concept") or {}),
    }
    theme_buckets = _theme_buckets(
        industry_payload or {}, concept_payload or {}, trend_for_buckets
    )
    etf_rows = _collect_theme_etf_rows(
        etf_payload or {}, selection_payload, etf_trend_payload
    )
    theme_snapshots: List[Dict[str, Any]] = []
    for bucket in theme_buckets.values():
        theme_name = str(bucket.get("theme") or "").strip()
        if not theme_name:
            continue
        related_etfs = _match_related_etfs(theme_name, etf_rows)
        primary_item = _pick_primary_board_item(bucket)
        theme_snapshots.append(
            {
                "bucket": bucket,
                "theme": theme_name,
                "related_etfs": related_etfs,
                "ret_5d": _to_float(primary_item.get("ret_5d")),
                "ret_10d": _to_float(primary_item.get("ret_10d")),
                "ret_20d": _to_float(primary_item.get("ret_20d")),
                "top_industry_rank": min(
                    (
                        int(it.get("rank"))
                        for it in (bucket.get("industry_mentions") or [])
                        if it.get("rank")
                    ),
                    default=None,
                ),
                "news_heat": _theme_news_heat(theme_name, news_payload or {}),
            }
        )
    relative_strength_map = _build_relative_strength_map(theme_snapshots)

    breakout_rows: List[Dict[str, Any]] = []
    leader_rows: List[Dict[str, Any]] = []
    crowded_rows: List[Dict[str, Any]] = []

    for snapshot in theme_snapshots:
        bucket = snapshot.get("bucket") or {}
        theme_name = str(snapshot.get("theme") or "").strip()
        related_etfs = list(snapshot.get("related_etfs") or [])
        ret5 = _to_float(snapshot.get("ret_5d"))
        ret10 = _to_float(snapshot.get("ret_10d"))
        ret20 = _to_float(snapshot.get("ret_20d"))
        top_industry_rank = snapshot.get("top_industry_rank")
        news_heat = int(snapshot.get("news_heat") or 0)
        persistent = all(
            value is not None and value > 0 for value in (ret5, ret10, ret20)
        )
        ret5_gt_ret10 = ret5 is not None and ret10 is not None and ret5 > ret10
        ret10_gt_ret20 = ret10 is not None and ret20 is not None and ret10 > ret20
        turning_up = bool(
            ret5 is not None
            and ret5 > 0
            and (
                (ret10 is not None and ret10 <= 0) or (ret20 is not None and ret20 <= 0)
            )
        )
        emerging = bool(ret5_gt_ret10 and (turning_up or ret10_gt_ret20))
        mature_trend = bool(
            persistent
            and ret5 is not None
            and ret10 is not None
            and ret20 is not None
            and ret5 <= ret10 <= ret20
        )

        trend_score = 0.0
        trend_score += 16.0 if ret5 is not None and ret5 > 0 else 0.0
        trend_score += 12.0 if ret10 is not None and ret10 > 0 else 0.0
        trend_score += 8.0 if ret20 is not None and ret20 > 0 else 0.0
        if persistent:
            trend_score += 6.0
        elif turning_up:
            trend_score += 4.0
        trend_score = min(42.0, trend_score)

        acceleration_score = 0.0
        if ret5 is not None and ret10 is not None:
            acceleration_score += min(14.0, max(0.0, ret5 - ret10) * 2.4)
        if ret10 is not None and ret20 is not None:
            acceleration_score += min(10.0, max(0.0, ret10 - ret20) * 1.8)
        if turning_up:
            acceleration_score += 8.0
        if persistent and ret5_gt_ret10 and ret10_gt_ret20:
            acceleration_score += 4.0
        acceleration_score = min(30.0, acceleration_score)

        etf_heat_count = sum(
            1
            for etf in related_etfs
            if (etf.get("turnover_rank") and int(etf.get("turnover_rank") or 999) <= 10)
            or (etf.get("gainer_rank") and int(etf.get("gainer_rank") or 999) <= 10)
        )
        etf_trend_count = sum(
            1
            for etf in related_etfs
            if (_to_float(etf.get("trend_score")) or 0.0) >= 60.0
            or str(etf.get("recommendation") or "") in {"优先关注", "持有观察"}
        )
        etf_confirmed_count = sum(
            1
            for etf in related_etfs
            if str(etf.get("confirmation") or "") in {"trend_confirmed", "heat_confirmed"}
        )
        etf_dual_confirmation_count = sum(
            1
            for etf in related_etfs
            if (
                (_to_float(etf.get("trend_score")) or 0.0) >= 60.0
                or str(etf.get("recommendation") or "") in {"优先关注", "持有观察"}
            )
            and (
                (
                    etf.get("turnover_rank")
                    and int(etf.get("turnover_rank") or 999) <= 10
                )
                or (
                    etf.get("gainer_rank")
                    and int(etf.get("gainer_rank") or 999) <= 10
                )
            )
        )
        etf_confirmation_breadth = (
            round(etf_confirmed_count / float(len(related_etfs)), 2)
            if related_etfs
            else 0.0
        )
        etf_confirmation_score = min(
            20.0,
            float(len(related_etfs)) * 4.0
            + float(etf_heat_count) * 4.0
            + float(etf_trend_count) * 6.0,
        )

        industry_confirmation_score = 0.0
        if top_industry_rank is not None and top_industry_rank <= 3:
            industry_confirmation_score = 6.0
        elif top_industry_rank is not None and top_industry_rank <= 5:
            industry_confirmation_score = 4.0
        elif top_industry_rank is not None and top_industry_rank <= 8:
            industry_confirmation_score = 2.0

        relative_strength = relative_strength_map.get(theme_name) or {
            "score": 0.0,
            "signal": "peer_unavailable",
            "rank": None,
            "total": 0,
            "summary": "可比主题不足，暂不做强弱排序",
            "peer_score": None,
            "vs_median": None,
        }
        relative_strength_score = _to_float(relative_strength.get("score")) or 0.0

        source_tags: List[str] = []
        if bucket.get("industry_mentions"):
            source_tags.append("行业")
        if bucket.get("concept_mentions"):
            source_tags.append("概念")
        if news_heat > 0:
            source_tags.append("消息")
        source_count = len(source_tags)
        if source_count >= 2:
            source_signal = "multi_source_resonance"
            source_summary = f"{'/'.join(source_tags)}三路共振"
        elif source_count == 2:
            source_signal = "dual_source_confirmation"
            source_summary = f"{'+'.join(source_tags)}双确认"
        elif source_count == 1:
            source_signal = "single_source"
            source_summary = f"仅{source_tags[0]}侧验证"
        else:
            source_signal = "none"
            source_summary = "暂无额外共振"

        if related_etfs:
            if etf_confirmation_breadth >= 0.67 and etf_dual_confirmation_count > 0:
                breadth_signal = "broad_confirmation"
            elif etf_confirmation_breadth > 0:
                breadth_signal = "partial_confirmation"
            else:
                breadth_signal = "narrow_mapping"
            breadth_summary = (
                f"{etf_confirmed_count}/{len(related_etfs)} 只ETF已确认，双确认 {etf_dual_confirmation_count} 只"
            )
        else:
            breadth_signal = "none"
            breadth_summary = "暂无ETF广度确认"

        if persistent and ret5_gt_ret10 and ret10_gt_ret20:
            persistence_signal = "reaccelerating"
            persistence_summary = "短中长同步抬升，延续性更强"
        elif emerging:
            persistence_signal = "fresh_turn"
            persistence_summary = "短线先抬头，仍在启动段"
        elif persistent and ret5 is not None and ret10 is not None and ret20 is not None and ret5 <= ret10 <= ret20:
            persistence_signal = "mature_persistent"
            persistence_summary = "长周期底子更稳，延续观察"
        elif persistent:
            persistence_signal = "persistent"
            persistence_summary = "中短期仍为正，走势延续"
        elif ret5 is not None and ret10 is not None and ret5 > 0 and ret10 > 0 and ret5 < ret10:
            persistence_signal = "cooling"
            persistence_summary = "短线斜率放缓，留意降温"
        elif ret5 is not None and ret10 is not None and ret5 <= 0 < ret10:
            persistence_signal = "fading"
            persistence_summary = "短线转弱，需防回落"
        else:
            persistence_signal = "mixed"
            persistence_summary = "节奏分化，持续性待确认"

        crowding_penalty = 0.0
        if persistent and etf_heat_count >= 2:
            crowding_penalty += 8.0
        if etf_trend_count >= 2:
            crowding_penalty += 6.0
        if mature_trend:
            crowding_penalty += 4.0
        crowding_penalty = min(20.0, crowding_penalty)

        trend_signal = (
            "persistent_trend"
            if persistent
            else "trend_turning_positive"
            if turning_up
            else "mixed_trend"
        )
        acceleration_signal = (
            "emerging_breakout"
            if emerging
            else "accelerating"
            if acceleration_score >= 10.0
            else "stable"
        )
        etf_signal = (
            "confirmed"
            if etf_confirmation_score >= 14.0
            else "partial"
            if etf_confirmation_score > 0
            else "none"
        )
        crowding_signal = (
            "crowded"
            if crowding_penalty >= 10.0
            else "elevated"
            if crowding_penalty > 0
            else "clean"
        )
        industry_signal = (
            "top_rank_confirmation"
            if industry_confirmation_score >= 6.0
            else "secondary_confirmation"
            if industry_confirmation_score > 0
            else "none"
        )

        trend_summary = f"5/10/20日趋势 {_format_pct(ret5)}/{_format_pct(ret10)}/{_format_pct(ret20)}"
        acceleration_summary = (
            "短周期强于中周期，符合启动/加速特征"
            if emerging
            else "趋势延续但加速度一般"
            if acceleration_score >= 10.0
            else "暂未形成明显加速"
        )
        etf_summary = (
            f"关联ETF {len(related_etfs)} 只，热度确认 {etf_heat_count} 只，趋势确认 {etf_trend_count} 只"
            if related_etfs
            else "暂无明显关联ETF确认"
        )
        crowding_summary = (
            f"ETF热度偏高，拥挤惩罚 {crowding_penalty:.1f} 分"
            if crowding_penalty > 0
            else "拥挤度可控"
        )
        industry_summary = (
            f"行业强度榜确认：第 {top_industry_rank} 名"
            if top_industry_rank is not None
            else "无行业强度榜确认"
        )

        keywords = _theme_keywords(theme_name)
        concept_evidence = _dedupe_texts(
            [
                str(item.get("headline") or "")
                for item in (bucket.get("concept_mentions") or [])
                if isinstance(item, dict)
            ],
            limit=2,
        )
        news_evidence = _dedupe_texts(
            [
                str(item.get("title") or "")
                for item in (news_payload or {}).get("items") or []
                if isinstance(item, dict)
                and any(
                    token and token in str(item.get("title") or "")
                    for token in keywords
                )
            ],
            limit=2,
        )

        reason_dimensions = {
            "trend": {
                "score": round(trend_score, 1),
                "signal": trend_signal,
                "ret_5d": ret5,
                "ret_10d": ret10,
                "ret_20d": ret20,
                "summary": trend_summary,
            },
            "acceleration": {
                "score": round(acceleration_score, 1),
                "signal": acceleration_signal,
                "emerging": emerging,
                "summary": acceleration_summary,
            },
            "etf_confirmation": {
                "score": round(etf_confirmation_score, 1),
                "signal": etf_signal,
                "related_count": len(related_etfs),
                "heat_count": etf_heat_count,
                "trend_count": etf_trend_count,
                "summary": etf_summary,
            },
            "crowding": {
                "score": round(-crowding_penalty, 1),
                "signal": crowding_signal,
                "penalty": round(crowding_penalty, 1),
                "summary": crowding_summary,
            },
            "industry_confirmation": {
                "score": round(industry_confirmation_score, 1),
                "signal": industry_signal,
                "top_rank": top_industry_rank,
                "summary": industry_summary,
            },
            "relative_strength": {
                "score": round(relative_strength_score, 1),
                "signal": relative_strength.get("signal"),
                "rank": relative_strength.get("rank"),
                "total": relative_strength.get("total"),
                "peer_score": relative_strength.get("peer_score"),
                "vs_median": relative_strength.get("vs_median"),
                "summary": relative_strength.get("summary"),
            },
            "etf_breadth": {
                "score": round(etf_confirmation_breadth * 10.0, 1),
                "signal": breadth_signal,
                "confirmed_count": etf_confirmed_count,
                "dual_confirmation_count": etf_dual_confirmation_count,
                "breadth_ratio": etf_confirmation_breadth,
                "summary": breadth_summary,
            },
            "persistence": {
                "score": 0.0,
                "signal": persistence_signal,
                "summary": persistence_summary,
            },
            "source_confirmation": {
                "score": 0.0,
                "signal": source_signal,
                "source_count": source_count,
                "news_heat": news_heat,
                "summary": source_summary,
            },
        }

        base_evidence = [
            trend_summary,
            acceleration_summary,
            str(relative_strength.get("summary") or ""),
            etf_summary,
            breadth_summary,
            persistence_summary,
            crowding_summary,
            industry_summary,
            source_summary,
            *concept_evidence,
            *news_evidence,
        ]
        item_base = {
            "theme": theme_name,
            "related_etfs": related_etfs,
            "reason_dimensions": reason_dimensions,
        }

        is_crowded_risk = (
            persistent and etf_confirmation_score >= 10.0 and crowding_penalty >= 10.0
        )
        is_confirmed_leader = persistent and etf_confirmation_score >= 8.0
        is_potential_breakout = (
            not persistent
            and trend_score >= 18.0
            and acceleration_score >= 10.0
            and etf_confirmation_score >= 4.0
            and crowding_penalty < 10.0
        )

        if is_potential_breakout:
            total_score = _bounded_score(
                trend_score
                + acceleration_score
                + etf_confirmation_score
                + relative_strength_score
                + industry_confirmation_score * 0.5
                - crowding_penalty
            )
            evidence = _dedupe_texts(
                base_evidence + ["趋势变化先行，属于启动/加速观察对象"], limit=6
            )
            breakout_rows.append(
                {
                    **item_base,
                    "stage": "potential_breakout",
                    "score": total_score,
                    "confidence": round(total_score / 100.0, 2),
                    "reasons": evidence,
                    "evidence": evidence,
                }
            )

        if is_confirmed_leader:
            total_score = _bounded_score(
                trend_score
                + min(acceleration_score, 12.0)
                + etf_confirmation_score
                + relative_strength_score
                + industry_confirmation_score
                - crowding_penalty * 0.5
            )
            evidence = _dedupe_texts(
                base_evidence + ["5/10/20日趋势延续，且已有ETF确认"], limit=6
            )
            leader_rows.append(
                {
                    **item_base,
                    "stage": "confirmed_leader",
                    "score": total_score,
                    "confidence": round(total_score / 100.0, 2),
                    "reasons": evidence,
                    "evidence": evidence,
                }
            )

        if is_crowded_risk:
            total_score = _bounded_score(
                trend_score
                + etf_confirmation_score
                + relative_strength_score
                + industry_confirmation_score
                + crowding_penalty
            )
            evidence = _dedupe_texts(
                base_evidence + ["强趋势已获确认，但ETF热度偏高需防拥挤回撤"], limit=6
            )
            crowded_rows.append(
                {
                    **item_base,
                    "stage": "crowded_risk",
                    "score": total_score,
                    "confidence": round(total_score / 100.0, 2),
                    "reasons": evidence,
                    "evidence": evidence,
                }
            )

    def rank_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: (
                -float(item.get("score") or 0.0),
                -float(
                    (
                        (item.get("reason_dimensions") or {}).get("etf_confirmation")
                        or {}
                    ).get("score")
                    or 0.0
                ),
                str(item.get("theme") or ""),
            ),
        )[:limit]

    return {
        "mode": "derived_theme_breakout",
        "source": "existing_etf_sector_payloads",
        "potential_breakouts": rank_items(breakout_rows),
        "confirmed_leaders": rank_items(leader_rows),
        "crowded_risks": rank_items(crowded_rows),
    }


def select_hot_etf_candidates(
    *,
    sina_rows: Optional[List[Dict[str, Any]]] = None,
    ths_rows: Optional[List[Dict[str, Any]]] = None,
    industry_payload: Optional[Dict[str, Any]] = None,
    concept_payload: Optional[Dict[str, Any]] = None,
    trend_payload: Optional[Dict[str, Any]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Auto-select ETFs via theme discovery -> ETF mapping -> trend confirmation."""
    if sina_rows is None:
        sina_rows = normalize_etf_spot_sina(fetch_etf_spot_sina(), limit=120)
    if ths_rows is None:
        ths_rows = normalize_etf_spot_ths(fetch_etf_spot_ths(), limit=120)
    if industry_payload is None:
        industry_payload = normalize_industry_summary_ths(
            fetch_industry_summary_ths(), limit=20
        )
    if concept_payload is None:
        concept_payload = _extract_concept_payload()

    limit = max(3, min(int(limit or 10), 20))
    theme_inputs = _extract_theme_names(industry_payload or {}, concept_payload or {})
    if trend_payload is None:
        trend_payload = _fetch_board_trend_payload(
            theme_inputs["industry"], theme_inputs["concept"]
        )

    trend_for_buckets = {
        "industry": ((trend_payload or {}).get("industry") or {}),
        "concept": ((trend_payload or {}).get("concept") or {}),
    }
    theme_buckets = _theme_buckets(
        industry_payload or {}, concept_payload or {}, trend_for_buckets
    )
    ranked_themes = sorted(
        theme_buckets.values(),
        key=lambda item: (
            -float(item.get("score") or 0.0),
            -int(item.get("source_votes") or 0),
            str(item.get("theme") or ""),
        ),
    )[:5]

    pool = _candidate_pool_from_sources(sina_rows or [], ths_rows or [])
    ranked_pool = _score_etfs_for_themes(ranked_themes, pool)

    selected = [item for item in ranked_pool if item.get("matched_themes")][:limit]
    selected = _fill_with_defaults(selected, ranked_pool, limit)

    return {
        "mode": "heuristic_theme_selection",
        "limit": limit,
        "codes": [str(item.get("code")) for item in selected if item.get("code")],
        "theme_inputs": theme_inputs,
        "themes": [
            {
                "theme": item.get("theme"),
                "stage": item.get("stage"),
                "score": round(float(item.get("score") or 0.0), 2),
                "source_votes": int(item.get("source_votes") or 0),
                "reasons": list(dict.fromkeys(item.get("reasons") or []))[:5],
                "industry_mentions": item.get("industry_mentions") or [],
                "concept_mentions": item.get("concept_mentions") or [],
            }
            for item in ranked_themes
        ],
        "items": [
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "score": round(float(item.get("score") or 0.0), 2),
                "matched_themes": sorted(set(item.get("matched_themes") or [])),
                "reasons": list(dict.fromkeys(item.get("reasons") or []))[:6],
            }
            for item in selected
        ],
    }
