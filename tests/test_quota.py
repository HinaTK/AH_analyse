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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import confirmed_runtime as rt
import holdings as H


def _no_gate():
    class G:
        def blocks_buy(self, code):
            return False

        def reason(self, code):
            return ''
    return G()


def _write_holdings(td, include_512980=False):
    """把生产 holdings 拷进临时根并清掉 buy_paused：测试不得继承用户当前暂停状态。

    2026-11-09：512980 已按 Master 指示从两链枚举移除；首格测试需显式注册该
    夹具标的，才能让「空仓注册标的」用例与真实配置解耦（测试隔离要求）。
    """
    import json
    src = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account/holdings.json')
    data = json.loads(src.read_text(encoding='utf-8'))
    for entry in data['holdings'].values():
        entry.pop('buy_paused', None)
    if include_512980:
        data['holdings'].setdefault('sh512980', dict(
            name='传媒ETF广发', lot_budget='8000', active=True, quota=30000))
    Path(td, 'holdings.json').write_text(json.dumps(data), encoding='utf-8')


class QuotaTests(unittest.TestCase):
    def test_buy_blocked_when_quota_exhausted(self):
        """净投入已到额度 → 买入建议不生成，标'额度用尽'。"""
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            from confirmed_589720 import build
            # 2026-11-07 起「保留两格」是新规则：夹具需 ≥3 格才能验证卖出不受额度限制。
            # 三格净投入约 23,553；quota 8,000 → 下一格买入必超，仍测「额度用尽」。
            trades = [('buy', 10000, '0.797'), ('buy', 10000, '0.785'),
                      ('buy', 10000, '0.773')]
            state = build(trades, code='sh589720', name='x')
            state['sellable_qty'] = state['qty']
            state['quota'] = '8000'
            Path(td, 'confirmed-589720.json').write_text(json.dumps(state), encoding='utf-8')
            for code in ('159363', '159992', '512980'):
                src = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account') / f'confirmed-{code}.json'
                Path(td, f'confirmed-{code}.json').write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
            _write_holdings(td)

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
            _write_holdings(td)

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
            _write_holdings(td)

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
            _write_holdings(td, include_512980=True)
            codes = ('sh589720', 'sz159363',
                     'sz159992', 'sh512980')
            with patch.object(H, 'held_codes', return_value=codes):
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
            _write_holdings(td, include_512980=True)
            codes = ('sh589720', 'sz159363',
                     'sz159992', 'sh512980')
            with patch.object(H, 'held_codes', return_value=codes):
                ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh512980']
            self.assertEqual(buys, [])
