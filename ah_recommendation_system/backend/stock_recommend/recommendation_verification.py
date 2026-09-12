"""Immutable, bounded verification records for recommendation outcomes."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

HORIZONS = {"short": 5, "swing": 20, "medium": 60}


def _stable_id(as_of: str, market: str, symbol: str, version: str, horizon: str) -> str:
    raw = "|".join((as_of, market, symbol, version, horizon))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def build_verification_plan(candidates: list[dict], decisions: list[dict], *, as_of: str, model_version: str) -> list[dict]:
    by_id = {str(d.get("candidate_id")): d for d in decisions}
    records = []
    for c in candidates:
        cid = str(c.get("candidate_id", "")); d = by_id.get(cid, {})
        selected = bool(d.get("selected", False))
        for horizon, sessions in HORIZONS.items():
            rid = _stable_id(as_of, str(c.get("market", "")), str(c.get("symbol", "")), model_version, horizon)
            records.append({
                "recommendation_id": rid, "candidate_id": cid, "as_of": as_of,
                "symbol": c.get("symbol"), "market": c.get("market"),
                "instrument_type": c.get("instrument_type"), "theme": c.get("theme"),
                "price": c.get("price"), "benchmark": c.get("benchmark"),
                "source_modules": c.get("source_modules", []), "evidence": c.get("evidence", []),
                "source_mode": c.get("source_mode", c.get("data_mode", "unknown")),
                "horizon": horizon, "window_sessions": sessions, "status": "pending",
                "selected": selected, "state": d.get("state", "unclassified"),
                "excluded_reason": None if selected else ("decision_excluded" if d else "decision_missing"),
                "confidence": d.get("confidence"), "trigger": d.get("trigger"),
                "invalidation": d.get("invalidation"), "model_version": model_version,
                "verification_window": d.get("verification_window", {}),
            })
    return records


def persist_verification_plan(records: list[dict], root: Path) -> dict:
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    result = {"saved": 0, "duplicates": 0, "conflicts": 0, "paths": []}
    for record in records:
        rid = record["recommendation_id"]; path = root / f"{rid}.json"
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if path.exists():
            try: existing = path.read_text(encoding="utf-8")
            except OSError: existing = ""
            if existing == payload: result["duplicates"] += 1
            else: result["conflicts"] += 1
            result["paths"].append(str(path)); continue
        fd, tmp = tempfile.mkstemp(prefix=f".{rid}.", suffix=".tmp", dir=str(root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh: fh.write(payload); fh.flush(); os.fsync(fh.fileno())
            try: os.replace(tmp, path)
            except FileExistsError: result["duplicates"] += 1; continue
            result["saved"] += 1; result["paths"].append(str(path))
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    return result


def _date(value: Any) -> datetime | None:
    if not value: return None
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError): return None


def evaluate_record(record: dict, observation: dict) -> dict:
    out = dict(record); out["evaluation"] = dict(observation)
    out.update(gross_return_pct=None, net_return_pct=None, benchmark_return_pct=None,
               excess_return_pct=None, price_hit=None, timing_hit=None, tradable=None)
    entry, exit_, observed = (_date(observation.get(k)) for k in ("entry_at", "exit_at", "observed_at"))
    required = [observation.get(k) for k in ("entry_price", "exit_price", "benchmark_entry_price", "benchmark_exit_price")]
    anchor = _date(record.get("as_of"))
    if not all((entry, exit_, observed)) or (anchor and entry < anchor) or exit_ < entry or observed < exit_ or any(v is None for v in required):
        out.update(status="invalid", invalid_reason="invalid_or_reversed_dates_or_prices")
        return out
    if observation.get("trigger_occurred") is not True:
        out.update(status="not_triggered", invalid_reason="trigger_not_observed")
        return out
    if observation.get("round_trip_cost_pct") is None:
        out.update(status="invalid", invalid_reason="missing_round_trip_cost")
        return out
    try:
        ep, xp, bep, bxp = map(float, required); cost = float(observation["round_trip_cost_pct"])
        gross = (xp / ep - 1) * 100; bench = (bxp / bep - 1) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        out.update(status="invalid", invalid_reason="non_numeric_or_zero_price"); return out
    if observation.get("session_count") is None or int(observation["session_count"]) < int(record.get("window_sessions", 0)):
        out.update(status="pending", invalid_reason="insufficient_observed_sessions"); return out
    net = gross - cost
    out.update(status="matured", gross_return_pct=gross, net_return_pct=net,
               benchmark_return_pct=bench, excess_return_pct=net - bench,
               price_hit=net > 0, timing_hit=True, tradable=bool(observation.get("tradable")),
               failure_classification=observation.get("failure_classification"))
    return out


def summarize_verification(records: list[dict]) -> dict:
    matured = [r for r in records if r.get("status") == "matured" and r.get("tradable") is True]
    excess = [r["excess_return_pct"] for r in matured if r.get("excess_return_pct") is not None]
    bins = {"low": 0, "medium": 0, "high": 0}
    for r in records:
        c = r.get("confidence")
        if isinstance(c, (int, float)): bins["low" if c < .5 else "medium" if c < .75 else "high"] += 1
    groups = {}
    for r in records:
        key = (r.get("market"), r.get("theme"), r.get("horizon"), r.get("state"))
        groups["|".join(str(x) for x in key)] = groups.get("|".join(str(x) for x in key), 0) + 1
    return {"total": len(records), "matured_valid": len(matured), "excluded": sum(1 for r in records if r.get("excluded_reason")),
            "mean_excess_return_pct": sum(excess) / len(excess) if excess else None,
            "hit_rate": sum(1 for r in matured if r.get("price_hit")) / len(matured) if matured else None,
            "confidence_bins": bins, "groups": groups, "drawdown": "unavailable",
            "confidence_reliability": "available" if len(matured) >= 30 else "insufficient_sample"}
