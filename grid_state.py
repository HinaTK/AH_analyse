"""Locked atomic confirmed-state transitions; no inferred broker fills."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import os
import tempfile
import time


@contextmanager
def locked(path):
    """OS-held lock released even on process death (Windows and POSIX)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        if os.name == 'nt':
            import msvcrt
            deadline = time.monotonic() + 30
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('状态锁超时')
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def save(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def rollover(path, day):
    date.fromisoformat(day)
    with locked(path):
        state = json.loads(Path(path).read_text(encoding='utf-8'))
        from confirmed_state_validation import validate_state
        validate_state(state, allow_uninitialized_sellable=True)
        if state.get('sellable_updated_on', '') >= day:
            return state
        qty = 0
        seen = set()
        for trade in state['trades']:
            if trade['id'] in seen or trade['side'] not in ('buy', 'sell') or type(trade['qty']) is not int or trade['qty'] <= 0:
                raise ValueError('非法或重复成交，拒绝写账')
            seen.add(trade['id'])
            qty += trade['qty'] if trade['side'] == 'buy' else -trade['qty']
            if qty < 0:
                raise ValueError('历史库存为负，拒绝写账')
        # A late midnight invocation must not settle today's confirmed buys or
        # restore inventory already sold today. Explicit dated fills suffice.
        for trade in state['trades']:
            if trade.get('date') and trade['date'] >= day and trade['side'] == 'buy':
                qty -= trade['qty']
        if qty < 0:
            raise ValueError('可卖库存为负')
        state.update(qty=sum(t['qty'] if t['side'] == 'buy' else -t['qty'] for t in state['trades']), sellable_qty=qty, sellable_updated_on=day)
        save(path, state)
        return state


def record(path, side, qty, price, day, execution_id=None):
    from confirmed_589720 import build
    from decimal import Decimal
    date.fromisoformat(day)
    if side not in ('buy', 'sell') or type(qty) is not int or qty <= 0 or not Decimal(price).is_finite() or Decimal(price) <= 0:
        raise ValueError('非法成交')
    with locked(path):
        previous = json.loads(Path(path).read_text(encoding='utf-8'))
        from confirmed_state_validation import validate_state
        validate_state(previous)
        if execution_id is None:
            raise ValueError('必须提供显式成交ID，禁止推定成交')
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ValueError('成交ID不能为空')
        for trade in previous['trades']:
            if trade['id'] == execution_id:
                if (trade['side'], trade['qty'], trade['price'], trade['date']) != (side, qty, price, day):
                    raise ValueError('同一成交ID数据冲突')
                return previous
        available = previous.get('sellable_qty')
        if type(available) is not int or not 0 <= available <= previous['qty']:
            raise ValueError('可卖份额尚未初始化或无效')
        if side == 'sell' and qty > available:
            raise ValueError('可卖库存不足')
        depth = len(previous['open_grid_positions'])
        if previous['max_grid'] != (chr(64 + depth) if depth else None):
            raise ValueError('持久化序号与交易记录不一致，拒绝覆盖')
        if previous.get('sellable_updated_on', '') > day:
            raise ValueError('历史补录需独立核对库存，拒绝倒写')
        inputs = [(t['side'], t['qty'], t['price']) for t in previous['trades']]
        rebuilt = build(inputs + [(side, qty, price)], code=previous['code'], name=previous['name'])
        mapping = {new['id']: old['id'] for old, new in zip(previous['trades'], rebuilt['trades'])}
        mapping[rebuilt['trades'][-1]['id']] = execution_id
        for old, new in zip(previous['trades'], rebuilt['trades']):
            new.update(old)
        rebuilt['trades'][-1].update(id=execution_id, date=day, source='explicit_confirmed_fill')
        for cycle in rebuilt['t_records']:
            cycle['buy_id'] = mapping[cycle['buy_id']]
            cycle['sell_id'] = mapping[cycle['sell_id']]
        # open positions reference the same rebuilt trade dictionaries.
        updated = dict(previous)
        updated.update(rebuilt)
        updated['sellable_qty'] = available - qty if side == 'sell' else available
        updated['date_status'] = '历史未知日期保留null；可卖库存使用用户初始化/午夜保存变量，银河可用与冻结另行核对'
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
    print(json.dumps({k: state[k] for k in ('code', 'qty', 'sellable_qty', 'max_grid', 'sellable_updated_on')}, ensure_ascii=False))
