import json
from pathlib import Path

out = Path(r'D:/Code/AH_analyse/docs/analyse/_repair8_inspect.txt')
p = Path(r'D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.json')
d = json.loads(p.read_text(encoding='utf-8'))
lines = []

def dump(title, obj, limit=4000):
    lines.append('==== ' + title + ' ====')
    if isinstance(obj, (dict, list)):
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    else:
        text = str(obj)
    lines.append(text[:limit])
    lines.append('')

panel = d.get('candidate_panel') or d.get('candidates_top') or []
lines.append('panel_type=' + type(panel).__name__ + ' len=' + (str(len(panel)) if hasattr(panel, '__len__') else 'na'))
if isinstance(panel, dict):
    dump('CANDIDATE_PANEL_KEYS', list(panel.keys())[:80])
    dump('CANDIDATE_PANEL_SAMPLE', panel, 2500)
    rows = panel.get('rows') or panel.get('candidates') or panel.get('items') or []
else:
    rows = panel
if not rows:
    rows = d.get('candidates_top') or []

pe_ok = price_ok = chg_ok = 0
pe_none = price_none = chg_none = 0
pe_neg = 0
pe_kind = {}
pe_source = {}
price_types = {}
for row in rows:
    if not isinstance(row, dict):
        continue
    pe = row.get('pe')
    price = row.get('price')
    chg = row.get('change_pct') if 'change_pct' in row else row.get('change')
    price_types[type(price).__name__] = price_types.get(type(price).__name__, 0) + 1
    if pe is None:
        pe_none += 1
    else:
        pe_ok += 1
        try:
            if float(pe) < 0:
                pe_neg += 1
        except Exception:
            pass
    if price is None or price == '':
        price_none += 1
    else:
        price_ok += 1
    if chg is None or chg == '':
        chg_none += 1
    else:
        chg_ok += 1
    pe_kind[str(row.get('pe_kind'))] = pe_kind.get(str(row.get('pe_kind')), 0) + 1
    pe_source[str(row.get('pe_source'))] = pe_source.get(str(row.get('pe_source')), 0) + 1

lines.append('panel_rows=' + str(len(rows) if hasattr(rows, '__len__') else type(rows).__name__))
lines.append('pe_ok=%s pe_none=%s pe_neg=%s' % (pe_ok, pe_none, pe_neg))
lines.append('price_ok=%s price_none=%s types=%s' % (price_ok, price_none, price_types))
lines.append('chg_ok=%s chg_none=%s' % (chg_ok, chg_none))
lines.append('pe_kind=' + json.dumps(pe_kind, ensure_ascii=False))
lines.append('pe_source=' + json.dumps(pe_source, ensure_ascii=False))

slim_rows = []
for row in (rows[:8] if isinstance(rows, list) else []):
    if not isinstance(row, dict):
        continue
    slim_rows.append({k: row.get(k) for k in ['code','name','price','change_pct','pe','pe_kind','pe_source','industry','quality_flags','reasons']})
dump('PANEL_SAMPLE', slim_rows, 4000)

picks = d.get('picks') or []
lines.append('picks_type=' + type(picks).__name__)
lines.append('picks_count=' + (str(len(picks)) if hasattr(picks, '__len__') else 'na'))
if isinstance(picks, dict):
    dump('PICKS_DICT', picks, 6000)
elif isinstance(picks, list):
    for i, pick in enumerate(picks):
        dump('PICK_'+str(i)+'_KEYS', list(pick.keys()) if isinstance(pick, dict) else type(pick).__name__)
        dump('PICK_'+str(i), pick, 5000)

recs = d.get('recommendations')
lines.append('recommendations_type=' + type(recs).__name__)
if isinstance(recs, dict):
    dump('RECS_KEYS', list(recs.keys())[:50])
    dump('RECS', recs, 4000)
elif isinstance(recs, list):
    lines.append('recommendations_count=' + str(len(recs)))
    for i, rec in enumerate(recs[:6]):
        dump('REC_'+str(i), rec, 3000)
else:
    dump('RECS', recs, 2000)

for key in ['hotspots', 'market_hotspots']:
    dump(key.upper(), d.get(key), 9000)

for key in ['research_audit', 'evidence_audit', 'quality', 'delivery', 'llm']:
    dump(key.upper(), d.get(key), 4000)

md = Path(r'D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.md').read_text(encoding='utf-8')
lines.append('==== MD ====')
lines.append(md)

out.write_text('\n'.join(lines), encoding='utf-8')
print('wrote', out, 'chars', out.stat().st_size)
print('panel_rows', len(rows) if hasattr(rows,'__len__') else type(rows).__name__, 'pe_ok', pe_ok, 'price_ok', price_ok, 'chg_ok', chg_ok)
