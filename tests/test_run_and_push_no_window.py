# -*- coding: utf-8 -*-
"""windows 下 run_and_push 的所有子进程都不得弹控制台窗口。

2026-11-06 14:15 Master 看到两个 python 黑框一闪而过：计划任务本身用
pythonw.exe（无窗口），但 run_and_push._run() 用 python.exe 起子脚本且未设
creationflags，导致每个任务为子脚本再起一个带控制台的进程。
本测试用 AST 静态检查所有 subprocess.run/Popen 调用，要求显式传入
creationflags（值不限，Windows 上由实现取 CREATE_NO_WINDOW）。
"""
import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / 'deploy_scripts' / 'run_and_push.py'


def _subprocess_calls():
    tree = ast.parse(TARGET.read_text(encoding='utf-8'))
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == 'subprocess'
                and func.attr in ('run', 'Popen', 'call', 'check_output', 'check_call')):
            continue
        keywords = {kw.arg for kw in node.keywords}
        calls.append((node.lineno, func.attr, 'creationflags' in keywords))
    return calls


class NoConsoleWindowTests(unittest.TestCase):
    def test_all_subprocess_calls_pass_creationflags(self):
        """每个 subprocess 调用都必须显式传 creationflags，否则 Windows 下会弹窗。"""
        calls = _subprocess_calls()
        self.assertTrue(calls, '未找到任何 subprocess 调用，检查脚本是否改过')
        missing = [(line, name) for line, name, has_flag in calls if not has_flag]
        self.assertEqual([], missing,
                         f'以下 subprocess 调用缺少 creationflags，会弹控制台窗口：{missing}')

    def test_no_bare_system_python_console_in_run(self):
        """_run() 必须用无窗口标志起子脚本，且保留 stdout/stderr 捕获。"""
        tree = ast.parse(TARGET.read_text(encoding='utf-8'))
        run_fn = next((n for n in tree.body
                       if isinstance(n, ast.FunctionDef) and n.name == '_run'), None)
        self.assertIsNotNone(run_fn, '未找到 _run()')
        run_calls = [n for n in ast.walk(run_fn)
                     if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute)
                     and isinstance(n.func.value, ast.Name)
                     and n.func.value.id == 'subprocess'
                     and n.func.attr == 'run']
        self.assertTrue(run_calls, '_run() 里未找到 subprocess.run')
        for call in run_calls:
            keywords = {kw.arg: kw.value for kw in call.keywords}
            self.assertIn('creationflags', keywords,
                          f'_run() 第{call.lineno}行的 subprocess.run 缺少 creationflags')
            self.assertIn('capture_output', keywords,
                          '_run() 必须继续捕获 stdout/stderr')


if __name__ == '__main__':
    unittest.main()
