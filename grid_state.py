"""Persist confirmed ETF state; midnight sync does not invent transactions."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import os


def save(path, state):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def rollover(path, day):
    path = Path(path)
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('sellable_updated_on') == day:
        return state
    qty = 0
    seen = set()
    for trade in state['trades']:
        if trade['id'] in seen or trade['side'] not in ('buy', 'sell') or trade['qty'] <= 0:
            raise ValueError('非法或重复成交，拒绝写账')
        seen.add(trade['id'])
        qty += trade['qty'] if trade['side'] == 'buy' else -trade['qty']
        if qty < 0:
            raise ValueError('历史库存为负，拒绝写账')
    state.update(qty=qty, sellable_qty=qty, sellable_updated_on=day)
    save(path, state)
    return state


def record(path, side, qty, price, day):
    from confirmed_589720 import build
    path = Path(path)
    previous = json.loads(path.read_text(encoding='utf-8'))
    available = previous.get('sellable_qty')
    if not isinstance(available, int):
        raise ValueError('可卖份额尚未初始化')
    if side == 'sell' and qty > available:
        raise ValueError('可卖库存不足')
    depth = len(previous['open_grid_positions'])
    expected = chr(64 + depth) if depth else None
    if previous['max_grid'] != expected:
        raise ValueError('持久化序号与交易记录不一致，拒绝覆盖')
    grid = chr(ord(previous['max_grid']) + 1) if side == 'buy' and previous['max_grid'] else ('A' if side == 'buy' else previous['max_grid'])
    inputs = [(t['side'], t['qty'], t['price']) for t in previous['trades']]
    updated = build(inputs + [(side, qty, price)], code=previous['code'], name=previous['name'])
    if updated['trades'][-1]['lot'] != grid:
        raise ValueError('序号生成不一致')
    for old, new in zip(previous['trades'], updated['trades']):
        new.update(old)
    updated['trades'][-1]['date'] = day
    updated['sellable_qty'] = available - qty if side == 'sell' else available
    if 'sellable_updated_on' in previous:
        updated['sellable_updated_on'] = previous['sellable_updated_on']
    save(path, updated)
    return updated


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    args = parser.parse_args()
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    state = rollover(args.state, day)
    print(json.dumps({k: state[k] for k in ('code','qty','sellable_qty','max_grid','sellable_updated_on')}, ensure_ascii=False))
