# -*- coding: utf-8 -*-
"""TDD：门控缓存预计算循环重试（用户 2026-10-29："就要循环执行直到成功"）。

旧脚本只拉一次：行情源限流（东财/腾讯501）失败即放弃，只留旧缓存条目。
新要求：失败后循环重试（只重拉缺失标的、退避加长），直到全部成功；
到安全截止线仍失败才带 missed 退出。

2026-11-03 事故（11-02/11-03 连续两天 15:30 任务被 cron 3600s 硬杀、
零落盘）后截止线语义更新：min(次日09:00, now+1800s)——自身 30 分钟
上限永远早于 cron 硬杀；on_round 回调每轮增量落盘，被杀不丢已成功标的。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'deploy_scripts'))

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

    def test_production_deadline_caps_at_30_minutes(self):
        # 2026-11-03 修复A：15:30 触发 → 截止线 = now+1800s（16:00），
        # 永远早于 cron 3600s 硬杀；不再重试到次日 09:00
        start = datetime(2026, 11, 3, 15, 30, 0, tzinfo=_CN)
        dl = grc.production_deadline(start)
        self.assertEqual(dl, datetime(2026, 11, 3, 16, 0, 0, tzinfo=_CN))
        self.assertLess((dl - start).total_seconds(), 3600 - 60)

    def test_production_deadline_keeps_next_09_for_early_runs(self):
        # 晨间临近消费线（如 08:45 补跑）：now+1800s=09:15 越过 09:00
        # → 被 09:00 钳制，不挤占 09:20 盘前消费窗口
        start = datetime(2026, 11, 3, 8, 45, 0, tzinfo=_CN)
        dl = grc.production_deadline(start)
        self.assertEqual((dl.hour, dl.minute), (9, 0))
        self.assertEqual(dl.date(), datetime(2026, 11, 4, tzinfo=_CN).date() - timedelta(days=1))

    def test_production_deadline_early_morning_gets_30min_not_next_09(self):
        # 远离消费线的晨间（如 08:00）：30 分钟上限更早生效（08:30），
        # 不再是旧的"重试到次日 09:00"
        start = datetime(2026, 11, 3, 8, 0, 0, tzinfo=_CN)
        dl = grc.production_deadline(start)
        self.assertEqual(dl, datetime(2026, 11, 3, 8, 30, 0, tzinfo=_CN))

    def test_self_limit_stops_loop_with_partial_regimes(self):
        # 永不成功 + 自设 30 分钟截止 → 停止并返回部分结果；
        # 已成功的标的不丢（增量落盘的输入）
        now = datetime(2026, 11, 3, 15, 30, 0, tzinfo=_CN)
        deadline = grc.production_deadline(now)
        self.assertEqual(deadline, now + timedelta(seconds=1800))
        counter = {'n': 0}

        def clock():
            counter['n'] += 1
            # 轮1 后（判定1）：未到线；轮2 后（判定2）：到线 → 停，共 2 轮
            return now if counter['n'] == 1 else now + timedelta(seconds=1800)
        regimes, missed, attempts = grc.collect_regimes(
            lambda code: _ok(code) if code == 'sh589720' else {'adx': None, 'bars': None},
            ['sh589720', 'sz159992'], sleep_fn=lambda s: None,
            deadline=deadline, clock=clock)
        self.assertIn('sh589720', regimes)
        self.assertEqual(missed, ['sz159992'])
        self.assertEqual(attempts, 2)

    def test_on_round_called_every_round_with_partial_state(self):
        # 2026-11-03 修复B：每轮结束回调 (round_no, regimes, missed)，
        # 调用方借它增量落盘——第 1 轮部分成功时已能看到已成功标的
        calls = []
        def fetch(code):
            if code == 'sh589720':
                return _ok(code)
            if len(calls) == 0:
                raise OSError('腾讯501')  # 第一轮失败 → 触发 on_round(1, …)
            return _ok(code)  # 第二轮成功 → 收敛退出
        grc.collect_regimes(
            fetch, ['sh589720', 'sz159992'], sleep_fn=lambda s: None,
            on_round=lambda n, got, miss: calls.append((n, sorted(got), sorted(miss))))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], (1, ['sh589720'], ['sz159992']))

    def test_on_round_exception_does_not_break_retry(self):
        # 回调抛异常（落盘失败）不得阻断重试循环
        calls = []
        def bad_on_round(n, got, miss):
            calls.append(n)
            raise OSError('disk full')
        def fetch(code):
            if len(calls) == 0:
                raise OSError('腾讯501')
            return _ok(code)
        regimes, missed, attempts = grc.collect_regimes(
            fetch, ['sh589720'], sleep_fn=lambda s: None, on_round=bad_on_round)
        self.assertEqual(missed, [])
        self.assertEqual(attempts, 2)
        self.assertIn('sh589720', regimes)

    def test_merge_old_entries_keeps_missing_codes(self):
        # 修复B共用逻辑：缺失标的从旧缓存补条目，宁旧勿缺；
        # 已在 cache 里的不被旧条目覆盖
        import json as _json
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            old = _P(td) / 'regime-cache.json'
            old.write_text(_json.dumps({
                'sz159992': {'level': 'no_entry', 'blocks_buy': True, 'asof': '2026-11-02'},
                'sh589720': {'level': 'probe_only', 'blocks_buy': False, 'asof': '2026-11-02'},
            }), encoding='utf-8')
            cache = {'sh589720': {'level': 'no_entry', 'blocks_buy': True, 'asof': '2026-11-03'}}
            merged = grc.merge_old_entries(cache, ['sz159992'], old)
            self.assertIn('sz159992', merged)
            self.assertEqual(merged['sz159992']['asof'], '2026-11-02')  # 旧条目兜底
            self.assertEqual(merged['sh589720']['asof'], '2026-11-03')  # 新数据不被覆盖
            # 缺失为空 → 原样返回（fresh dict 防原地更新干扰断言）
            again = grc.merge_old_entries({'sh589720': dict(cache['sh589720'])}, [], old)
            self.assertEqual(sorted(again), ['sh589720'])

    def test_merge_old_entries_missing_file_is_noop(self):
        from pathlib import Path as _P
        cache = {'sh589720': {'level': 'no_entry', 'blocks_buy': True, 'asof': '2026-11-03'}}
        merged = grc.merge_old_entries(cache, ['sz159992'], _P('Z:/nonexistent/regime-cache.json'))
        self.assertEqual(sorted(merged), ['sh589720'])  # 文件不存在：不炸、不补


if __name__ == '__main__':
    unittest.main()
