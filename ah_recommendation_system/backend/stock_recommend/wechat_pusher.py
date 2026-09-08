"""Optional WeCom robot webhook adapter sharing the recommendation report."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


def build_wechat_payload(report: Dict[str, Any]) -> Dict[str, Any]:
    coverage = (report.get("coverage") or {}).get("label") or "未知范围"
    lines = [f"## A股每日观察 · {report.get('as_of', '')}", f"> 数据范围：{coverage}"]
    picks = report.get("picks") or []
    if not picks:
        lines.append("**今日无正式个股推荐**：没有标的通过数据质量和证据门槛。")
    for index, pick in enumerate(picks[:3], 1):
        lines.append(f"**{index}. {pick.get('name', '')}（{pick.get('code', '')}）**")
        lines.append(str(pick.get("rationale") or ""))
        lines.append(f"触发：{pick.get('trigger', '—')}；失效：{pick.get('invalidation', '—')}")
    observations = report.get("observation_pool") or []
    if observations:
        lines.append("### 观察池")
        for item in observations[:6]:
            lines.append(f"- {item.get('name', '')}（{item.get('code', '')}）")
    return {"msgtype": "markdown", "markdown": {"content": "\n\n".join(lines)}}


def push_to_wechat(
    report: Dict[str, Any], *, webhook: Optional[str] = None, timeout: float = 10.0
) -> Dict[str, Any]:
    hook = (webhook or os.environ.get("AH_WECHAT_WEBHOOK") or "").strip()
    if not hook:
        return {"ok": False, "skipped": True, "reason": "AH_WECHAT_WEBHOOK not set"}
    try:
        response = requests.post(hook, json=build_wechat_payload(report), timeout=timeout)
        payload = response.json() if response.text else {}
        return {"ok": response.status_code == 200 and payload.get("errcode", 0) == 0, "status": response.status_code, "response": payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
