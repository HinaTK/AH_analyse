# -*- coding: utf-8 -*-
"""gate_check 统一建仓/买入门控的 TDD 测试。

背景 2026-10-26：entry_timing（榜单禁入）与 RegimeGate（EOD 暂停买入）
两套判定在"下跌不许买"上重复且打架（实测 6 票 3 只打架：589720 五线
全破但 ADX 17 放行）。用户确认合并为单一四级判定 gate_check：

    禁入     五线全破（收盘 < ma5/10/20/30/60 全部）
    暂停买   ADX>=25 且收盘 < ma60（动能够强且仍在跌势）
    试错仓   破 1-4 条线（配 20 日最低退出价）
    正常     收盘 >= ma60（含均线之上的防追高细分，交由 entry_timing）

从严者胜：禁入 > 暂停买 > 试错仓 > 正常。行情缺失 fail-open 不拦截
（沿用 RegimeGate 语义）。单一数据源：东财日K（market_phase_check
fetch_kline），entry_timing 的均线与 ADX 全部在同一批 bars 上计算。
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.etf_research import gate_check


def daily_frame(closes, adx=None, mdi=0, pdi=0):
    """合成日线 DataFrame + 可选注入的市况值（绕开网络）。"""
    dates = pd.bdate_range('2026-06-01', periods=len(closes)).strftime('%Y-%m-%d')
    frame = pd.DataFrame({
        'date': dates,
        'open': closes,
        'high': [c * 1.01 for c in closes],
        'low': [c * 0.99 for c in closes],
        'close': closes,
        'volume': [1e8] * len(closes),
    })
    regime = None if adx is None else dict(adx=adx, mdi=mdi, pdi=pdi)
    return frame, regime


def test_gate_no_entry_when_all_five_mas_broken():
    """五线全破 → 禁入：从严最高级，覆盖 ADX 放行的历史打架场景。"""
    closes = [10.0] * 75 + [8.5, 8.3, 8.1, 7.9, 7.7, 7.5]
    frame, regime = daily_frame(closes, adx=17.3, mdi=30, pdi=20)  # ADX 低于阈值
    verdict = gate_check.gate(frame, regime)
    assert verdict['level'] == 'no_entry'
    assert verdict['blocks_buy'] is True, '禁入必须拦买入'
    assert '5日线' in verdict['reason']


def test_gate_pause_buy_when_strong_downtrend_but_not_all_mas_broken():
    """ADX>=25 且收盘<60日线（但未五线全破）→ 暂停买。"""
    # 先涨后急跌两天，跌破 60 日线但 5 日线还在下方托住（未全破）
    closes = [10 + 0.02 * i for i in range(90)] + [11.0, 10.8, 10.6, 10.5, 10.9]
    frame, regime = daily_frame(closes, adx=36.1, mdi=35, pdi=10)
    verdict = gate_check.gate(frame, regime)
    assert verdict['level'] == 'pause_buy'
    assert verdict['blocks_buy'] is True
    assert 'ADX' in verdict['reason']


def test_gate_probe_when_partially_broken_and_weak_trend():
    """破 1-4 条线 + ADX<25 → 试错仓（不拦，但标注退出价）。"""
    closes = [10 + 0.02 * i for i in range(90)] + [11.0, 10.8, 10.6, 10.5, 10.9]
    frame, regime = daily_frame(closes, adx=12.1, mdi=25, pdi=10)
    verdict = gate_check.gate(frame, regime)
    assert verdict['level'] == 'probe_only'
    assert verdict['blocks_buy'] is False
    assert verdict['exit_price'] is not None, '试错仓必须带 20 日最低退出价'


def test_gate_stricter_level_wins_between_no_entry_and_pause():
    """五线全破 + ADX>=25 同时满足 → 禁入（从严者胜）。"""
    closes = [2 - i * 0.01 for i in range(80)]
    frame, regime = daily_frame(closes, adx=40.0, mdi=45, pdi=5)
    verdict = gate_check.gate(frame, regime)
    assert verdict['level'] == 'no_entry'


def test_gate_fail_open_when_regime_missing():
    """市况缺失 → 不因 ADX 拦（fail-open），均线照判。"""
    closes = [10 + 0.02 * i for i in range(90)] + [11.0, 10.8, 10.6, 10.5, 10.9]
    frame, regime = daily_frame(closes, adx=None)
    verdict = gate_check.gate(frame, regime)
    assert verdict['level'] == 'probe_only', '无 ADX 不触发暂停买，只按均线判'
    assert verdict['blocks_buy'] is False


def test_gate_reuses_entry_timing_verdict_for_position_sizing():
    """gate 的 ma 判定必须与 entry_timing 同源：不重复实现均线逻辑。

    防追高/整仓等"上方"场景 gate 不负责——gate.delegates 返回
    entry_timing 的完整判定供 EOD 报告展示仓位资格。
    """
    closes = [10.0] * 75 + [8.5, 8.3, 8.1, 7.9, 7.7, 7.5]
    frame, regime = daily_frame(closes)
    verdict = gate_check.gate(frame, regime)
    assert verdict['entry_verdict'] == 'no_entry', '与 entry_timing 同一判定'
