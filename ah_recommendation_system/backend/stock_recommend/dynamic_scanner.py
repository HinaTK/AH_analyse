"""Build a fresh candidate universe from current market signals."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional


EXCLUDE_NAME_PATTERNS = ("ST", "退", "暂停", "B股")


def _is_excluded(name: str) -> bool:
    return any(pattern in name for pattern in EXCLUDE_NAME_PATTERNS)


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
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Tradability pre-screen; heuristic tags become sidecar provenance only."""
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
        for row in sorted(market_rows, key=lambda item: _safe_amount(item.get("amount")), reverse=True)[: min(300, limit if limit is not None else 300)]
        if _safe_amount(row.get("amount")) >= 100_000_000
    }
    seeds: List[Dict[str, Any]] = []
    for row in market_rows:
        raw_code = str(row.get("code") or "").strip()
        if len(raw_code) != 6 or not raw_code.isdigit():
            continue
        code = raw_code.zfill(6)
        price = _float(row.get("price"))
        name = str(row.get("name") or "")
        if len(code) != 6 or not price or price <= 0 or _is_excluded(name) or _safe_amount(row.get("amount")) < 100_000_000:
            continue
        change = _float(row.get("change_pct"))
        momentum = _float(row.get("change_60d_pct"))
        amount = _safe_amount(row.get("amount"))
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
        seed = dict(row)
        seed["source_tags_sidecar"] = tags
        seed["source_tags"] = list(tags)
        seed["candidate_sources"] = list(tags)
        seed["industries"] = industries
        seed["focus_industries"] = industries
        seeds.append(seed)
    seeds.sort(
        key=lambda item: (
            -_safe_amount(item.get("amount")),
            item.get("code") or "",
            -float(item.get("change_60d_pct") or 0),
        )
    )
    if limit is None:
        return seeds
    return seeds[: max(0, limit)]
