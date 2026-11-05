"""DSH-only intraday gate observer. External wrapper owns push and scheduling."""
import os
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
os.environ.setdefault('HERMES_HOME', str(REPOSITORY / '.cache/grid-home'))

from tools.intraday_gate_watch import main


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
