"""Install thin launchers only; never change ledger, orders or research results."""
import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path


def deploy(home, repo):
    home, repo = Path(home), Path(repo)
    launchers = repo / 'tools/etf_research/launchers'
    targets = {
        'grid_weekly_rotation.py': home / 'scripts/grid_weekly_rotation.py',
        'run_rotation.py': home / 'scripts/run_rotation.py',
        'research.py': home / 'cache/grid-third-20260930/research.py',
    }
    # Validate all sources before making any writes.
    payloads = {name: (launchers / name).read_bytes() for name in targets}
    for name, payload in payloads.items():
        compile(payload, name, 'exec')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = home / 'cache/research-unification/backups' / stamp
    backup.mkdir(parents=True, exist_ok=False)
    result = {}
    for name, target in targets.items():
        if target.exists():
            shutil.copy2(target, backup / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix('.tmp')
        temp.write_bytes(payloads[name])
        temp.replace(target)
        expected = hashlib.sha256(payloads[name]).hexdigest()
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f'launcher verification failed: {target}')
        result[str(target)] = actual
    return {'backup': str(backup), 'targets': result}


if __name__ == '__main__':
    import json
    repo = Path(__file__).resolve().parents[2]
    home = os.environ.get('HERMES_HOME', 'D:/Hermes Agent CN Desktop/data/hermes-home')
    print(json.dumps(deploy(home, repo), ensure_ascii=False, indent=2))
