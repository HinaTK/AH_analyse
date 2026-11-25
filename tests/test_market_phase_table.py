# -*- coding: utf-8 -*-
"""TDD：市况推送排版（2026-10-27 用户反馈：好乱，没有分段、没有表格整理）。

要求：整份推送 = 两段式 markdown——
  1) 一张全标的汇总表（标的 | 收盘 | 动作·成数 | 三信号 | 理由）；
  2) 每标的关键读数分块（【标的】+ 读数行，不再 6 行散排）。
铁律：表格单元格的数字只能来自传入 metrics 字典，禁止手拼。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import unittest

import market_phase_check as mp


def _metrics(adx=46.0, adx_prev=41.0, pdi=18.0, mdi=30.0, vol_ratio=0.55,
             golden=False, kdj_k=42.0, dd250=-8.0, trend='down',
             name='上证指数', secid='1.000001'):
    sig = mp.evaluate_phase_signals({
        'vol_ratio': vol_ratio, 'adx': adx, 'adx_prev': adx_prev,
        'kdj_golden': golden, 'kdj_k': kdj_k,
    })
    label, fraction, reason = mp.action_label({
        'trigger': sig['trigger'], 'adx': adx, 'trend': trend,
        'dd250': dd250, 'dilVolume': sig['dilVolume'], 'kdj_golden': sig['kdj_golden'],
    })
    return {
        'name': name, 'secid': secid, 'date': '2026-10-27',
        'close': 3697.52, 'pct': -1.33,
        'adx': adx, 'adx_prev': adx_prev, 'pdi': pdi, 'mdi': mdi,
        'vol_ratio': vol_ratio, 'kdj_golden': golden, 'kdj_k': kdj_k,
        'dd250': dd250, 'trend': trend,
        'label': label, 'fraction': fraction, 'reason': reason,
        'signals': sig,
        'ma_pos': {20: -3.1, 30: -4.2, 60: -2.0},
    }


class TableRenderTests(unittest.TestCase):
    def test_summary_table_is_markdown_with_separator(self):
        """汇总表必须有 markdown 表头分隔行（|---|），否则飞书不渲染成表格。"""
        text = mp.render_summary_table([_metrics(), _metrics(name='沪深300', secid='1.000300')])
        self.assertIn('| 标的 |', text)
        self.assertRegex(text, r'\|[-:|-]+\|')
        # 两行数据
        self.assertIn('| 上证指数 |', text)
        self.assertIn('| 沪深300 |', text)

    def test_summary_row_contains_readings_and_action(self):
        """汇总行必须含：收盘、涨跌、动作·成数、三信号亮灭、理由关键词。"""
        text = mp.render_summary_table([_metrics()])
        row = [l for l in text.splitlines() if '上证指数' in l][0]
        for needle in ('3697.52', '-1.33%', '空仓观望·0成', '○○○'):
            self.assertIn(needle, row)

    def test_three_signals_render_as_symbols(self):
        """三信号用 ●/○ 记号成串（●○○ 风格），不是长文本堆在一行。"""
        row = [l for l in mp.render_summary_table([_metrics()]).splitlines() if '上证指数' in l][0]
        self.assertRegex(row, r'[●○]{3}')
        # 地量亮时第一格变 ●
        row2 = [l for l in mp.render_summary_table(
            [_metrics(vol_ratio=0.30)]).splitlines() if '上证指数' in l][0]
        self.assertIn('●○○', row2)

    def test_render_report_has_sections(self):
        """整份报告分段：表头说明 → 汇总表，到表格为止（2026-10-29 用户定调：
        【关键读数】分节太长，砍掉，只留表头+汇总表）。"""
        text = mp.render_report([_metrics()])
        self.assertIn('| 标的 |', text)                      # 汇总表
        self.assertNotIn('关键读数', text)                   # 分节标题已砍
        self.assertNotIn('【上证指数】', text)               # 标的读数块不再出现在推送
        self.assertNotIn('MA20', text)                       # 明细读数不再进入报告

    def test_instrument_block_max_two_lines_per_group(self):
        """单标的读数块收紧：收盘/均线/回撤一行，量能/动能一行，信号一行（3行内）。"""
        block = mp.render_instrument(_metrics())
        body = [l for l in block.splitlines() if l.strip() and not l.startswith('【')]
        self.assertLessEqual(len(body), 4, f'读数行数应≤4，当前{len(body)}行:\n{block}')

    def test_numbers_come_from_metrics_only(self):
        """收盘价等数字必须逐格来自 metrics，不得手拼（表格交付铁律）。"""
        m = _metrics()
        m['close'] = 1234.56
        row = [l for l in mp.render_summary_table([m]).splitlines() if '上证指数' in l][0]
        self.assertIn('1234.56', row)
        self.assertNotIn('3697', row)


if __name__ == '__main__':
    unittest.main()
