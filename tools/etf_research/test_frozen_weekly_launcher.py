"""Regression for the Desktop runtime's preloaded tools package."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_weekly_launcher_with_preloaded_runtime_tools():
    launcher = Path(__file__).parent / 'launchers/grid_weekly_rotation.py'
    code = (
        "import sys,types,runpy;"
        "m=types.ModuleType('tools');m.__path__=['frozen/tools'];"
        "sys.modules['tools']=m;"
        f"runpy.run_path({str(launcher)!r},run_name='probe');"
        "assert sys.modules['tools'] is m"
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_frozen_launcher_uses_external_python_and_preserves_cli(tmp_path):
    launcher = Path(__file__).parent / 'launchers/grid_weekly_rotation.py'
    repo = tmp_path / 'research repo'
    package = repo / 'tools/etf_research'
    package.mkdir(parents=True)
    (repo / 'tools/__init__.py').write_text('', encoding='utf-8')
    (package / '__init__.py').write_text('', encoding='utf-8')
    (package / 'weekly.py').write_text(
        'import json,os,sys\n'
        'print(json.dumps(dict(argv=sys.argv[1:],cwd=os.getcwd(),frozen=getattr(sys,"frozen",False))))\n'
        'print("child diagnostic",file=sys.stderr)\n'
        'sys.exit(17)\n', encoding='utf-8',
    )
    env = dict(os.environ, ETF_RESEARCH_REPO=str(repo), ETF_RESEARCH_PYTHON=sys.executable)
    code = (
        'import sys,runpy;'
        'sys.frozen=True;sys.executable="not-a-python-runtime.exe";'
        'sys.modules["pandas"]=None;'
        f'sys.argv=[{str(launcher)!r},"--output-path","path with spaces","--offline"];'
        f'runpy.run_path({str(launcher)!r},run_name="__main__")'
    )
    result = subprocess.run([sys.executable, '-c', code], env=env,
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 17, result.stderr
    payload = json.loads(result.stdout)
    assert payload['frozen'] is False
    assert payload['argv'] == ['--output-path', 'path with spaces', '--offline']
    assert Path(payload['cwd']) == repo
    assert result.stderr == 'child diagnostic\n'
