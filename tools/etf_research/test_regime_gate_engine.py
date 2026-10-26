# -*- coding: utf-8 -*-
"""regime_gate=True 时门控必须真实生效的回归测试。

2026-10-27 bug：engine 用裁剪后的 63 日窗口算 blocked_buy_days，
判定需 >=65 根日线历史 → 63<65 全部 fail-open，门控版与无门控版
结果逐字节相同（全池 d_cycles 全 0）。生产路径用未裁剪全历史是对的；
回测必须同样给 blocked_buy_days 全历史，只对"窗口内日期"下判定。
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
# tools/ 顶层目录 (market_phase_check 所在) 必须进 sys.path——
# 否则 blocked_buy_days 的 ADX 分支 fail-open, 单跑/全量行为分叉
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from tools.etf_research import gate_check  # noqa: E402


def _m5(closes, cal, hours=None):
    hours = hours or ['09:35', '10:00', '14:55', '15:00']
    rows = []
    for day, close in zip(cal, closes):
        hi, lo = round(close * 1.004, 4), round(close * 0.996, 4)
        for h in hours:
            last = h == hours[-1]
            rows.append(dict(time=f'{day} {h}:00', open=lo, high=hi, low=lo,
                             close=(close if last else lo), volume=1e8))
    return pd.DataFrame(rows)


def test_blocked_buy_days_accepts_history_and_window():
    """full-history frame + 63 日窗口：窗口尾部日期的判定必须基于全历史。

    构造: 150 根日线 (含 60 根窗口前历史 + 90 根窗口内)，
    全破发生在窗口中段 → 窗口内后续日必须被拦。
    若实现只用窗口内 63 根 → 不足 65 → fail-open 全 False → 测试挂。
    """
    # 全历史: 长横盘 → 急跌全破 (发生在总长度的第 80 天, 窗口中段)
    stable = [10.0] * 80
    crash = [9.0, 8.8, 8.6, 8.4, 8.2, 8.0, 7.8, 7.6]
    recover = [7.7, 7.9, 8.1, 8.3, 8.5, 8.7, 9.0,
               9.2, 9.4, 9.6, 9.8, 10.0, 10.2, 10.4, 10.6, 10.8, 11.0,
               11.2, 11.4, 11.6, 11.8, 12.0]
    closes = stable + crash + recover
    cal = pd.bdate_range('2026-01-05', periods=len(closes)).strftime('%Y-%m-%d').tolist()
    full_frame = _m5(closes, cal)

    # 模拟 engine 的窗口裁剪: 窗口=最后 63 日
    window_days = set(cal[-63:])
    windowed_frame = full_frame[full_frame.time.str[:10].isin(window_days)].reset_index(drop=True)

    # 正确实现: 拿全历史判定, 只输出窗口内日期
    blocked = gate_check.blocked_buy_days(full_frame)
    in_window_blocked = {d: v for d, v in blocked.items() if d in window_days}

    # 全破起点在窗口内 → 次日起必须有拦截日 (不是全 False)
    crash_day = cal[80]
    assert crash_day in window_days, '夹具: 全破起点须落在窗口内'
    assert any(in_window_blocked.values()), (
        '窗口内日期的判定基于全历史——若此处全 False，说明实现只吃了窗口数据，'
        '63<65 会 fail-open，门控形同虚设（2026-10-27 bug 回归）')

    # 错误实现 (引擎旧 bug): 只喂窗口数据 → 应全 False (证明 bug 真实存在)
    blocked_windowed_only = gate_check.blocked_buy_days(windowed_frame)
    assert not any(list(blocked_windowed_only.values())[:63]), '63 根窗口数据本身判不了——这正是 bug'


def test_engine_regime_gate_changes_results(tmp_path, monkeypatch):
    """simulate 层面: gated vs ungated 必须有差异。

    夹具教训: 合成数据容易"被拦日无买入信号"——被拦日价格恰在反弹段,
    target 未被触发, 门控拦了个寂寞。用实证受影响的真实形态构造:
    长横盘 → 深跌(全破+买入信号密集) → 修复。
    """
    from tools.etf_research.grid_model import simulate

    # 长横盘后深跌: 跌破全部均线(触发 gate), 且连续下跌每天刷新 target
    # (确保被拦日有真实买入信号被拦掉)
    stable = [10.0] * 80
    # 12 根阶梯下跌 (每根 -2.2% > gap 1.5%, 每天都产生新买入信号)
    crash = []
    p = 10.0
    for _ in range(12):
        p = round(p * 0.978, 4)
        crash.append(p)
    # 15 根持续反弹 (DMI 翻转+站回均线后解除)
    recover = []
    for i in range(15):
        p = round(p * 1.025, 4)
        recover.append(p)
    closes = stable + crash + recover
    cal = pd.bdate_range('2026-01-05', periods=len(closes)).strftime('%Y-%m-%d').tolist()
    full_frame = _m5(closes, cal)

    gate = gate_check.blocked_buy_days(full_frame)
    assert any(gate.values()), '夹具应产生被拦日'

    base = simulate(full_frame, gap=0.015, lot_budget=6000)
    gated = simulate(full_frame, gap=0.015, lot_budget=6000, gate_days=gate)
    assert gated != base, '门控必须改变结果——否则引擎接线无效 (2026-10-27 bug 回归)'
    # 注意: 不比较 end_cost —— 被拦买入顺延到反弹段后接回等价货,
    # 成本近似相同 (浮点尾差可正可负), 语义约束只有"结果发生改变"。
