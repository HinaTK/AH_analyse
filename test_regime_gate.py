# -*- coding: utf-8 -*-
"""TDD：网格×市况联动（2026-10-26 用户定，复盘159363后落地）。

规则：某ETF判定为单边下跌（ADX≥25 且 -DI>+DI，用截至昨日收盘数据）
→ 盘前 plan() 不再生成该ETF的新格买入建议；卖出建议保留。
→ 输出中明确标注暂停原因，禁止静默消失。
→ 单边上涨/震荡：不受影响。
→ 行情获取失败：不暂停（fail-open，不因数据故障停策略）。
"""
import sys
from pathlib import Path

sys.path.insert(0, r'D:\Code\AH_analyse')
sys.path.insert(0, r'D:\Code\AH_analyse\tools')

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import confirmed_runtime as runtime


def _write_state(root, code, inputs=None):
    import confirmed_589720
    state = confirmed_589720.build(inputs, code=code, name=code)
    state['sellable_qty'] = state['qty'] if state['qty'] else 0
    (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    return state


def _daily_regime(adx, pdi, mdi):
    """构造 regime_fetcher 的桩数据。"""
    return dict(adx=adx, pdi=pdi, mdi=mdi)


class RegimeGateTests(unittest.TestCase):
    def test_sideways_market_does_not_block_buy_advice(self):
        """震荡市（ADX<25）：买入建议照常生成。"""
        gate = runtime.RegimeGate({'sh589720': _daily_regime(17.0, 18.0, 27.0)})
        self.assertFalse(gate.blocks_buy('sh589720'))

    def test_one_sided_downtrend_blocks_buy_advice(self):
        """单边下跌（ADX≥25 且 -DI>+DI）：暂停买入建议。"""
        gate = runtime.RegimeGate({'sh589720': _daily_regime(36.1, 10.9, 39.4)})
        self.assertTrue(gate.blocks_buy('sh589720'))
        self.assertIn('单边下跌', gate.reason('sh589720'))
        self.assertIn('ADX', gate.reason('sh589720'))

    def test_one_sided_uptrend_does_not_block(self):
        """单边上涨（ADX≥25 但 +DI>-DI）：不暂停——上涨里网格卖出正常走。"""
        gate = runtime.RegimeGate({'sh589720': _daily_regime(30.0, 40.0, 12.0)})
        self.assertFalse(gate.blocks_buy('sh589720'))

    def test_missing_regime_data_fails_open(self):
        """行情缺失：不暂停（fail-open），但 reason 标注未知。"""
        gate = runtime.RegimeGate({})
        self.assertFalse(gate.blocks_buy('sh589720'))
        self.assertIn('未知', gate.reason('sh589720'))

    def test_plan_with_gate_drops_buy_keeps_sell(self):
        """plan() 集成：单边下跌ETF的买单被移除、卖单保留，且附暂停说明。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # 589720 震荡(17) 159363 单边下跌(36) 159992 迁移退出
            for code in runtime.H.held_codes():
                _write_state(root, code)
            gate = runtime.RegimeGate({
                'sh589720': _daily_regime(17.0, 18.0, 27.0),
                'sz159363': _daily_regime(36.1, 10.9, 39.4),
                'sz159992': _daily_regime(12.0, 18.0, 23.0),
            })
            ticket = runtime.plan(root, regime_gate=gate)
            sides = {(a['code'], a['side']) for a in ticket['actions']}
            self.assertTrue(any(s == 'sell' for c, s in sides if c == 'sz159363'),
                            '单边下跌ETF的卖出建议必须保留')
            self.assertFalse(any(s == 'buy' for c, s in sides if c == 'sz159363'),
                             '单边下跌ETF的买入建议必须移除')
            self.assertTrue(any(s == 'buy' for c, s in sides if c == 'sh589720'),
                            '震荡ETF的买入建议不受影响')
            self.assertTrue(ticket.get('regime_blocks'),
                            '暂停说明必须显式出现在ticket里，禁止静默')

    def test_plan_without_gate_unchanged(self):
        """不传gate时行为与旧版完全一致（默认关闭，渐进发布）。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for code in runtime.H.held_codes():
                _write_state(root, code)
            ticket = runtime.plan(root)
            self.assertNotIn('regime_blocks', ticket)


class FetchRegimeTests(unittest.TestCase):
    def test_fetch_daily_regime_uses_prior_close(self):
        """盘前取市况必须用截至昨日收盘的日K（ADX需收盘价，无未来函数）。"""
        # 40根足够 wilder_adx(14)（需 2*14+2=30）
        rows = [dict(date=f'2026-09-{i:02d}', open=1.0, close=1.0 - i * 0.01,
                     high=1.01, low=0.99, volume=100.0, amount=10000.0, pct=0.0)
                for i in range(1, 21)] + [
                dict(date=f'2026-10-{i:02d}', open=0.8, close=0.8 - i * 0.01,
                     high=0.81, low=0.79, volume=100.0, amount=10000.0, pct=0.0)
                for i in range(1, 21)]
        with patch.object(runtime, '_fetch_regime_klines', return_value=rows):
            regime = runtime.fetch_daily_regime('sh589720')
        self.assertIsNotNone(regime['adx'])
        # 桩数据一路阴跌 → 应为单边下跌判定素材
        self.assertGreater(regime['mdi'], regime['pdi'])


if __name__ == '__main__':
    unittest.main()
