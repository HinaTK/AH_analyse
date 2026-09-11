import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSE_DIR = ROOT / "docs" / "analyse"
LEDGER_PATH = ANALYSE_DIR / "abnormal-movement-ledger.jsonl"
STATS_PATH = ANALYSE_DIR / "abnormal-movement-stats.md"


INSTRUMENT_MAP = {
    "CPO/光模块/光纤/PCB/算力硬件": {
        "instrument": "通信ETF(代理)",
        "instrument_type": "etf",
        "benchmark_instrument": "沪深300指数",
        "upstream_reason_tag": "AI / 算力催化",
        "transmission_tag": "AI基础设施景气扩散至通信与算力硬件链",
        "market_amplifier_tag": "主题资金轮动",
        "review_note": "迁移时采用通信ETF作为CPO/光模块方向代理。",
    },
    "新型电网/储能/绿电/液冷IDC": {
        "instrument": "中证智能电网主题指数(代理)",
        "instrument_type": "industry_index",
        "benchmark_instrument": "沪深300指数",
        "upstream_reason_tag": "实时增补原因：AI+能源双向赋能",
        "transmission_tag": "政策驱动算力配套电网与储能需求提升",
        "market_amplifier_tag": "政策主题发酵",
        "review_note": "迁移时采用智能电网主题指数作为政策链条代理。",
    },
    "港股半导体/恒生科技/港股互联网": {
        "instrument": "恒生科技指数",
        "instrument_type": "hk_index",
        "benchmark_instrument": "恒生指数",
        "upstream_reason_tag": "实时增补原因：港股估值修复 / 外资回流",
        "transmission_tag": "外资回流与科技估值修复传导至港股科技板块",
        "market_amplifier_tag": "风险偏好提升",
        "review_note": "迁移时采用恒生科技指数作为港股科技链代理。",
    },
    "航空机场/物流/下游化工": {
        "instrument": "中证航空运输主题指数(代理)",
        "instrument_type": "industry_index",
        "benchmark_instrument": "沪深300指数",
        "upstream_reason_tag": "原油上涨 / 大宗商品涨价",
        "transmission_tag": "能源成本上行压缩航空运输利润",
        "market_amplifier_tag": "风险偏好下降",
        "review_note": "原始行业标签为混合篮子，迁移时统一到航空运输方向。",
    },
    "AI应用/软件": {
        "instrument": "软件ETF(515230)",
        "instrument_type": "etf",
        "benchmark_instrument": "沪深300指数",
        "upstream_reason_tag": "AI / 算力催化",
        "transmission_tag": "海外AI资本开支向应用层扩散",
        "market_amplifier_tag": "高低切换",
        "review_note": "迁移时采用软件ETF作为AI应用方向代理。",
    },
    "半导体设备/存储器": {
        "instrument": "半导体设备ETF(159516)",
        "instrument_type": "etf",
        "benchmark_instrument": "科创50指数",
        "upstream_reason_tag": "国产替代",
        "transmission_tag": "设备扩产与存储景气共振",
        "market_amplifier_tag": "主题资金轮动",
        "review_note": "迁移时采用半导体设备ETF作为设备与存储代理。",
    },
    "黄金/银行/海运": {
        "instrument": "黄金ETF(518880)",
        "instrument_type": "etf",
        "benchmark_instrument": "沪深300指数",
        "upstream_reason_tag": "避险降温",
        "transmission_tag": "避险需求回落导致黄金与防御风格承压",
        "market_amplifier_tag": "风险偏好提升",
        "review_note": "原始行业标签为混合篮子，迁移时统一到黄金避险方向。",
    },
}


MARKET_AMPLIFIER_FALLBACK = {
    "主题资金轮动": "主题资金轮动",
    "风险偏好提升": "风险偏好提升",
    "AI / 算力催化": "主题资金轮动",
    "国产替代": "主题资金轮动",
    "原油上涨 / 大宗商品涨价": "风险偏好下降",
}


def load_rows(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def thesis_key_from_row(row: dict) -> str:
    row_id = row.get("id", "")
    parts = row_id.split("-")
    if len(parts) >= 4:
        return "-".join(parts[:-1]).replace("+", "")
    return row_id.replace("+", "")


def migrate_row(row: dict) -> dict:
    industry = row.get("industry", "")
    mapping = INSTRUMENT_MAP.get(industry, {})
    reason_tag = row.get("reason_tag", "未分类")
    benchmark = row.get("benchmark", "沪深300")
    note_parts = [row.get("review_note", "").strip(), mapping.get("review_note", "").strip(), "v2迁移补齐字段。"]
    review_note = " ".join(part for part in note_parts if part)

    migrated = {
        "id": row.get("id"),
        "thesis_key": thesis_key_from_row(row),
        "created_at": row.get("created_at"),
        "user_request": row.get("user_request", "异动分析"),
        "mode": "full",
        "event": row.get("event"),
        "source_category": row.get("source_category"),
        "upstream_reason_tag": mapping.get("upstream_reason_tag", reason_tag),
        "transmission_tag": mapping.get("transmission_tag", "待后续补充传导链说明"),
        "market_amplifier_tag": mapping.get(
            "market_amplifier_tag",
            MARKET_AMPLIFIER_FALLBACK.get(reason_tag, "待后续补充市场放大器"),
        ),
        "industry": industry,
        "instrument": mapping.get("instrument", f"{industry}(代理)"),
        "instrument_type": mapping.get("instrument_type", "industry_index"),
        "direction": row.get("direction"),
        "benchmark": benchmark,
        "benchmark_instrument": mapping.get("benchmark_instrument", f"{benchmark}指数"),
        "horizon": row.get("horizon"),
        "expected_behavior": row.get("expected_behavior"),
        "confidence": row.get("confidence"),
        "evidence_urls": row.get("evidence_urls", []),
        "entry_rule": "默认收盘价建模",
        "evaluation_rule": "到期日收盘价评估",
        "created_price": row.get("created_price"),
        "created_benchmark_price": row.get("created_benchmark_price"),
        "due_date": row.get("due_date"),
        "status": row.get("status"),
        "actual_return": row.get("actual_return"),
        "benchmark_return": row.get("benchmark_return"),
        "excess_return": row.get("excess_return"),
        "price_hit": row.get("price_hit"),
        "reason_hit": row.get("reason_hit"),
        "timing_hit": None,
        "composite_hit": row.get("composite_hit"),
        "evaluated_at": row.get("evaluated_at"),
        "review_note": review_note,
    }
    return migrated


def reliability_label(count: int) -> str:
    if count < 5:
        return "样本极少"
    if count < 20:
        return "样本偏少"
    return "可参考"


def build_stats(rows: list[dict]) -> str:
    evaluated = [
        row
        for row in rows
        if row.get("status") == "evaluated" and row.get("composite_hit") is not None
    ]
    pending = [row for row in rows if row.get("status") == "pending"]
    thesis_keys = {row["thesis_key"] for row in rows}
    pending_by_horizon = Counter(row["horizon"] for row in pending)
    due_by_horizon = {}
    for row in pending:
        horizon = row["horizon"]
        due_by_horizon.setdefault(horizon, row["due_date"])

    total_eval = len(evaluated)
    composite_hits = sum(1 for row in evaluated if row.get("composite_hit") is True)
    total_rate = f"{(composite_hits / total_eval) * 100:.1f}%" if total_eval else "N/A"
    recent_eval = evaluated[-20:]
    recent_hits = sum(1 for row in recent_eval if row.get("composite_hit") is True)
    recent_rate = f"{(recent_hits / len(recent_eval)) * 100:.1f}%" if recent_eval else "N/A"

    lines = [
        "# 异动预测命中率统计",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S +08:00')}",
        "- 台账路径: `docs/analyse/abnormal-movement-ledger.jsonl`",
        "- 用户请求: 异动分析",
        "- 本次状态: 完成 ledger v2 迁移，尚无到期可评估预测",
        "",
        "## 总览",
        "",
        "| 指标 | 数值 | 可靠性 |",
        "| --- | ---: | --- |",
        f"| 已评估预测数 | {total_eval} | {reliability_label(total_eval)} |",
        f"| 总体综合命中率 | {total_rate} | {reliability_label(total_eval)} |",
        f"| 最近20条综合命中率 | {recent_rate} | {reliability_label(len(recent_eval))} |",
        f"| Thesis 数 | {len(thesis_keys)} | 结构化统计 |",
        f"| 待验证预测数 | {len(pending)} | 待验证 |",
        "",
        "## 分组命中率",
        "",
        "当前没有已评估预测，暂不计算分组命中率。后续运行会按 `upstream_reason_tag`、`industry`、`horizon`、`confidence`、`source_category`、`direction` 以及 `thesis_key` 统计。",
        "",
        "## 待验证窗口 (累计)",
        "",
        "| 窗口 | 到期日 | 累计条数 |",
        "| --- | --- | ---: |",
    ]

    for horizon in ("T+1", "T+3", "T+5", "T+20"):
        lines.append(f"| {horizon} | {due_by_horizon.get(horizon, 'N/A')} | {pending_by_horizon.get(horizon, 0)} |")

    lines.extend(
        [
            "",
            "## 备注",
            "",
            "- 本统计文件由 `tools/migrate_abnormal_movement_ledger_v2.py` 生成。",
            "- 旧字段 `reason_tag` 已迁移为 `upstream_reason_tag` / `transmission_tag` / `market_amplifier_tag`。",
            "- 旧台账已备份，后续 `异动分析` 运行应直接写入 v2 结构。",
        ]
    )
    return "\n".join(lines) + "\n"


def main():
    if not LEDGER_PATH.exists():
        raise FileNotFoundError(f"Ledger not found: {LEDGER_PATH}")

    rows = load_rows(LEDGER_PATH)
    backup_path = ANALYSE_DIR / f"abnormal-movement-ledger-v1-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    backup_path.write_text(LEDGER_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    migrated_rows = [migrate_row(row) for row in rows]
    with LEDGER_PATH.open("w", encoding="utf-8") as f:
        for row in migrated_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    STATS_PATH.write_text(build_stats(migrated_rows), encoding="utf-8")
    print(f"Migrated {len(migrated_rows)} rows to v2")
    print(f"Backup: {backup_path}")
    print(f"Ledger: {LEDGER_PATH}")
    print(f"Stats: {STATS_PATH}")


if __name__ == "__main__":
    main()
