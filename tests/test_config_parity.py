"""双链账本配置漂移的只读校验（2026-11-05 防复发）。

用户定：两条链各自读写、各自推送，不做自动账本镜像或跨链去重。
本校验只读两份 holdings.json、比对字节哈希与配置字段差异，只告警，
绝不复制、镜像、改写任何一侧文件。
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / 'deploy_scripts'


def _load():
    spec = importlib.util.spec_from_file_location(
        'config_parity_under_test', DEPLOY / 'config_parity.py')
    if spec is None or spec.loader is None:
        raise ImportError('config_parity.py 不存在')
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _home(root: Path, name: str, holdings: dict) -> Path:
    home = root / name
    acct = home / 'cache' / 'grid-account'
    acct.mkdir(parents=True)
    (acct / 'holdings.json').write_text(
        json.dumps({'holdings': holdings}, ensure_ascii=False, indent=2),
        encoding='utf-8')
    return home


class ConfigParityTests(unittest.TestCase):
    def setUp(self):
        self.cp = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.base = {
            'sh111111': {'name': '甲', 'lot_budget': '8000', 'active': True},
            'sz222222': {'name': '乙', 'lot_budget': '6000', 'active': True},
        }

    def test_identical_holdings_report_match(self):
        dsh = _home(self.root, 'dsh', self.base)
        hermes = _home(self.root, 'hermes', self.base)
        result = self.cp.check_holdings_parity(dsh, hermes)
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, 'match')
        self.assertEqual(result.differences, ())
        self.assertEqual(self.cp.format_alert(result), '')

    def test_buy_paused_drift_is_reported(self):
        drifted = json.loads(json.dumps(self.base))
        drifted['sh111111']['buy_paused'] = True
        dsh = _home(self.root, 'dsh', drifted)
        hermes = _home(self.root, 'hermes', self.base)
        result = self.cp.check_holdings_parity(dsh, hermes)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'drift')
        self.assertTrue(any('buy_paused' in d for d in result.differences))
        alert = self.cp.format_alert(result)
        self.assertIn('buy_paused', alert)
        self.assertIn('只读', alert)
        self.assertNotIn('sh111111', alert)  # 告警不打印标的代码/值，避免泄密

    def test_missing_file_is_reported_without_raising(self):
        dsh = _home(self.root, 'dsh', self.base)
        hermes = self.root / 'hermes'
        (hermes / 'cache' / 'grid-account').mkdir(parents=True)
        result = self.cp.check_holdings_parity(dsh, hermes)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'missing')
        self.assertIn('缺失', self.cp.format_alert(result))

    def test_check_never_writes_or_copies(self):
        drifted = json.loads(json.dumps(self.base))
        drifted['sz222222']['quota'] = 1
        dsh = _home(self.root, 'dsh', drifted)
        hermes = _home(self.root, 'hermes', self.base)
        before = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.root.rglob('*') if p.is_file()
        }
        self.cp.check_holdings_parity(dsh, hermes)
        after = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.root.rglob('*') if p.is_file()
        }
        self.assertEqual(before, after, '校验必须只读，不得改写或复制任何文件')
        self.assertFalse((hermes / 'cache' / 'grid-account' / 'holdings.json.bak').exists())

    def test_alert_signature_changes_only_with_content(self):
        drifted = json.loads(json.dumps(self.base))
        drifted['sh111111']['buy_paused'] = True
        r1 = self.cp.check_holdings_parity(
            _home(self.root, 'dsh', drifted), _home(self.root, 'hermes', self.base))
        r2 = self.cp.check_holdings_parity(
            _home(self.root, 'dsh2', drifted), _home(self.root, 'hermes2', self.base))
        self.assertEqual(self.cp.alert_signature(r1), self.cp.alert_signature(r2))
        clean = self.cp.check_holdings_parity(
            _home(self.root, 'dsh3', self.base), _home(self.root, 'hermes3', self.base))
        self.assertEqual(self.cp.alert_signature(clean), '')


if __name__ == '__main__':
    unittest.main()
