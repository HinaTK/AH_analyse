# -*- coding: utf-8 -*-
"""TDD：窗口锚点位移披露 + 多起点稳健性离线诊断（2026-11-06 Master 授权）。

只读诊断，不替换生产口径、不写账本、不联网、不跑生产研究。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, r'D:\Code\AH_analyse')

from tools.etf_research import anchor_sensitivity as a


def _frame(days, first_open=1.250):
    """合成 5 分钟 bars：每天 2 根，time 为字符串。"""
    import pandas as pd
    rows = []
    for i, day in enumerate(days):
        for hhmm in ('09:35:00', '15:00:00'):
            px = first_open if i == 0 else 1.20 + i * 0.001
            rows.append(dict(time=f'{day} {hhmm}', open=px, high=px * 1.01,
                             low=px * 0.99, close=px, volume=1_000_000.0))
    return pd.DataFrame(rows)


class AnchorInfoTests(unittest.TestCase):
    def test_anchor_uses_first_open_and_grid_price_rule(self):
        info = a.anchor_of_first_open(1.250, '2026-08-03 09:35:00')
        self.assertEqual(info['start'], '2026-08-03 09:35:00')
        self.assertAlmostEqual(info['first_open'], 1.250)
        # 与 grid_model.price(1.250, True, 0.0005) 一致：向上取整到 0.001
        self.assertAlmostEqual(info['initial_buy'], 1.251, places=3)
        self.assertAlmostEqual(info['first_sell'], 1.251 * 1.02, places=3)

    def test_shift_summary_percent_and_grid_count(self):
        prev = a.anchor_of_first_open(1.250, 'A')
        curr = a.anchor_of_first_open(1.289, 'B')
        s = a.shift_summary(prev, curr)
        self.assertGreater(s['pct'], 3.0)     # 1.251 → 1.290，约 +3.1%
        self.assertGreater(s['grids'], 1.0)    # 超过一个 2% 格距
        self.assertLess(s['pct'], 3.3)

    def test_disclosure_lines_are_chinese_and_include_shift(self):
        prev = a.anchor_of_first_open(1.250, '2026-08-03 09:35:00')
        curr = a.anchor_of_first_open(1.289, '2026-08-04 09:35:00')
        lines = a.disclosure_lines(prev, curr, '2026-11-05', '2026-11-06')
        text = '\n'.join(lines)
        for word in ('锚价位移', '首根', '格距', '敏感', '仅披露'):
            with self.subTest(word=word):
                self.assertIn(word, text)
        for banned in ('full_cycles', 'qualification', 'initial_p', 'anchor'):
            self.assertNotIn(banned, text)


class DiagnoseTests(unittest.TestCase):
    def test_shifts_return_one_run_each_and_same_window_length(self):
        days = [f'2026-{m:02d}-{d:02d}' for m, d in
                [(8, 3)] * 1] + [f'2026-09-{i:02d}' for i in range(1, 31)] + \
               [f'2026-10-{i:02d}' for i in range(1, 31)] + \
               [f'2026-11-{i:02d}' for i in range(1, 7)]
        frame = _frame(days)
        calls = []

        def fake_simulate(f, **kwargs):
            calls.append((f['time'].iloc[0][:10], f['time'].iloc[-1][:10], len(f)))
            return dict(cycles=10 + len(calls), cycle_net=1000.0 + len(calls))

        out = a.diagnose(frame, sessions=10, shifts=(0, -1, -2), simulate=fake_simulate)
        self.assertEqual(len(out['runs']), 3)
        self.assertEqual([r['shift'] for r in out['runs']], [0, -1, -2])
        self.assertEqual([r['cycles'] for r in out['runs']], [11, 12, 13])
        self.assertTrue(all(len(c[0]) == 10 and len(c[1]) == 10 for c in calls))
        self.assertEqual(len({c[0] for c in calls}), 3, '每个起点须不同')
        self.assertEqual(out['spread'], 2)

    def test_failed_window_is_disclosed_not_silently_dropped(self):
        days = [f'2026-09-{i:02d}' for i in range(1, 21)]
        frame = _frame(days)

        state = {'n': 0}

        def fake_simulate(f, **kwargs):
            state['n'] += 1
            if state['n'] == 3:  # 第三个窗口抛异常，验证失败被披露而非静默丢弃
                raise ValueError('首根成交量不足')
            return dict(cycles=7, cycle_net=700.0)

        out = a.diagnose(frame, sessions=5, shifts=(0, -1, -2), simulate=fake_simulate)
        self.assertTrue(any(r['error'] for r in out['runs']))
        self.assertIn('首根成交量不足', ' '.join(str(r['error']) for r in out['runs']))

    def test_render_has_chinese_table_and_disclaimer(self):
        days = [f'2026-09-{i:02d}' for i in range(1, 21)]
        frame = _frame(days)
        diag = a.diagnose(frame, sessions=5, shifts=(0, -1, -2),
                          simulate=lambda f, **kw: dict(cycles=6, cycle_net=600.0))
        prev = a.anchor_of_first_open(1.250, '2026-08-03 09:35:00')
        curr = a.anchor_of_first_open(1.289, '2026-08-04 09:35:00')
        text = a.render(disclosure=a.disclosure_lines(prev, curr, '2026-11-05', '2026-11-06'),
                        diagnosis=diag, code='TEST', name='测试ETF',
                        prev_asof='2026-11-05', curr_asof='2026-11-06')
        for word in ('锚点敏感性', '窗口起点', '63日往返次数', '离散度',
                     '不叠加市况门控', '不替换生产口径', '非真实成交'):
            with self.subTest(word=word):
                self.assertIn(word, text)
        self.assertNotIn('full_cycles', text)


if __name__ == '__main__':
    unittest.main()
