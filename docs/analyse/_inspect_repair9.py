import json
from pathlib import Path
from collections import Counter

p = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.json")
d = json.loads(p.read_text(encoding="utf-8"))
print("generated_at", d.get("generated_at"))
print("run", json.dumps(d.get("run"), ensure_ascii=False)[:1200])
print("quality_gate", json.dumps(d.get("quality_gate"), ensure_ascii=False))
print("data_status", d.get("data_status"))
print("coverage_mode", (d.get("coverage") or {}).get("mode"), (d.get("coverage") or {}).get("source"), (d.get("coverage") or {}).get("label"))
print("picks", len(d.get("picks") or []))
print("rec_stocks", len((d.get("recommendations") or {}).get("stocks") or []))
print("quality", d.get("quality"))

panel = d.get("candidate_panel") or []
pe_ok = sum(1 for r in panel if r.get("pe") is not None)
price_ok = sum(1 for r in panel if r.get("price") is not None)
chg_ok = sum(1 for r in panel if r.get("change_pct") is not None)
amount_ev = 0
rej = Counter()
for r in panel:
    for reason in r.get("rejection_reasons") or []:
        rej[reason] += 1
    for ev in r.get("evidence") or []:
        if ev.get("factor") == "price_volume":
            amount_ev += 1
print("panel", len(panel), "pe", pe_ok, "price", price_ok, "chg", chg_ok, "price_volume_ev", amount_ev)
print("reject_top", rej.most_common(12))
print("picks_detail")
for pick in d.get("picks") or []:
    print({k: pick.get(k) for k in ["code","name","action","score","composite","rationale"]})
    ev = [e.get("statement") for e in (pick.get("evidence") or [])]
    print(" evidence", ev)
print("hotspots")
for hs in d.get("market_hotspots") or []:
    print(hs.get("theme"), hs.get("status_label"), hs.get("representatives"), hs.get("mapping_gap"), "ev", hs.get("evidence_count"), "src", hs.get("independent_source_count"), hs.get("evidence_grade"))
print("md_has_confidence", "置信" in Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.md").read_text(encoding="utf-8"))
