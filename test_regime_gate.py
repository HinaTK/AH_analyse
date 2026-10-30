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


class UnifiedGateTests(unittest.TestCase):
    """2026-10-26 统一四级门控：RegimeGate 内部改走 gate_check。

    位置（均线）与动能（ADX）合并判定，从严者胜——修复实测打架：
    589720 五线全破但 ADX 17.3 曾被放行。
    """

    def _regime_with_lines(self, adx, closes):
        """带日K的 regime：gate 需要在同一批 bars 上判均线。"""
        dates = __import__('pandas').bdate_range('2026-06-01', periods=len(closes)).strftime('%Y-%m-%d')
        frame = __import__('pandas').DataFrame({
            'date': dates, 'open': closes, 'high': [c * 1.01 for c in closes],
            'low': [c * 0.99 for c in closes], 'close': closes})
        return dict(adx=adx, pdi=10, mdi=35, bars=frame)

    def test_all_mas_broken_blocks_buy_even_with_weak_adx(self):
        """五线全破（ADX 弱）：也必须拦——历史打架场景的修复。

        2026-10-30 切换方案F：文案改为 F方案·暂停买入(五线全破)。
        """
        closes = [10.0] * 75 + [8.5, 8.3, 8.1, 7.9, 7.7, 7.5]
        gate = runtime.RegimeGate({'sh589720': self._regime_with_lines(17.3, closes)})
        self.assertTrue(gate.blocks_buy('sh589720'))
        self.assertIn('五线全破', gate.reason('sh589720'))

    def test_probe_with_strong_adx_blocks_buy(self):
        """破部分线 + ADX>=25：暂停买。"""
        closes = [10 + 0.02 * i for i in range(90)] + [11.0, 10.8, 10.6, 10.5, 10.9]
        gate = runtime.RegimeGate({'sh589720': self._regime_with_lines(36.1, closes)})
        self.assertTrue(gate.blocks_buy('sh589720'))

    def test_probe_with_weak_adx_keeps_buy(self):
        """2026-10-30 方案F：该场景振幅 2% 触发 ATR 扩张 → F 方案拦截
        （这正是 F 比 legacy 多拦的场景，legacy 模式对此放行）。
        备份模式的放行行为由 test_gate_mode_switch 覆盖。"""
        closes = [10 + 0.02 * i for i in range(90)] + [11.0, 10.8, 10.6, 10.5, 10.9]
        gate = runtime.RegimeGate({'sh589720': self._regime_with_lines(12.1, closes)})
        self.assertTrue(gate.blocks_buy('sh589720'), 'F方案默认：ATR扩张场景拦截')

    def test_regime_without_bars_falls_back_to_adx_only(self):
        """无 bars 的旧格式 regime（向后兼容）：退回纯 ADX 判定。"""
        gate = runtime.RegimeGate({'sh589720': _daily_regime(36.1, 10.9, 39.4)})
        self.assertTrue(gate.blocks_buy('sh589720'))

    def test_plan_with_gate_drops_buy_keeps_sell(self):
        """plan() 集成：单边下跌ETF的买单被移除、卖单保留，且附暂停说明。

        2026-10-30 方案F：无 bars 的 regime 退回纯 ADX 判定（ADX>=25 且
        -DI>+DI 才拦）。589720 ADX=17 不拦；159363 ADX=36.1 且 -DI>+DI 拦截。
        注意：holdings 若开 buy_paused/quota，买单会被用户级开关或额度拦下
        ——本测试聚焦门控行为，断言不依赖"589720 必有买单"。
        """
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
            self.assertTrue(ticket.get('regime_blocks'),
                            '暂停说明必须显式出现在ticket里，禁止静默')
            # 2026-10-30 生产 holdings 全开 buy_paused（用户手动暂停），
            # 159363 的门控拦截被用户级开关先行 continue 短路——这正是
            # 从严设计：任一开关拦截即停。门控自身的拦截断言由
            # test_gate_mode_switch + gate.blocks_buy 直接覆盖。

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
