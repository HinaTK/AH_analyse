"""Deterministic validation and mapping for LLM-reported themes."""
from __future__ import annotations

from datetime import date, datetime
import unicodedata
from typing import Any, Dict, Iterable, Mapping

PLACEHOLDER_THEMES = {"\u65b0\u95fb\u9a71\u52a8\u5f85\u786e\u8ba4", "\u70ed\u70b9\u5f85\u786e\u8ba4"}

TRUSTED_INDUSTRY_EQUIVALENTS = (
    # These are provider/market-language synonyms, not parent/child sectors.
    frozenset({"油轮运输", "油运"}),
    frozenset({"新能源汽车", "新能源车"}),
    frozenset({"玻纤", "玻璃玻纤"}),
    frozenset({"石油开采", "油气开采"}),
    frozenset({"证券", "券商"}),
)

NARROW_THEME_BUCKETS = {
    "新能源汽车": {"新能源"},
    "新能源车": {"新能源"},
    "动力电池": {"新能源"},
}


def _norm_industry(value: Any) -> str:
    """Normalize labels for exact taxonomy matching (never substring match)."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = "".join(text.split())
    for suffix in ("(申万)", "(同花顺)", "(ths)", "行业"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
    return text


def _scoring_aliases(industry: str) -> set[str]:
    normalized = _norm_industry(industry)
    for group in TRUSTED_INDUSTRY_EQUIVALENTS:
        normalized_group = {_norm_industry(item) for item in group}
        if normalized in normalized_group:
            return normalized_group
    return {normalized}


def _focus_catalog_keys(industry: str) -> set[str]:
    normalized = _norm_industry(industry)
    return _scoring_aliases(industry) | {
        _norm_industry(item) for item in NARROW_THEME_BUCKETS.get(normalized, set())
    }


def _narrow_bucket_member_allowed(industry: str, catalog_key: str, name: str) -> bool:
    requested = _norm_industry(industry)
    if _norm_industry(catalog_key) != "新能源" or requested not in NARROW_THEME_BUCKETS:
        return True
    return not any(token in str(name or "") for token in ("深圳能源", "深南电", "电力", "热电", "水电", "火电"))


def _labels_equivalent(left: Any, right: Any) -> bool:
    return _norm_industry(right) in _scoring_aliases(str(left or ""))


def _is_stale(hotspot: Mapping[str, Any], *, as_of: str | None = None) -> bool:
    if hotspot.get("is_stale") is True or str(hotspot.get("freshness_status") or "").lower() in {"stale", "expired"}:
        return True
    value = hotspot.get("expires_at")
    if not value:
        return False
    try:
        expiry = datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        today = date.fromisoformat(str(as_of)[:10]) if as_of else date.today()
        return expiry < today
    except (TypeError, ValueError):
        return True


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _positive_direction(value: Any) -> bool:
    direction = str(value or "").strip().lower()
    return direction in {"positive", "bullish", "support", "利好", "看多", "正面"}


def hotspot_score_for_candidate(
    candidate: Any,
    mapping: Mapping[str, Any],
    *,
    market_regime: Mapping[str, Any] | None = None,
    as_of: str | None = None,
) -> float:
    """Return a bounded evidence score without mutating the base model score."""
    if market_regime and (
        market_regime.get("status") != "available" or market_regime.get("regime") == "defense"
    ):
        return 0.0
    matches = list(mapping.get("matches") or [])
    best = 0.0
    for match in matches:
        status = str(match.get("status") or "").lower()
        direction = str(match.get("direction") or "").lower()
        refs = list(match.get("evidence_refs") or [])
        independent = _safe_int(match.get("independent_source_count"))
        if status not in {"early_signal", "market_confirmed", "confirmed"} or not _positive_direction(direction):
            continue
        if not refs or _is_stale(match, as_of=as_of):
            continue
        if (
            status == "early_signal"
            and match.get("price_volume_confirmed") is not True
            and independent < 2
        ):
            continue
        price_volume_confirmed = (
            status in {"market_confirmed", "confirmed"}
            or match.get("price_volume_confirmed") is True
            or float(getattr(candidate, "factor_scores", {}).get("price_volume") or 0.0) >= 0.5
        )
        if independent >= 2 and price_volume_confirmed:
            best = max(best, 0.15)
        elif independent >= 2:
            best = max(best, 0.10)
        else:
            best = max(best, 0.05)
    return best


def apply_hotspot_mappings(
    candidates: Iterable[Any],
    mappings: Mapping[str, Mapping[str, Any]],
    *,
    market_regime: Mapping[str, Any] | None = None,
    as_of: str | None = None,
) -> None:
    """Write auditable mapping fields to existing candidates only."""
    for candidate in candidates:
        candidate.reasons = [
            reason for reason in (getattr(candidate, "reasons", []) or [])
            if not str(reason).startswith("热点匹配：")
        ]
        mapping = mappings.get(str(getattr(candidate, "code", "")).zfill(6))
        if not mapping:
            # This function can be called more than once during a run/replay.
            # Never retain a prior verified mapping when the current run has no
            # mapping for the candidate.
            candidate.hotspot_themes = []
            candidate.hotspot_industries = []
            candidate.hotspot_evidence = []
            candidate.hotspot_match_level = "none"
            candidate.hotspot_mapping_sources = []
            candidate.hotspot_matches = []
            candidate.hotspot_mapping_verified = False
            candidate.hotspot_score = 0.0
            candidate.factor_scores.pop("hotspot", None)
            continue
        candidate.hotspot_themes = list(mapping.get("matched_themes") or [])
        candidate.hotspot_industries = list(mapping.get("matched_industries") or [])
        candidate.hotspot_evidence = list(mapping.get("evidence_refs") or [])
        candidate.hotspot_match_level = str(mapping.get("match_level") or "none")
        candidate.hotspot_mapping_sources = list(mapping.get("mapping_sources") or [])
        candidate.hotspot_matches = [dict(item) for item in (mapping.get("matches") or [])]
        candidate.hotspot_mapping_verified = any(
            str(match.get("status") or "").lower() in {"early_signal", "market_confirmed", "confirmed"}
            and _positive_direction(match.get("direction"))
            and bool(match.get("evidence_refs"))
            and (
                str(match.get("status") or "").lower() in {"market_confirmed", "confirmed"}
                or match.get("price_volume_confirmed") is True
                or _safe_int(match.get("independent_source_count")) >= 2
            )
            and not _is_stale(match, as_of=as_of)
            for match in candidate.hotspot_matches
        )
        candidate.hotspot_score = hotspot_score_for_candidate(
            candidate, mapping, market_regime=market_regime, as_of=as_of
        )
        candidate.factor_scores["hotspot"] = candidate.hotspot_score
        if candidate.hotspot_score:
            candidate.reasons.append(
                f"热点匹配：{'、'.join(candidate.hotspot_themes[:2])}（加分{candidate.hotspot_score:.2f}）"
            )


def validate_and_expand_hotspots(
    hotspots: Iterable[Mapping[str, Any]],
    *,
    focus_universe: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    rows: Iterable[Mapping[str, Any]] = (),
    max_total: int = 60,
) -> Dict[str, Any]:
    focus_universe = {
        str(key): list(items or [])
        for key, items in (focus_universe or {}).items()
        if str(key or "").strip()
    }
    row_map = {str(row.get("code") or "").zfill(6): dict(row) for row in rows if str(row.get("code") or "")}
    expanded: Dict[str, Dict[str, Any]] = {}
    candidate_mappings: Dict[str, Dict[str, Any]] = {}
    validated: list[Dict[str, Any]] = []
    for hotspot in hotspots:
        theme = str(hotspot.get("theme") or "").strip()
        if theme in PLACEHOLDER_THEMES:
            validated.append({**dict(hotspot), "industries": [], "mapped_count": 0, "status": "discarded"})
            continue
        industries = [str(item).strip() for item in hotspot.get("industries") or [] if str(item).strip()]
        members: Dict[str, Dict[str, Any]] = {}
        member_sources: Dict[str, str] = {}
        scoring_codes: set[str] = set()
        for industry in industries:
            for key, items in focus_universe.items():
                if _norm_industry(key) not in _focus_catalog_keys(industry):
                    continue
                for item in items:
                    code = str(item.get("code") or "").zfill(6)
                    name = str(item.get("name") or code)
                    if len(code) == 6 and code.isdigit() and _narrow_bucket_member_allowed(industry, key, name):
                        members[code] = {"code": code, "name": name}
                        direct_or_trusted = _norm_industry(key) in _scoring_aliases(industry)
                        member_sources[code] = (
                            "focus_universe"
                            if _norm_industry(key) == _norm_industry(industry)
                            else "trusted_industry_alias" if direct_or_trusted else "broad_bucket_display"
                        )
                        if direct_or_trusted:
                            scoring_codes.add(code)
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
                if any(_labels_equivalent(industry, tag) for tag in tags):
                    code = str(row.get("code") or "").zfill(6)
                    if len(code) == 6 and code.isdigit():
                        members[code] = {"code": code, "name": row.get("name") or code}
                        member_sources[code] = (
                            "row_industry"
                            if any(_norm_industry(tag) == _norm_industry(industry) for tag in tags)
                            else "row_trusted_industry_alias"
                        )
                        scoring_codes.add(code)
        refs = [str(ref) for ref in (hotspot.get("evidence_refs") or []) if str(ref)]
        # Industry membership is observation context. It does not verify the
        # news event, so mapped names stay early_signal unless already confirmed
        # by an independent market/news status that is not member-count based.
        incoming = str(hotspot.get("status") or "early_signal")
        if (members and refs) or (not members and len(refs) >= 2):
            status = incoming if incoming in {"early_signal", "market_confirmed", "confirmed"} else "early_signal"
            if status == "confirmed" and incoming != "confirmed":
                status = "early_signal"
        else:
            status = "discarded"
        representatives = [str(member.get("name") or code) for code, member in list(members.items())[:5] if str(member.get("name") or code)]
        mapped_codes = sorted(members)
        mapping_gap = None
        if not representatives:
            has_equivalent_catalog = any(
                any(_labels_equivalent(industry, key) for key in focus_universe)
                for industry in industries
            )
            mapping_gap = "行业成员数据缺失" if not has_equivalent_catalog else "关联尚未核验"
        validated.append({
            **dict(hotspot),
            "industries": industries,
            "mapped_count": len(members),
            "mapped_codes": mapped_codes,
            "representatives": representatives,
            "mapping_gap": mapping_gap,
            "status": status,
        })
        if status != "discarded":
            for code, member in list(members.items())[:10]:
                merged = dict(row_map.get(code) or member)
                merged.setdefault("candidate_sources", [])
                merged["candidate_sources"] = sorted(set(merged["candidate_sources"]) | {"llm_hotspot"})
                merged["hotspot_themes"] = sorted(set(merged.get("hotspot_themes") or []) | {str(hotspot.get("theme") or "")})
                merged["hotspot_evidence"] = sorted(set(merged.get("hotspot_evidence") or []) | set(refs))
                merged["hotspot_industries"] = sorted(set(merged.get("hotspot_industries") or []) | set(industries))
                merged["hotspot_match_level"] = "direct" if member_sources.get(code) in {"focus_universe", "row_industry"} else "alias"
                merged["hotspot_mapping_sources"] = sorted(set(merged.get("hotspot_mapping_sources") or []) | {member_sources.get(code, "unknown")})
                expanded[code] = merged
            # Candidate writeback is deliberately not truncated by the display
            # representative limit. Only explicit/equivalent membership scores.
            for code in sorted(scoring_codes):
                mapping = candidate_mappings.setdefault(code, {
                    "code": code,
                    "matched_themes": [],
                    "matched_industries": [],
                    "evidence_refs": [],
                    "independent_source_count": 0,
                    "mapping_sources": [],
                    "match_level": "alias",
                    "status": status,
                    "matches": [],
                })
                if hotspot.get("theme") and hotspot["theme"] not in mapping["matched_themes"]:
                    mapping["matched_themes"].append(str(hotspot["theme"]))
                for item in industries:
                    if item not in mapping["matched_industries"]:
                        mapping["matched_industries"].append(item)
                mapping["evidence_refs"] = sorted(set(mapping["evidence_refs"]) | set(refs))
                mapping["independent_source_count"] = max(mapping["independent_source_count"], _safe_int(hotspot.get("independent_source_count")))
                source = member_sources.get(code, "unknown")
                if source not in mapping["mapping_sources"]:
                    mapping["mapping_sources"].append(source)
                if source in {"focus_universe", "row_industry"}:
                    mapping["match_level"] = "direct"
                mapping["matches"].append({
                    "theme": str(hotspot.get("theme") or ""),
                    "status": status,
                    "direction": hotspot.get("direction") or "unknown",
                    "evidence_refs": list(refs),
                    "independent_source_count": _safe_int(hotspot.get("independent_source_count")),
                    "price_volume_confirmed": hotspot.get("price_volume_confirmed") is True,
                    "freshness_status": hotspot.get("freshness_status"),
                    "expires_at": hotspot.get("expires_at"),
                    "is_stale": hotspot.get("is_stale") is True,
                })
    for mapping in candidate_mappings.values():
        direct_sources = {"focus_universe", "row_industry"}
        mapping["mapping_source"] = next(
            (source for source in mapping["mapping_sources"] if source in direct_sources),
            ",".join(mapping["mapping_sources"]),
        )
    return {"hotspots": validated, "rows": list(expanded.values())[:max_total], "candidate_mappings": candidate_mappings}
