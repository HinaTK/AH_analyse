# -*- coding: utf-8 -*-
"""TDD for EOD 表格化改造（用户 2026-10-26 要求：15:20 每日任务输出表格，
含 ①总的做T情况 ②当天做T情况，两者都由脚本产出）。

RED：现有 render_eod 是逐行文字，没有 markdown 表格、没有当日做T表。
"""
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json


def _build_report(root, trades, **kw):
    """构造最小 eod_report 输入：build 生成一致账本，t_records 保持 build 原样，
    日期只注入 trades（validate_state 重放核对 t_records 必须逐字节一致）。"""
    import confirmed_runtime as runtime
    import confirmed_589720
    codes = runtime.H.held_codes()
    for code in codes:
        inputs = None
        if code == 'sh589720':
            inputs = [(t['side'], t['qty'], t['price']) for t in trades]
        state = confirmed_589720.build(inputs, code=code, name=code)
        state['sellable_qty'] = state['qty'] if state['qty'] else 0
        if code == 'sh589720':
            date_map = {t['id']: t['date'] for t in trades}
            for t in state['trades']:
                t['date'] = date_map.get(t['id'])
        (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    now = datetime(2026, 10, 26, 15, 20, tzinfo=timezone(timedelta(hours=8)))
    quotes = {code: dict(time='20261026150000', last='0.8', high='0.9', low='0.7') for code in codes}
    bars = {code: [dict(date='2026-10-26', close='0.8')] for code in codes}
    return runtime.eod_report(root, now, quotes, bars)


TODAY_TRADES = [
    dict(id='589720-001', sequence=1, code='sh589720', side='buy', qty=10000, price='0.797',
         lot='F', date='2026-10-26', fee='1.00', amount='7970.00', source='explicit_confirmed_fill'),
    dict(id='589720-002', sequence=2, code='sh589720', side='sell', qty=10000, price='0.809',
         lot='F', date='2026-10-26', fee='1.00', amount='8090.00', source='explicit_confirmed_fill'),
]
# t_records 保持 build 的原样（validate_state 会重放核对逐字节一致）。
# 日期信息只存在 trades 里（daily 统计从 trades + t_records 的 sell_id 关联出日期）。
def _build_inputs_and_records(trades):
    """从描述性 trades 生成 (inputs, id_order)——t_records 直接用 build 的输出。"""
    inputs = [(t['side'], t['qty'], t['price']) for t in trades]
    return inputs


class EodTableTests(unittest.TestCase):
    def test_render_eod_outputs_markdown_tables_for_total_and_today(self):
        import tempfile
        import confirmed_runtime as runtime
        with tempfile.TemporaryDirectory() as directory:
            report = _build_report(Path(directory), TODAY_TRADES)
            text = runtime.render_eod(report)
            # ① 持仓概览表
            self.assertIn('| ETF |', text)
            self.assertIn('|---', text)
            self.assertIn('sh589720', text)
            # ② 总做T表
            self.assertIn('累计做T', text)
            # ③ 当日做T表
            self.assertIn('当日做T', text)
            self.assertIn('2026-10-26', text)
            self.assertIn('118.00', text)
            # 当日表合计行
            self.assertIn('合计', text)

    def test_report_contains_summary_from_grid_summary(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            report = _build_report(Path(directory), TODAY_TRADES)
            self.assertIn('summary', report)
            self.assertIn('daily', report['summary'])
            self.assertEqual(report['summary']['daily']['2026-10-26']['rounds'], 1)
            self.assertEqual(report['summary']['daily']['2026-10-26']['t_net'], '118.00')

    def test_today_empty_when_no_trades_today(self):
        import tempfile
        import confirmed_runtime as runtime
        trades = [dict(TODAY_TRADES[0], date='2026-10-20'),
                  dict(TODAY_TRADES[1], date='2026-10-20')]
        with tempfile.TemporaryDirectory() as directory:
            report = _build_report(Path(directory), trades)
            text = runtime.render_eod(report)
            self.assertIn('当日无成交', text)


if __name__ == '__main__':
    unittest.main()
