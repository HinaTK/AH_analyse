"""DSH 包装器接线测试：00:01 只读配置校验 + 防误传生产根。

用户定：两条链各自读写，不做自动账本镜像或跨链去重；校验只读、只告警。
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
RAP = REPO / 'deploy_scripts' / 'run_and_push.py'


def _load():
    spec = importlib.util.spec_from_file_location('run_and_push_parity_under_test', RAP)
    if spec is None or spec.loader is None:
        raise ImportError('run_and_push.py 不存在')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _home(root, name, holdings):
    home = root / name
    acct = home / 'cache' / 'grid-account'
    acct.mkdir(parents=True)
    (acct / 'holdings.json').write_text(
        json.dumps({'holdings': holdings}, ensure_ascii=False, indent=2),
        encoding='utf-8')
    return home


class WrapperParityTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.base = {
            'sh111111': {'name': '甲', 'lot_budget': '8000', 'active': True},
            'sz222222': {'name': '乙', 'lot_budget': '6000', 'active': True},
        }
        self.pushed = []
        self.logged = []
        self.push_fn = lambda text: self.pushed.append(text) or True
        self.log_fn = lambda text: self.logged.append(text)

    def _guard(self, dsh, hermes):
        return self.m.config_parity_guard(
            dsh, hermes, push_fn=self.push_fn, log_fn=self.log_fn)

    def test_drift_pushes_read_only_alert(self):
        drifted = json.loads(json.dumps(self.base))
        drifted['sh111111']['buy_paused'] = True
        dsh = _home(self.root, 'dsh', drifted)
        hermes = _home(self.root, 'hermes', self.base)
        alert = self._guard(dsh, hermes)
        self.assertEqual(len(self.pushed), 1)
        self.assertIn('buy_paused', alert)
        self.assertIn('未复制、未镜像、未改写', alert)
        self.assertNotIn('sh111111', alert)
        self.assertEqual(len(self.logged), 1)

    def test_identical_does_not_push(self):
        dsh = _home(self.root, 'dsh', self.base)
        hermes = _home(self.root, 'hermes', self.base)
        self.assertIsNone(self._guard(dsh, hermes))
        self.assertEqual(self.pushed, [])
        self.assertEqual(self.logged, [])

    def test_guard_never_modifies_either_ledger(self):
        drifted = json.loads(json.dumps(self.base))
        drifted['sz222222']['quota'] = 1
        dsh = _home(self.root, 'dsh', drifted)
        hermes = _home(self.root, 'hermes', self.base)
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob('*') if p.is_file()}
        self._guard(dsh, hermes)
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after, '告警不得改写任何账本/配置文件')

    def test_prod_home_is_rejected_for_dsh_wrapper(self):
        prod = Path(r'D:\Hermes Agent CN Desktop\data\hermes-home')
        with self.assertRaises(ValueError):
            self.m.assert_dsh_home(prod)
        self.m.assert_dsh_home(REPO / '.cache' / 'grid-home')

    def test_main_wires_guard_for_midnight_rollover(self):
        """00:01 可卖同步任务运行前必须做一次只读校验；其他 job 不做。"""
        with mock.patch.object(sys, 'argv', ['run_and_push.py', '--job', 'midnight_0001', '--dry']), \
             mock.patch.object(self.m, 'config_parity_guard', return_value=None) as guard, \
             mock.patch.object(self.m, '_run', return_value=(0, '', '')), \
             mock.patch.object(self.m, '_log'), \
             mock.patch.object(self.m, '_save_latest'):
            self.m.main()
        self.assertEqual(guard.call_count, 1)

    def test_main_skips_guard_for_other_jobs(self):
        with mock.patch.object(sys, 'argv', ['run_and_push.py', '--job', 'git_2300', '--dry']), \
             mock.patch.object(self.m, 'config_parity_guard') as guard, \
             mock.patch.object(self.m, '_run', return_value=(0, '', '')), \
             mock.patch.object(self.m, '_log'), \
             mock.patch.object(self.m, '_save_latest'):
            self.m.main()
        guard.assert_not_called()


if __name__ == '__main__':
    unittest.main()
