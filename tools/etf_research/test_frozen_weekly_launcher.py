"""Regression for the Desktop runtime's preloaded tools package."""
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
