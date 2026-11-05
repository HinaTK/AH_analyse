# -*- coding: utf-8 -*-
"""TDD（2026-11-05）：周轮换状态路径必须跟随 HERMES_HOME。

DSH 链给子进程设 HERMES_HOME=D:/Code/AH_analyse/.cache/grid-home，
轮换状态必须落在该根的 cache/grid-account/rotation 下；
未设 HERMES_HOME 时保持 Hermes 生产默认路径不变。
测试只做路径计算与模块重载，不读写任何真实账本、不联网。
"""
import importlib
import os
import tempfile
import unittest
from pathlib import Path

PROD_HOME = Path('D:/Hermes Agent CN Desktop/data/hermes-home')


def _reload_with_home(home):
    saved = os.environ.get('HERMES_HOME')
    try:
        if home is None:
            os.environ.pop('HERMES_HOME', None)
        else:
            os.environ['HERMES_HOME'] = str(home)
        pair = importlib.reload(importlib.import_module('tools.etf_research.pair_review'))
        weekly = importlib.reload(importlib.import_module('tools.etf_research.weekly'))
        return pair.DEFAULT_STATE, weekly.DEFAULT_STATE, weekly.STATE_VERSION
    finally:
        if saved is None:
            os.environ.pop('HERMES_HOME', None)
        else:
            os.environ['HERMES_HOME'] = saved
        importlib.reload(importlib.import_module('tools.etf_research.pair_review'))
        importlib.reload(importlib.import_module('tools.etf_research.weekly'))


class RotationStateHomeTests(unittest.TestCase):
    def test_state_paths_follow_hermes_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            pair_state, weekly_state, version = _reload_with_home(tmp)
            rotation = Path(tmp) / 'cache/grid-account/rotation'
            self.assertEqual(weekly_state, rotation / f'{version}.json')
            self.assertEqual(pair_state, rotation / 'pair-review-v1.json')

    def test_state_paths_default_to_production_when_unset(self):
        pair_state, weekly_state, version = _reload_with_home(None)
        rotation = PROD_HOME / 'cache/grid-account/rotation'
        self.assertEqual(weekly_state, rotation / f'{version}.json')
        self.assertEqual(pair_state, rotation / 'pair-review-v1.json')


if __name__ == '__main__':
    unittest.main()
