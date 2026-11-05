# -*- coding: utf-8 -*-
"""TDD（2026-11-05）：市况监控读的 holdings.json 必须跟随 HERMES_HOME。

DSH 链（HERMES_HOME=D:/Code/AH_analyse/.cache/grid-home）只能读自己的账本根；
未设 HERMES_HOME 时保持 Hermes 生产默认路径。不联网、不写真实账本。
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import market_phase_check as mp

PROD_HOME = Path('D:/Hermes Agent CN Desktop/data/hermes-home')


def _reload_with_home(home):
    saved = os.environ.get('HERMES_HOME')
    try:
        if home is None:
            os.environ.pop('HERMES_HOME', None)
        else:
            os.environ['HERMES_HOME'] = str(home)
        importlib.reload(mp)
        return mp.HOLDINGS_PATH, mp.build_instruments()
    finally:
        if saved is None:
            os.environ.pop('HERMES_HOME', None)
        else:
            os.environ['HERMES_HOME'] = saved
        importlib.reload(mp)


class HoldingsPathHomeTests(unittest.TestCase):
    def test_holdings_path_follows_hermes_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            account = Path(tmp) / 'cache/grid-account'
            account.mkdir(parents=True)
            (account / 'holdings.json').write_text(
                json.dumps({'holdings': {'sz999999': {'name': '隔离测试ETF'}}}, ensure_ascii=False),
                encoding='utf-8')
            path, instruments = _reload_with_home(tmp)
            self.assertEqual(path, account / 'holdings.json')
            self.assertIn(('0.999999', '999999隔离测试ETF'), instruments)

    def test_holdings_path_defaults_to_production_when_unset(self):
        path, _ = _reload_with_home(None)
        self.assertEqual(path, PROD_HOME / 'cache/grid-account/holdings.json')


if __name__ == '__main__':
    unittest.main()
