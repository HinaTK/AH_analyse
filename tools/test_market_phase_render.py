# -*- coding: utf-8 -*-
"""TDD：市况监控推送信息量不足（2026-10-26 用户反馈：一行简报看不出是什么）。

要求：每标的输出关键读数（收盘、涨跌、MA20/60 位置、量能比、ADX±DI、
三信号各自亮没亮、回撤），让人不查文档也能看懂当前市况和判定依据。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import unittest
from unittest.mock import patch

import market_phase_check as mp


def _metrics(adx=46.0, adx_prev=41.0, pdi=18.0, mdi=30.0, vol_ratio=0.55,
             golden=False, kdj_k=42.0, dd250=-8.0, trend='down'):
    sig = mp.evaluate_phase_signals({
        'vol_ratio': vol_ratio, 'adx': adx, 'adx_prev': adx_prev,
        'kdj_golden': golden, 'kdj_k': kdj_k,
    })
    label, fraction, reason = mp.action_label({
        'trigger': sig['trigger'], 'adx': adx, 'trend': trend,
        'dd250': dd250, 'dilVolume': sig['dilVolume'], 'kdj_golden': sig['kdj_golden'],
    })
    return {
        'name': '上证指数', 'secid': '1.000001', 'date': '2026-10-26',
        'close': 3697.52, 'pct': -0.7,
        'adx': adx, 'adx_prev': adx_prev, 'pdi': pdi, 'mdi': mdi,
        'vol_ratio': vol_ratio, 'kdj_golden': golden, 'kdj_k': kdj_k,
        'dd250': dd250, 'trend': trend,
        'label': label, 'fraction': fraction, 'reason': reason,
        'signals': sig,
        'ma_pos': {20: -3.1, 30: -4.2, 60: -2.0},
    }


class MonitorRenderTests(unittest.TestCase):
    def test_render_instrument_includes_key_readings(self):
        """每标的的渲染必须含：收盘/涨跌、MA20与MA60位置、量能比、ADX与±DI、回撤、三信号状态。"""
        text = mp.render_instrument(_metrics())
        for needle in (
            '上证指数', '3697.52', '-0.70%', 'MA20', 'MA60',
            '量能', '0.55', 'ADX', '+DI', '-DI', '距250日高点',
            '地量', 'ADX降破25', '周线金叉',
            '空仓观望', '0成',
        ):
            self.assertIn(needle, text, f'缺少关键读数: {needle}')

    def test_render_signals_show_on_or_off(self):
        """三个信号必须显式亮/未亮，不是只在触发时才提。"""
        text = mp.render_instrument(_metrics())
        self.assertIn('未亮', text)
        # 地量阈值内则亮（2026-10-27 记号由 ✅ 改为 ●，与汇总表 ●/○ 一致）
        text2 = mp.render_instrument(_metrics(vol_ratio=0.30))
        self.assertIn('●地量', text2)

    def test_render_header_explains_semantics(self):
        """表头带一句口径说明：右侧三信号是什么、成数指什么。"""
        head = mp.render_header('2026-10-26')
        self.assertIn('右侧三信号', head)
        self.assertIn('地量', head); self.assertIn('ADX', head); self.assertIn('周线', head)
        self.assertIn('方向仓', head)  # 成数指方向仓，不是清仓网格

    def test_monitor_main_uses_rich_render(self):
        """monitor_main 走富渲染路径（不再是一行简报）。"""
        fake_results = [_metrics()]
        text = mp.render_report(fake_results)
        self.assertIn('MA20', text)
        self.assertIn('地量', text)


if __name__ == '__main__':
    unittest.main()
