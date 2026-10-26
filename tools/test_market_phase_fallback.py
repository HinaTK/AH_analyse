# -*- coding: utf-8 -*-
"""TDD：市况监控两个问题（2026-10-26 用户反馈）

1. 持仓缺失：用户有 3 只持仓（589720/159363/159992），监控清单是硬编码的
   只有 589720/159363。要求：从账本 holdings.json 动态读取全部持仓
   （含迁移退出的 159992——它仍是真实持仓，方向信号对它清仓时机也有意义）。
2. 东财接口限流会全挂：加腾讯日K备用源，东财失败自动切换。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import unittest
from unittest.mock import patch

import market_phase_check as mp


class InstrumentsTests(unittest.TestCase):
    def test_instruments_include_all_ledger_holdings(self):
        """监控标的 = 4个指数 + 账本全部持仓（从holdings.json动态读，不再硬编码）。"""
        instruments = mp.build_instruments()
        names = [name for _, name in instruments]
        for code in ('sh589720', 'sz159363', 'sz159992'):
            # 名字里含6位代码即可（159992 迁移退出也必须监控）
            self.assertTrue(any(code[2:] in n for n in names),
                            f'账本持仓 {code} 未进监控清单')

    def test_instruments_keep_four_indices(self):
        instruments = mp.build_instruments()
        names = [name for _, name in instruments]
        for idx in ('上证指数', '沪深300', '创业板指', '科创50'):
            self.assertIn(idx, names)


class TencentFallbackTests(unittest.TestCase):
    def test_fetch_kline_falls_back_to_tencent(self):
        """东财抛异常 → 自动切腾讯拉同标的日K，不再整批失败。"""
        with patch.object(mp, 'fetch_eastmoney', side_effect=OSError('rate limited')), \
             patch.object(mp, 'fetch_tencent_kline', return_value=[
                 {'date': '2026-10-26', 'open': 1.0, 'close': 1.01, 'high': 1.02,
                  'low': 0.99, 'volume': 100.0, 'amount': 10000.0, 'pct': 1.0},
             ]):
            rows = mp.fetch_kline('1.000001')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['close'], 1.01)

    def test_fetch_kline_uses_eastmoney_first(self):
        """东财正常时优先东财（口径不变），腾讯只是兜底。"""
        with patch.object(mp, 'fetch_eastmoney', return_value=[
                 {'date': '2026-10-26', 'open': 1.0, 'close': 0.98, 'high': 1.02,
                  'low': 0.97, 'volume': 100.0, 'amount': 10000.0, 'pct': -1.0},
             ]), patch.object(mp, 'fetch_tencent_kline', wraps=mp.fetch_tencent_kline) as spy:
            rows = mp.fetch_kline('1.000001')
        self.assertEqual(rows[0]['close'], 0.98)
        spy.assert_not_called()

    def test_tencent_kline_maps_secid(self):
        """腾讯源 secid 映射：1.000001→sh000001，0.159363→sz159363。"""
        self.assertEqual(mp.tencent_symbol('1.000001'), 'sh000001')
        self.assertEqual(mp.tencent_symbol('0.159363'), 'sz159363')
        self.assertEqual(mp.tencent_symbol('1.589720'), 'sh589720')


if __name__ == '__main__':
    unittest.main()
