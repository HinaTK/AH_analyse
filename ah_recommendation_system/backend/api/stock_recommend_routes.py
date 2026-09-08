from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ah_recommendation_system.backend.stock_recommend.feishu_pusher import push_to_feishu


router = APIRouter(prefix="/api/v1/recommendations", tags=["stock-recommendations"])


def _recommend_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "stock_recommend"


def _load(name: str) -> Dict[str, Any]:
    path = _recommend_dir() / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/pre-market")
async def get_pre_market() -> Dict[str, Any]:
    return _load("latest.json")


@router.get("/post-market")
async def get_post_market() -> Dict[str, Any]:
    return _load("latest_review.json")


@router.get("/history")
async def get_history(limit: int = 20) -> Dict[str, Any]:
    directory = _recommend_dir()
    rows = []
    for path in sorted(directory.glob("recommend_*.json"), reverse=True)[: max(1, min(limit, 100))]:
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return {"success": True, "reports": rows}


@router.get("/stats")
async def get_stats() -> Dict[str, Any]:
    ledger = Path(__file__).resolve().parents[3] / "docs" / "analyse" / "stock-recommend-ledger.jsonl"
    if not ledger.exists():
        return {"success": True, "verified_reports": 0, "hit_rate_T5_pct": None}
    rows = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    valid = [r for r in rows if r.get("hit_rate_T5_pct") is not None]
    return {
        "success": True,
        "verified_reports": len(rows),
        "hit_rate_T5_pct": round(sum(float(r["hit_rate_T5_pct"]) for r in valid) / len(valid), 2) if valid else None,
    }


@router.post("/notifications/test")
async def test_notification() -> Dict[str, Any]:
    return push_to_feishu(
        {
            "type": "stock_recommend_pre_market",
            "as_of": "test",
            "summary": "飞书通知测试",
            "market_view": "如果收到这条消息，Webhook 配置成功。",
            "picks": [],
        }
    )


@router.get("/{prediction_id}")
async def get_prediction(prediction_id: str) -> Dict[str, Any]:
    history = await get_history(limit=100)
    for report in history.get("reports") or []:
        for item in report.get("picks") or []:
            if f"{report.get('as_of', '')}:{item.get('code', '')}" == prediction_id:
                return {"report": report, "pick": item}
    raise HTTPException(status_code=404, detail="prediction not found")
