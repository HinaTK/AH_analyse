import json
from pathlib import Path
from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

d = json.loads(Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.json").read_text(encoding="utf-8"))
card = build_card(d)
text = json.dumps(card, ensure_ascii=False)
Path(r"D:/Code/AH_analyse/docs/analyse/_audit_feishu.txt").write_text(text, encoding="utf-8")
print("len", len(text))
for needle in ["置信", "·置信", "报道", "独立", "未知", "行业成员数据缺失", "关联尚未核验", "深圳能源", "深南电A", "宁德时代", "东方财富", "立讯精密", "宁波银行", "招商银行", "长电科技", "韦尔股份", "盾安环境", "中国船舶"]:
    print(needle, needle in text)
