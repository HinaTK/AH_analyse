"""成交确认后的「剩余操作建议」必须过门控，且只含本次入账的 ETF。

事故 2026-11-05：589720 F格卖 10,000@0.809 入账后，confirm_main 用
render(plan(root_from_home())) 打印建议——不带 regime_gate，被 pause_buy
拦截的 F格买 10,000@0.797 以普通买单出现、无 ⛔；且输出了全部 ETF。
用户规则：被拦买单须标 ⛔+原因；哪只入账只给哪只的建议。
"""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import confirmed_589720
import confirmed_runtime as runtime

CODE = 'sh589720'
OTHER_ACTIVE = ('sz159363', 'sh512980')


def _yesterday():
    return (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=1)).date().isoformat()


class ConfirmGateScopeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        codes = runtime.H.held_codes()
        for code in codes:
            inputs = [('buy', 9200, '0.877'), ('buy', 9400, '0.859')] if code == CODE else [('buy', 4600, '1.28')]
            state = confirmed_589720.build(inputs, code=code, name=code)
            state['sellable_qty'] = state['qty']
            (self.root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state), encoding='utf-8')
        holdings = {c: dict(runtime.H.load_holdings()[c]) for c in codes}
        for entry in holdings.values():
            entry.pop('buy_paused', None)
            entry.pop('quota', None)
        runtime.H.save_holdings_to_root(holdings, self.root)
        asof = _yesterday()
        cache = {}
        for code in codes:
            if code == CODE:
                cache[code] = dict(level='pause_buy', blocks_buy=True, reason=f'{code} 暂停买入(强动能跌势)：测试', adx=20.9, close='0.796', asof=asof)
            else:
                # 其它标的门控放行：若输出未按 code 过滤，它们的买单会出现在回执里
                cache[code] = dict(level='normal', blocks_buy=False, reason='正常', adx=15.0, close='1.2', asof=asof)
        (self.root / 'regime-cache.json').write_text(json.dumps(cache), encoding='utf-8')
        self._old_home = runtime.root_from_home
        runtime.root_from_home = lambda: self.root

    def tearDown(self):
        runtime.root_from_home = self._old_home
        self.folder.cleanup()

    def _confirm(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            runtime.confirm_main(['成功', '--code', CODE, '--side', 'buy', '--qty', '9600',
                                  '--price', '0.846', '--message-id', 'test-gate-scope'])
        return out.getvalue()

    def test_gated_buy_marked_not_listed(self):
        output = self._confirm()
        self.assertIn('现在的剩余操作建议', output)
        self.assertIn(f'⛔ {CODE}', output, '被门控拦截的买入必须标 ⛔ 和原因')
        buy_lines = [l for l in output.splitlines() if l.startswith(f'- ✅ {CODE}') and '条件买' in l]
        self.assertEqual(buy_lines, [], f'门控拦截时不得列出可执行买单：{buy_lines}')
        self.assertTrue(any(l.startswith(f'- ✅ {CODE}') and '条件卖' in l for l in output.splitlines()),
                        '卖出建议必须保留')

    def test_only_confirmed_code_in_advice(self):
        output = self._confirm()
        advice = output.split('现在的剩余操作建议', 1)[1]
        for code in OTHER_ACTIVE:
            self.assertNotIn(code, advice, f'只给本次入账 ETF 的建议，不应出现 {code}')


if __name__ == '__main__':
    unittest.main()
