# -*- coding: utf-8 -*-
"""TDD RED：15:35 市况信号与 15:30 门控拦买结论打架（Master 2026-11-10）。

要求：对门控拦买的持仓标的，市况汇总表不得出现任何买入措辞，
降级为「方向仓观察·0成」并写明门控级别；门控状态未知时 fail-closed；
指数行不受影响；三信号齐的 🔔 买入铃铛也不得对拦买标的响。
"""
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# import 前钉死到不存在的目录，避免模块级 HOLDINGS_PATH 读到任何真实账本
os.environ['HERMES_HOME'] = str(REPO / '.cache' / 'no-such-home-for-tests')
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tools'))

import market_phase_check as mp


def _row(secid='0.159363', label='试仓买入', fraction='1成',
         reason='周线金叉先行，日线动能 ADX=50 未衰竭，轻仓试探', trigger=False):
    return {
        'name': '159363创业板人工智能ETF华宝', 'secid': secid,
        'date': '2026-11-10', 'close': 0.87, 'pct': 3.33,
        'label': label, 'fraction': fraction, 'reason': reason,
        'signals': {'dilVolume': False, 'adx_break': False,
                    'kdj_golden': True, 'trigger': trigger},
        'ma_pos': {}, 'vol_ratio': 0.55, 'adx': 50.0, 'adx_prev': 52.0,
        'pdi': 11.0, 'mdi': 33.0, 'dd250': -25.0, 'trend': 'down',
        'kdj_k': 42.0,
    }


class GateAlignmentTests(unittest.TestCase):
    def test_blocked_holding_is_downgraded_to_observation(self):
        out = mp.apply_gate_alignment(
            [_row()], {'0.159363': {'level': 'pause_buy', 'blocks_buy': True}})[0]
        self.assertEqual(out['label'], '方向仓观察')
        self.assertEqual(out['fraction'], '0成')
        self.assertIn('**⏸️ 暂停买入**', out['reason'])
        self.assertIn('不生成买入动作', out['reason'])
        self.assertIn('周线金叉先行', out['reason'])  # 原信号不丢失
        self.assertTrue(out['gate_blocked'])
        self.assertNotIn('买入', out['label'] + out['fraction'])

    def test_no_entry_uses_forbidden_label(self):
        out = mp.apply_gate_alignment(
            [_row()], {'0.159363': {'level': 'no_entry', 'blocks_buy': True}})[0]
        self.assertIn('**⛔ 禁止建仓**', out['reason'])

    def test_unblocked_holding_keeps_original_action(self):
        for level in ('probe_only', 'normal'):
            out = mp.apply_gate_alignment(
                [_row()], {'0.159363': {'level': level, 'blocks_buy': False}})[0]
            self.assertEqual(out['label'], '试仓买入')
            self.assertEqual(out['fraction'], '1成')
            self.assertFalse(out.get('gate_blocked', False))

    def test_index_row_never_downgraded(self):
        out = mp.apply_gate_alignment(
            [_row(secid='1.000001', label='空仓观望', fraction='0成')],
            {'0.159363': {'level': 'no_entry', 'blocks_buy': True}})[0]
        self.assertEqual(out['label'], '空仓观望')

    def test_unknown_gate_fails_closed(self):
        out = mp.apply_gate_alignment([_row()], {'0.159363': None})[0]
        self.assertEqual(out['label'], '方向仓观察')
        self.assertIn('未核实', out['reason'])
        self.assertTrue(out['gate_blocked'])

    def test_header_states_gate_alignment(self):
        text = mp.render_header('2026-11-10')
        self.assertIn('门控', text)
        self.assertIn('不生成买入动作', text)

    def test_report_has_no_buy_wording_for_blocked(self):
        out = mp.apply_gate_alignment(
            [_row()], {'0.159363': {'level': 'pause_buy', 'blocks_buy': True}})
        text = mp.render_report(out)
        self.assertNotIn('试仓买入', text)
        self.assertIn('方向仓观察', text)
        self.assertIn('**⏸️ 暂停买入**', text)

    def test_trigger_bell_suppressed_for_blocked(self):
        blocked = _row(trigger=True)
        blocked['gate_blocked'] = True
        self.assertFalse(mp.trigger_eligible(blocked))
        self.assertTrue(mp.trigger_eligible(_row(trigger=True)))

    def test_level_labels_match_production_constants(self):
        """守门：四档中文加粗+emoji 文案与生产常量一致，防漂移。"""
        import confirmed_runtime as rt
        from tools.intraday_gate_watch import LEVEL_LABELS
        self.assertEqual(mp.GATE_LEVEL_LABELS, rt.LEVEL_NAMES_CN)
        self.assertEqual(mp.GATE_LEVEL_LABELS, LEVEL_LABELS)

    def test_load_gate_map_from_injected_files(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'holdings.json').write_text(json.dumps({'holdings': {
                'sz159363': {'name': '创业板人工智能ETF华宝', 'active': True},
            }}), encoding='utf-8')
            (root / 'regime-cache.json').write_text(json.dumps({
                'sz159363': {'level': 'pause_buy', 'blocks_buy': True,
                                        'asof': '2026-11-10'},
            }), encoding='utf-8')
            gates = mp.load_gate_map(root / 'holdings.json', root / 'regime-cache.json')
            self.assertIn('0.159363', gates)
            self.assertTrue(gates['0.159363']['blocks_buy'])


if __name__ == '__main__':
    unittest.main()
