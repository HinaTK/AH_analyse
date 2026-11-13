# -*- coding: utf-8 -*-
"""TDD：盘中门控观察推送的格式整理（Master 2026-11-13「格式有点乱，整理一下」）。

整理点：①浮点噪音 0.8019999999999999 → 三位小数；②ISO 时间改可读格式；
③分组标题 + 空行分层；④指标用 Markdown 表格；⑤超长原因按分号/均线明细折行。
语义契约保持不变：中文加粗+emoji 门控级别、两套口径并列用｜不用→、
写清本次变化、只输出与本次相关的标的、降噪规则不动。
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tools'))
import intraday_gate_watch as watch


def _alert(reason_official=None, reason_provisional=None, change=None):
    d = {
        'code': 'sh589720', 'name': '科创创新药ETF国泰', 'status': 'ok',
        'quote': {'last': 0.783, 'timestamp': '2026-11-13T13:14:57+08:00'},
        'official': {'level': 'probe_only', 'blocks_buy': False,
                     'asof': '2026-11-12',
                     'reason': reason_official or '破线未全破（试错仓），退出价 0.734；5日线 0.8019999999999999'},
        'provisional': {'level': 'no_entry', 'blocks_buy': True,
                        'reason': reason_provisional or
                                  '收盘0.783低于全部五条均线（5/10/20/30/60日线：0.799/0.791/0.787/0.805/0.856），破线计数5≥5；'
                                  '暂停买入：五线全破。等收盘先站回5日线0.799上方，自动恢复可建仓'},
        'adx': 14.33, 'pdi': 19.28, 'mdi': 20.26,
    }
    if change is not None:
        d['change'] = change
    return d


class FormatTidyTests(unittest.TestCase):
    def test_no_float_noise(self):
        out = watch._render([_alert()])
        self.assertNotIn('0.8019999999999999', out)
        self.assertIn('0.802', out)

    def test_timestamp_is_readable(self):
        out = watch._render([_alert()])
        self.assertNotIn('T13:14:57+08:00', out)
        self.assertIn('2026-11-13 13:14:57', out)

    def test_has_group_heading_and_markdown_table(self):
        out = watch._render([_alert()])
        self.assertIn('### ', out, '标的应有分组标题')
        self.assertIn('| 项 | 读数 |', out)
        self.assertIn('| --- | --- |', out)
        self.assertIn('| ADX | 14.33 |', out)
        self.assertIn('| -DI | 20.26 |', out)

    def test_long_reason_is_broken_into_lines(self):
        out = watch._render([_alert()])
        self.assertIn('5/10/20/30/60 日线：', out)
        self.assertIn('恢复条件：', out)
        longest = max(len(line) for line in out.splitlines())
        self.assertLess(longest, 120, '不应再有超长单行：%d' % longest)

    def test_parallel_line_and_change_line_contract_kept(self):
        change = dict(kind='change', **{'from': 'probe_only'}, to='no_entry',
                      official_changed=False, official_from=None, official_to=None)
        out = watch._render([_alert(change=change)])
        self.assertIn('正式 ' + watch.LEVEL_LABELS['probe_only'] + '（2026-11-12） ｜ ', out)
        self.assertNotIn('） → 盘中预估', out)
        self.assertIn('本次变化：盘中预估 由 ' + watch.LEVEL_LABELS['probe_only']
                      + ' → ' + watch.LEVEL_LABELS['no_entry'] + '（正式门控未变）', out)

    def test_level_labels_and_footer_kept(self):
        out = watch._render([_alert()])
        self.assertTrue(out.startswith(watch.HEADER))
        self.assertTrue(out.rstrip().endswith(watch.FOOTER))
        for bare in ('no_entry', 'pause_buy', 'probe_only', 'normal'):
            self.assertNotIn(bare, out)
        self.assertIn(watch.LEVEL_LABELS['probe_only'], out)
        self.assertIn(watch.LEVEL_LABELS['no_entry'], out)

    def test_multiple_alerts_each_get_own_heading(self):
        out = watch._render([_alert(), _alert()])
        self.assertEqual(out.count('### '), 2)

    def test_error_and_buy_paused_rows_intact(self):
        err = dict(code='sh589720', name='科创创新药ETF国泰', status='error',
                   message='行情超时', kind='quote')
        out = watch._render([err])
        self.assertIn('⚠️取数/状态未验证', out)
        d = _alert()
        d['buy_paused'] = True
        self.assertIn('buy_paused=true', watch._render([d]))


if __name__ == '__main__':
    unittest.main()
