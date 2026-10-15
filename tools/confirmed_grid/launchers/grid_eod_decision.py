"""Confirmed-state EOD consumer; no legacy ledger cleanup or apply."""
import sys
sys.path.insert(0, 'D:/Code/AH_analyse')
from confirmed_runtime import eod_main, safe_entrypoint

if __name__ == '__main__':
    safe_entrypoint(eod_main, True)