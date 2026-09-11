"""Validate whether stock candidates match a market theme.

This keeps deterministic industry / role checks out of long prompt context.
The output is intentionally compact so it can be pasted into analysis reports
as the `行业-角色-催化错配检查` section.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP_PATH = ROOT / "docs" / "analyse" / "reference" / "stock_industry_map.jsonl"
DEFAULT_ETF_MAP_PATH = ROOT / "docs" / "analyse" / "reference" / "etf_theme_map.jsonl"

THEME_ALIASES = {
    "ai能源": "AI能源/算电协同",
    "算电协同": "AI能源/算电协同",
    "绿电直连": "绿电直连",
    "源网荷储": "AI能源/算电协同",
    "电网": "电网设备",
    "电网设备": "电网设备",
    "智能电网": "电网设备",
    "特高压": "电网设备",
    "火电": "火电弹性",
    "火电弹性": "火电弹性",
    "容量电价": "火电弹性",
    "电价修复": "火电弹性",
    "区域电价": "区域电价弹性",
    "绿电": "绿电运营",
    "绿电运营": "绿电运营",
    "绿电防御": "绿电防御",
    "水电": "水电红利",
    "水电红利": "水电红利",
    "核电": "核电",
    "电力": "电力ETF",
    "电力etf": "电力ETF",
    "新能源": "新能源",
    "半导体": "半导体设备",
    "半导体设备": "半导体设备",
    "科技": "科技硬件",
    "科技硬件": "科技硬件",
    "ai硬件": "AI硬件",
    "cpo": "CPO/光通信",
    "光通信": "CPO/光通信",
    "先进封装": "先进封装",
    "券商": "券商",
    "金融科技": "金融科技",
    "医疗": "医疗",
    "创新药": "创新药",
    "医药出海": "医药出海",
    "cxo": "CXO",
    "黄金": "黄金",
    "油气": "油气",
    "资源": "资源对冲",
    "资源对冲": "资源对冲",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check stock candidates against theme, sub-industry, role, and catalyst fit."
    )
    parser.add_argument("--theme", action="append", required=True, help="Theme name. Repeatable.")
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="Candidate stock as code=name. Comma-separated values are accepted.",
    )
    parser.add_argument(
        "--mode",
        default="",
        help="Optional session mode label, such as 盘前, 盘中, or 盘后.",
    )
    parser.add_argument(
        "--map",
        default=str(DEFAULT_MAP_PATH),
        help="Path to stock_industry_map.jsonl.",
    )
    parser.add_argument(
        "--etf-map",
        default=str(DEFAULT_ETF_MAP_PATH),
        help="Path to etf_theme_map.jsonl.",
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    return parser.parse_args()


def normalize_code(value: str) -> str:
    raw = value.strip().upper()
    match = re.search(r"(\d{6})", raw)
    return match.group(1) if match else raw


def split_theme(value: str) -> list[str]:
    parts = re.split(r"[、,，/+\s]+", value.strip())
    output: list[str] = []
    for part in parts:
        token = part.strip()
        if not token:
            continue
        key = token.lower()
        output.append(THEME_ALIASES.get(key, token))
    return output


def unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def load_one_map(path: Path, required: bool = True) -> list[dict[str, Any]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"theme map not found: {path}")
        return []

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return rows


def load_map(paths: list[Path]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_code: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        rows.extend(load_one_map(path, required=index == 0))
    for row in rows:
        by_code[normalize_code(str(row.get("code", "")))] = row
        name = str(row.get("name", "")).strip()
        if name:
            by_name[name] = row
    return by_code, by_name


def parse_candidates(values: list[str]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for value in values:
        for raw_item in value.split(","):
            item = raw_item.strip()
            if not item:
                continue
            separator = "=" if "=" in item else ":" if ":" in item else ""
            if separator:
                code, name = item.split(separator, 1)
            else:
                code, name = item, ""
            candidates.append({"code": code.strip(), "name": name.strip()})
    return candidates


def role_for_theme(row: dict[str, Any], theme_hits: list[str], fallback: str) -> str:
    role_by_theme = row.get("role_by_theme") or {}
    for theme in theme_hits:
        role = role_by_theme.get(theme)
        if role:
            return str(role)
    return fallback


def is_defensive_role(role: str) -> bool:
    return "防御锚" in role or "对冲锚" in role


def evaluate_candidate(
    candidate: dict[str, str],
    themes: list[str],
    by_code: dict[str, dict[str, Any]],
    by_name: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    code = normalize_code(candidate.get("code", ""))
    input_name = candidate.get("name", "")
    row = by_code.get(code) or by_name.get(input_name)
    display = f"{code} {input_name}".strip()

    if row is None:
        return {
            "stock": display,
            "theme": "/".join(themes),
            "sub_industry": "未收录",
            "role": "观察锚",
            "catalyst_fit": "未确认",
            "etf_match": "未确认",
            "handling": "观察/需人工确认",
            "placement": "禁止进入主线行",
            "core_allowed": False,
            "note": "行业映射库未收录，不能作为核心候选。",
        }

    name = str(row.get("name", input_name))
    display = f"{normalize_code(str(row.get('code', code)))} {name}"
    direct = set(row.get("direct_themes") or [])
    indirect = set(row.get("indirect_themes") or [])
    excluded = set(row.get("excluded_themes") or [])

    direct_hits = [theme for theme in themes if theme in direct]
    indirect_hits = [theme for theme in themes if theme in indirect]
    excluded_hits = [theme for theme in themes if theme in excluded]
    fallback_role = str(row.get("default_role") or "观察锚")

    if direct_hits:
        role = role_for_theme(row, direct_hits, fallback_role)
        catalyst_fit = "直接催化"
        etf_match = "匹配" if not excluded_hits else "部分匹配"
        if excluded_hits:
            handling = "拆分后仅用于直接匹配主题"
            placement = "禁止混入当前混合主线；仅可单独用于" + "/".join(direct_hits)
            core_allowed = False
        elif is_defensive_role(role):
            handling = "列为防御锚"
            placement = "单独防御/对冲行，不进入主线行"
            core_allowed = False
        else:
            handling = "纳入核心候选"
            placement = "可进入当前主线行"
            core_allowed = True
    elif indirect_hits:
        role = role_for_theme(row, indirect_hits, fallback_role)
        catalyst_fit = "间接受益"
        etf_match = "不匹配" if excluded_hits else "部分匹配"
        if excluded_hits:
            handling = "剔出当前主线，单独观察" if not is_defensive_role(role) else "剔出当前主线，单独防御观察"
            placement = "禁止进入当前主线行"
        else:
            handling = "列为防御锚/观察" if is_defensive_role(role) else "观察"
            placement = "单独观察/防御行，不进入主线行"
        core_allowed = False
    elif excluded_hits:
        role = "剔除/降权"
        catalyst_fit = "无明确关系"
        etf_match = "不匹配"
        handling = "剔除降权"
        placement = "禁止进入当前主线行"
        core_allowed = False
    else:
        role = "剔除/降权"
        catalyst_fit = "无明确关系"
        etf_match = "不匹配"
        handling = "剔除降权"
        placement = "禁止进入当前主线行"
        core_allowed = False

    note_parts: list[str] = []
    if direct_hits:
        note_parts.append("直接=" + "/".join(direct_hits))
    if indirect_hits and not direct_hits:
        note_parts.append("间接=" + "/".join(indirect_hits))
    if excluded_hits:
        note_parts.append("排除=" + "/".join(excluded_hits))
    if row.get("notes"):
        note_parts.append(str(row["notes"]))

    return {
        "stock": display,
        "theme": "/".join(themes),
        "sub_industry": str(row.get("sub_industry", "")),
        "role": role,
        "catalyst_fit": catalyst_fit,
        "etf_match": etf_match,
        "handling": handling,
        "placement": placement,
        "core_allowed": core_allowed,
        "note": "；".join(note_parts),
    }


def markdown_table(rows: list[dict[str, Any]], mode: str, themes: list[str], map_paths: list[Path]) -> str:
    map_labels = []
    for path in map_paths:
        if not path.exists():
            continue
        map_labels.append(str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path))
    lines = [
        "## 行业-角色-催化错配检查",
        f"- mode: {mode or '未指定'}",
        f"- themes: {' / '.join(themes)}",
        f"- maps: `{'; '.join(map_labels)}`",
        "- rule: 非直接催化、被任一当前主题排除、或仅防御相关的标的不得进入当前主线行；必须拆分到真实子行业行或剔除。",
        "",
        "| 标的 | 主线方向 | 真实子行业 | 交易角色 | 催化关系 | ETF/指数匹配 | 处理 | 主线行限制 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {stock} | {theme} | {sub_industry} | {role} | {catalyst_fit} | "
            "{etf_match} | {handling} | {placement} | {note} |".format(**row)
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    map_path = Path(args.map)
    etf_map_path = Path(args.etf_map)
    map_paths = [map_path, etf_map_path]
    by_code, by_name = load_map(map_paths)
    themes = unique_preserve([theme for raw in args.theme for theme in split_theme(raw)])
    candidates = parse_candidates(args.candidate)
    rows = [evaluate_candidate(candidate, themes, by_code, by_name) for candidate in candidates]

    if args.format == "json":
        print(
            json.dumps(
                {"mode": args.mode, "themes": themes, "maps": [str(path) for path in map_paths], "rows": rows},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(markdown_table(rows, args.mode, themes, map_paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
