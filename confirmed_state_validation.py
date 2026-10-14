"""Read-only authoritative replay validation shared by readers and writers."""
from decimal import Decimal

from confirmed_589720 import build


def validate_state(state, *, allow_uninitialized_sellable=False):
    """Reject inconsistent saved state without repairing records or metadata."""
    try:
        trades = state['trades']
        ids = set()
        for trade in trades:
            ident = trade['id']
            if not isinstance(ident, str) or not ident.strip() or ident in ids:
                raise ValueError('非法或重复成交ID')
            ids.add(ident)
            if (trade['side'] not in ('buy', 'sell') or
                    type(trade['qty']) is not int or trade['qty'] <= 0 or
                    not Decimal(trade['price']).is_finite() or Decimal(trade['price']) <= 0):
                raise ValueError('非法成交')
        rebuilt = build([(t['side'], t['qty'], t['price']) for t in trades],
                        code=state['code'], name=state['name'])
        if type(state['qty']) is not int:
            raise ValueError('保存的总份额无效')
        for key in ('qty', 'max_grid', 'net_invested', 'net_unit_cost', 't_net',
                    'remaining_buy_cost', 'remaining_unit_cost'):
            if state[key] != rebuilt[key]:
                raise ValueError('已保存状态与成交记录不一致：' + key)
        mapping = {}
        for stored, derived in zip(trades, rebuilt['trades']):
            if any(stored[key] != derived[key] for key in
                   ('code', 'lot', 'sequence', 'side', 'qty', 'price', 'fee', 'amount')):
                raise ValueError('保存成交标签/金额与权威重放不一致')
            mapping[derived['id']] = stored['id']
        for cycle in rebuilt['t_records']:
            cycle['buy_id'] = mapping[cycle['buy_id']]
            cycle['sell_id'] = mapping[cycle['sell_id']]
        if state['t_records'] != rebuilt['t_records']:
            raise ValueError('经济周期成交ID链接不一致')
        fields = ('id', 'lot', 'qty', 'price')
        expected_open = [(mapping[t['id']], t['lot'], t['qty'], t['price'])
                         for t in rebuilt['open_grid_positions']]
        if [tuple(t[key] for key in fields) for t in state['open_grid_positions']] != expected_open:
            raise ValueError('经济网格持仓与成交记录不一致')
        available = state['sellable_qty']
        if not (allow_uninitialized_sellable and available is None):
            if type(available) is not int or not 0 <= available <= rebuilt['qty']:
                raise ValueError('可卖份额尚未初始化或无效')
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise ValueError('已保存状态格式无效') from exc
