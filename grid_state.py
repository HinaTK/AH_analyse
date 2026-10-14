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


def record(path, side, qty, price, day=None, execution_id=None, *, received_at=None,
           message_id=None, fill_item_key='0', ingestion_at=None):
    from confirmed_589720 import build
    from decimal import Decimal
    started_at = datetime.now(timezone(timedelta(hours=8)))
    supplied_day, supplied_received_at = day, received_at
    if message_id is not None and (not isinstance(message_id, str) or not message_id.strip()):
        raise ValueError('message-id不能为空')
    if not isinstance(fill_item_key, str) or not fill_item_key.strip():
        raise ValueError('fill-item-key不能为空')
    if message_id is None and fill_item_key != '0':
        raise ValueError('fill-item-key需要message-id')
    if received_at is None:
        received_at = ingestion_at or started_at.isoformat()
        date_source = 'local_ingestion_beijing'
    else:
        stamp = datetime.fromisoformat(received_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('received-at必须包含时区')
        date_source = 'received_at_beijing'
    stamp = datetime.fromisoformat(received_at)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('接收时间必须包含时区')
    if stamp > started_at:
        raise ValueError('接收时间不能在未来')
    if day is None:
        day = stamp.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    else:
        date_source = 'explicit_date'
    date.fromisoformat(day)
    if side not in ('buy', 'sell') or type(qty) is not int or qty <= 0 or not Decimal(price).is_finite() or Decimal(price) <= 0:
        raise ValueError('非法成交')
    with locked(path):
        previous = json.loads(Path(path).read_text(encoding='utf-8'))
        from confirmed_state_validation import validate_state
        validate_state(previous)
        if message_id is not None:
            matches = [t for t in previous['trades']
                       if (t.get('message_id'), t.get('fill_item_key')) == (message_id, fill_item_key)]
            if len(matches) > 1:
                raise ValueError('重复来源消息成交身份，拒绝写账')
            if matches:
                trade = matches[0]
                if ((trade['side'], trade['qty'], trade['price']) != (side, qty, price)
                        or (execution_id is not None and execution_id != trade['id'])
                        or (supplied_day is not None and day != trade['date'])
                        or (supplied_received_at is not None and
                            (received_at != trade.get('received_at') or
                             (supplied_day is None and day != trade['date'])))):
                    raise ValueError('同一来源消息成交数据冲突')
                return previous
        if execution_id is None:
            if not isinstance(message_id, str) or not message_id.strip():
                raise ValueError('自动成交ID必须提供适配器稳定message-id；人工重试可使用显式ID')
            import re
            prefix = previous['code'][-6:] + '-'
            numbers = [int(t['id'][len(prefix):]) for t in previous['trades']
                       if re.fullmatch(re.escape(prefix) + r'\d+', t['id'])]
            numbers.extend(t['sequence'] for t in previous['trades'])
            execution_id = f'{prefix}{max(numbers, default=0) + 1:03d}'
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ValueError('成交ID不能为空')
        for trade in previous['trades']:
            if trade['id'] == execution_id:
                if ((trade['side'], trade['qty'], trade['price']) != (side, qty, price)
                        or (supplied_day is not None and trade['date'] != day)
                        or (supplied_received_at is not None and
                            (trade.get('received_at') != received_at or
                             (supplied_day is None and trade['date'] != day)))
                        or (message_id is not None and
                            (trade.get('message_id'), trade.get('fill_item_key')) !=
                            (message_id, fill_item_key))):
                    raise ValueError('同一成交ID数据冲突')
                return previous
        if day > started_at.date().isoformat():
            raise ValueError('成交日期不能在未来')
        if any(t.get('date') and t['date'] > day for t in previous['trades']):
            raise ValueError('历史补录日期乱序，需独立核对')
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
        rebuilt['trades'][-1].update(id=execution_id, date=day, source='explicit_confirmed_fill',
                                    received_at=received_at, date_source=date_source)
        if message_id is not None:
            rebuilt['trades'][-1].update(message_id=message_id, fill_item_key=fill_item_key)
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
