"""Persistent delivery idempotency for scheduled pushes."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def _load(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def should_deliver(path: Path, *, trade_date: str, session: str, force: bool = False) -> bool:
    if force:
        return True
    entry = _load(path).get(f"{trade_date}:{session}") or {}
    return not bool(entry.get("accepted") or entry.get("ambiguous"))


def get_delivery(path: Path, *, trade_date: str, session: str) -> Dict[str, Any]:
    """Return the persisted audit entry for one trading session."""
    entry = _load(path).get(f"{trade_date}:{session}") or {}
    return dict(entry) if isinstance(entry, dict) else {}


def record_delivery(
    path: Path,
    *,
    trade_date: str,
    session: str,
    run_id: str,
    payload_hash: str,
    accepted: bool,
    ambiguous: bool = False,
) -> None:
    ledger = _load(path)
    ledger[f"{trade_date}:{session}"] = {
        "run_id": run_id,
        "payload_hash": payload_hash,
        "accepted": bool(accepted),
        "ambiguous": bool(ambiguous),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
