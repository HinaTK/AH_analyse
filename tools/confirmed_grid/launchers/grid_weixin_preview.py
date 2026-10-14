"""09:10 read-only conditional preview."""
import sys
sys.path.insert(0, 'D:/Code/AH_analyse')
from confirmed_runtime import ops_main, safe_entrypoint

if __name__ == '__main__':
    safe_entrypoint(ops_main, ['--phase', 'preview', *sys.argv[1:]])
