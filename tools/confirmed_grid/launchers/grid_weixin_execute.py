"""09:31 conditional advice, never automatic broker orders."""
import sys
sys.path.insert(0, 'D:/Code/AH_analyse')
from confirmed_runtime import ops_main, safe_entrypoint

if __name__ == '__main__':
    safe_entrypoint(ops_main, ['--phase', 'execute', *sys.argv[1:]])
