import json
from pathlib import Path

p = Path(r'D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/recommend_20260911.json')
d = json.loads(p.read_text(encoding='utf-8'))
rows = d.get('candidate_panel') or []
keys = set()
for row in rows:
    keys.update(row.keys())
print('panel_keys', sorted(keys))

amount_none = 0
volume_none = 0
amount_vals = []
for row in rows:
    a = row.get('amount') if 'amount' in row else row.get('turnover')
    v = row.get('volume') if 'volume' in row else row.get('vol')
    if a is None or a == '':
        amount_none += 1
    else:
        amount_vals.append((row.get('code'), row.get('name'), a, type(a).__name__))
    if v is None or v == '':
        volume_none += 1
print('amount_none', amount_none, 'volume_none', volume_none, 'amount_present', len(amount_vals))
print('amount_sample', amount_vals[:8])
print('first_row_amount_related')
row0 = rows[0]
for k,v in row0.items():
    lk = k.lower()
    if any(x in lk for x in ['amt','amount','turn','vol','money','value','quality','reject']):
        print(k, '=', v)

print('\n=== quality sample from candidates_top ===')
top = d.get('candidates_top') or []
print('top_type', type(top).__name__, 'len', len(top) if hasattr(top,'__len__') else None)
if isinstance(top, list) and top:
    print('top0_keys', sorted(top[0].keys()) if isinstance(top[0], dict) else type(top[0]))
    for row in top[:5]:
        print({k: row.get(k) for k in ['code','name','amount','volume','turnover','quality_flags','reject_reasons','rejection_reason','score','pe','price']})

obs = d.get('observation_pool') or d.get('internal_observation_pool')
print('\nobs_type', type(obs).__name__)
if isinstance(obs, list):
    print('obs_len', len(obs))
    if obs:
        print('obs0_keys', list(obs[0].keys()) if isinstance(obs[0], dict) else obs[0])
        print(json.dumps(obs[:3], ensure_ascii=False)[:2000])
elif isinstance(obs, dict):
    print('obs_keys', list(obs.keys())[:20])
