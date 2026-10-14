"""Deployed intraday monitor: confirmed states only."""
import sys
sys.path.insert(0, 'D:/Code/AH_analyse')
from confirmed_runtime import intraday_main, safe_entrypoint

if __name__ == '__main__':
    safe_entrypoint(intraday_main)
