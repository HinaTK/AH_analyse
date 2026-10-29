# -*- coding: utf-8 -*-
"""TDD：门控缓存预计算循环重试（用户 2026-10-29："就要循环执行直到成功"）。

旧脚本只拉一次：行情源限流（东财/腾讯501）失败即放弃，只留旧缓存条目。
新要求：失败后循环重试（只重拉缺失标的、退避加长），直到全部成功；
到安全截止线（次日09:00，早于09:20消费方）仍失败才带 missed 退出。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'deploy_scripts'))

from datetime import datetime, timezone, timedelta

import grid_regime_cache as grc

_CN = timezone(timedelta(hours=8))


def _ok(code):
    return {'adx': 20.0, 'pdi': 15.0, 'mdi': 10.0, 'bars': 'frame'}


class CollectRegimesRetryTests(unittest.TestCase):
    def test_first_attempt_success_no_sleep(self):
        sleeps = []
        regimes, missed, attempts = grc.collect_regimes(
            lambda code: _ok(code), ['sh589720', 'sz159363'],
            sleep_fn=sleeps.append)
        self.assertEqual(missed, [])
        self.assertEqual(attempts, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(sorted(regimes), ['sh589720', 'sz159363'])

    def test_retries_only_missed_until_success(self):
        # 159363 第一次拉失败（限流），第二次成功 → 只重拉它，睡一次
        calls = []
        def fetch(code):
            calls.append(code)
            if code == 'sz159363' and calls.count('sz159363') == 1:
                return {'adx': None, 'bars': None}  # 拉空
            return _ok(code)
        sleeps = []
        regimes, missed, attempts = grc.collect_regimes(
            fetch, ['sh589720', 'sz159363'], sleep_fn=sleeps.append)
        self.assertEqual(missed, [])
        self.assertEqual(attempts, 2)
        self.assertEqual(sleeps, [120.0])  # 首轮退避120s
        self.assertEqual(calls.count('sh589720'), 1)  # 成功的不重拉
        self.assertEqual(calls.count('sz159363'), 2)

    def test_fetch_exception_counts_as_miss_and_retried(self):
        calls = []
        def fetch(code):
            calls.append(code)
            if len(calls) == 1:
                raise OSError('腾讯501')
            return _ok(code)
        regimes, missed, attempts = grc.collect_regimes(
            fetch, ['sh589720'], sleep_fn=lambda s: None)
        self.assertEqual(missed, [])
        self.assertEqual(attempts, 2)
        self.assertIn('sh589720', regimes)

    def test_backoff_grows_and_caps(self):
        # 永不成功 → 退避 120,180,270,405,600,600… 封顶600
        sleeps = []
        deadline = datetime.now(_CN)  # 立即到截止线 → 只跑一轮
        regimes, missed, attempts = grc.collect_regimes(
            lambda code: {'adx': None, 'bars': None}, ['sh589720'],
            sleep_fn=sleeps.append, deadline=deadline)
        self.assertEqual(missed, ['sh589720'])
        self.assertEqual(attempts, 1)
        # 用不截止的跑法验证退避序列（第7次clock起视为到截止线 → 恰好6次sleep）
        counter = {'n': 0}
        def clock():
            counter['n'] += 1
            return datetime.now(_CN) if counter['n'] <= 6 else datetime.max.replace(tzinfo=_CN)
        sleeps2 = []
        grc.collect_regimes(
            lambda code: {'adx': None, 'bars': None}, ['sh589720'],
            sleep_fn=sleeps2.append, deadline=None, clock=clock)
        self.assertEqual(sleeps2, [120.0, 180.0, 270.0, 405.0, 600.0, 600.0])

    def test_deadline_stops_loop_with_missed(self):
        # 永不成功且到截止线 → 停止并返回 missed（调用方走旧缓存兜底）
        sleeps = []
        deadline = datetime.now(_CN)
        regimes, missed, attempts = grc.collect_regimes(
            lambda code: {'adx': None, 'bars': None}, ['sh589720', 'sz159992'],
            sleep_fn=sleeps.append, deadline=deadline)
        self.assertEqual(sorted(missed), ['sh589720', 'sz159992'])
        self.assertEqual(attempts, 1)
        self.assertEqual(sleeps, [])  # 到线即停，不再睡

    def test_stale_bars_after_close_are_retried(self):
        # 收盘后（>=15:00）拉到旧数据（asof≠今日）不算成功，要重试
        now = datetime.now(_CN)
        stale = {'adx': 19.7, 'bars': 'stale-frame'}  # 非空但旧
        fresh = {'adx': 20.1, 'bars': 'fresh-frame'}
        calls = []
        def fetch(code):
            calls.append(code)
            return stale if len(calls) == 1 else fresh
        def is_fresh(r):
            return r is fresh
        regimes, missed, attempts = grc.collect_regimes(
            fetch, ['sh589720'], sleep_fn=lambda s: None, is_fresh=is_fresh)
        self.assertEqual(missed, [])
        self.assertEqual(attempts, 2)
        self.assertIn('sh589720', regimes)

    def test_production_deadline_is_next_09(self):
        # 生产截止线 = 次日09:00（早于09:20消费方，且窗口<24h不会跨天堆叠）
        dl = grc.production_deadline()
        now = datetime.now(_CN)
        self.assertGreater(dl, now)
        self.assertEqual((dl.hour, dl.minute), (9, 0))
        self.assertLess((dl - now).total_seconds(), 24 * 3600)


if __name__ == '__main__':
    unittest.main()
