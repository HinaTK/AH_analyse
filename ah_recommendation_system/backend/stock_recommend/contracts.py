"""Shared, JSON-friendly contracts for evidence-driven recommendations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MarketSnapshot:
    as_of: str
    price_timestamp: Optional[str] = None
    market_session: Optional[str] = None
    source: str = "unknown"
    source_timestamp: Optional[str] = None
    data_quality: str = "unknown"
    is_mock: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    evidence_type: str
    source: str
    claim: str
    observed_at: Optional[str] = None
    published_at: Optional[str] = None
    valid_until: Optional[str] = None
    reliability: str = "medium"
    direction: str = "support"
    subject: Optional[str] = None

    def is_active(self, as_of: str) -> bool:
        expiry = _parse(self.valid_until)
        point = _parse(as_of)
        return not expiry or not point or point <= expiry

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class QualityResult:
    status: str
    reasons: List[str] = field(default_factory=list)
    active_evidence: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Candidate:
    symbol: str
    market: str
    snapshot: MarketSnapshot
    evidence: List[EvidenceItem] = field(default_factory=list)
    candidate_id: Optional[str] = None
    instrument_type: str = "stock"
    theme: Optional[str] = None
    price: Optional[float] = None
    benchmark: Optional[str] = None
    factors: Dict[str, Any] = field(default_factory=dict)
    signals: Dict[str, Any] = field(default_factory=dict)

    def quality_check(self) -> QualityResult:
        reasons: List[str] = []
        active: List[Dict[str, Any]] = []
        if not self.snapshot.as_of:
            reasons.append("missing_as_of")
        if not self.snapshot.price_timestamp:
            reasons.append("missing_price_timestamp")
        for item in self.evidence:
            if item.is_active(self.snapshot.as_of):
                active.append(item.to_dict())
            else:
                reasons.append("expired_evidence")
        if not active and self.evidence:
            reasons.append("no_active_evidence")
        if self.price is None:
            reasons.append("missing_price")
        if reasons and any(x.startswith("missing_") for x in reasons):
            status = "rejected"
        elif reasons:
            status = "degraded"
        else:
            status = "passed"
        return QualityResult(status=status, reasons=sorted(set(reasons)), active_evidence=active)

    def to_dict(self) -> Dict[str, Any]:
        quality = self.quality_check()
        return {
            "candidate_id": self.candidate_id or f"{self.market}:{self.symbol}",
            "symbol": self.symbol,
            "market": self.market,
            "instrument_type": self.instrument_type,
            "theme": self.theme,
            "price": self.price,
            "benchmark": self.benchmark,
            "snapshot": self.snapshot.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "factors": self.factors,
            "signals": self.signals,
            "quality": {"status": quality.status, "reasons": quality.reasons, "active_evidence": quality.active_evidence},
        }


def normalize_candidate(row: Dict[str, Any], *, snapshot: MarketSnapshot) -> Dict[str, Any]:
    """Normalize a legacy row without destroying its original fields."""
    evidence = []
    for raw in row.get("evidence") or []:
        if not isinstance(raw, dict):
            continue
        item = EvidenceItem(
            evidence_id=str(raw.get("evidence_id") or raw.get("id") or f"legacy-{len(evidence)}"),
            evidence_type=str(raw.get("evidence_type") or raw.get("factor") or "unknown"),
            source=str(raw.get("source") or "legacy"),
            claim=str(raw.get("claim") or raw.get("statement") or ""),
            observed_at=raw.get("observed_at") or raw.get("as_of"),
            published_at=raw.get("published_at"),
            valid_until=raw.get("valid_until"),
            reliability=str(raw.get("reliability") or "medium"),
            direction="support" if raw.get("supports", True) else "contradict",
            subject=raw.get("subject") or row.get("code"),
        )
        payload = item.to_dict()
        payload["active"] = item.is_active(snapshot.as_of)
        evidence.append(payload)
    candidate = Candidate(
        symbol=str(row.get("symbol") or row.get("code") or ""),
        market=str(row.get("market") or "A"),
        snapshot=snapshot,
        evidence=[EvidenceItem(
            evidence_id=e["evidence_id"], evidence_type=e["evidence_type"], source=e["source"], claim=e["claim"],
            observed_at=e.get("observed_at"), published_at=e.get("published_at"), valid_until=e.get("valid_until"),
            reliability=e.get("reliability", "medium"), direction=e.get("direction", "support"), subject=e.get("subject")
        ) for e in evidence],
        candidate_id=row.get("candidate_id"),
        instrument_type=str(row.get("instrument_type") or "stock"),
        theme=row.get("theme") or (row.get("focus_industries") or [None])[0],
        price=row.get("price") or row.get("reference_price"),
        benchmark=row.get("benchmark"),
        factors=row.get("factors") or row.get("factor_scores") or {},
        signals=row.get("signals") or {},
    )
    payload = candidate.to_dict()
    payload["evidence"] = evidence
    # Map legacy factor names while preserving original factors above.
    old = row.get("factor_scores") or row.get("factors") or {}
    aliases = {"trend": "trend", "relative_strength": "trend", "price_volume": "flow", "capital": "flow", "event": "catalyst", "value_quality": "quality"}
    payload["factors"] = {name: {"score": old.get(source), "confidence": 1.0, "completeness": 1.0} for source, name in aliases.items() if old.get(source) is not None}
    payload["source_modules"] = row.get("source_modules") or ["legacy_pipeline"]
    payload["source_mode"] = row.get("source_mode") or ("mock" if snapshot.is_mock else "live")
    return {**row, **payload}


def normalize_candidates(rows: Iterable[Dict[str, Any]], *, snapshot: MarketSnapshot) -> List[Dict[str, Any]]:
    return [normalize_candidate(dict(row), snapshot=snapshot) for row in rows if isinstance(row, dict)]
