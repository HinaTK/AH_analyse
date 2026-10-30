# -*- coding: utf-8 -*-
"""TDD：全局暂停买入开关（用户2026-10-30指令"都暂停买入了"）。

规则：holdings.json 每只可配 buy_paused=true。
plan() 生成买入建议前检查：buy_paused → 不生成买入，显式⛔标注"用户暂停买入"，卖出不受限。
无 buy_paused 字段 → 不限（向后兼容）。

附带回归：quota 读取改为 state.get('quota') 若无则回退 holdings 的 quota 字段
（2026-10-29 额度机制遗留断点：holdings 有 quota 但从未同步进 state，plan() 读不到）。
"""
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import confirmed_runtime as rt
import holdings as H


def _no_gate():
    class G:
        def blocks_buy(self, code):
            return False

        def reason(self, code):
            return ''
    return G()


GRID_ACCOUNT = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account')


def _setup_root(td, buy_paused=None, holdings_quota=None, state_quota=None):
    """临时目录：589720 一格持仓可卖；其余三只拷生产文件；holdings 定向覆盖。"""
    import tempfile, json
    from confirmed_589720 import build
    trades = [('buy', 10000, '0.797')]
    state = build(trades, code='sh589720', name='x')
    state['sellable_qty'] = state['qty']
    if state_quota is not None:
        state['quota'] = state_quota
    Path(td, 'confirmed-589720.json').write_text(json.dumps(state), encoding='utf-8')
    for code in ('159363', '159992', '512980'):
        src = GRID_ACCOUNT / f'confirmed-{code}.json'
        Path(td, f'confirmed-{code}.json').write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
    if buy_paused is not None or holdings_quota is not None:
        data = json.loads((GRID_ACCOUNT / 'holdings.json').read_text(encoding='utf-8'))
        if buy_paused is not None:
            data['holdings']['sh589720']['buy_paused'] = buy_paused
        if holdings_quota is not None:
            data['holdings']['sh589720']['quota'] = holdings_quota
        Path(td, 'holdings.json').write_text(json.dumps(data), encoding='utf-8')
    return td


class BuyPausedTests(unittest.TestCase):
    def test_buy_paused_blocks_buy_keeps_sell(self):
        """buy_paused=true → 不生成买入，显式标注；卖出建议保留。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            _setup_root(td, buy_paused=True)
            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh589720']
            self.assertFalse(buys, 'buy_paused 时不得生成买入建议')
            blocked = [b for b in ticket.get('regime_blocks', []) if '暂停买入' in b and '用户' in b]
            self.assertTrue(blocked, '必须显式标注用户暂停买入')
            sells = [a for a in ticket['actions'] if a['side'] == 'sell' and a['code'] == 'sh589720']
            self.assertTrue(sells, '卖出不受暂停买入影响')

    def test_buy_paused_false_unaffected(self):
        """buy_paused=false / 缺省 → 正常生成买入（向后兼容）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            _setup_root(td, buy_paused=False)
            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh589720']
            self.assertTrue(buys, '未暂停时正常生成买入')

    def test_quota_fallback_to_holdings(self):
        """state 无 quota 但 holdings 有 → 额度检查生效（修复遗留断点）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            # 净投入≈7,971，quota=8,000 → 下一格≈7,880 投入会超 → 必须拦截
            _setup_root(td, holdings_quota='8000')
            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh589720']
            self.assertFalse(buys, 'holdings quota 超限时必须拦截买入')
            blocked = [b for b in ticket.get('regime_blocks', []) if '额度' in b]
            self.assertTrue(blocked, '必须显式标注额度用尽')

    def test_quota_state_takes_precedence(self):
        """state 与 holdings 都有 quota → 以 state 为准（现状语义）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            # state quota 50,000（充足） vs holdings quota 8,000（会拦）→ 放行
            _setup_root(td, holdings_quota='8000', state_quota='50000')
            ticket = rt.plan(td, regime_gate=_no_gate())
            buys = [a for a in ticket['actions'] if a['side'] == 'buy' and a['code'] == 'sh589720']
            self.assertTrue(buys, 'state quota 优先且充足时应放行')


if __name__ == '__main__':
    unittest.main()
