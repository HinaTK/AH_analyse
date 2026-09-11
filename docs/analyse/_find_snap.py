from pathlib import Path
import json
# look for parquet snapshots
roots = [Path(r'D:/Code/AH_analyse/ah_recommendation_system/backend/data'), Path(r'D:/Code/AH_analyse/data')]
for root in roots:
    if not root.exists():
        continue
    for p in root.rglob('*'):
        if p.suffix.lower() in {'.parquet', '.pkl'} or 'snapshot' in p.name.lower():
            print(p, p.stat().st_size, p.stat().st_mtime)
