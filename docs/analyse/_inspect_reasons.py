import json
from pathlib import Path
from collections import Counter
p=Path(r'D:/Code/AH_analyse/docs/analyse/run-monitor-20260911-092524-repair8/result.json')
d=json.loads(p.read_text(encoding='utf-8'))
reasons=Counter()
for row in d.get('candidate_panel') or []:
    rs=row.get('rejection_reasons') or []
    print(row.get('code'), row.get('name'), rs)
    for rsn in rs:
        reasons[rsn]+=1
print('---counts---')
for k,v in reasons.most_common():
    print(v, k)
print('quality_block', d.get('quality'))
print('obs', [(x.get('code'), x.get('name'), x.get('rejection_reasons')) for x in (d.get('observation_pool') or [])])
