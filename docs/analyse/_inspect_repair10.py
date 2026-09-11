import json
from pathlib import Path
from collections import Counter
from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

p = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.json")
d = json.loads(p.read_text(encoding="utf-8"))
print("generated_at", d.get("generated_at"))
print("run_status", (d.get("run") or {}).get("status"))
print("quality_gate_passed", (d.get("quality_gate") or {}).get("passed"))
print("checks", [(c.get("name"), c.get("passed")) for c in (d.get("quality_gate") or {}).get("checks") or []])
print("coverage", (d.get("coverage") or {}).get("mode"), (d.get("coverage") or {}).get("source"))
print("picks", [(x.get("code"), x.get("name"), x.get("action"), x.get("rationale")) for x in (d.get("picks") or [])])
print("rec_stocks", len((d.get("recommendations") or {}).get("stocks") or []))
print("quality", d.get("quality"))
panel = d.get("candidate_panel") or []
print("panel", len(panel), "pe", sum(1 for r in panel if r.get("pe") is not None), "price", sum(1 for r in panel if r.get("price") is not None), "chg", sum(1 for r in panel if r.get("change_pct") is not None))
print("price_volume_ev", sum(1 for r in panel for e in (r.get("evidence") or []) if e.get("factor")=="price_volume"))
rej=Counter()
for r in panel:
    for reason in r.get("rejection_reasons") or []:
        rej[reason]+=1
print("reject_top", rej.most_common(8))
print("HOTSPOTS")
bad=False
for hs in d.get("market_hotspots") or []:
    reps = hs.get("representatives") or []
    print(hs.get("theme"), hs.get("status_label"), reps, hs.get("mapping_gap"), "ev", hs.get("evidence_count"), "src", hs.get("independent_source_count"))
    if any(name in {"深圳能源","深南电A","宁德时代","东方财富","立讯精密"} and "新能源" not in str(hs.get("theme") or "") and "电池" not in str(hs.get("theme") or "") for name in reps):
        pass
    if "深圳能源" in reps or "深南电A" in reps:
        print("  BAD_POWER_IN", hs.get("theme"))
        bad=True
print("bad_power", bad)
md = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.md").read_text(encoding="utf-8")
print("md_conf", "置信" in md)
print("md_power", "深圳能源" in md, "深南电A" in md)
card = str(build_card(d))
print("card_conf", "置信" in card, "·置信" in card)
print("card_power", "深圳能源" in card, "深南电A" in card)
print("card_gap", "行业成员数据缺失" in card or "关联尚未核验" in card)
print("card_report", "报道" in card)
