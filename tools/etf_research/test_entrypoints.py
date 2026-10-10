"""The managed compatibility launchers must delegate, not rank again."""
import ast
from pathlib import Path


def test_compatibility_launchers_have_no_second_model():
    folder = Path(__file__).parent / 'launchers'
    for filename in ('grid_weekly_rotation.py', 'run_rotation.py', 'research.py'):
        path = folder / filename
        assert path.exists(), f'missing managed launcher: {filename}'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        assert not any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(tree))
        source = path.read_text(encoding='utf-8')
        assert 'simulate_daily_grid' not in source
        assert 'tools.etf_research' in source


def test_deployment_backs_up_launchers_and_preserves_ledger(tmp_path):
    from tools.etf_research.deploy_launchers import deploy
    home = tmp_path / 'home'
    home.mkdir()
    scripts = home / 'scripts'
    scripts.mkdir()
    old = scripts / 'grid_weekly_rotation.py'
    old.write_text('# previous script', encoding='utf-8')
    ledger = home / 'cache/grid-account/ledger.json'
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"cash": 123}', encoding='utf-8')
    repo = Path(__file__).resolve().parents[2]
    report = deploy(home, repo)
    assert (Path(report['backup']) / 'grid_weekly_rotation.py').read_text(encoding='utf-8') == '# previous script'
    assert ledger.read_text(encoding='utf-8') == '{"cash": 123}'
    assert len(report['targets']) == 3
