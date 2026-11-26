"""Confirmed-state EOD consumer + post-close regime cache precompute (merged 15:20+15:30)."""
import os
import sys

SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'
_IS_312 = sys.version_info[:2] == (3, 12) and 'Programs' in sys.executable

if __name__ == '__main__' and not _IS_312:
    import subprocess
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(subprocess.call([SYSTEM_PY, os.path.abspath(__file__)] + sys.argv[1:]))

sys.path.insert(0, 'D:/Code/AH_analyse')
from confirmed_runtime import eod_with_cache_main, safe_entrypoint

if __name__ == '__main__':
    safe_entrypoint(eod_with_cache_main, True)