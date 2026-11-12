# -*- coding: utf-8 -*-
"""TDD：地量判据单一真源（Master 2026-11-12 选 A）。

市况操作信号(15:35) 与 观察哨哨①(15:50) 原本对同一个上证指数、
同一个「近5日均额/120日峰值 < 1/3」判据用两套数据源、两套阈值(1/3 vs 0.33)、
两套实现各算一遍，可能同日给出相反结论且无裁决层。

本测试钉死：两边共用 tools/volume_dry.py 的阈值与纯计算函数，
观察哨不再调用 westock 第二套取数；两条任务/两套状态机/两条推送保持不变。
"""
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))


class SingleSourceTests(unittest.TestCase):
    def test_shared_threshold_is_exactly_one_third(self):
        import volume_dry
        import market_phase_check
        import watchtower_monitor
        self.assertEqual(volume_dry.DRY_THRESHOLD, 1 / 3)
        # 两边阈值必须引用同一常量，不允许再出现 0.33 第二套
        self.assertEqual(watchtower_monitor.TH_VOLRATIO, volume_dry.DRY_THRESHOLD)
        self.assertEqual(market_phase_check.DRY_THRESHOLD, volume_dry.DRY_THRESHOLD)

    def test_calculator_matches_original_market_phase_formula(self):
        """公共纯函数必须与市况原有内联公式逐位一致（数据正序、旧→新）。"""
        import volume_dry
        amounts = [float(1000 + (i * 37) % 900) * 1e8 for i in range(300)]
        out = volume_dry.calculate(amounts)
        win = min(120, len(amounts))
        expected = (sum(amounts[-5:]) / 5) / max(amounts[-win:])
        self.assertAlmostEqual(out['ratio_raw'], expected, places=12)
        self.assertEqual(out['ratio'], round(expected, 3))

    def test_watchtower_volume_ratio_delegates_to_shared_source(self):
        """观察哨哨①必须调用公共真源，不再走 westock。"""
        import volume_dry
        import watchtower_monitor as wm
        sentinel = dict(ratio=0.25, avg5_yi=3000.0, peak_yi=12000.0, date='2026-11-12')
        with patch.object(volume_dry, 'shanghai_volume_ratio', return_value=sentinel) as shared, \
             patch.object(wm, 'westock', side_effect=AssertionError('不得再调用 westock')):
            self.assertEqual(wm.volume_ratio(), sentinel)
            shared.assert_called_once()

    def test_check_sentries_uses_shared_threshold_label(self):
        """哨①状态判定用统一阈值与统一文案，不残留 0.33。"""
        import volume_dry
        import watchtower_monitor as wm
        v = dict(ratio=0.20, avg5_yi=3000.0, peak_yi=12000.0, date='2026-11-12')
        with patch.object(wm, 'volume_ratio', return_value=v), \
             patch.object(wm, 'margin_data', return_value=None), \
             patch.object(wm, 'scan_since', return_value=[]), \
             patch.object(wm, 'policy_sentry', return_value=('人工盯守', 'x')):
            sigs = wm.check_sentries()
        vol = [s for s in sigs if s[0] == 'vol_dry'][0]
        self.assertEqual(vol[2], '✅地量达成')
        self.assertIn('1/3', vol[3] + vol[1])
        self.assertNotIn('0.33', vol[3] + vol[1])

    def test_market_phase_signal_uses_shared_threshold(self):
        import market_phase_check as mp
        self.assertTrue(mp.evaluate_phase_signals(
            dict(vol_ratio=0.30, adx=20.0, adx_prev=30.0, kdj_golden=True, kdj_k=40.0))['dilVolume'])
        self.assertFalse(mp.evaluate_phase_signals(
            dict(vol_ratio=0.40, adx=20.0, adx_prev=30.0, kdj_golden=True, kdj_k=40.0))['dilVolume'])

    def test_production_entrypoints_import_clean(self):
        import importlib
        for name in ('volume_dry', 'market_phase_check', 'watchtower_monitor'):
            importlib.import_module(name)


if __name__ == '__main__':
    unittest.main()
