# -*- coding: utf-8 -*-
"""TDD：门控恢复日重锚（2026-10-29 用户定，"落地一下"）。

问题：门控拦截期越长、跌得越深，恢复时旧格买价偏离现市越大——
G买价0.785 vs 恢复时现价0.75x → 僵尸单/追高，买入腿瘫痪。

规则（用户确认的方案三）：
1. 只在"门控从拦转放的首个交易日"检查一次（reanchor 事件日）
2. 偏离 = 下一格买价 / 现价 - 1；|偏离| > 1.5%（一个格距）才重锚
3. 重锚：新格买价 = 现价 × 0.985（GAP 下方一档），后续格从新锚延伸
4. 旧格原样保留（卖单挂原价等解套——"旧亏损不消失"）
5. 账本记 reanchor 事件（日期/旧锚/新锚/当时现价），格号顺延不重置
6. 卖侧不重锚
"""
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import confirmed_runtime as rt


class ReanchorTests(unittest.TestCase):
    def test_deviation_below_gap_no_reanchor(self):
        """偏离 0.6%（<1.5%）→ 不重锚，维持原格价。"""
        old_next = D('0.785')
        spot = D('0.780')
        self.assertIsNone(rt.reanchor_price(old_next, spot))

    def test_deviation_above_gap_reanchors_to_spot_below(self):
        """偏离 4%（>1.5%）→ 重锚为 现价×0.985。"""
        old_next = D('0.785')
        spot = D('0.756')
        new = rt.reanchor_price(old_next, spot)
        self.assertIsNotNone(new)
        self.assertEqual(new, rt.price(spot * (1 - rt.GAP)))

    def test_reanchor_never_above_spot(self):
        """重锚价必须低于现价（挂得出去，不追高）。"""
        old_next = D('0.785')
        spot = D('0.700')
        new = rt.reanchor_price(old_next, spot)
        self.assertLess(D(new), spot)

    @staticmethod
    def _build_root(td):
        """以真实账本为模板构造合法根（validate_state 全过），589720 换成六格测试结构。"""
        import json
        from decimal import Decimal as D

        REAL = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account')

        def make_589720():
            # 用 validate 的同一事实源 build() 生成——保证全字段一致
            from confirmed_589720 import build
            trades = [('buy', 10000, '0.877'), ('buy', 10000, '0.859'),
                      ('buy', 10000, '0.833'), ('buy', 10000, '0.821'),
                      ('buy', 10000, '0.809'), ('buy', 10000, '0.797')]
            state = build(trades, code='sh589720', name='科创创新药ETF国泰')
            state['sellable_qty'] = state['qty']
            return state

        Path(td, 'confirmed-589720.json').write_text(json.dumps(make_589720()), encoding='utf-8')
        for code in ('159363', '159992'):
            src = REAL / f'confirmed-{code}.json'
            Path(td, f'confirmed-{code}.json').write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
        return td



    def test_plan_uses_reanchor_when_gate_just_lifted(self):
        """端到端：门控恢复日 + 大偏离 → plan() 买价用重锚价。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self._build_root(td)

            class _NoGate:
                def blocks_buy(self, code):
                    return False

                def reason(self, code):
                    return ''

            ticket = rt.plan(td, regime_gate=_NoGate(), spot={'sh589720': D('0.756')},
                             gate_lifted={'sh589720': True})
            buys = [a for a in ticket['actions'] if a['side'] == 'buy']
            self.assertTrue(buys)
            # 重锚价 = 0.756×0.985 = 0.745（不是旧格价0.785）
            self.assertEqual(D(str(buys[0]['price'])), D(rt.price(D('0.756') * (1 - rt.GAP))))
            self.assertIn('reanchor', ticket)

    def test_plan_keeps_grid_price_when_small_deviation(self):
        """端到端：恢复日但偏离小（现价0.78 vs G=0.785）→ 用原格价0.785。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self._build_root(td)

            class _NoGate:
                def blocks_buy(self, code):
                    return False

                def reason(self, code):
                    return ''

            ticket = rt.plan(td, regime_gate=_NoGate(), spot={'sh589720': D('0.780')},
                             gate_lifted={'sh589720': True})
            buys = [a for a in ticket['actions'] if a['side'] == 'buy']
            self.assertEqual(D(str(buys[0]['price'])), D('0.785'))

    def test_plan_no_reanchor_without_spot(self):
        """无现价（盘前旧路径）→ 行为与现状完全一致。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self._build_root(td)

            class _NoGate:
                def blocks_buy(self, code):
                    return False

                def reason(self, code):
                    return ''

            ticket = rt.plan(td, regime_gate=_NoGate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy']
            self.assertEqual(D(str(buys[0]['price'])), D('0.785'))


if __name__ == '__main__':
    unittest.main()
