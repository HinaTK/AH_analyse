"""Backtest verification for stock recommendations.

Reads historical `recommend_YYYYMMDD.json` files, fetches subsequent prices,
computes T+1/3/5/10 return, max drawdown, hit rate.
Writes to a JSONL ledger `docs/analyse/stock-recommend-ledger.jsonl`.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher


HORIZONS = (1, 3, 5, 10, 20)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _load_report(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _returns_for_pick(
    code: str,
    as_of: str,
    *,
    price_fetcher=None,
) -> Dict[str, Any]:
    """Fetch prices for `code` from `as_of` and compute horizon returns.

    as_of: 'YYYY-MM-DD'. Returns dict with T+N return (%), max drawdown (%), and entry price.
    """
    pf = price_fetcher or get_price_fetcher()
    # as_of 紧凑化 YYYYMMDD
    dt = datetime.strptime(as_of, "%Y-%m-%d")
    start = (dt - timedelta(days=2)).strftime("%Y%m%d")
    end = (dt + timedelta(days=max(HORIZONS) + 5)).strftime("%Y%m%d")

    try:
        df = pf.get_a_share_price(code, start_date=start, end_date=end)
    except Exception as e:
        return {"code": code, "error": f"price_fetch:{e}"}

    if df is None or df.empty or "date" not in df.columns:
        return {"code": code, "error": "no_price"}

    df = df.copy()
    df["date"] = df["date"].astype(str).str[:10]
    # find first available date >= as_of
    future = df[df["date"] >= as_of].reset_index(drop=True)
    if future.empty:
        return {"code": code, "error": "no_future_price"}
    entry = float(future.iloc[0]["close"])
    entry_date = str(future.iloc[0]["date"])
    out: Dict[str, Any] = {
        "code": code,
        "entry_price": entry,
        "entry_date": entry_date,
    }
    closes = future["close"].astype(float).tolist()
    for h in HORIZONS:
        if len(closes) > h:
            ret = (closes[h] - entry) / entry * 100
            out[f"return_T{h}_pct"] = round(ret, 2)
        else:
            out[f"return_T{h}_pct"] = None

    # Max drawdown over the window
    if closes:
        peak = closes[0]
        max_dd = 0.0
        for v in closes:
            peak = max(peak, v)
            dd = (v - peak) / peak * 100
            max_dd = min(max_dd, dd)
        out["max_drawdown_pct"] = round(max_dd, 2)
    return out


def verify_recommendation(
    report: Dict[str, Any],
    *,
    ledgers_dir: Path,
    price_fetcher=None,
) -> Dict[str, Any]:
    """Verify a single recommendation report. Returns a per-pick metrics dict."""
    as_of = report.get("as_of") or datetime.now().strftime("%Y-%m-%d")
    picks = report.get("picks") or []
    per_pick: List[Dict[str, Any]] = []
    for p in picks:
        code = str(p.get("code") or "").strip()
        if not code:
            continue
        metrics = _returns_for_pick(code, as_of, price_fetcher=price_fetcher)
        metrics["name"] = p.get("name", "")
        metrics["action"] = p.get("action", "")
        metrics["confidence"] = p.get("confidence", 0)
        metrics["factors"] = p.get("factors") or {}
        metrics["as_of"] = as_of
        per_pick.append(metrics)

    # Aggregate hit rate (T+5 return > 0)
    valid = [m for m in per_pick if m.get("return_T5_pct") is not None]
    hit_t5 = (
        sum(1 for m in valid if (m.get("return_T5_pct") or 0) > 0) / len(valid) * 100
        if valid
        else None
    )
    avg_t5 = (
        round(sum(m.get("return_T5_pct", 0) for m in valid) / len(valid), 2)
        if valid
        else None
    )

    summary = {
        "as_of": as_of,
        "pick_count": len(picks),
        "verified_count": len(valid),
        "hit_rate_T5_pct": round(hit_t5, 2) if hit_t5 is not None else None,
        "avg_return_T5_pct": avg_t5,
        "per_pick": per_pick,
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Append to ledger
    ledgers_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledgers_dir / "stock-recommend-ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")

    logger.info(
        f"verified as_of={as_of} picks={len(picks)} verified={len(valid)} "
        f"hit_T5={summary['hit_rate_T5_pct']} avg_T5={avg_t5}"
    )
    return summary


def verify_all_pending(
    report_dir: Path,
    ledgers_dir: Path,
) -> List[Dict[str, Any]]:
    """Verify all reports whose T+10 window is closed but not yet verified."""
    out: List[Dict[str, Any]] = []
    if not report_dir.exists():
        return out
    ledger_path = ledgers_dir / "stock-recommend-ledger.jsonl"
    seen = {row.get("as_of") for row in _read_jsonl(ledger_path)}

    today = datetime.now()
    cutoff = today - timedelta(days=max(HORIZONS) + 3)

    for p in sorted(report_dir.glob("recommend_*.json")):
        try:
            report = _load_jsonl_compat(p)
        except Exception:
            continue
        if not report:
            continue
        as_of = report.get("as_of") or ""
        if as_of in seen:
            continue
        try:
            dt = datetime.strptime(as_of, "%Y-%m-%d")
        except Exception:
            continue
        if dt > cutoff:
            continue
        out.append(verify_recommendation(report, ledgers_dir=ledgers_dir))
    return out


def _load_jsonl_compat(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
