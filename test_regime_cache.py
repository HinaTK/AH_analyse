# -*- coding: utf-8 -*-
"""TDD：门控判定提前算好（盘后缓存，盘前用缓存兜底）。

用户 2026-10-28 指出："我就说早上拉取会出问题。。要么就提前一点做好判断"
——09:20 当场拉行情若失败（东财限流/腾讯501），gate=None fail-open，
单边下跌日的买入拦截会静默消失（10-27/10-28 两次事故的共因之一）。

方案：15:35 市况监控跑完收盘数据后，把每只持仓的门控判定（四级 level/
blocks_buy/adx/五线）落盘 cache/grid-account/regime-cache.json；
次日 09:20 优先用缓存（缓存命中→不再拉行情）；缓存缺失/过期才现拉；
现拉又失败→最后退回缓存（哪怕过期）再退 fail-open。
防陈旧：缓存只认"昨日收盘"或"今日收盘"两种日期戳。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json
from datetime import date, timedelta


def _mk_cache(tmpdir, payload):
    p = Path(tmpdir) / 'regime-cache.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return p


class RegimeCacheTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        from confirmed_runtime import save_regime_cache, load_regime_cache
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            save_regime_cache(td, {'sh589720': {'level': 'no_entry', 'blocks_buy': True,
                                                'reason': '五线全破', 'asof': '2026-10-27'}})
            got = load_regime_cache(td, expect_asof='2026-10-27')
            self.assertEqual(got['sh589720']['level'], 'no_entry')
            self.assertTrue(got['sh589720']['blocks_buy'])

    def test_stale_cache_rejected_when_fresh_expected(self):
        # 缓存日期既不是昨日也不是今日 → 视为过期
        from confirmed_runtime import load_regime_cache
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            _mk_cache(td, {'sh589720': {'level': 'no_entry', 'blocks_buy': True, 'asof': '2026-10-20'}})
            got = load_regime_cache(td, expect_asof='2026-10-27')
            self.assertIsNone(got, '过期缓存（10-20 vs 期望10-27）不应被采用')

    def test_yesterday_cache_valid_for_today(self):
        # 盘前场景：期望昨日收盘数据，缓存戳=昨日 → 有效
        from confirmed_runtime import load_regime_cache
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            _mk_cache(td, {'sh589720': {'level': 'no_entry', 'blocks_buy': True, 'asof': '2026-10-27'}})
            got = load_regime_cache(td, expect_asof='2026-10-27')
            self.assertIsNotNone(got)

    def test_expired_cache_still_usable_as_fallback(self):
        # allow_stale=True：现拉失败的兜底路径，过期缓存好过没缓存
        from confirmed_runtime import load_regime_cache
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            _mk_cache(td, {'sh589720': {'level': 'no_entry', 'blocks_buy': True, 'asof': '2026-10-20'}})
            got = load_regime_cache(td, expect_asof='2026-10-27', allow_stale=True)
            self.assertIsNotNone(got)
            self.assertEqual(got['sh589720']['level'], 'no_entry')

    def test_missing_file_returns_none(self):
        from confirmed_runtime import load_regime_cache
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            got = load_regime_cache(td, expect_asof='2026-10-28')
            self.assertIsNone(got)

    def test_ops_main_uses_cache_when_fetch_fails(self):
        """端到端：现拉失败时退回缓存，gate 不为 None（拦截不消失）。"""
        from confirmed_runtime import build_gate
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            _mk_cache(td, {'sh589720': {'level': 'no_entry', 'blocks_buy': True,
                                        'reason': '五线全破', 'asof': '2026-10-27'},
                           'sz159363': {'level': 'no_entry', 'blocks_buy': True,
                                        'reason': '五线全破+ADX37.8', 'asof': '2026-10-27'},
                           'sz159992': {'level': 'probe_only', 'blocks_buy': False,
                                        'reason': '试错仓', 'asof': '2026-10-27'}})
            # 模拟现拉失败：fetch_daily_regime 抛异常
            import confirmed_runtime as rt
            orig = rt.fetch_daily_regime

            def broken(code):
                raise OSError('行情源失败')

            rt.fetch_daily_regime = broken
            try:
                gate = rt.build_gate(td, expect_asof='2026-10-27')
                self.assertIsNotNone(gate, '有缓存时 gate 不得为 None')
                self.assertTrue(gate.blocks_buy('sh589720'))
                self.assertTrue(gate.blocks_buy('sz159363'))
                self.assertFalse(gate.blocks_buy('sz159992'))
            finally:
                rt.fetch_daily_regime = orig


if __name__ == '__main__':
    unittest.main()
