# -*- coding: utf-8 -*-
"""TDD：F 方案已从生产门控移除（2026-11-07 Master 拍板「F方案不接入了」）。

Master 要求：F 不接入，实际代码里有用到的就去掉。
预期：RegimeGate 只有 legacy 一条路径，不再有 mode 分派、不再 import patrol_f、不再有
GATE_MODE / ATR_EXPAND_TH；盘中 gate_watch 不再需要按 F 口径做 method_mismatch 判定。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, r'D:\Code\AH_analyse')
sys.path.insert(0, r'D:\Code\AH_analyse\tools')

import confirmed_runtime as runtime


class NoFGateTests(unittest.TestCase):
    def test_no_gate_mode_switch_symbols(self):
        """生产运行时不得再暴露 GATE_MODE_DEFAULT / ATR_EXPAND_TH。"""
        self.assertFalse(hasattr(runtime, 'GATE_MODE_DEFAULT'))
        self.assertFalse(hasattr(runtime, 'ATR_EXPAND_TH'))

    def test_regime_gate_has_no_f_branch(self):
        """RegimeGate 不得再有 _patrol_f 或 mode 分派。"""
        self.assertFalse(hasattr(runtime.RegimeGate, '_patrol_f'))
        self.assertNotIn("'f'", (runtime.RegimeGate.__init__.__code__.co_consts))

    def test_regime_gate_ignores_explicit_f_mode(self):
        """即使外部误传 mode='f'，也必须走 legacy，不得静默启用 F。"""
        import pandas as pd
        closes = [10.0] * 88
        frame = pd.DataFrame({
            'date': pd.bdate_range('2026-06-01', periods=88).strftime('%Y-%m-%d'),
            'open': closes, 'high': [c * 1.05 for c in closes],
            'low': [c * 0.95 for c in closes], 'close': closes})
        gate = runtime.RegimeGate({'x': dict(adx=12.0, pdi=20, mdi=8, bars=frame)}, mode='f')
        self.assertFalse(gate.blocks_buy('x'), 'F 已移除，ATR 扩张场景不得再被 F 拦')

    def test_patrol_f_module_removed(self):
        """独立 F 巡检模块不得留在生产 tools/ 目录。"""
        self.assertFalse(Path(r'D:\Code\AH_analyse\tools\patrol_f.py').exists())

    def test_no_unverifiable_f_numbers_in_skill(self):
        """SKILL.md 里无法复核的 F 回测数字必须清理。"""
        text = Path(r'D:\Code\AH_analyse\skills\etf-grid-maintenance\SKILL.md').read_text(
            encoding='utf-8')
        for needle in ('+317.1k', '+251.9k', '680次', '均-95.9元', '56.9%', '47.4%'):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, text)


if __name__ == '__main__':
    unittest.main()
