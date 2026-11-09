# -*- coding: utf-8 -*-
"""TDD：门控级别在推送文案中一律用「中文加粗 + emoji」表示（Master 2026-11-09 要求）。

四个内部级别（LEVELS）保持不变，只改展示层，避免影响判据、快照与去重签名。
"""
import unittest

from tools.intraday_gate_watch import LEVELS, LEVEL_LABELS, _render


def _alert(official_level, provisional_level, official_blocks, provisional_blocks):
    return {
        'code': 'sz159363', 'name': '创业板人工智能ETF华宝', 'status': 'ok',
        'quote': {'last': 0.848, 'timestamp': '2026-11-09T11:15:00+08:00'},
        'official': {'level': official_level, 'blocks_buy': official_blocks,
                     'asof': '2026-11-06', 'reason': '五线全破'},
        'provisional': {'level': provisional_level, 'blocks_buy': provisional_blocks,
                        'reason': '五线全破（盘中预估）'},
        'adx': 49.85, 'pdi': 10.96, 'mdi': 35.22,
    }


class GateLevelLabelTests(unittest.TestCase):
    def test_four_levels_and_blocking_flags_unchanged(self):
        self.assertEqual(LEVELS, {
            'normal': False, 'probe_only': False,
            'pause_buy': True, 'no_entry': True})

    def test_every_level_has_chinese_bold_emoji_label(self):
        self.assertEqual(set(LEVEL_LABELS), set(LEVELS))
        for level, label in LEVEL_LABELS.items():
            with self.subTest(level=level):
                self.assertTrue(label.startswith('**') and label.endswith('**'),
                                '必须加粗：' + level)
                self.assertTrue(any(ord(ch) > 0x2000 for ch in label),
                                '必须含 emoji：' + level)
                self.assertTrue(any('\u4e00' <= ch <= '\u9fff' for ch in label),
                                '必须含中文：' + level)

    def test_render_uses_labels_for_both_sides(self):
        out = _render([_alert('no_entry', 'no_entry', True, True)])
        self.assertIn('正式 ' + LEVEL_LABELS['no_entry'], out)
        self.assertIn(LEVEL_LABELS['no_entry'] + '\n', out)
        self.assertIn('盘中预估（均线/DMI口径） ' + LEVEL_LABELS['no_entry'], out)

    def test_render_has_no_bare_english_level_names(self):
        for official, provisional, ob, pb in (
                ('no_entry', 'no_entry', True, True),
                ('pause_buy', 'probe_only', True, False),
                ('normal', 'normal', False, False)):
            with self.subTest(official=official, provisional=provisional):
                out = _render([_alert(official, provisional, ob, pb)])
                for bare in ('no_entry', 'pause_buy', 'probe_only', 'normal'):
                    self.assertNotIn(bare, out, '推送正文不得残留裸英文级别名')

    def test_transition_between_two_blocking_levels_is_readable(self):
        out = _render([_alert('no_entry', 'pause_buy', True, True)])
        self.assertIn(LEVEL_LABELS['no_entry'], out)
        self.assertIn(LEVEL_LABELS['pause_buy'], out)


if __name__ == '__main__':
    unittest.main()
