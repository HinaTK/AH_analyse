"""UTF-8 file-based preview; inspect the card before an explicit --send."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from .card_content_audit import audit_pre_market_card
from .feishu_pusher import build_card, push_to_feishu


def build_preview_report(report: dict) -> dict:
    preview = deepcopy(report)
    contract = report.get("recommendation_contract") or {}
    counts = Counter(d.get("state", "未知") for d in contract.get("decisions", []))
    mock = (report.get("coverage") or {}).get("mode") == "mock_sample"
    preview["is_preview"] = True
    label = "MOCK 功能预览｜模拟数据，不代表当前行情" if mock else "报告功能预览"
    preview["summary"] = (
        f"【{label}】\n"
        f"生成时间：{report.get('generated_at', '未知')}\n"
        f"新增决策层：{contract.get('model_version', '未接入')}；"
        f"候选 {contract.get('candidate_count', 0)} 个；"
        f"5/20/60 交易日验证计划 {len(contract.get('verification_plan', []))} 条。\n"
        "新层状态：" + "、".join(f"{state} {count}" for state, count in counts.items()) + "。\n"
        "下方为现有推荐卡片展示；新决策层尚未替换旧推荐展示，验证计划数量不等于已完成验证数量。"
    )
    if mock:
        preview.setdefault("coverage", {})["label"] = "MOCK 模拟样本功能预览"
    return preview


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    report = build_preview_report(json.loads(args.report.read_text(encoding="utf-8")))
    card = build_card(report)
    audit = audit_pre_market_card(report, card)
    if not audit["passed"]:
        print(json.dumps(audit, ensure_ascii=True))
        return 1
    target = args.report.parent / "previews"
    target.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    report_path = target / f"corrected_preview_{stamp}.json"
    card_path = target / f"corrected_card_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"audit": audit, "report_path": str(report_path), "card_path": str(card_path), "sent": False}
    if args.send:
        delivery = push_to_feishu(report, retries=1)
        result.update(sent=bool(delivery.get("ok")), status=delivery.get("status"),
                      business_code=(delivery.get("response") or {}).get("code"),
                      payload_hash=delivery.get("payload_hash"), reason=delivery.get("reason"),
                      delivery_ambiguous=delivery.get("delivery_ambiguous", False))
        (target / f"corrected_receipt_{stamp}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if not args.send or result["sent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
