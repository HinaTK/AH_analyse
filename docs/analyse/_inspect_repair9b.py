import json
from pathlib import Path
p = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.json")
d = json.loads(p.read_text(encoding="utf-8"))
print("=== HOTSPOTS RAW ===")
for hs in d.get("hotspots") or []:
    print(json.dumps({k: hs.get(k) for k in ["theme","industries","representatives","mapping_gap","mapped_count","status","evidence_count","independent_source_count","drivers"]}, ensure_ascii=False, indent=2))
    print("---")
print("=== MD HOTSPOT SECTION ===")
md = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.md").read_text(encoding="utf-8")
start = md.find("## 市场热点")
end = md.find("**消息热点")
print(md[start:end] if start>=0 else md[:2000])
print("=== FEISHU TEXT CHECK ===")
from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
card = build_card(d)
text = str(card)
print("has_conf", "置信" in text)
print("has_90", "置信90" in text or "·置信" in text)
for needle in ["深圳能源","深南电A","行业成员数据缺失","报道","独立"]:
    print(needle, needle in text)
# print hotspot lines from card if possible
