"""Validate final market-analysis rows do not mix unrelated sub-industries.

This catches a common report-generation failure: a broad theme row such as
"新能源/电力AI能源" contains 电力运营, 电网设备, 光伏设备, or水电红利
at the same time. Those are separate executable branches and must be split
before the final ETF / stock table is considered valid.
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
DEFAULT_ETF_MAP_PATH = ROOT / "docs" / "analyse" / "reference" / "etf_theme_map.jsonl"

GROUP_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("水电红利", ("水电", "长江电力", "600900", "华能水电", "川投能源")),
    ("火电弹性", ("火电", "容量电价", "粤电力", "大唐发电", "华能国际", "华电国际")),
    ("电网设备", ("电网", "特高压", "输变电", "国电南瑞", "电网设备ETF")),
    ("光伏设备", ("光伏", "逆变器", "光伏ETF")),
    ("储能", ("储能",)),
    ("电池", ("电池",)),
    ("新能源车", ("新能源车", "智能车", "小鹏")),
    ("核电", ("核电",)),
    ("风电运营", ("风电运营", "风电运营商", "龙源电力")),
    ("光伏运营", ("光伏运营", "光伏电站")),
    ("光模块CPO", ("CPO", "光通信", "光模块", "通信ETF")),
    ("MLCC被动元件", ("MLCC", "被动元件")),
    ("PCB载板", ("PCB", "载板", "ABF")),
    ("HBM存储", ("存储", "HBM", "DRAM", "NAND")),
    ("半导体设备", ("半导体设备", "半导体设备ETF", "北方华创", "中微公司")),
    ("半导体材料", ("半导体材料", "光刻胶", "电子气体", "硅片")),
    ("科创芯片", ("科创半导体", "科创芯片", "芯片ETF", "科创芯片ETF", "科创半导体ETF")),
    ("先进封装", ("先进封装", "CoWoS")),
    ("封测", ("封测", "长电科技", "通富微电", "华天科技")),
    ("AI服务器ODM", ("AI服务器", "服务器", "ODM", "工业富联", "浪潮信息")),
    ("液冷散热", ("液冷", "散热", "水冷", "温控")),
    ("AI应用SaaS", ("AI应用", "SaaS", "软件")),
    ("港股互联网平台", ("港股科技", "恒生科技", "互联网平台", "平台权重")),
    ("AI终端消费电子", ("AI终端", "消费电子", "AI眼镜", "XR")),
    ("机器人核心部件", ("减速器", "丝杠", "传感器", "控制器", "电机")),
    ("机器人本体", ("机器人本体", "工业机器人", "协作机器人")),
    ("A股创新药", ("A股创新药", "创新药ETF银华", "159992")),
    ("港股创新药", ("港股创新药", "港股创新药ETF", "513120", "信达生物", "康方生物")),
    ("港股医疗", ("港股医疗", "恒生医疗", "513060")),
    ("CXO", ("CXO", "药明康德")),
    ("医疗器械设备", ("医疗器械", "医疗设备", "影像", "高值耗材", "IVD", "手术机器人")),
    ("医疗服务", ("医疗服务", "眼科", "牙科", "医美")),
    ("中药", ("中药",)),
    ("原料药仿制药", ("原料药", "仿制药", "普药")),
    ("疫苗血制品", ("疫苗", "血制品")),
    ("AI医疗信息化", ("AI医疗", "医疗信息化")),
    ("券商", ("券商", "证券ETF", "券商ETF", "中信证券", "东方财富")),
    ("券商经纪/成交贝塔", ("经纪", "成交贝塔")),
    ("券商财富管理", ("财富管理", "基金代销")),
    ("券商投行并购", ("投行", "IPO", "并购重组")),
    ("券商自营资本中介", ("自营", "两融", "衍生品", "资本中介")),
    ("跨境合规", ("跨境", "QDII", "港股通")),
    ("金融IT", ("金融IT", "交易系统")),
]

BROAD_SUB_INDUSTRY_PATTERNS: list[tuple[str, str]] = [
    ("broad power container", r"^(电力|电力运营|电力运营综合|综合电力|绿电运营)$"),
    ("broad sector container", r"^(科技|新能源|券商|医疗|医药)$"),
    ("broad theme container", r"^(AI硬件|AI能源|创新药|半导体|储能|电池|新能源车|港股科技|券商贝塔)$"),
]

BRANCH_SEPARATOR_PATTERN = re.compile(r"[/+＋、，,]|\s和\s|和")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate ETF direction rows in a saved market-composite report."
    )
    parser.add_argument("report", help="Path to market-composite-analysis-*.md")
    parser.add_argument(
        "--etf-map",
        default=str(DEFAULT_ETF_MAP_PATH),
        help="Path to etf_theme_map.jsonl.",
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    return parser.parse_args()


def normalize_code(value: str) -> str:
    match = re.search(r"(\d{6})", value)
    return match.group(1) if match else value.strip().upper()


def load_etf_map(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        rows[normalize_code(str(row.get("code", "")))] = row
    return rows


def concrete_groups(text: str) -> set[str]:
    groups: set[str] = set()
    normalized = text.upper()
    for group, patterns in GROUP_PATTERNS:
        if any(pattern.upper() in normalized for pattern in patterns):
            groups.add(group)
    return groups


def etf_groups(text: str, etf_map: dict[str, dict[str, Any]]) -> set[str]:
    groups: set[str] = set()
    for match in re.finditer(r"\b\d{6}\b", text):
        code = match.group(0)
        prefix = text[max(0, match.start() - 12) : match.start()]
        if re.search(r"不可用|不能用|不得用|不使用|禁止用", prefix):
            continue
        row = etf_map.get(normalize_code(code))
        if not row:
            continue
        parts = [
            str(row.get("name", "")),
            str(row.get("sub_industry", "")),
            " ".join(str(item) for item in row.get("theme_tags", []) or []),
        ]
        groups.update(concrete_groups(" ".join(parts)))
    return groups


def invalid_subindustry_labels(text: str) -> list[str]:
    normalized = re.sub(r"[`*_]", "", text).strip()
    issues: list[str] = []
    if BRANCH_SEPARATOR_PATTERN.search(normalized):
        issues.append("sub-industry cell concatenates branches; split into atomic rows")
    for label, pattern in BROAD_SUB_INDUSTRY_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            issues.append(label)
    return issues


def extract_final_table(lines: list[str]) -> tuple[int, list[list[str]]]:
    start = next((idx for idx, line in enumerate(lines) if "ETF方向与最终个股" in line), -1)
    if start < 0:
        return -1, []

    table_rows: list[list[str]] = []
    table_start = -1
    for idx in range(start + 1, len(lines)):
        line = lines[idx]
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        if table_start < 0:
            table_start = idx
        table_rows.append(cells)

    return table_start, table_rows


def validate_rows(path: Path, etf_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    table_start, rows = extract_final_table(lines)
    if table_start < 0 or not rows:
        return [
            {
                "line": None,
                "severity": "error",
                "message": "missing `ETF方向与最终个股` table",
                "row": "",
            }
        ]

    header = rows[0]
    issues: list[dict[str, Any]] = []
    try:
        main_idx = header.index("主线方向")
        sub_idx = header.index("子行业/真实归属")
        etf_idx = header.index("ETF")
        core_idx = header.index("核心弹性/角色锚点（含价格+状态）")
        defensive_idx = header.index("防御/观察锚（含价格+状态）")
    except ValueError as exc:
        return [
            {
                "line": table_start + 1,
                "severity": "error",
                "message": f"unexpected final table header: {exc}",
                "row": " | ".join(header),
            }
        ]

    for offset, row in enumerate(rows[1:], 1):
        if len(row) < len(header):
            issues.append(
                {
                    "line": table_start + offset + 1,
                    "severity": "error",
                    "message": "malformed final table row",
                    "row": " | ".join(row),
                }
            )
            continue

        line_number = table_start + offset + 1
        main_direction = row[main_idx]
        sub_industry = row[sub_idx]
        etf = row[etf_idx]
        candidate_text = f"{row[core_idx]} {row[defensive_idx]}"
        sub_groups = concrete_groups(sub_industry)
        mapped_etf_groups = etf_groups(etf, etf_map)
        candidate_groups = concrete_groups(candidate_text)
        invalid_labels = invalid_subindustry_labels(sub_industry)

        if invalid_labels:
            issues.append(
                {
                    "line": line_number,
                    "severity": "error",
                    "message": "sub-industry must be one atomic branch, not a broad or concatenated label",
                    "groups": invalid_labels,
                    "row": " | ".join(row),
                }
            )
        if len(sub_groups) > 1:
            issues.append(
                {
                    "line": line_number,
                    "severity": "error",
                    "message": "final row mixes multiple real sub-industries; split into separate rows",
                    "groups": sorted(sub_groups),
                    "row": " | ".join(row),
                }
            )
        if len(mapped_etf_groups) > 1:
            issues.append(
                {
                    "line": line_number,
                    "severity": "error",
                    "message": "final row mixes ETFs from multiple mapped branches; split ETF expressions",
                    "groups": sorted(mapped_etf_groups),
                    "row": " | ".join(row),
                }
            )
        if candidate_groups and (sub_groups or mapped_etf_groups):
            allowed = sub_groups | mapped_etf_groups
            unrelated = candidate_groups - allowed
            if unrelated:
                issues.append(
                    {
                        "line": line_number,
                        "severity": "error",
                        "message": "candidate / defensive anchor belongs to a different real sub-industry than the row",
                        "groups": sorted(unrelated),
                        "row": " | ".join(row),
                    }
                )
        if "/" in main_direction and len(sub_groups | mapped_etf_groups) > 1:
            issues.append(
                {
                    "line": line_number,
                    "severity": "warning",
                    "message": "broad main direction is being used as an action container",
                    "groups": sorted(sub_groups | mapped_etf_groups),
                    "row": " | ".join(row),
                }
            )

    return issues


def render_markdown(report: Path, issues: list[dict[str, Any]]) -> str:
    lines = [f"## Report Theme Row Validation", f"- report: `{report}`"]
    if not issues:
        lines.append("- result: pass")
        return "\n".join(lines)

    lines.append(f"- result: fail ({len(issues)} issue(s))")
    lines.append("")
    lines.append("| line | severity | issue | groups | row |")
    lines.append("| ---: | --- | --- | --- | --- |")
    for issue in issues:
        groups = ", ".join(issue.get("groups", []))
        row = str(issue.get("row", "")).replace("|", "\\|")
        lines.append(
            f"| {issue.get('line') or ''} | {issue['severity']} | {issue['message']} | {groups} | {row} |"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    report = Path(args.report)
    etf_map = load_etf_map(Path(args.etf_map))
    issues = validate_rows(report, etf_map)
    if args.format == "json":
        print(json.dumps({"report": str(report), "issues": issues}, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report, issues))
    return 1 if any(issue.get("severity") == "error" for issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
