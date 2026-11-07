# -*- coding: utf-8 -*-
"""TDD：参与底仓登记脚本（写入+备份+读回核验，不改账本）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'deploy_scripts'))

import set_core_qty as scq

CODE = 'sh589720'


def _root(td, qty=10000):
    Path(td, 'holdings.json').write_text(json.dumps(
        {'holdings': {CODE: {'name': '测试ETF', 'active': True, 'lot_budget': '12000'}}},
        ensure_ascii=False), encoding='utf-8')
    Path(td, f'confirmed-{CODE[-6:]}.json').write_text(
        json.dumps({'code': CODE, 'qty': qty}), encoding='utf-8')
    return td


class RegisterTests(unittest.TestCase):
    def test_register_writes_backup_and_reads_back(self):
        with tempfile.TemporaryDirectory() as td:
            _root(td)
            out = scq.register(td, CODE, 4000)
            self.assertTrue(out['verified'])
            self.assertEqual(out['core_qty'], 4000)
            data = json.loads(Path(td, 'holdings.json').read_text(encoding='utf-8'))
            self.assertEqual(data['holdings'][CODE]['core_qty'], 4000)
            self.assertEqual(data['holdings'][CODE]['lot_budget'], '12000', '不得覆盖其它配置')
            self.assertTrue(Path(out['backup']).exists(), '必须留备份')
            self.assertFalse(Path(td, 'holdings.json.tmp').exists(), '临时文件须清理')
            state = json.loads(Path(td, f'confirmed-{CODE[-6:]}.json').read_text(encoding='utf-8'))
            self.assertEqual(state['qty'], 10000, '不得改 confirmed 账本')

    def test_reject_negative_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            _root(td)
            before = Path(td, 'holdings.json').read_bytes()
            with self.assertRaises(ValueError):
                scq.register(td, CODE, -1)
            self.assertEqual(Path(td, 'holdings.json').read_bytes(), before)

    def test_reject_above_current_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            _root(td, qty=10000)
            before = Path(td, 'holdings.json').read_bytes()
            with self.assertRaises(ValueError):
                scq.register(td, CODE, 10001)
            self.assertEqual(Path(td, 'holdings.json').read_bytes(), before)

    def test_reject_unknown_code(self):
        with tempfile.TemporaryDirectory() as td:
            _root(td)
            with self.assertRaises(ValueError):
                scq.register(td, 'sh999999', 100)

    def test_unregister_with_zero(self):
        with tempfile.TemporaryDirectory() as td:
            _root(td)
            scq.register(td, CODE, 4000)
            scq.register(td, CODE, 0)
            data = json.loads(Path(td, 'holdings.json').read_text(encoding='utf-8'))
            self.assertEqual(data['holdings'][CODE]['core_qty'], 0)


if __name__ == '__main__':
    unittest.main()
