from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
ANALYSE_DIR = ROOT / "docs" / "analyse"
LEDGER_PATH = ANALYSE_DIR / "abnormal-movement-ledger.jsonl"
STATS_PATH = ANALYSE_DIR / "abnormal-movement-stats.md"

REPORT_SECTION_NAMES = [
    "结论摘要",
    "命中率更新",
    "重大事件分流表",
    "异动表现表",
    "原因到行业映射",
    "当前行业评分",
    "未来1-3个月展望评分",
    "ETF行动矩阵",
    "新增预测",
    "结论有效期与风控",
    "证伪信号",
    "排除/降级事件审计",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a compact, source-linked context summary for market analysis runs."
    )
    parser.add_argument(
        "--as-of",
        default=date.today().isoformat(),
        help="Trading date used for due/evaluated/new row summaries, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--latest-reports",
        type=int,
        default=1,
        help="Number of latest reports per report family to list.",
    )
    parser.add_argument(
        "--recent-rows",
        type=int,
        default=8,
        help="Number of latest ledger rows to print.",
    )
    parser.add_argument(
        "--section-lines",
        type=int,
        default=6,
        help="Maximum lines to preview for each selected report section.",
    )
    parser.add_argument(
        "--max-ledger-items",
        type=int,
        default=10,
        help="Maximum row-level ledger items to print for each summary bucket.",
    )
    parser.add_argument(
        "--max-due-windows",
        type=int,
        default=12,
        help="Maximum pending due-date windows to print.",
    )
    return parser.parse_args()


def load_ledger(path: Path) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    errors: list[str] = []
    if not path.exists():
        return rows, [f"missing ledger: {path}"]

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: {exc}")
            continue
        row["__line__"] = line_number
        rows.append(row)
    return rows, errors


def bool_result(value: object) -> str:
    if value is True:
        return "hit"
    if value is False:
        return "miss"
    return "noise/na"


def fmt_rate(hits: int, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{hits / total:.2%}"


def concise_row(row: dict) -> str:
    line = row.get("__line__", "?")
    row_id = row.get("id", "")
    status = row.get("status", "")
    due = row.get("due_date", "")
    horizon = row.get("horizon", "")
    instrument = row.get("instrument", "")
    benchmark = row.get("benchmark_instrument", row.get("benchmark", ""))
    excess = row.get("excess_return")
    hit = bool_result(row.get("composite_hit"))
    return (
        f"L{line} `{row_id}` | {status} | {horizon} due {due} | "
        f"{instrument} vs {benchmark} | excess={excess} | {hit}"
    )


def latest_files(pattern: str, limit: int) -> list[Path]:
    return sorted(ANALYSE_DIR.glob(pattern), key=lambda path: path.name, reverse=True)[:limit]


def heading_ranges(lines: list[str]) -> dict[str, tuple[int, int]]:
    headings: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append((match.group(2), idx))

    ranges: dict[str, tuple[int, int]] = {}
    for pos, (name, start) in enumerate(headings):
        end = headings[pos + 1][1] if pos + 1 < len(headings) else len(lines)
        ranges[name] = (start, end)
    return ranges


def section_preview(path: Path, names: Iterable[str], max_lines: int) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    ranges = heading_ranges(lines)
    output: list[str] = []

    for wanted in names:
        match_name = next((name for name in ranges if wanted in name), None)
        if not match_name:
            continue
        start, end = ranges[match_name]
        section = lines[start : min(end, start + max_lines)]
        output.append(f"### {path.name} :: {match_name} (L{start + 1}-L{end})")
        output.extend(section)
        if end - start > max_lines:
            output.append(f"... truncated; read `{path}` from line {start + max_lines + 1} if needed")
        output.append("")
    return output


def print_ledger_summary(
    rows: list[dict],
    errors: list[str],
    as_of: str,
    recent_rows: int,
    max_ledger_items: int,
    max_due_windows: int,
) -> None:
    print("## Ledger Summary")
    print(f"- path: `{LEDGER_PATH.relative_to(ROOT)}`")
    print(f"- rows: {len(rows)}")
    print(f"- json_errors: {len(errors)}")
    for error in errors[:10]:
        print(f"  - {error}")

    ids = [row.get("id") for row in rows]
    duplicate_ids = [row_id for row_id, count in Counter(ids).items() if count > 1]
    print(f"- duplicate_ids: {len(duplicate_ids)}")
    for row_id in duplicate_ids[:10]:
        print(f"  - `{row_id}`")

    status_counts = Counter(row.get("status") for row in rows)
    print("- status_counts: " + ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items())))

    evaluated_samples = [
        row for row in rows if row.get("status") == "evaluated" and row.get("composite_hit") is not None
    ]
    hits = sum(1 for row in evaluated_samples if row.get("composite_hit") is True)
    recent = evaluated_samples[-20:]
    recent_hits = sum(1 for row in recent if row.get("composite_hit") is True)

    thesis_latest: dict[str, dict] = {}
    for row in evaluated_samples:
        thesis_latest[row.get("thesis_key", row.get("id", ""))] = row
    thesis_rows = list(thesis_latest.values())
    thesis_hits = sum(1 for row in thesis_rows if row.get("composite_hit") is True)

    print(f"- evaluated_hit_rate: {hits}/{len(evaluated_samples)} = {fmt_rate(hits, len(evaluated_samples))}")
    print(f"- recent20_hit_rate: {recent_hits}/{len(recent)} = {fmt_rate(recent_hits, len(recent))}")
    print(f"- thesis_hit_rate: {thesis_hits}/{len(thesis_rows)} = {fmt_rate(thesis_hits, len(thesis_rows))}")

    evaluated_on = [row for row in rows if str(row.get("evaluated_at") or "").startswith(as_of)]
    created_on = [row for row in rows if str(row.get("created_at") or "").startswith(as_of)]
    due_or_overdue_pending = [
        row for row in rows if row.get("status") == "pending" and str(row.get("due_date") or "") <= as_of
    ]

    print(f"- evaluated_on_{as_of}: {len(evaluated_on)}")
    for row in evaluated_on[:max_ledger_items]:
        print(f"  - {concise_row(row)}")
    if len(evaluated_on) > max_ledger_items:
        print(f"  - ... {len(evaluated_on) - max_ledger_items} more evaluated rows")

    print(f"- created_on_{as_of}: {len(created_on)}")
    for row in created_on[:max_ledger_items]:
        print(f"  - {concise_row(row)}")
    if len(created_on) > max_ledger_items:
        print(f"  - ... {len(created_on) - max_ledger_items} more created rows")

    print(f"- pending_due_or_overdue_as_of_{as_of}: {len(due_or_overdue_pending)}")
    for row in due_or_overdue_pending[:max_ledger_items]:
        print(f"  - {concise_row(row)}")
    if len(due_or_overdue_pending) > max_ledger_items:
        print(f"  - ... {len(due_or_overdue_pending) - max_ledger_items} more due/overdue pending rows")

    due_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("status") == "pending":
            due_groups[str(row.get("due_date"))].append(row)
    print("- pending_due_windows:")
    due_dates = sorted(due_groups)
    for due in due_dates[:max_due_windows]:
        horizons = " / ".join(sorted({str(row.get("horizon")) for row in due_groups[due]}))
        print(f"  - {due}: {len(due_groups[due])} rows ({horizons})")
    if len(due_dates) > max_due_windows:
        print(f"  - ... {len(due_dates) - max_due_windows} more due windows")

    print(f"- latest_{recent_rows}_ledger_rows:")
    for row in rows[-recent_rows:]:
        print(f"  - {concise_row(row)}")
    print("")


def print_report_index(latest_reports: int, section_lines: int) -> None:
    print("## Prior Report Index")
    families = [
        ("market-composite", "market-composite-analysis-*.md"),
        ("abnormal-movement", "abnormal-movement-analysis-*.md"),
        ("investment-sector", "investment-sector-analysis-*.md"),
    ]
    for family, pattern in families:
        files = latest_files(pattern, latest_reports)
        print(f"- {family}: {len(files)} latest files")
        for path in files:
            print(f"  - `{path.relative_to(ROOT)}`")
    print("")

    print("## Selected Prior Report Sections")
    for path in latest_files("market-composite-analysis-*.md", latest_reports):
        previews = section_preview(path, REPORT_SECTION_NAMES, section_lines)
        if previews:
            print("\n".join(previews))


def main() -> None:
    args = parse_args()
    rows, errors = load_ledger(LEDGER_PATH)

    print("# Analysis Context Summary")
    print("")
    print("This is a compact navigation summary. Authoritative data remains in the referenced files and live sources.")
    print(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S +08:00')}")
    print(f"As-of date: {args.as_of}")
    print("")
    print_ledger_summary(
        rows,
        errors,
        args.as_of,
        args.recent_rows,
        args.max_ledger_items,
        args.max_due_windows,
    )
    print(f"## Stats File")
    if STATS_PATH.exists():
        print(f"- path: `{STATS_PATH.relative_to(ROOT)}`")
        print(f"- size_bytes: {STATS_PATH.stat().st_size}")
    else:
        print(f"- missing: `{STATS_PATH.relative_to(ROOT)}`")
    print("")
    print_report_index(args.latest_reports, args.section_lines)


if __name__ == "__main__":
    main()
