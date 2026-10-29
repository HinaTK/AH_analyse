# -*- coding: utf-8 -*-
"""TDD：额度机制（quota）——给额度不是买入（用户2026-10-22定语义，10-29落地）。

规则：holdings.json 每只可配 quota（总净投入上限）。
plan() 生成买入建议前检查：该ETF当前净投入 + 本次买入金额 ≤ quota。
超限 → 不生成买入（卖出生成不受限），显式标注"额度用尽"而非静默。
无 quota 字段 → 不限（向后兼容，159363/159992 不设）。
"""
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import confirmed_runtime as rt


def _no_gate():
    class G:
        def blocks_buy(self, code):
            return False

        def reason(self, code):
            return ''
    return G()


class QuotaTests(unittest.TestCase):
    def test_buy_blocked_when_quota_exhausted(self):
        """净投入已到额度 → 买入建议不生成，标'额度用尽'。"""
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            from confirmed_589720 import build
            trades = [('buy', 10000, '0.797')]
            state = build(trades, code='sh589720', name='x')
            state['sellable_qty'] = state['qty']
            # 净投入 ≈ 7,970+1佣金 ≈ 7,971；quota 设 8,000 → 下一格买入 8,000×0.985 ≈ 7,880 会超
            state['quota'] = '8000'
            Path(td, 'confirmed-589720.json').write_text(json.dumps(state), encoding='utf-8')
            for code in ('159363', '159992', '512980'):
                src = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account') / f'confirmed-{code}.json'
                Path(td, f'confirmed-{code}.json').write_text(src.read_text(encoding='utf-8'), encoding='utf-8')

            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh589720']
            self.assertFalse(buys, '额度用尽时不得生成买入建议')
            blocked = [b for b in ticket.get('regime_blocks', []) if '额度' in b]
            self.assertTrue(blocked, '必须显式标注额度用尽')
            # 卖出建议不受额度限制
            sells = [a for a in ticket['actions'] if a['side'] == 'sell' and a['code'] == 'sh589720']
            self.assertTrue(sells, '卖出不受额度限制')

    def test_no_quota_means_unlimited(self):
        """无 quota 字段 → 行为与现状完全一致（向后兼容）。"""
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            from confirmed_589720 import build
            trades = [('buy', 10000, '0.797')]
            state = build(trades, code='sh589720', name='x')
            state['sellable_qty'] = state['qty']
            Path(td, 'confirmed-589720.json').write_text(json.dumps(state), encoding='utf-8')
            for code in ('159363', '159992', '512980'):
                src = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account') / f'confirmed-{code}.json'
                Path(td, f'confirmed-{code}.json').write_text(src.read_text(encoding='utf-8'), encoding='utf-8')

            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh589720']
            self.assertTrue(buys, '无quota时正常生成买入')

    def test_quota_allows_buy_within_limit(self):
        """额度充足 → 正常买入。"""
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            from confirmed_589720 import build
            trades = [('buy', 10000, '0.797')]
            state = build(trades, code='sh589720', name='x')
            state['sellable_qty'] = state['qty']
            state['quota'] = '50000'  # 充足
            Path(td, 'confirmed-589720.json').write_text(json.dumps(state), encoding='utf-8')
            for code in ('159363', '159992', '512980'):
                src = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account') / f'confirmed-{code}.json'
                Path(td, f'confirmed-{code}.json').write_text(src.read_text(encoding='utf-8'), encoding='utf-8')

            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh589720']
            self.assertTrue(buys)


if __name__ == '__main__':
    unittest.main()


class FirstGridTests(unittest.TestCase):
    def test_empty_ledger_generates_first_grid_buy(self):
        """空仓注册标的（如512980首格前）：entry_price 存在 → 生成首格买入。"""
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            from confirmed_589720 import build
            state = build([], code='sh512980', name='传媒ETF广发')
            state['sellable_qty'] = 0
            state['entry_price'] = '0.780'
            Path(td, 'confirmed-512980.json').write_text(json.dumps(state), encoding='utf-8')
            for code in ('589720', '159363', '159992'):
                src = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account') / f'confirmed-{code}.json'
                Path(td, f'confirmed-{code}.json').write_text(src.read_text(encoding='utf-8'), encoding='utf-8')

            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh512980']
            self.assertEqual(len(buys), 1, '空仓+entry_price 必须生成首格买入')
            self.assertEqual(buys[0]['lot'], 'A')
            self.assertEqual(buys[0]['price'], '0.780')  # price() 返回str（三位小数）
            # 8000预算 / 0.78 = 10,256 → 取整百 10,200
            self.assertEqual(buys[0]['qty'], 10200)

    def test_empty_ledger_without_entry_price_no_buy(self):
        """空仓且无 entry_price → 不生成买入（不猜价格）。"""
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            from confirmed_589720 import build
            state = build([], code='sh512980', name='传媒ETF广发')
            state['sellable_qty'] = 0
            Path(td, 'confirmed-512980.json').write_text(json.dumps(state), encoding='utf-8')
            for code in ('589720', '159363', '159992'):
                src = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account') / f'confirmed-{code}.json'
                Path(td, f'confirmed-{code}.json').write_text(src.read_text(encoding='utf-8'), encoding='utf-8')

            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh512980']
            self.assertEqual(buys, [])
