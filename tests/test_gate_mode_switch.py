# -*- coding: utf-8 -*-
"""方案切换测试（2026-11-06 Master 拍板：F 方案先放弃，默认回退 legacy）。

背景：2026-10-30 曾把默认切成方案F（五线全破 OR ATR5/ATR20>1.15），
但 11-06 批判性检查发现生产缓存链全程走 legacy、F 回测数字不可复核、
且 F 把用户确认的 ER+ATR 组合降维成单指标。故默认改回 legacy，
让代码默认值与实际生产执行一致；F 保留为显式可选备份，待复盘再议。

  - 'legacy'（默认）：走原四级 gate_check 判定（与缓存链一致）
  - 'f'：走方案F判定（patrol_f 同源逻辑），需显式传 mode 或 GATE_MODE
"""
import sys
from pathlib import Path

sys.path.insert(0, r'D:\Code\AH_analyse')
sys.path.insert(0, r'D:\Code\AH_analyse\tools')

import unittest
import pandas as pd

import confirmed_runtime as runtime


def _frame(closes, hi_pct=1.01, lo_pct=0.99):
    dates = pd.bdate_range('2026-06-01', periods=len(closes)).strftime('%Y-%m-%d')
    return pd.DataFrame({
        'date': dates, 'open': closes,
        'high': [c * hi_pct for c in closes],
        'low': [c * lo_pct for c in closes], 'close': closes})


class GateModeSwitchTests(unittest.TestCase):
    """方案切换：legacy 为默认，F 为显式可选备份（2026-11-06 回退）。"""

    def test_default_mode_is_legacy(self):
        """默认必须是 legacy——与生产缓存链实际执行一致（Master 2026-11-06 拍板）。"""
        self.assertEqual(runtime.GATE_MODE_DEFAULT, 'legacy')
        gate = runtime.RegimeGate({}, mode=None)
        self.assertEqual(gate.mode, 'legacy')

    def test_f_mode_still_available_explicitly(self):
        """F 模块保留为备份：显式 mode='f' 仍可选用，不删除。"""
        gate = runtime.RegimeGate({}, mode='f')
        self.assertEqual(gate.mode, 'f')

    def test_legacy_mode_still_available(self):
        """legacy 可显式选择（mode='legacy' 或 GATE_MODE=legacy）。"""
        gate = runtime.RegimeGate({}, mode='legacy')
        self.assertEqual(gate.mode, 'legacy')

    def test_invalid_mode_falls_back_to_legacy(self):
        """未知 mode 值：回落到默认 legacy，不 crash、不静默启用未验证的 F。"""
        gate = runtime.RegimeGate({}, mode='bogus')
        self.assertEqual(gate.mode, 'legacy')

    def test_f_mode_blocks_on_five_break(self):
        """F 模式：五线全破拦截（与原方案共有的行为）。"""
        closes = [10.0] * 75 + [8.5, 8.3, 8.1, 7.9, 7.7, 7.5]
        frame = _frame(closes)
        gate = runtime.RegimeGate({'sh589720': dict(adx=17.3, pdi=10, mdi=35, bars=frame)}, mode='f')
        self.assertTrue(gate.blocks_buy('sh589720'))
        self.assertIn('五线全破', gate.reason('sh589720'))

    def test_f_mode_blocks_on_atr_expand_above_lines(self):
        """F 模式核心增量：均线上方但 ATR 扩张>15% 也拦截。

        原 legacy 模式对这个场景放行（五线不全破 + ADX 不超线）——
        这是两方案的本质差异，512980 式的波动冲击场景。
        """
        # 80 根平静横盘 + 8 根大振幅上涨（收盘抬升保证在均线上方）
        rows = []
        cal = pd.bdate_range('2026-06-01', periods=88).strftime('%Y-%m-%d').tolist()
        for i, day in enumerate(cal):
            if i < 80:
                c = 10.0
                hi, lo = c * 1.004, c * 0.996
            else:
                c = 10.0 + 0.3 * (i - 79)
                hi, lo = c * 1.05, c * 0.95
            rows.append(dict(date=day, open=lo, high=hi, low=lo, close=round(c, 4)))
        frame = pd.DataFrame(rows)
        f_gate = runtime.RegimeGate({'sh589720': dict(adx=12.0, pdi=20, mdi=8, bars=frame)}, mode='f')
        self.assertTrue(f_gate.blocks_buy('sh589720'), 'F方案应拦 ATR 扩张（即使均线上方、ADX弱）')
        self.assertIn('波动扩张', f_gate.reason('sh589720'))

    def test_legacy_mode_keeps_old_behavior_on_atr_expand(self):
        """备份模式对同一场景放行——证明切换真的改变了行为（可对账）。"""
        rows = []
        cal = pd.bdate_range('2026-06-01', periods=88).strftime('%Y-%m-%d').tolist()
        for i, day in enumerate(cal):
            if i < 80:
                c = 10.0
                hi, lo = c * 1.004, c * 0.996
            else:
                c = 10.0 + 0.3 * (i - 79)
                hi, lo = c * 1.05, c * 0.95
            rows.append(dict(date=day, open=lo, high=hi, low=lo, close=round(c, 4)))
        frame = pd.DataFrame(rows)
        legacy_gate = runtime.RegimeGate({'sh589720': dict(adx=12.0, pdi=20, mdi=8, bars=frame)}, mode='legacy')
        self.assertFalse(legacy_gate.blocks_buy('sh589720'), 'legacy 模式维持原四级判定（此场景放行）')

    def test_f_mode_quiet_sideways_allows(self):
        """F 模式：平静震荡（ATR 未扩张 + 未全破）放行。"""
        closes = [10.0] * 90
        frame = _frame(closes)
        gate = runtime.RegimeGate({'sh589720': dict(adx=15.0, pdi=18, mdi=12, bars=frame)}, mode='f')
        self.assertFalse(gate.blocks_buy('sh589720'))

    def test_f_mode_insufficient_data_fails_open(self):
        """F 模式：数据不足 fail-open（与 legacy 语义一致）。"""
        frame = _frame([10.0] * 30)
        gate = runtime.RegimeGate({'sh589720': dict(adx=None, pdi=None, mdi=None, bars=frame)}, mode='f')
        self.assertFalse(gate.blocks_buy('sh589720'))

    def test_f_mode_sells_never_blocked_and_reason_readable(self):
        """F 模式：文案可读（⛔行直接引用），sells_allowed 恒 True。"""
        closes = [10.0] * 75 + [8.5, 8.3, 8.1, 7.9, 7.7, 7.5]
        gate = runtime.RegimeGate({'sh589720': dict(adx=17.3, pdi=10, mdi=35, bars=_frame(closes))}, mode='f')
        reason = gate.reason('sh589720')
        self.assertIn('F方案', reason)
        self.assertIn('暂停', reason)

    def test_no_bars_falls_back_adx_only_both_modes(self):
        """无 bars 的旧格式 regime：两个模式都退回纯 ADX 判定（向后兼容不变）。"""
        f_gate = runtime.RegimeGate({'sh589720': dict(adx=36.1, pdi=10.9, mdi=39.4)}, mode='f')
        legacy_gate = runtime.RegimeGate({'sh589720': dict(adx=36.1, pdi=10.9, mdi=39.4)}, mode='legacy')
        self.assertTrue(f_gate.blocks_buy('sh589720'))
        self.assertTrue(legacy_gate.blocks_buy('sh589720'))


if __name__ == '__main__':
    unittest.main()
