"""Compatibility entry: weekly orchestration only; research owns ranking."""
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get('ETF_RESEARCH_REPO', 'D:/Code/AH_analyse'))
sys.path.insert(0, str(REPO))
# Desktop's frozen runtime already imports its own tools package. Extend its
# search path without replacing the runtime module or any of its children.
import tools
research_tools = str(REPO / 'tools')
if research_tools not in tools.__path__:
    tools.__path__ = [research_tools, *tools.__path__]
from tools.etf_research.weekly import main

if __name__ == '__main__':
    main()
