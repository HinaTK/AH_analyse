"""Build a fresh candidate universe from current market signals."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional


def _float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_amount(value: Any) -> float:
    amount = _float(value)
    return amount or 0.0


def scan_snapshot(
    rows: Iterable[Dict[str, Any]],
    *,
    focus_industries: Optional[Mapping[str, Iterable[Dict[str, Any]]]] = None,
    activity_rows: Optional[Iterable[Dict[str, Any]]] = None,
    limit: int = 600,
) -> List[Dict[str, Any]]:
    """Tag leaders, volume expansion, new highs, resilience and seat activity."""
    memberships: Dict[str, List[str]] = {}
    for industry, members in (focus_industries or {}).items():
        for member in members:
            code = str(member.get("code") or "").zfill(6)
            if code:
                memberships.setdefault(code, []).append(str(industry))
    activity: Dict[str, List[str]] = {}
    for item in activity_rows or []:
        code = str(item.get("code") or "").zfill(6)
        source = str(item.get("source") or "")
        if code and source and float(item.get("net_buy") or 0) > 0:
            activity.setdefault(code, []).append(source)

    market_rows = list(rows)
    liquid_codes = {
        str(row.get("code") or "").zfill(6)
        for row in sorted(market_rows, key=lambda item: _safe_amount(item.get("amount")), reverse=True)[: min(300, limit)]
        if _safe_amount(row.get("amount")) >= 100_000_000
    }
    seeds: List[Dict[str, Any]] = []
    for row in market_rows:
        code = str(row.get("code") or "").zfill(6)
        price = _float(row.get("price"))
        if len(code) != 6 or not price or price <= 0:
            continue
        change = _float(row.get("change_pct"))
        momentum = _float(row.get("change_60d_pct"))
        amount = _float(row.get("amount"))
        volume_ratio = _float(row.get("volume_ratio") or row.get("volume_ratio_20d"))
        high20 = _float(row.get("high_20d"))
        tags: List[str] = list(dict.fromkeys(str(tag) for tag in (row.get("source_tags") or row.get("candidate_sources") or [])))
        if code in liquid_codes:
            tags.append("liquidity_leader")
        if change is not None and change >= 3:
            tags.append("market_leader")
        if volume_ratio is not None and volume_ratio >= 1.5 and (amount or 0) >= 100_000_000:
            tags.append("volume_expansion")
        if high20 is not None and price >= high20 * 0.995:
            tags.append("new_high")
        if momentum is not None and momentum >= 10:
            tags.append("relative_strength")
        if change is not None and change >= 0 and (momentum or 0) > 0:
            tags.append("resilient")
        tags.extend(tag for tag in activity.get(code, []) if tag not in tags)
        industries = memberships.get(code, []) or list(row.get("focus_industries") or row.get("industries") or [])
        if industries:
            tags.append("focus_industry")
        if not tags:
            continue
        seed = dict(row)
        seed["source_tags"] = tags
        seed["candidate_sources"] = tags
        seed["industries"] = industries
        seed["focus_industries"] = industries
        seeds.append(seed)
    seeds.sort(
        key=lambda item: (
            -len([tag for tag in item["source_tags"] if tag != "focus_industry"]),
            -_safe_amount(item.get("amount")),
            -float(item.get("change_60d_pct") or 0),
        )
    )
    return seeds[: max(0, limit)]
