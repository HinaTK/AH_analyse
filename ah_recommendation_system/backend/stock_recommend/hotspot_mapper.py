"""Deterministic validation and mapping for LLM-reported themes."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

PLACEHOLDER_THEMES = {"\u65b0\u95fb\u9a71\u52a8\u5f85\u786e\u8ba4", "\u70ed\u70b9\u5f85\u786e\u8ba4"}

INDUSTRY_ALIASES = {
    "银行": ["银行"],
    "石油石化": ["石油开采", "油运"],
    "油气开采": ["石油开采"],
    "沥青": ["石油开采"],
    "印制电路板": ["功率半导体"],
    "AI算力硬件": ["功率半导体"],
    "算力硬件": ["功率半导体"],
    "覆铜板": ["功率半导体"],
    "电子材料": ["功率半导体"],
    "光通信设备": ["功率半导体"],
    "光芯片": ["功率半导体"],
    "电子元件": ["功率半导体"],
    "电容器": ["功率半导体"],
    "半导体": ["功率半导体"],
    "功率器件": ["功率半导体"],
    "通信设备": ["功率半导体"],
    "新能源汽车": ["新能源"],
    "动力电池": ["新能源"],
}


def _alias_keys(industry: str) -> list[str]:
    keys = [industry]
    keys.extend(INDUSTRY_ALIASES.get(industry, []))
    return keys


def _is_unrelated_power_name(name: str) -> bool:
    text = str(name or "")
    if any(token in text for token in ("新能源", "光伏", "锂电", "电池", "储能")):
        return False
    return any(token in text for token in ("深圳能源", "深南电", "电力", "热电", "水电", "火电"))


def _keep_mapped_member(name: str, alias: str) -> bool:
    return not (alias == "新能源" and _is_unrelated_power_name(name))


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
        theme = str(hotspot.get("theme") or "").strip()
        if theme in PLACEHOLDER_THEMES:
            validated.append({**dict(hotspot), "industries": [], "mapped_count": 0, "status": "discarded"})
            continue
        industries = [str(item).strip() for item in hotspot.get("industries") or [] if str(item).strip()]
        members: Dict[str, Dict[str, Any]] = {}
        for industry in industries:
            for alias in _alias_keys(industry):
                for item in focus_universe.get(alias, ()):
                    code = str(item.get("code") or "").zfill(6)
                    name = str(item.get("name") or code)
                    if len(code) == 6 and _keep_mapped_member(name, alias):
                        members[code] = {"code": code, "name": name}
            for key, items in focus_universe.items():
                if any(alias == str(key) for alias in _alias_keys(industry)):
                    for item in items:
                        code = str(item.get("code") or "").zfill(6)
                        name = str(item.get("name") or code)
                        if len(code) == 6 and _keep_mapped_member(name, str(key)):
                            members[code] = {"code": code, "name": name}
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
                if any(industry == tag for tag in tags):
                    code = str(row.get("code") or "").zfill(6)
                    if len(code) == 6:
                        members[code] = {"code": code, "name": row.get("name") or code}
        refs = hotspot.get("evidence_refs") or []
        # Industry membership is observation context. It does not verify the
        # news event, so mapped names stay early_signal unless already confirmed
        # by an independent market/news status that is not member-count based.
        incoming = str(hotspot.get("status") or "early_signal")
        if members or len(refs) >= 2:
            status = incoming if incoming in {"early_signal", "market_confirmed", "confirmed"} else "early_signal"
            if status == "confirmed" and incoming != "confirmed":
                status = "early_signal"
        else:
            status = "discarded"
        representatives = [str(member.get("name") or code) for code, member in list(members.items())[:5] if str(member.get("name") or code)]
        mapping_gap = None
        if not representatives:
            mapping_gap = "行业成员数据缺失" if not any(focus_universe.get(item) for item in industries) else "关联尚未核验"
        validated.append({
            **dict(hotspot),
            "industries": industries,
            "mapped_count": len(members),
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
                merged["hotspot_evidence"] = list(hotspot.get("evidence_refs") or [])
                expanded[code] = merged
    return {"hotspots": validated, "rows": list(expanded.values())[:max_total]}
