# -*- coding: utf-8 -*-
"""单一门控契约（2026-11-07 Master 拍板「F方案不接入了」）。

F 方案（五线全破 OR ATR5/ATR20>1.15）经全池可复跑对照判定证据不足，
已从生产代码整体移除。本文件取代原 test_gate_mode_switch.py，
验证 RegimeGate 只有 legacy 一条路径、误传 mode 不改变行为。
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


class SingleGateTests(unittest.TestCase):
    def test_default_mode_is_legacy(self):
        self.assertEqual(runtime.RegimeGate({}, mode=None).mode, 'legacy')

    def test_explicit_f_mode_is_ignored(self):
        """误传 mode='f' 一律走 legacy，不得静默启用已移除的 F。"""
        self.assertEqual(runtime.RegimeGate({}, mode='f').mode, 'legacy')

    def test_unknown_mode_is_legacy(self):
        self.assertEqual(runtime.RegimeGate({}, mode='bogus').mode, 'legacy')

    def test_five_break_still_blocks_under_legacy(self):
        """legacy 自身仍拦五线全破（F 移除不得削弱下跌侧防护）。"""
        closes = [10.0] * 75 + [8.5, 8.3, 8.1, 7.9, 7.7, 7.5]
        gate = runtime.RegimeGate({'sh589720': dict(
            adx=17.3, pdi=10, mdi=35, bars=_frame(closes))})
        self.assertTrue(gate.blocks_buy('sh589720'))
        self.assertIn('暂停', gate.reason('sh589720'))

    def test_atr_expansion_above_lines_is_not_blocked(self):
        """F 独有的 ATR 扩张拦截已移除：均线上方大振幅场景 legacy 放行。"""
        rows = []
        cal = pd.bdate_range('2026-06-01', periods=88).strftime('%Y-%m-%d').tolist()
        for i, day in enumerate(cal):
            if i < 80:
                c, hi, lo = 10.0, 10.004, 9.996
            else:
                c = 10.0 + 0.3 * (i - 79)
                hi, lo = c * 1.05, c * 0.95
            rows.append(dict(date=day, open=lo, high=hi, low=lo, close=round(c, 4)))
        frame = pd.DataFrame(rows)
        gate = runtime.RegimeGate({'sh589720': dict(
            adx=12.0, pdi=20, mdi=8, bars=frame)})
        self.assertFalse(gate.blocks_buy('sh589720'))

    def test_no_bars_falls_back_to_adx_only(self):
        gate = runtime.RegimeGate({'sh589720': dict(adx=36.1, pdi=10.9, mdi=39.4)})
        self.assertTrue(gate.blocks_buy('sh589720'))


if __name__ == '__main__':
    unittest.main()
