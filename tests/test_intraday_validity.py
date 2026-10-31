"""盘中提醒有效性：成交后生成的新建议，只有生成之后的触碰才算有效。

用户规则 2026-10-26: 我说成交之后，价格涨跌到触价才有效。
背景事故：10-23/10-26 买F成交后生成"卖F@0.809"，但早晨高点0.821是
建议生成前的旧日内极值，旧 monitor() 拿全日极值比对触发价导致误报。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import confirmed_runtime as runtime


def _ticket(*actions):
    return dict(actions=[
        dict(code='sh589720', side=side, price=price, qty=qty, lot=lot)
        for side, price, qty, lot in actions
    ])


def _quotes(last, high=None, low=None, t='20261026110000'):
    q = dict(last=last, time=t)
    if high is not None:
        q['high'] = high
    if low is not None:
        q['low'] = low
    return {'sh589720': q}


def test_morning_extreme_does_not_validate_advice_born_mid_session():
    """10-26 实际事故复现：10:38 买F成交后生成"卖F@0.809"，
    日内高点0.821是建议生成前的旧极值，不得触发提醒。"""
    ticket = _ticket(('sell', '0.809', 10000, 'F'))
    state = {}
    assert runtime.monitor(ticket, _quotes('0.798', high='0.821', low='0.796'), state, '2026-10-26') == ''


def test_new_extreme_after_birth_is_valid_touch():
    ticket = _ticket(('sell', '0.809', 10000, 'F'))
    state = {}
    runtime.monitor(ticket, _quotes('0.798', high='0.821', low='0.796'), state, '2026-10-26')
    # 高点越过基准0.821 → 生成后的新触碰，有效
    msg = runtime.monitor(ticket, _quotes('0.798', high='0.825', low='0.796'), state, '2026-10-26')
    assert '触价不等于成交' in msg
    # 同一触碰去重
    assert runtime.monitor(ticket, _quotes('0.798', high='0.825', low='0.796'), state, '2026-10-26') == ''


def test_current_price_touch_on_first_sighting_is_valid():
    """首见时现价已触价：触碰发生在当下，必然晚于建议生成，有效。"""
    ticket = _ticket(('sell', '0.809', 10000, 'F'))
    state = {}
    msg = runtime.monitor(ticket, _quotes('0.812', high='0.821', low='0.796'), state, '2026-10-26')
    assert '触价不等于成交' in msg


def test_reborn_advice_after_absence_gets_fresh_window():
    """卖E@0.821早晨触发过→成交→建议消失→09:56接回E后同价建议重生：
    重生后的新触碰应再次提醒（旧代码按天+价位去重会吞掉）。"""
    ticket = _ticket(('sell', '0.821', 9800, 'E'))
    state = {}
    assert runtime.monitor(ticket, _quotes('0.825', high='0.825', low='0.810'), state, '2026-10-26')
    # 成交后建议消失一轮（清理）
    runtime.monitor(dict(actions=[]), _quotes('0.825'), state, '2026-10-26')
    # 重生：现价0.815未触价，不报
    assert runtime.monitor(ticket, _quotes('0.815', high='0.825', low='0.812'), state, '2026-10-26') == ''
    # 重生后现价触价：再报
    msg = runtime.monitor(ticket, _quotes('0.822', high='0.825', low='0.812'), state, '2026-10-26')
    assert '触价不等于成交' in msg


def test_buy_side_new_low_after_birth_is_valid():
    ticket = _ticket(('buy', '0.797', 10000, 'F'))
    state = {}
    # 首见：现价0.809未触及0.797；日内低点0.805记为基准
    assert runtime.monitor(ticket, _quotes('0.809', high='0.818', low='0.805'), state, '2026-10-26') == ''
    # 新低0.794越过基准且触及触发价 → 有效
    msg = runtime.monitor(ticket, _quotes('0.799', high='0.818', low='0.794'), state, '2026-10-26')
    assert '触价不等于成交' in msg
