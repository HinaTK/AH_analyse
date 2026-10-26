# -*- coding: utf-8 -*-
"""gate_check.blocked_buy_days 的 TDD 测试——统一门控接入回测引擎。

生产规则（confirmed_runtime.RegimeGate → gate_check.gate）要求：
- 每个交易日 D 的买入建议，由截至 D-1 收盘的日线判定（盘前只知昨日）。
- 拦五线全破（level=no_entry）；拦 ADX>=25 且收盘<ma60（pause_buy）；
  probe_only/normal 不拦。
- 回测里同样的口径 = 对 5 分钟 K 线按日聚合，逐日用"截至昨日"窗口判定。
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
# tools/ 顶层目录 (market_phase_check 所在) 必须进 sys.path——
# 否则 blocked_buy_days 的 ADX 分支 fail-open, 单跑/全量行为分叉
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from tools.etf_research import gate_check  # noqa: E402


def m5_frame(daily_closes, hours=None):
    """由日收盘序列构造 5 分钟 K：日内有真实振幅（high/low ±0.4%），
    收盘价放在最后一根——保证 ATR>0，与真实 ETF 结构一致。"""
    hours = hours or ['09:35', '10:00', '14:55', '15:00']
    rows = []
    for day, close in daily_closes:
        hi, lo = round(close * 1.004, 4), round(close * 0.996, 4)
        for h in hours:
            is_last = h == hours[-1]
            p = close if is_last else lo
            rows.append(dict(time=f'{day} {h}:00', open=lo, high=hi, low=lo,
                             close=(close if is_last else lo), volume=1e8))
    return pd.DataFrame(rows)


def test_blocked_buy_days_exists_and_returns_dict_of_dates():
    """API 形状：输入 5 分钟 frame，输出 {date: bool}，只含窗口内可判定日。"""
    days = [f'2026-08-{d:02d}' for d in range(1, 16)]
    # 80 根横盘日线，保证足够判定窗口（60+5）
    all_days = [f'2026-05-{d:02d}' for d in range(1, 32)] + \
               [f'2026-06-{d:02d}' for d in range(1, 31)] + \
               [f'2026-07-{d:02d}' for d in range(1, 32)] + days
    closes = [10.0] * len(all_days)
    frame = m5_frame(list(zip(all_days, closes)))
    blocked = gate_check.blocked_buy_days(frame)
    assert isinstance(blocked, dict)
    # 横盘向上不破线: 任何一天都不该拦
    assert not any(blocked.values())


def test_full_break_day_blocks_next_day_but_not_break_day_itself():
    """五线全破发生在 D0 → D0 当日不拦（判定用的是截至 D-1 的数据），
    D0+1 起拦截，充分反弹（DMI 翻转+站回均线）后解除。无前视。"""
    # 75 根横盘 + 8 根急跌（全破出现） + 15 根持续反弹（足让 -DI 衰减、
    # +DI 接管、收盘站回短中期均线——短反弹不会解除，Wilder 平滑需要时间）
    stable = [10.0] * 75
    crash = [9.0, 8.8, 8.6, 8.4, 8.2, 8.0, 7.8, 7.6]
    recover = [7.7, 7.8, 7.9, 8.1, 8.3, 8.5, 8.7, 9.0,
               9.2, 9.4, 9.6, 9.8, 10.0, 10.2, 10.4]
    closes = stable + crash + recover
    cal = pd.bdate_range('2026-05-01', periods=len(closes)).strftime('%Y-%m-%d').tolist()
    frame = m5_frame(list(zip(cal, closes)))
    blocked = gate_check.blocked_buy_days(frame)

    crash_start = len(stable)  # 第一根急跌 = 全破首次出现
    day0 = cal[crash_start]
    day1 = cal[crash_start + 1]
    assert blocked.get(day0, False) is False, '当日跌破不影响当日判定（无前视）'
    assert blocked.get(day1, False) is True, '全破次日应拦截'
    # 充分反弹后: DMI 已翻转、收盘站回均线 → 解除
    last_days = cal[-3:]
    assert all(not blocked.get(d, False) for d in last_days), '充分反弹后应解除'


def test_blocked_buy_days_adx_pause_needs_yesterday_data():
    """ADX 分支: 需要昨日前的 high/low/close 历史; 强动能+破60日线才拦。

    构造: 长期缓跌 (低于 ma60) 且方向一致 → ADX 高 + -DI 主导 → pause_buy。
    横盘段不拦; 跌破段次日起拦。
    """
    n = 90
    closes = [10.0] * 30 + [round(10 - 0.03 * i, 3) for i in range(1, n - 30 + 1)]
    cal = pd.bdate_range('2026-03-02', periods=n).strftime('%Y-%m-%d').tolist()
    frame = m5_frame(list(zip(cal, closes)))
    blocked = gate_check.blocked_buy_days(frame)
    # 缓跌后期: 收盘 < ma60 且趋势单调 → 末段应有拦截日
    late = [cal[i] for i in range(n - 5, n)]
    assert any(blocked.get(d, False) for d in late), '长期单边缓跌末端应触发暂停买'


def test_blocked_buy_days_insufficient_history_fails_open():
    """历史不足 65 根: 无从判定 → fail-open (全 False)，与生产 RegimeGate 语义一致。"""
    cal = pd.bdate_range('2026-09-01', periods=30).strftime('%Y-%m-%d').tolist()
    closes = [10 - 0.1 * i for i in range(30)]  # 单边急跌也不拦: 数据不足
    frame = m5_frame(list(zip(cal, closes)))
    blocked = gate_check.blocked_buy_days(frame)
    assert not any(blocked.values())
