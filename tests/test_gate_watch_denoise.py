# -*- coding: utf-8 -*-
"""TDD：盘中门控观察 ①文案写清变化 ②降噪（Master 2026-11-09 授权「按推荐」）。

背景：12 拍里 159363 推了 5 次，但拦买结论从头到尾没变；
「暂停买入 ↔ 禁止建仓」两档都拦买，价格贴 5 日线来回跳就推一条，属噪音。
且旧文案 `正式 X → 盘中预估 Y` 的箭头是并列对照、被误读成状态迁移，
真正触发推送的「盘中预估变了什么」一个字没写。
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tools'))
import intraday_gate_watch as watch


def _alert(official_level, provisional_level, official_blocks, provisional_blocks,
           change=None):
    d = {
        'code': 'sz159363', 'name': '创业板人工智能ETF华宝', 'status': 'ok',
        'quote': {'last': 0.848, 'timestamp': '2026-11-09T11:15:00+08:00'},
        'official': {'level': official_level, 'blocks_buy': official_blocks,
                     'asof': '2026-11-06', 'reason': '五线全破'},
        'provisional': {'level': provisional_level, 'blocks_buy': provisional_blocks,
                        'reason': '五线全破（盘中预估）'},
        'adx': 49.85, 'pdi': 10.96, 'mdi': 35.22,
    }
    if change is not None:
        d['change'] = change
    return d


class DenoiseRuleTests(unittest.TestCase):
    """② 降噪：只在拦买结论翻转或正式门控变化时推。"""

    def test_both_blocking_level_flip_is_silent(self):
        # 11:15 与 11:30 的真实情形：暂停买入 ↔ 禁止建仓，两档都拦买
        off = ['no_entry', True]
        self.assertIsNone(watch._alert_reason(['pause_buy', True],
                                              ['no_entry', True], off, off))
        self.assertIsNone(watch._alert_reason(['no_entry', True],
                                              ['pause_buy', True], off, off))

    def test_both_releasing_level_flip_is_silent(self):
        off = ['normal', False]
        self.assertIsNone(watch._alert_reason(['probe_only', False],
                                              ['normal', False], off, off))

    def test_block_flip_from_release_to_block_alerts(self):
        reason = watch._alert_reason(['normal', False], ['no_entry', True],
                                    ['no_entry', True], ['no_entry', True])
        self.assertIsNotNone(reason)
        self.assertEqual(reason['from'], 'normal')
        self.assertEqual(reason['to'], 'no_entry')

    def test_block_flip_from_block_to_release_alerts(self):
        self.assertIsNotNone(watch._alert_reason(['pause_buy', True],
                                                 ['normal', False],
                                                 ['normal', False], ['normal', False]))

    def test_official_gate_change_still_alerts(self):
        """正式门控变化必须推，即使盘中预估没变。"""
        reason = watch._alert_reason(['no_entry', True], ['no_entry', True],
                                    ['pause_buy', True], ['no_entry', True])
        self.assertIsNotNone(reason)
        self.assertTrue(reason['official_changed'])

    def test_first_run_only_when_two_readings_disagree_on_blocking(self):
        self.assertIsNotNone(watch._alert_reason(None, ['normal', False],
                                                 None, ['no_entry', True]))
        self.assertIsNone(watch._alert_reason(None, ['no_entry', True],
                                              None, ['no_entry', True]))


class ChangeLineTests(unittest.TestCase):
    """① 文案：并列符 + 写清本次变化。"""

    def test_parallel_line_uses_separator_not_transition_arrow(self):
        out = watch._render([_alert('no_entry', 'no_entry', True, True)])
        self.assertIn('正式 ' + watch.LEVEL_LABELS['no_entry'] + '（2026-11-06） ｜ ', out)
        self.assertNotIn('） → 盘中预估', out)

    def test_change_line_states_before_and_after(self):
        change = dict(kind='change', **{'from': 'normal'}, to='no_entry',
                      official_changed=False, official_from=None, official_to=None)
        out = watch._render([_alert('no_entry', 'no_entry', True, True, change)])
        self.assertIn('本次变化：盘中预估 由 ' + watch.LEVEL_LABELS['normal']
                      + ' → ' + watch.LEVEL_LABELS['no_entry'] + '（正式门控未变）', out)

    def test_change_line_mentions_official_change(self):
        change = dict(kind='change', **{'from': 'no_entry'}, to='normal',
                      official_changed=True, official_from='pause_buy',
                      official_to='normal')
        out = watch._render([_alert('normal', 'normal', False, False, change)])
        self.assertIn('正式门控由', out)
        self.assertIn(watch.LEVEL_LABELS['pause_buy'], out)

    def test_first_run_change_line(self):
        change = dict(kind='first', **{'from': None}, to='normal',
                      official_changed=False, official_from=None, official_to=None)
        out = watch._render([_alert('pause_buy', 'normal', True, False, change)])
        self.assertIn('本次变化：本交易日首拍', out)

    def test_render_still_has_no_bare_english_levels(self):
        out = watch._render([_alert('no_entry', 'no_entry', True, True,
                                    dict(kind='first', **{'from': None},
                                         to='no_entry', official_changed=False,
                                         official_from=None, official_to=None))])
        for bare in ('no_entry', 'pause_buy', 'probe_only', 'normal'):
            self.assertNotIn(bare, out)


if __name__ == '__main__':
    unittest.main()
