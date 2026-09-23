"""Promote pre-market conditional tickets after the open, or cancel them."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping


def _parse_zone(buy_zone: Any) -> tuple[float, float] | None:
    text = str(buy_zone or "")
    if "-" not in text:
        return None
    left, right = text.split("-", 1)
    try:
        low, high = float(left), float(right)
    except (TypeError, ValueError):
        return None
    if low <= 0 or high <= 0 or high < low:
        return None
    return low, high


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def confirm_open_picks(
    picks: Iterable[Mapping[str, Any]],
    *,
    quotes: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Dict[str, Any]]:
    """One-shot open check: BUY in-zone with volume, else CANCEL. Never invent replacements."""
    book = dict(quotes or {})
    confirmed: list[Dict[str, Any]] = []
    for raw in picks or []:
        pick = dict(raw)
        code = str(pick.get("code") or "").zfill(6) if str(pick.get("code") or "").isdigit() else str(pick.get("code") or "")
        quote = dict(book.get(code) or book.get(str(pick.get("code") or "")) or {})
        action = str(pick.get("action") or "")
        if action not in {"CONDITIONAL_BUY", "WATCH"}:
            confirmed.append(pick)
            continue
        price = _number(quote.get("price"))
        amount = _number(quote.get("amount"))
        amount_20d = _number(quote.get("amount_20d"))
        sector = _number(quote.get("sector_change_pct"))
        zone = _parse_zone(pick.get("buy_zone"))
        reasons: list[str] = []
        if price is None or zone is None:
            reasons.append("quote_missing")
        else:
            low, high = zone
            if price > high:
                reasons.append("gap_up")
            elif amount is None or amount_20d is None or amount_20d <= 0 or amount < amount_20d:
                reasons.append("volume")
            if sector is not None and sector <= -0.5:
                reasons.append("sector_weak")
        if reasons:
            pick["action"] = "CANCEL"
            pick["cancel_reason"] = "+".join(reasons)
            pick["execution_status"] = "cancelled"
            pick["fill_constraint"] = "当日条件单已取消，不再换票"
        elif price is not None and zone is not None and zone[0] <= price <= zone[1]:
            pick["action"] = "BUY"
            pick["execution_status"] = "open_confirmed"
            pick["fill_constraint"] = "可下单"
            pick["reference_price"] = price
        else:
            pick["action"] = "CANCEL"
            pick["cancel_reason"] = "not_confirmed"
            pick["execution_status"] = "cancelled"
            pick["fill_constraint"] = "当日条件单已取消，不再换票"
        confirmed.append(pick)
    return confirmed
