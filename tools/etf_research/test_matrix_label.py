# -*- coding: utf-8 -*-
"""TDD：entry_rank 渲染加“双窗口判断矩阵”标注（2026-10-26 用户定）。

矩阵四档（63日往返 vs 近20日往返）：
- 高/高 → ✅双高：长期稳+当下活，建仓池正常候选
- 高/低 → ⏳等信号：长期好+当下哑（常为单边压网格），观察名单
- 低/高 → ⚠️脉冲：近期才活跃可持续性未验证，仅试错仓对待（159366型）
- 低/低 → ❌死水：出池

阈值与 rank_entries 的建仓门槛一致：full>=10, recent20>=2。
铁律：标注必须由代码从 row 的真实字段计算，禁止手写。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.etf_research.entry_rank import window_matrix_label, render_markdown


def _row(code='sz159999', name='测试', full=29.0, r20=7.0, net=4000.0, label='持仓'):
    return dict(rank=1, code=code, name=name, label=label,
                full_cycles=full, full_cycle_net=net,
                recent20_cycles=r20,
                full_cycle_net_per_avg_cost_pct=3.0)


def _report(rows):
    return dict(asof='2026-10-23', rows=rows,
                excluded={'holding': 0, 'incomplete': 0, 'timing': 0,
                          'recent20': 0, 'no_bars': 0, 'error': 0})


class MatrixLabelTests(unittest.TestCase):
    def test_double_high(self):
        self.assertEqual(window_matrix_label(_row(full=29, r20=7)), '✅双高')

    def test_high_low_wait_signal(self):
        # 近20日<2 才算“低”（门槛 recent20>=2 入选，边界含2）
        self.assertEqual(window_matrix_label(_row(full=26, r20=1)), '⏳等信号')

    def test_low_high_pulse(self):
        self.assertEqual(window_matrix_label(_row(full=4, r20=7)), '⚠️脉冲')

    def test_low_low_dead(self):
        self.assertEqual(window_matrix_label(_row(full=4, r20=1)), '❌死水')

    def test_boundary_full_eq_10_is_high(self):
        # full=10 边界含：full高 + r20=1低 → 等信号（同时验证边界归属）
        self.assertEqual(window_matrix_label(_row(full=10, r20=1)), '⏳等信号')

    def test_boundary_r20_eq_2_is_high(self):
        self.assertEqual(window_matrix_label(_row(full=9, r20=2)), '⚠️脉冲')


class RenderTests(unittest.TestCase):
    def test_render_contains_matrix_column(self):
        out = render_markdown(_report([_row(full=29, r20=7)]), top_n=10)
        self.assertIn('判断', out)            # 表头有判断列
        self.assertIn('✅双高', out)          # 标注出现在行内

    def test_render_matrix_values_from_rows_only(self):
        # 标注由行内字段推导（full=4,r20=7 必须渲染成 ⚠️脉冲）
        out = render_markdown(_report([_row(full=4, r20=7)]), top_n=10)
        self.assertIn('⚠️脉冲', out)
        self.assertNotIn('✅双高', out)


if __name__ == '__main__':
    unittest.main()
