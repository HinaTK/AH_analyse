"""Feishu (Lark) webhook pusher for daily stock recommendation.

Sends an interactive card via incoming webhook.
Configure via env: AH_FEISHU_WEBHOOK (required), AH_FEISHU_SECRET (optional, for signing).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from typing import Any, Dict, Optional

import requests
from loguru import logger


def _sign(secret: str, timestamp: str) -> str:
    """Compute Feishu sign for incoming webhook."""
    string_to_sign = f"{timestamp}\n{secret}"
    h = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(h).decode("utf-8")


def build_card(report: Dict[str, Any]) -> Dict[str, Any]:
    """Build Feishu interactive card payload."""
    as_of = report.get("as_of", "")
    summary = report.get("summary", "")
    market_view = report.get("market_view", "")
    picks = report.get("picks") or []
    etf_picks = report.get("etf_picks") or []
    review_items = report.get("items") or []

    elements: list[Any] = []
    status = report.get("data_status")
    coverage_label = (report.get("coverage") or {}).get("label")
    if status in {"degraded", "failed"} or coverage_label:
        status_text = {
            "degraded": "⚠️ 有限数据源：本次仅使用重点行业+龙虎榜观察池",
            "failed": "⚠️ 数据采集失败：本次不生成策略结论",
        }.get(status, "")
        if coverage_label and status != "failed":
            status_text = f"{status_text + ' · ' if status_text else ''}范围：{coverage_label}"
        if status_text:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": status_text}})
    if summary:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**盘前总结**: {summary}"},
            }
        )
    if market_view:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**大盘**: {market_view}"},
            }
        )

    if report.get("type") == "stock_recommend_post_market":
        for item in review_items:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": (
                f"**{item.get('name', '')} ({item.get('code', '')})** · "
                f"状态 `{item.get('status', 'pending')}` · 收益 {item.get('return_pct', '-')}% · "
                f"修正 `{item.get('correction', 'confirm')}`"
            )}})
    elif picks:
        for i, p in enumerate(picks, 1):
            code = p.get("code", "?")
            name = p.get("name", "?")
            action = p.get("action", "WATCH")
            conf = p.get("confidence", 0)
            buy = p.get("buy_zone", "—")
            sl = p.get("stop_loss", "—")
            tgt = p.get("target", "—")
            hd = p.get("holding_days", "—")
            rat = p.get("rationale", "")
            risks = p.get("key_risks") or []
            factors = p.get("factors") or {}
            comp = factors.get("composite", "—")
            md = (
                f"**{i}. {name} ({code})** · `{action}` · 信心 {conf}\n"
                f"买入 {buy}  止损 {sl}  目标 {tgt}  持有 {hd}\n"
                f"理由: {rat}\n"
                f"composite: {comp}"
            )
            if risks:
                md += "\n风险: " + "; ".join(risks)
            elements.append(
                {"tag": "hr"}
            )
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": md}})
    else:
        if report.get("data_status") == "failed":
            empty_text = "⚠️ 数据采集失败，本次不生成策略结论"
        elif report.get("data_status") == "degraded":
            empty_text = "⚠️ 有限数据源下暂无个股通过确认条件"
        else:
            empty_text = "⚠️ 暂无推荐"
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": empty_text},
            }
        )

    observation_pool = report.get("observation_pool") or []
    if observation_pool:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**观察池（未达正式推荐门槛）**\n" + "\n".join(
                    f"- {item.get('name', '')} ({item.get('code', '')})："
                    f"{'；'.join(item.get('rejection_reasons') or []) or '等待更多证据'}"
                    for item in observation_pool[:6]
                ),
            },
        })

    if etf_picks:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content":
            "**ETF观察**\n" + "\n".join(
                f"- {e.get('name', '')} ({e.get('code', '')})：{e.get('rationale', '')}"
                for e in etf_picks[:2]
            )
        }})

    fals = report.get("falsification") or []
    if fals:
        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**证伪信号**: " + "; ".join(fals),
                },
            }
        )

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"A 股盘前推荐 · {as_of}",
                },
                "template": "blue",
            },
            "elements": elements,
        },
    }


def push_to_feishu(
    report: Dict[str, Any],
    *,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
    timeout: float = 10.0,
    retries: int = 3,
    backoff_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Push report to Feishu webhook. Returns response info."""
    hook = (webhook or os.environ.get("AH_FEISHU_WEBHOOK") or "").strip()
    if not hook:
        return {"ok": False, "skipped": True, "reason": "AH_FEISHU_WEBHOOK not set"}

    sec = (secret if secret is not None else os.environ.get("AH_FEISHU_SECRET") or "").strip()

    payload = build_card(report)
    if sec:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(sec, ts)

    attempts = max(1, int(retries))
    last_error: Optional[str] = None
    last_status: Optional[int] = None
    last_data: Any = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(hook, json=payload, timeout=timeout)
            last_status = resp.status_code
            try:
                last_data = resp.json()
            except Exception:
                last_data = {"raw": resp.text[:500]}
            business_code = last_data.get("code") if isinstance(last_data, dict) else None
            ok = resp.status_code == 200 and business_code in (None, 0, "0")
            if ok:
                logger.info(f"feishu push status={resp.status_code} ok=True")
                return {"ok": True, "status": resp.status_code, "response": last_data, "retry_count": attempt}
            last_error = f"business_{business_code}" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            last_error = str(e)
        if attempt < attempts and backoff_seconds > 0:
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
    logger.warning(f"feishu push failed after {attempts} attempts: {last_error}")
    return {
        "ok": False,
        "status": last_status,
        "response": last_data,
        "error": last_error,
        "retry_count": attempts,
    }


def push_markdown_simple(
    text: str,
    *,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Push plain text (Markdown) - use when interactive card not desired."""
    hook = (webhook or os.environ.get("AH_FEISHU_WEBHOOK") or "").strip()
    if not hook:
        return {"ok": False, "skipped": True, "reason": "AH_FEISHU_WEBHOOK not set"}

    sec = (secret if secret is not None else os.environ.get("AH_FEISHU_SECRET") or "").strip()
    payload: Dict[str, Any] = {"msg_type": "markdown", "content": {"text": text}}
    if sec:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(sec, ts)

    try:
        resp = requests.post(hook, json=payload, timeout=timeout)
        return {
            "ok": resp.status_code == 200,
            "status": resp.status_code,
            "response": (resp.json() if resp.text else {}),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
