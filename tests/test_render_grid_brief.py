# -*- coding: utf-8 -*-
"""TDD: 09:20 盘前条件建议紧凑渲染（2026-11-23 Master 指出「排版好乱、文字有点多」）。

只做展示层整形，不改任何数字、门控级别、账本口径：
1. 持仓表格化（代码+名称 / 持有 / 可卖 / 最大格 / 净投入 / 做T净），迁移退出标的标「只读」；
2. 门控理由压缩成「五线全破（收盘 X / 5日线 Y）· ADX Z」，无法压缩时原样保留；
3. 免责说明移到末尾，标题由调用方给（不在正文里再叠一行）。
"""
import unittest
from unittest.mock import patch

import confirmed_runtime as runtime


def _ticket():
    return dict(
        states={
            'sh589720': dict(qty=82900, sellable_qty=82900, max_grid='G',
                             net_invested='65276.52', t_net='2694.77'),
            'sz159992': dict(qty=18300, sellable_qty=18300, max_grid='B',
                             net_invested='15552.10', t_net='315.60'),
        },
        names={'sh589720': '科创创新药ETF国泰', 'sz159992': '创新药ETF银华'},
        actions=[dict(code='sh589720', side='sell', lot='G', qty=15200, price='0.797')],
        regime_blocks=[
            'sh589720 **⛔ 禁止建仓**：收盘0.679低于全部五条均线'
            '（5/10/20/30/60日线：0.717/0.757/0.766/0.778/0.834），破线计数5≥5；'
            '暂停买入：五线全破。等收盘先站回5日线0.717上方，自动恢复可建仓；'
            'ADX=20.1 强动能（双重确认）',
        ],
        warning=runtime.WARNING,
    )


def _render(ticket):
    with patch.object(runtime.H, 'is_active', side_effect=lambda code: code != 'sz159992'):
        return runtime.render_grid_brief(ticket)


class RenderGridBriefTests(unittest.TestCase):
    def setUp(self):
        self.out = _render(_ticket())
        self.lines = self.out.splitlines()

    def test_holdings_become_table_with_thousand_separator(self):
        self.assertIn('| 标的 | 持有 | 可卖 | 最大格 | 净投入 | 做T净 |', self.lines)
        row = next(line for line in self.lines if line.startswith('| sh589720 '))
        self.assertIn('科创创新药ETF国泰', row)
        self.assertIn('82,900', row)
        self.assertIn('65,276.52', row)
        self.assertIn('| G |', row)

    def test_migration_exit_marked_readonly(self):
        row = next(line for line in self.lines if line.startswith('| sz159992 '))
        self.assertIn('（只读）', row)
        self.assertIn('18,300', row)

    def test_gate_reason_compressed_keeps_close_ma5_adx(self):
        gate = next(line for line in self.lines if '禁止建仓' in line)
        self.assertIn('**⛔ sh589720 禁止建仓**', gate)
        self.assertIn('收盘 0.679', gate)
        self.assertIn('5日线 0.717', gate)
        self.assertIn('ADX 20.1', gate)
        # 压缩后不再罗列五档均线明细
        self.assertNotIn('0.757', gate)

    def test_adx_fall_branch_compressed(self):
        ticket = _ticket()
        ticket['regime_blocks'] = [
            'sh589720 **⏸️ 暂停买入**：ADX=21.2>=20 且 -DI 31 > +DI 15，'
            '收盘 0.712 在 60日线 0.830 下方，强动能跌势，暂停新格买入，卖出保留']
        out = _render(ticket)
        gate = next(line for line in out.splitlines() if '暂停买入' in line)
        self.assertIn('**⏸️ sh589720 暂停买入**', gate)
        self.assertIn('强动能跌势（收盘 0.712 / 60日线 0.830）', gate)
        self.assertIn('ADX 21.2', gate)
        self.assertNotIn('-DI', gate)

    def test_uncompressible_block_kept_verbatim(self):
        ticket = _ticket()
        ticket['regime_blocks'] = ['sz159363 额度用尽：净投入 45,855.40 超过额度 40,000（给额度≠买入）']
        out = _render(ticket)
        self.assertIn('sz159363 额度用尽：净投入 45,855.40 超过额度 40,000（给额度≠买入）', out)

    def test_actions_keep_icon_and_bold_qty_price(self):
        action = next(line for line in self.lines if line.startswith('- ✅'))
        self.assertEqual(
            action,
            '- ✅ sh589720 科创创新药ETF国泰 条件卖 G格 **15,200份** @ **0.797**')

    def test_warning_moves_to_last_line(self):
        self.assertTrue(self.lines[-1].startswith('⚠️ '), self.lines[-1])
        self.assertIn('触价不等于成交', self.lines[-1])

    def test_no_duplicate_title_inside_body(self):
        self.assertNotIn('【', self.out)

    def test_gate_level_never_bare_english(self):
        for level in ('no_entry', 'pause_buy', 'probe_only', 'normal'):
            self.assertNotIn(level, self.out)


if __name__ == '__main__':
    unittest.main()