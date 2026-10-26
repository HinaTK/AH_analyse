# -*- coding: utf-8 -*-
"""TDD：entry_rank 双窗口矩阵——近20日高/低线改为“当期入选池中位数”（2026-10-26 用户确认）。

背景：固定 ≥2 是入选过滤线（用户个人定的及格线），不能冒充效率分界线；
固定绝对数（如4）会随市场节奏过期。改为动态线：每次研究用入选池
recent20_cycles 的中位数切割，表头必须印出线值供核对。

矩阵四档（63日高/低线维持 ≥10 不变）：
- 高/高 → ✅双高   高/低 → ⏳等信号   低/高 → ⚠️脉冲   低/低 → ❌死水
铁律：标注与线值必须由代码从真实字段计算，禁止手写。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.etf_research.entry_rank import (
    MIN_FULL_CYCLES,
    median_r20_threshold,
    render_markdown,
    window_matrix_label,
)


def _row(code='sz159999', name='测试', full=29.0, r20=7.0, net=4000.0, label='持仓'):
    return dict(rank=1, code=code, name=name, label=label,
                full_cycles=full, full_cycle_net=net,
                recent20_cycles=r20,
                full_cycle_net_per_avg_cost_pct=3.0)


def _report(rows):
    return dict(asof='2026-10-23', rows=rows,
                excluded={'holding': 0, 'incomplete': 0, 'timing': 0,
                          'recent20': 0, 'no_bars': 0, 'error': 0})


class MedianThresholdTests(unittest.TestCase):
    def test_median_odd_count(self):
        rows = [_row(r20=v) for v in (2, 6, 12)]
        self.assertEqual(median_r20_threshold(rows), 6)

    def test_median_even_count_averages(self):
        rows = [_row(r20=v) for v in (2, 4, 6, 8)]
        self.assertEqual(median_r20_threshold(rows), 5.0)

    def test_empty_pool_falls_back_to_admission_gate(self):
        self.assertEqual(median_r20_threshold([]), 2)


class MatrixLabelTests(unittest.TestCase):
    def test_double_high(self):
        self.assertEqual(window_matrix_label(_row(full=29, r20=7), 6), '✅双高')

    def test_high_low_wait_signal(self):
        # r20 低于当期中位线 → 近20日算“低”
        self.assertEqual(window_matrix_label(_row(full=26, r20=5), 6), '⏳等信号')

    def test_low_high_pulse(self):
        self.assertEqual(window_matrix_label(_row(full=4, r20=7), 6), '⚠️脉冲')

    def test_low_low_dead(self):
        self.assertEqual(window_matrix_label(_row(full=4, r20=1), 6), '❌死水')

    def test_boundary_r20_eq_median_is_high(self):
        # 边界含：恰好等于中位线算“高”
        self.assertEqual(window_matrix_label(_row(full=29, r20=6), 6), '✅双高')

    def test_boundary_full_eq_10_is_high(self):
        self.assertEqual(window_matrix_label(_row(full=10, r20=1), 6), '⏳等信号')


class RenderTests(unittest.TestCase):
    def test_render_header_prints_threshold(self):
        rows = [_row(code='sh588001', r20=2), _row(code='sh588002', r20=6),
                _row(code='sh588003', r20=12)]
        out = render_markdown(_report(rows), top_n=10)
        self.assertIn('近20日高/低线=6（当期入选池中位）', out)

    def test_render_labels_use_pool_median(self):
        # 池中位=6：r20=2 标⏳，r20=12 标✅
        rows = [_row(code='sh588001', full=29, r20=2),
                _row(code='sh588002', full=29, r20=6),
                _row(code='sh588003', full=29, r20=12)]
        out = render_markdown(_report(rows), top_n=10)
        self.assertIn('⏳等信号', out)
        self.assertIn('✅双高', out)

    def test_render_values_from_rows_only(self):
        rows = [_row(code='sz159366', full=4, r20=7),
                _row(code='sh588004', full=29, r20=7)]
        out = render_markdown(_report(rows), top_n=10)
        self.assertIn('⚠️脉冲', out)
        self.assertIn('✅双高', out)


if __name__ == '__main__':
    unittest.main()
