# -*- coding: utf-8 -*-
"""TDD：512980 传媒ETF 按 Master 2026-11-09 指示「先不开，去掉」从持仓枚举移除，
2026-11-16 进一步指示「去掉」→ 空账本归档出活跃路径（可恢复）。

「去掉」= 不再枚举、不再生成任何买卖建议；2026-11-16 起空账本也不在活跃路径，
归档到 grid-account/backups/ 保留（可恢复），活跃路径不再含 confirmed-512980.json。

验证范围：
  1. 副本链 holdings.json 不再含该标的
  2. 运行时 plan() 不再为它生成动作、也不再载入它的账本
  3. 空账本不在活跃路径，backups/ 中保留且可恢复（qty=0、无成交）
  4. 两链配置都不含该标的（既有字节一致契约 + 00:01 配置一致性守卫的配套）
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(r'D:\Code\AH_analyse')
sys.path.insert(0, str(REPO))

CODE = 'sh512980'
GRID_ACCOUNT = REPO / '.cache' / 'grid-home' / 'cache' / 'grid-account'
DSH = GRID_ACCOUNT / 'holdings.json'
BACKUPS = GRID_ACCOUNT / 'backups'
PROD = Path(r'D:\Hermes Agent CN Desktop\data\hermes-home\cache\grid-account\holdings.json')


def _holdings(path):
    return json.loads(path.read_text(encoding='utf-8'))['holdings']


class Remove512980Tests(unittest.TestCase):
    def test_replica_holdings_excludes_code(self):
        self.assertNotIn(CODE, _holdings(DSH), '副本链持仓枚举仍含 512980')

    def test_prod_holdings_excludes_code(self):
        """两链配置必须一致，否则 00:01 配置一致性守卫会告警、Hermes 仍推首格买入。"""
        self.assertNotIn(CODE, _holdings(PROD), '生产链持仓枚举仍含 512980')

    def test_empty_ledger_archived_out_of_active_path(self):
        """2026-11-16 Master 指示「去掉」：空账本不得再在活跃路径；
        归档到 backups/ 保留（可恢复），内容仍必须是无成交的空账本。"""
        active = GRID_ACCOUNT / 'confirmed-512980.json'
        self.assertFalse(active.is_file(), '空账本仍在活跃路径，未按指示去掉')
        archived = sorted(BACKUPS.glob('confirmed-512980*.json'))
        self.assertTrue(archived, 'backups/ 中没有 512980 空账本归档，无法恢复')
        st = json.loads(archived[-1].read_text(encoding='utf-8'))
        self.assertEqual(int(st.get('qty') or 0), 0, '归档账本不该有持仓')
        self.assertEqual(len(st.get('trades') or []), 0, '归档账本不该有成交')

    def test_plan_does_not_load_unregistered_ledger(self):
        """临时根：账本文件还在但 holdings 不枚举 → plan 不得载入、不得出动作。"""
        import confirmed_runtime as rt
        from confirmed_589720 import build
        from unittest.mock import patch
        import holdings as H

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            h = {
                'sh589720': dict(name='A', lot_budget='12000', active=True),
                'sz159363': dict(name='B', lot_budget='6000', active=True),
            }
            (root / 'holdings.json').write_text(
                json.dumps({'holdings': h}, ensure_ascii=False), encoding='utf-8')
            for code, suffix in (('sh589720', '589720'),
                                 ('sz159363', '159363')):
                st = build([('buy', 10000, '0.797')], code=code, name=code)
                st['sellable_qty'] = st['qty']
                (root / f'confirmed-{suffix}.json').write_text(
                    json.dumps(st, ensure_ascii=False), encoding='utf-8')
            # 刻意放入未枚举标的的空账本
            empty = build([], code=CODE, name='传媒ETF广发')
            empty['sellable_qty'] = 0
            empty['entry_price'] = '0.780'
            (root / 'confirmed-512980.json').write_text(
                json.dumps(empty, ensure_ascii=False), encoding='utf-8')

            with patch.object(H, 'held_codes', return_value=tuple(h.keys())):
                ticket = rt.plan(str(root))
            self.assertNotIn(CODE, ticket['states'], '未枚举标的仍被载入账本')
            self.assertFalse([a for a in ticket['actions'] if a['code'] == CODE],
                             '未枚举标的仍生成了买卖动作')


if __name__ == '__main__':
    unittest.main()
