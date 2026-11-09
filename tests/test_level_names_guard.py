# -*- coding: utf-8 -*-
"""守门回归（2026-11-09 生产事故）：中文加粗+emoji 级别映射必须是模块级常量。

事故：展示口径改造时先改了 _legacy_gate 的引用、后加常量定义，
中间窗口内盘中触价任务 import 到中间版本 → NameError: LEVEL_NAMES_CN is not defined，
rc=1。原验收只跑 unittest 与自制样例，未实跑生产入口，未捕获该缺陷。

本测试钉死三件事：常量存在、四档与盘中观察映射一致、正式拦买文案无裸英文。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import confirmed_runtime as rt
from tools import intraday_gate_watch as watch

# 测试只读副本链，禁止触碰生产根（用户级硬规则）。
REPLICA_HOME = str(REPO / '.cache' / 'grid-home')


class LevelNamesGuardTests(unittest.TestCase):
    def test_module_level_constant_exists_and_covers_four_levels(self):
        self.assertTrue(hasattr(rt, 'LEVEL_NAMES_CN'),
                        '必须定义在模块级，不能是函数内局部量')
        self.assertEqual(set(rt.LEVEL_NAMES_CN), set(watch.LEVELS))
        self.assertEqual(rt.LEVEL_NAMES_CN, watch.LEVEL_LABELS)

    def test_every_label_is_chinese_bold_emoji(self):
        for label in rt.LEVEL_NAMES_CN.values():
            with self.subTest(label=label):
                self.assertTrue(label.startswith('**') and label.endswith('**'))
                self.assertTrue(any('\u4e00' <= ch <= '\u9fff' for ch in label))
                self.assertTrue(any(ord(ch) > 0x2000 for ch in label))

    def test_production_gate_path_does_not_raise_nameerror(self):
        """覆盖报错栈：plan_with_gate → plan → blocks_buy → _unified → _legacy_gate。"""
        with patch.dict(os.environ, {'HERMES_HOME': REPLICA_HOME}):
            root = rt.root_from_home()
        try:
            ticket = rt.plan_with_gate(root)
        except NameError as exc:
            self.fail('生产门控链路抛 NameError：' + str(exc))
        self.assertIn('states', ticket)
        for block in ticket.get('regime_blocks') or []:
            for bare in ('no_entry', 'pause_buy', 'probe_only', 'normal'):
                self.assertNotIn(bare, str(block), '正式建议不得残留裸英文级别名')


if __name__ == '__main__':
    unittest.main()
