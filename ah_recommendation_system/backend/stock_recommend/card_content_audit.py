"""Content checks that block visibly broken cards before they reach Feishu."""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping


def audit_pre_market_card(report: Mapping[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Fail when the rendered card lost the report's date or stock picks.

    The gate is deliberately conservative: it only blocks when the report
    itself contains data the card failed to render, so genuinely empty days
    still deliver their "no recommendation" notice.
    """
    def strings(value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, Mapping):
            for child in value.values():
                yield from strings(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from strings(child)

    card_text = "\n".join(strings(payload))
    errors: list[str] = []
    # ASCII pipe encoding destroys Chinese before JSON serialization. HTTP 200
    # cannot detect this: inspect the actual outgoing card text before sending.
    if re.search(r"\?{3,}", card_text) or "\ufffd" in card_text:
        errors.append("卡片含连续问号或Unicode替换字符，疑似编码损坏")

    as_of = str(report.get("as_of") or "").strip()
    if as_of and as_of not in card_text:
        errors.append("卡片缺失报告日期")

    stocks = list((report.get("recommendations") or {}).get("stocks") or report.get("picks") or [])
    missing = [
        str(item.get("code"))
        for item in stocks[:5]
        if str(item.get("code") or "") and str(item.get("code")) not in card_text
    ]
    if missing:
        errors.append("卡片缺失推荐标的: " + ",".join(missing))

    return {"passed": not errors, "errors": errors, "version": "pre-market-content-v2"}
