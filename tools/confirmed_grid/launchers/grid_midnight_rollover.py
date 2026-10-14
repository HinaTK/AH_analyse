"""00:01 same locked authoritative state as confirmations and planners."""
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, 'D:/Code/AH_analyse')
from grid_state import rollover
from confirmed_runtime import CODES, root_from_home

if __name__ == '__main__':
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    for code in CODES:
        state = rollover(root_from_home() / f'confirmed-{code[-6:]}.json', day)
        print(f"{code} 持有={state['qty']} 可卖={state['sellable_qty']} 最大序号={state['max_grid']} 更新日={state['sellable_updated_on']}")
