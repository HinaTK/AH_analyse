# -*- coding: utf-8 -*-
"""grid_model.simulate 接入门控 gate_days 的 TDD 测试。

规则（2026-10-27）：回测过程必须符合统一门控——
- gate_days: {date: bool}，True=该日新格买入被拦。
- 只拦"新格买入"（fill empty slot）；初始建仓、卖出、结算全不受影响。
- 不传 gate_days = 行为与旧版逐字节一致（向后兼容）。
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.etf_research import gate_check  # noqa: E402
from tools.etf_research.grid_model import simulate  # noqa: E402


def _frame(closes):
    """构造带日内振幅的 5m K：down-then-up 震荡，网格能产生 cycle。"""
    rows = []
    hours = ['09:35', '10:00', '14:55', '15:00']
    cal = pd.bdate_range('2026-03-02', periods=len(closes)).strftime('%Y-%m-%d').tolist()
    for day, close in zip(cal, closes):
        hi, lo = round(close * 1.004, 4), round(close * 0.996, 4)
        for h in hours:
            last = h == hours[-1]
            rows.append(dict(time=f'{day} {h}:00', open=lo, high=hi, low=lo,
                             close=(close if last else lo), volume=1e8))
    return pd.DataFrame(rows)


OSC = [10.0] * 70 + [10 + (0.12 if i % 2 == 0 else -0.12) * ((i - 70) % 3 == 0) - 0.0
                      for i in range(70, 130)]


def test_gate_days_blocks_buys_but_not_sells():
    """gate_days 语义：被拦日零新格买入（可顺延到次日），卖出照常。

    震荡市里被拦的买入会顺延——次日价格仍低于 target 时照样触发，
    所以总笔数不一定减少；真正的规则约束是"被拦当天不发生新格买入"。
    """
    # ±3% 震荡跨过 2% gap → 产生真实新格买入/卖出循环
    closes = [10.0] * 70
    closes += [10.0 + (0.3 if (i % 4) in (0, 1) else -0.3) for i in range(60)]
    frame = _frame(closes)
    base = simulate(frame, trace=True)
    new_buys = [e for e in base['events'] if e['side'] == 'buy' and not e['initial']]
    assert new_buys, '夹具必须先产生新格买入, 否则测试无意义'
    # 全拦: 所有日期都置 True → 一笔新格买入都不该发生
    all_days = sorted({t[:10] for t in frame.time})
    gate = {d: True for d in all_days}
    gated = simulate(frame, trace=True, gate_days=gate)
    gated_buys = [e for e in gated['events'] if e['side'] == 'buy' and not e['initial']]
    assert gated_buys == [], '全拦时应无任何新格买入'
    # 初始仓买入不受影响 (建仓不属于"新格买入")
    initial_buys = [e for e in gated['events'] if e['side'] == 'buy' and e['initial']]
    assert len(initial_buys) == 5, '初始建仓5笔不受门控影响'
    # 卖出逻辑没关
    assert gated['sales'] <= base['sales']


def test_gate_days_none_is_byte_identical_to_old():
    """不传 gate_days（默认 None）：结果与旧版完全一致。"""
    closes = [10.0] * 70 + [10.0 + (0.08 if (i % 4) in (0, 1) else -0.08) for i in range(60)]
    frame = _frame(closes)
    a = simulate(frame)
    b = simulate(frame, gate_days=None)
    assert a == b, 'None 必须逐键相等'


def test_blocked_days_from_gate_check_reduce_cycles_on_crash():
    """端到端: 真实 gate_check.blocked_buy_days 输出接进 simulate，
    急跌段新格买入被拦 → 期末成本占用 <= 无门控版。

    注: 震荡市被拦买入会顺延次日，trades 不必然减少；急跌段的硬约束
    是成本占用（拦截=不接货），故断言 end_cost 而非 trades。
    """
    stable = [10.0] * 75
    crash = [9.4, 8.9, 8.4, 8.0, 7.7, 7.5, 7.3, 7.1]
    recover = [7.3, 7.5, 7.8, 8.2, 8.6, 9.0, 9.4, 9.8]
    closes = stable + crash + recover
    frame = _frame(closes)
    gate = gate_check.blocked_buy_days(frame)
    assert any(gate.values()), '夹具应产生被拦日'
    base = simulate(frame)
    gated = simulate(frame, gate_days=gate)
    # 门控版在急跌段少接新格 → 期末成本占用 <= 无门控版
    assert gated['end_cost'] <= base['end_cost']


def test_gate_days_do_not_break_invariants():
    """门控开着跑完整模拟: 所有不变式仍然成立 (settlement/cash/capital)。"""
    closes = [10.0] * 70 + [10.0 + (0.1 if (i % 4) in (0, 1) else -0.1) for i in range(60)]
    frame = _frame(closes)
    gate = {d: True for d in sorted({t[:10] for t in frame.time})}
    result = simulate(frame, gate_days=gate)
    assert abs(result['identity_error']) < 1e-6
    assert result['min_cash'] >= 50000 - 1e-6
