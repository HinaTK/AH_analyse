"""589720 格子参数配置契约（2026-11-05 Master 授权，两链同步）。

lot_budget（每格买入金额）8000→12000；quota（单只净投入上限）66227→90000。
其余三只标的、所有已确认成交账本均不动。
"""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DSH = REPO / '.cache' / 'grid-home' / 'cache' / 'grid-account' / 'holdings.json'
PROD = Path(r'D:\Hermes Agent CN Desktop\data\hermes-home\cache\grid-account\holdings.json')
CODE = 'sh589720'


def _holdings(path):
    return json.loads(path.read_text(encoding='utf-8'))['holdings']


class LotBudgetContractTests(unittest.TestCase):
    def test_both_chains_are_12000(self):
        for path in (DSH, PROD):
            with self.subTest(path=str(path)):
                self.assertTrue(path.is_file(), f'缺少配置文件：{path}')
                self.assertEqual(_holdings(path)[CODE]['lot_budget'], '12000')

    def test_both_chains_byte_identical(self):
        """00:01 的 config_parity_guard 按 sha256 比对，两链必须字节一致。"""
        self.assertEqual(hashlib.sha256(DSH.read_bytes()).hexdigest(),
                         hashlib.sha256(PROD.read_bytes()).hexdigest())

    def test_default_fallback_matches(self):
        """holdings.py 的 DEFAULT 兜底不得仍停留在 8000。"""
        spec = importlib.util.spec_from_file_location('holdings_contract', REPO / 'holdings.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.DEFAULT[CODE]['lot_budget'], '12000')

    def test_quota_is_90000_and_other_etfs_unchanged(self):
        for path in (DSH, PROD):
            with self.subTest(path=str(path)):
                h = _holdings(path)
                self.assertEqual(h[CODE]['quota'], 90000)
                self.assertEqual(h[CODE]['name'], '科创创新药ETF国泰')
                self.assertTrue(h[CODE]['active'])
                self.assertEqual(h['sz159363']['lot_budget'], '6000')
                self.assertIsNone(h['sz159992']['lot_budget'])
                # 2026-11-09 Master 指示「512980 先不开，去掉」：两链枚举均不再含该标的；
                # 空账本与配置备份保留以便日后恢复。
                self.assertNotIn('sh512980', h)

    def test_no_buy_paused_anywhere(self):
        for path in (DSH, PROD):
            with self.subTest(path=str(path)):
                for code, entry in _holdings(path).items():
                    self.assertNotIn('buy_paused', entry, f'{code} 残留 buy_paused')


if __name__ == '__main__':
    unittest.main()
