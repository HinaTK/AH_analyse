"""Install tracked launchers, back up originals, verify exact bytes and state hashes."""
import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import json
import sys

sys.path.insert(0, 'D:/Code/AH_analyse')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deploy(home):
    home = Path(home)
    source = Path(__file__).parent / 'launchers'
    import holdings as H
    held = H.held_codes()
    states = [home / 'cache/grid-account' / f'confirmed-{code[-6:]}.json' for code in held]
    before = {str(path): digest(path) for path in states}
    backup = home / 'cache/confirmed-runtime-deploy' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True)
    for path in source.glob('*.py'):
        target = home / 'scripts' / path.name
        if target.exists():
            shutil.copy2(target, backup / target.name)
        shutil.copy2(path, target)
        assert target.read_bytes() == path.read_bytes(), target
    H.save_holdings_to_root(H.load_holdings_from_root(home / 'cache/grid-account'), home / 'cache/grid-account')
    after = {str(path): digest(path) for path in states}
    assert before == after, 'Authoritative state changed during deployment'
    return dict(backup=str(backup), launchers=sorted(p.name for p in source.glob('*.py')), state_hashes=after)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True)
    print(json.dumps(deploy(parser.parse_args().home), ensure_ascii=False, indent=2))
