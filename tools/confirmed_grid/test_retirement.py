"""Managed-home retirement regression: historical state is not a live fallback."""
import ast
import os
from pathlib import Path

HOME = Path(os.environ.get('HERMES_HOME', 'D:/Hermes Agent CN Desktop/data/hermes-home'))
LEGACY = ('grid_account', 'grid_migration', 'grid_runtime_guard')


def test_managed_home_has_no_legacy_live_fallback():
    scripts = HOME / 'scripts'
    root = HOME / 'cache/grid-account'
    assert not any((scripts / f'{name}.py').exists() for name in LEGACY)
    assert not list(root.glob('ledger*'))
    assert not list(root.glob('migration*'))
    assert not list((root / 'tickets').glob('*'))
    for filename in ('confirmed-589720.json', 'confirmed-159363.json', 'confirmed-159992.json', 'confirmed-intraday-alerts.json'):
        assert (root / filename).is_file()
    assert not [p for p in root.glob('confirmed*') if any(s in p.name for s in ('before', 'previous', '.bak'))]
    for path in scripts.glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or '')
        assert not set(imports).intersection(LEGACY), path
