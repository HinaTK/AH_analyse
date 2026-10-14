"""One-time, explicit reversible quarantine; never processes trades or cron writes."""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

HOME = Path('D:/Hermes Agent CN Desktop/data/hermes-home')
REPO = Path('D:/Code/AH_analyse')
STAMP = datetime.now().strftime('%Y-%m-%d_%H%M%S')
DEST = HOME / 'archives/retired-grid' / STAMP
KEEP = {'confirmed-589720.json', 'confirmed-159363.json', 'confirmed-159992.json', 'confirmed-intraday-alerts.json'}
LAUNCHERS = {p.name for p in (REPO / 'tools/confirmed_grid/launchers').glob('*.py')}
RESEARCH = {'grid_weekly_rotation.py', 'run_rotation.py', 'grid_rotation_review.py', 'grid_intraday_bars.py'}
NAMES = {'grid_account.py', 'grid_migration.py', 'grid_runtime_guard.py', 'cleanup_unconfirmed.py', 'apply_589720.py', 'extract_fills.py', 'show_by_etf.py', 'show_589720.py', 'verify_new_logic.py'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    scripts = HOME / 'scripts'
    root = HOME / 'cache/grid-account'
    jobs = json.loads((HOME / 'cron/jobs.json').read_text(encoding='utf-8'))['jobs']
    protected = {str(p): digest(p) for p in root.iterdir() if p.is_file() and (p.name in KEEP or p.name.startswith('confirmed-') and p.suffix == '.lock')}
    protected.update({str(scripts / n): digest(scripts / n) for n in LAUNCHERS | RESEARCH})
    selected = [p for p in scripts.glob('*.py') if p.name in NAMES or p.name.startswith(('rebuild', '_book_', '_reconcile_')) or p.name.startswith('test_grid_') or p.name == 'test_tdd_589720.py']
    stems = {p.stem for p in selected}
    selected += [p for p in (scripts / '__pycache__').glob('*.pyc') if p.name.split('.')[0] in stems]
    for p in root.rglob('*'):
        if not p.is_file() or p.name in KEEP or p.suffix == '.lock':
            continue
        if p.relative_to(root).parts[0] in {'eod', 'rotation'}:
            continue
        selected.append(p)
    for filename in ('test_grid_runtime_guard.py', 'register_fills.py'):
        scratch = REPO / filename
        if scratch.exists():
            selected.append(scratch)
    for job in jobs:
        if job.get('enabled') and (job.get('script') or '').split('/')[-1] in {p.name for p in selected}:
            raise RuntimeError(f'Parent must pause/migrate cron first: {job["id"]}')
    records = []
    for p in selected:
        relative = Path('managed-home') / p.relative_to(HOME) if p.is_relative_to(HOME) else Path('repository') / p.relative_to(REPO)
        records.append(dict(source=str(p), destination=str(DEST / relative), sha256=digest(p), bytes=p.stat().st_size))
    DEST.mkdir(parents=True, exist_ok=False)
    manifest = dict(created_at=datetime.now().isoformat(), reversible=True, moves=records, protected_sha256=protected, cron=[dict(id=j['id'], script=j.get('script'), enabled=j.get('enabled')) for j in jobs])
    (DEST / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in records:
        target = Path(row['destination'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(row['source'], target)
        assert digest(target) == row['sha256'] and not Path(row['source']).exists()
    for p, sha in protected.items():
        assert digest(Path(p)) == sha, p
    report = dict(archive=str(DEST), moved=len(records), preserved=len(protected), state_sha256={p:sha for p,sha in protected.items() if Path(p).name in KEEP})
    (DEST / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
