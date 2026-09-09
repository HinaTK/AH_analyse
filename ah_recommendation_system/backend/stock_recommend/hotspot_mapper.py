"""Deterministic validation and mapping for LLM-reported themes."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping


def validate_and_expand_hotspots(
    hotspots: Iterable[Mapping[str, Any]],
    *,
    focus_universe: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    rows: Iterable[Mapping[str, Any]] = (),
    max_total: int = 60,
) -> Dict[str, Any]:
    focus_universe = focus_universe or {}
    row_map = {str(row.get("code") or "").zfill(6): dict(row) for row in rows if str(row.get("code") or "")}
    expanded: Dict[str, Dict[str, Any]] = {}
    validated: list[Dict[str, Any]] = []
    for hotspot in hotspots:
        industries = [str(item).strip() for item in hotspot.get("industries") or [] if str(item).strip()]
        members: Dict[str, Dict[str, Any]] = {}
        for industry in industries:
            for item in focus_universe.get(industry, ()):
                code = str(item.get("code") or "").zfill(6)
                if len(code) == 6:
                    members[code] = {"code": code, "name": item.get("name") or code}
            for key, items in focus_universe.items():
                if industry in str(key) or str(key) in industry:
                    for item in items:
                        code = str(item.get("code") or "").zfill(6)
                        if len(code) == 6:
                            members[code] = {"code": code, "name": item.get("name") or code}
            # Full-market providers often return an industry label on each
            # quote row but no separate constituent catalogue.  Reuse only
            # those already-scanned rows whose explicit tags match the LLM
            # industry; never infer membership from a ticker or company name.
            for row in row_map.values():
                tags = []
                for key in ("industry", "industry_name", "sector", "sector_name", "ths_industry"):
                    value = row.get(key)
                    if value:
                        tags.append(str(value))
                for key in ("industries", "focus_industries"):
                    value = row.get(key)
                    if isinstance(value, (list, tuple, set)):
                        tags.extend(str(item) for item in value if str(item).strip())
                    elif value:
                        tags.append(str(value))
                if any(industry == tag or industry in tag or tag in industry for tag in tags):
                    code = str(row.get("code") or "").zfill(6)
                    if len(code) == 6:
                        members[code] = {"code": code, "name": row.get("name") or code}
        status = "confirmed" if len(members) >= 3 else "early_signal" if members else "discarded"
        validated.append({**dict(hotspot), "industries": industries, "mapped_count": len(members), "status": status})
        if status in {"confirmed", "early_signal"}:
            for code, member in list(members.items())[:10]:
                merged = dict(row_map.get(code) or member)
                merged.setdefault("candidate_sources", [])
                merged["candidate_sources"] = sorted(set(merged["candidate_sources"]) | {"llm_hotspot"})
                merged["hotspot_themes"] = sorted(set(merged.get("hotspot_themes") or []) | {str(hotspot.get("theme") or "")})
                merged["hotspot_evidence"] = list(hotspot.get("evidence_refs") or [])
                expanded[code] = merged
    return {"hotspots": validated, "rows": list(expanded.values())[:max_total]}
