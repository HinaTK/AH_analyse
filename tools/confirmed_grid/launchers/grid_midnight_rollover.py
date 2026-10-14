"""00:01 same locked authoritative state as confirmations and planners."""
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, 'D:/Code/AH_analyse')
from grid_state import rollover
from confirmed_runtime import root_from_home
import holdings as H

if __name__ == '__main__':
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    root = root_from_home()
    H.save_holdings_to_root(H.load_holdings_from_root(root), root)
    for code in H.held_codes():
        state = rollover(root / f'confirmed-{code[-6:]}.json', day)
        print(f"{code} 持有={state['qty']} 可卖={state['sellable_qty']} 最大序号={state['max_grid']} 更新日={state['sellable_updated_on']}")
