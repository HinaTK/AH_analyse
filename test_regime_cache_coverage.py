# -*- coding: utf-8 -*-
"""TDD：新注册标的不得绕过门控（2026-10-30 事故第三击）。

事故回放：512980 昨晚轮换筛选后 00:01 注册进 holdings（active=True，
lot_budget=8000），但门控缓存 regime-cache.json 是前一日 16:43 生成的，
只含 3 只旧持仓。09:20 盘前推送直接用这份缓存 → _CachedGate 对
"不在缓存里的代码" 返回 False（放行）→ 512980 五线全破却推出了
"条件买 A格 @0.780"。

这是继 10-27（sys.path）、10-28（解释器）之后门控静默失效的第三次，
同类第三次=流程问题：不是单点 bug，是"缓存键集 ≠ 门控覆盖集"这个
设计缝隙。修复原则（用户一贯口径）：宁拦勿放。

两级修复：
1. _CachedGate.blocks_buy 对"代码不在缓存" → True（fail-CLOSED），
   reason 标注"门控缓存未覆盖（新注册/缓存残缺），暂停买入"；
   门控恢复日重锚逻辑用 was_blocked=False，不受影响。
2. ops_main 发现 holdings 里有代码不在缓存条目里 → 补拉现算，
   拉不到降级为拦截（市况未知），不再静默放行。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json


def _mk_cache(tmpdir, payload):
    p = Path(tmpdir) / 'regime-cache.json'
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return p


class TestCachedGateFailClosed(unittest.TestCase):
    """修复2（纵深防御）：_CachedGate 对缓存未覆盖的代码必须拦截。"""

    def test_blocks_buy_returns_true_for_code_missing_from_cache(self):
        """512980 不在缓存 → blocks_buy 必须 True，不得静默放行。"""
        from confirmed_runtime import _cache_to_regimes
        cache = {'sh589720': {'level': 'no_entry', 'blocks_buy': True,
                              'reason': '五线全破', 'asof': '2026-10-29'},
                 'sz159363': {'level': 'no_entry', 'blocks_buy': True,
                              'reason': '五线全破+ADX41.2', 'asof': '2026-10-29'}}
        gate = _cache_to_regimes(cache)
        self.assertTrue(
            gate.blocks_buy('sh512980'),
            '缓存未覆盖的代码必须拦截（fail-closed），不得放行建仓')
        self.assertFalse(gate.blocks_buy('sz159992') is None)  # 不 crash

    def test_missing_code_reason_is_explicit(self):
        """拦截理由必须自带"缓存未覆盖"字样，推送可见、可追责。"""
        from confirmed_runtime import _cache_to_regimes
        cache = {'sh589720': {'level': 'no_entry', 'blocks_buy': True,
                              'reason': '五线全破', 'asof': '2026-10-29'}}
        gate = _cache_to_regimes(cache)
        reason = gate.reason('sh512980')
        self.assertIn('未覆盖', reason)
        self.assertIn('暂停买入', reason)

    def test_cached_codes_still_work_as_before(self):
        """缓存内代码行为不变：True 还是 True，False 还是 False。"""
        from confirmed_runtime import _cache_to_regimes
        cache = {'sh589720': {'level': 'no_entry', 'blocks_buy': True,
                              'reason': '五线全破', 'asof': '2026-10-29'},
                 'sz159992': {'level': 'probe_only', 'blocks_buy': False,
                              'reason': '试错仓', 'asof': '2026-10-29'}}
        gate = _cache_to_regimes(cache)
        self.assertTrue(gate.blocks_buy('sh589720'))
        self.assertFalse(gate.blocks_buy('sz159992'))
        # 原有语义：无条目时 level 显示 None（兜底文案），但 blocks=True
        self.assertTrue(gate.blocks_buy('sz159363'))


class TestBuildGateCoversHeldCodes(unittest.TestCase):
    """修复1（根因）：build_gate 后置补拉，门控覆盖集=holdings 键集。"""

    def _mk_holdings(self, tmpdir):
        h = {'sh589720': {'name': '科创创新药ETF国泰', 'lot_budget': '8000',
                          'active': True, 'quota': '66227'},
             'sh512980': {'name': '传媒ETF广发', 'lot_budget': '8000',
                          'active': True, 'quota': '30000'}}
        p = Path(tmpdir) / 'holdings.json'
        p.write_text(json.dumps({'holdings': h}, ensure_ascii=False), encoding='utf-8')
        return p

    def test_new_code_gets_regime_backfilled_and_cached(self):
        """缓存缺 512980 → 补拉现算并入缓存，判定有据可查。"""
        import tempfile
        from confirmed_runtime import build_gate, load_regime_cache
        import confirmed_runtime as rt
        with tempfile.TemporaryDirectory() as td:
            self._mk_holdings(td)
            _mk_cache(td, {'sh589720': {'level': 'no_entry', 'blocks_buy': True,
                                        'reason': '五线全破', 'asof': '2026-10-29'}})
            calls = []

            def fake_fetch(code):
                calls.append(code)
                return dict(adx=16.1, mdi=21.7, pdi=13.2,
                            bars=_synthetic_bars(299))

            orig = rt.fetch_daily_regime
            rt.fetch_daily_regime = fake_fetch
            try:
                gate = rt.build_gate(td, expect_asof='2026-10-29', fetch=True)
                self.assertIn('sh512980', calls, '必须补拉 512980 的行情')
                self.assertIsNotNone(gate)
                # 判定并入缓存
                cache = load_regime_cache(td, expect_asof='2026-10-29')
                self.assertIn('sh512980', cache)
                self.assertIsNotNone(cache['sh512980'].get('adx'))
            finally:
                rt.fetch_daily_regime = orig

    def test_new_code_fetch_fails_degrades_to_blocked(self):
        """补拉也失败 → 512980 判定=拦截（市况未知），不得放行。"""
        import tempfile
        from confirmed_runtime import build_gate
        import confirmed_runtime as rt
        with tempfile.TemporaryDirectory() as td:
            self._mk_holdings(td)
            _mk_cache(td, {'sh589720': {'level': 'no_entry', 'blocks_buy': True,
                                        'reason': '五线全破', 'asof': '2026-10-29'}})

            def broken(code):
                raise OSError('行情源失败')

            orig = rt.fetch_daily_regime
            rt.fetch_daily_regime = broken
            try:
                gate = rt.build_gate(td, expect_asof='2026-10-29', fetch=True)
                self.assertIsNotNone(gate)
                self.assertTrue(gate.blocks_buy('sh512980'),
                                '补拉失败必须降级为拦截，不得放行')
                self.assertIn('未知', gate.reason('sh512980'))
            finally:
                rt.fetch_daily_regime = orig


def _synthetic_bars(n=299, close=0.777):
    """合成日K：五线全破形态（供 gate 现算判定，不走网络）。"""
    import pandas as pd
    from datetime import date, timedelta
    d0 = date(2026, 1, 1)
    rows = []
    px = close * 1.15
    for i in range(n):
        px = px * 0.999 if i < n - 1 else close
        rows.append(dict(date=(d0 + timedelta(days=i)).isoformat(),
                         open=px, high=px * 1.005, low=px * 0.995, close=px))
    return pd.DataFrame(rows)


if __name__ == '__main__':
    unittest.main()
