# -*- coding: utf-8 -*-
"""TDD：上涨侧持仓管理（2026-11-07 Master 拍板口径）。

规则：**不定份额底仓，按格子**——只要不是明确退出该 ETF（迁移退出/active=false），
就保留两格；低库存（≤2 格且已卖过）时出「上移基准人工复核」只读提醒。

只读层：不写账本、不改买价、不自动上移基准/抬高买价/追涨/换仓。
测试全部使用临时根 + patch 持仓枚举，不读取、不写入任何真实账本。
"""
import hashlib
import json
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import holdings as H
import confirmed_runtime as rt
import upside_guard as ug
from confirmed_589720 import build

CODE = 'sh589720'


def _state(trades, sellable=None):
    state = build(trades, code=CODE, name='测试ETF')
    state['sellable_qty'] = state['qty'] if sellable is None else sellable
    return state


def _root(td, state, active=True):
    Path(td, f'confirmed-{CODE[-6:]}.json').write_text(
        json.dumps(state, ensure_ascii=False), encoding='utf-8')
    Path(td, 'holdings.json').write_text(json.dumps(
        {'holdings': {CODE: {'name': '测试ETF', 'lot_budget': '12000', 'active': active}}},
        ensure_ascii=False), encoding='utf-8')
    return td


def _plan(td, spot=None):
    with patch.object(H, 'held_codes', return_value=(CODE,)):
        return rt.plan(td, spot=spot)


def _hash(td):
    return hashlib.sha256(
        (Path(td) / f'confirmed-{CODE[-6:]}.json').read_bytes()).hexdigest()


class GridFloorTests(unittest.TestCase):
    def test_rule_is_two_grids(self):
        self.assertEqual(ug.CORE_GRIDS, 2)

    def test_at_two_grids_no_sell_and_explicit_notice(self):
        """剩两格 → 不生成卖单，且显式说明是保留两格保护。"""
        with tempfile.TemporaryDirectory() as td:
            _root(td, _state([('buy', 10000, '0.800'), ('buy', 10000, '0.787')]))
            ticket = _plan(td)
            self.assertFalse(any(a['side'] == 'sell' for a in ticket['actions']),
                             '两格是保留下限，不得再卖')
            self.assertTrue(any('保留两格' in t for t in ticket.get('core_protected', [])),
                            '必须显式说明，不静默')

    def test_three_grids_allows_one_sell(self):
        """三格卖一格后仍剩两格 → 允许正常卖出。"""
        with tempfile.TemporaryDirectory() as td:
            trades = [('buy', 10000, '0.800'), ('buy', 10000, '0.787'),
                      ('buy', 10000, '0.775')]
            _root(td, _state(trades))
            ticket = _plan(td)
            self.assertTrue(any(a['side'] == 'sell' for a in ticket['actions']))

    def test_explicit_exit_not_protected(self):
        """明确退出（迁移退出/active=false）不受保留两格约束。"""
        with tempfile.TemporaryDirectory() as td:
            state = _state([('buy', 10000, '0.800'), ('buy', 10000, '0.787')])
            _root(td, state, active=False)
            self.assertFalse(
                ug.sell_blocked_by_grid_floor(state, H.load_holdings_from_root(td), CODE))
            ticket = _plan(td)
            self.assertFalse(ticket.get('core_protected'))

    def test_low_inventory_emits_manual_review_with_facts(self):
        """低库存 → 提醒含库存/已卖轮数/最近卖出价/已核实收盘价偏离/免责词。"""
        with tempfile.TemporaryDirectory() as td:
            state = _state([('buy', 10000, '0.800'), ('sell', 10000, '0.820'),
                            ('buy', 10000, '0.790')])
            _root(td, state)
            ticket = _plan(td, spot={CODE: D('0.900')})
            reviews = ticket.get('upside_reviews') or []
            self.assertEqual(len(reviews), 1)
            r = reviews[0]
            self.assertEqual(r['code'], CODE)
            self.assertEqual(r['qty'], 10000)
            self.assertEqual(r['open_grids'], 1)
            self.assertEqual(r['sold_rounds'], 1)
            self.assertEqual(str(r['last_sell_price']), '0.820')
            for word in ('上移基准人工复核', '当前库存', '已卖', '最近卖出价', '已核实收盘价',
                         '保留两格', '不自动上移基准', '不自动抬高既有买价', '不自动追涨'):
                with self.subTest(word=word):
                    self.assertIn(word, r['text'])
            self.assertIn('9.8', r['text'])

    def test_no_review_when_inventory_healthy(self):
        with tempfile.TemporaryDirectory() as td:
            trades = [('buy', 10000, '0.800')]
            for i in range(4):
                trades.append(('buy', 10000, str(round(0.787 - i * 0.012, 3))))
            _root(td, _state(trades))
            self.assertFalse(_plan(td, spot={CODE: D('0.900')}).get('upside_reviews'))

    def test_no_spot_no_fabricated_deviation(self):
        with tempfile.TemporaryDirectory() as td:
            state = _state([('buy', 10000, '0.800'), ('sell', 10000, '0.820'),
                            ('buy', 10000, '0.790')])
            _root(td, state)
            text = _plan(td, spot=None)['upside_reviews'][0]['text']
            self.assertIn('已核实收盘价未取得', text)
            self.assertNotIn('%', text)

    def test_render_shows_review_and_disclaimer(self):
        with tempfile.TemporaryDirectory() as td:
            state = _state([('buy', 10000, '0.800'), ('sell', 10000, '0.820'),
                            ('buy', 10000, '0.790')])
            _root(td, state)
            out = rt.render(_plan(td, spot={CODE: D('0.900')}))
            self.assertIn('上移基准人工复核', out)
            self.assertIn('不自动追涨', out)

    def test_plan_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            state = _state([('buy', 10000, '0.800'), ('sell', 10000, '0.820'),
                            ('buy', 10000, '0.790')])
            _root(td, state)
            before = _hash(td)
            plain = _plan(td, spot=None)
            plain_buys = [str(a['price']) for a in plain['actions'] if a['side'] == 'buy']
            with_spot = _plan(td, spot={CODE: D('0.900')})
            spot_buys = [str(a['price']) for a in with_spot['actions'] if a['side'] == 'buy']
            self.assertEqual(before, _hash(td), 'plan 不得写账本')
            self.assertEqual(plain_buys, spot_buys, '不得自动抬高既有买价')

    def test_eod_report_carries_review(self):
        with tempfile.TemporaryDirectory() as td:
            state = _state([('buy', 10000, '0.800'), ('sell', 10000, '0.820'),
                            ('buy', 10000, '0.790')])
            _root(td, state)
            from datetime import datetime
            quote = {'time': '20261107150000', 'last': '0.790'}
            bars = [{'date': '2026-11-07', 'close': '0.790'}]
            with patch.object(H, 'held_codes', return_value=(CODE,)):
                report = rt.eod_report(td, datetime(2026, 11, 7), {CODE: quote}, {CODE: bars})
            self.assertIn('上移基准人工复核', report['decisions'][CODE]['upside_review'])
            self.assertIn('上移基准人工复核', rt.render_eod(report))


if __name__ == '__main__':
    unittest.main()
