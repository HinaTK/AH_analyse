"""Compatibility entry: weekly orchestration only; research owns ranking."""
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get('ETF_RESEARCH_REPO', 'D:/Code/AH_analyse'))
sys.path.insert(0, str(REPO))
from tools.etf_research.weekly import main

if __name__ == '__main__':
    main()
