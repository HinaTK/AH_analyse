import json
from pathlib import Path
from collections import Counter

p = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.json")
d = json.loads(p.read_text(encoding="utf-8"))
out = Path(r"D:/Code/AH_analyse/docs/analyse/_audit_repair10.txt")
lines = []
def w(s=""):
    lines.append(str(s))

w("generated_at=" + str(d.get("generated_at")))
w("as_of=" + str(d.get("as_of")))
w("run=" + json.dumps(d.get("run"), ensure_ascii=False, indent=2)[:2000])
w("quality_gate=" + json.dumps(d.get("quality_gate"), ensure_ascii=False, indent=2))
w("quality=" + json.dumps(d.get("quality"), ensure_ascii=False))
w("coverage_mode=" + str((d.get("coverage") or {}).get("mode")))
w("coverage_source=" + str((d.get("coverage") or {}).get("source")))
w("picks_count=" + str(len(d.get("picks") or [])))
w("rec_stocks=" + str(len((d.get("recommendations") or {}).get("stocks") or [])))

panel = d.get("candidate_panel") or []
w("panel=" + str(len(panel)))
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
w("pe_ok=%s price_ok=%s chg_ok=%s price_volume_ev=%s" % (pe_ok, price_ok, chg_ok, amount_ev))
w("reject_top=" + json.dumps(rej.most_common(12), ensure_ascii=False))

w("\n=== PICKS ===")
for pick in d.get("picks") or []:
    w(json.dumps({
        "code": pick.get("code"),
        "name": pick.get("name"),
        "action": pick.get("action"),
        "rationale": pick.get("rationale"),
        "evidence": [e.get("statement") for e in (pick.get("evidence") or [])],
        "rejection_reasons": pick.get("rejection_reasons"),
        "score": pick.get("score") or pick.get("composite"),
    }, ensure_ascii=False, indent=2))

w("\n=== HOTSPOTS ===")
for hs in d.get("hotspots") or []:
    w(json.dumps({
        "theme": hs.get("theme"),
        "industries": hs.get("industries"),
        "representatives": hs.get("representatives"),
        "mapping_gap": hs.get("mapping_gap"),
        "mapped_count": hs.get("mapped_count"),
        "status": hs.get("status"),
        "evidence_count": hs.get("evidence_count"),
        "independent_source_count": hs.get("independent_source_count"),
        "drivers": hs.get("drivers"),
    }, ensure_ascii=False, indent=2))
    w("---")

w("\n=== MARKET_HOTSPOTS ===")
for hs in d.get("market_hotspots") or []:
    w(json.dumps({
        "theme": hs.get("theme"),
        "status_label": hs.get("status_label"),
        "evidence_grade": hs.get("evidence_grade"),
        "representatives": hs.get("representatives"),
        "mapping_gap": hs.get("mapping_gap"),
        "evidence_count": hs.get("evidence_count"),
        "independent_source_count": hs.get("independent_source_count"),
        "industries": hs.get("industries"),
    }, ensure_ascii=False, indent=2))

md = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.md").read_text(encoding="utf-8")
w("\n=== MD ===")
w(md)

out.write_text("\n".join(lines), encoding="utf-8")
print("wrote", out, "chars", out.stat().st_size)
