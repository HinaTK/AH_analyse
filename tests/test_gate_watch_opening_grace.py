# -*- coding: utf-8 -*-
"""TDD：连续交易时段开盘第一拍的行情滞后应静默跳过，不推「取数/状态未验证」。

真实证据（138 份观察快照）：11 次 quote_session 全部发生在 13:00:01~13:00:03，
13:15 那一拍全部 ok；11-13 行情时间戳恰为 13:00:00 时该拍也 ok。
根因：新时段已开始（afternoon 从 13:00），行情源时间戳仍停在午休尾盘
（12:59，_session_part=None），两者时段不等被当成硬错误。
修复口径：仅在「新时段开盘宽限期」内、同日且新鲜的边界滞后静默跳过；
宽限期外的跨时段旧快照仍按 quote_session 拒绝（安全契约不削弱）。
"""
import copy
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tests.test_intraday_gate_watch import CODE, NOW, ObserverTests, history_for, quote_for
from tools import intraday_gate_watch as watch

CN = timezone(timedelta(hours=8))


class OpeningGraceTests(unittest.TestCase):
    def test_grace_window_boundaries(self):
        self.assertTrue(watch._in_opening_grace(NOW.replace(hour=13, minute=0, second=0)))
        self.assertTrue(watch._in_opening_grace(NOW.replace(hour=13, minute=1, second=59)))
        self.assertFalse(watch._in_opening_grace(NOW.replace(hour=13, minute=2, second=0)))
        self.assertTrue(watch._in_opening_grace(NOW.replace(hour=9, minute=31, second=0)))
        self.assertFalse(watch._in_opening_grace(NOW.replace(hour=9, minute=33, second=0)))
        self.assertFalse(watch._in_opening_grace(NOW.replace(hour=10, minute=15)))
        self.assertFalse(watch._in_opening_grace(NOW.replace(hour=12, minute=0)))

    def test_1300_boundary_lag_is_silent_not_error(self):
        case = ObserverTests('test_valid_computation_matches_real_gate_and_wilder')
        case.setUp()
        self.addCleanup(case.doCleanups)
        now = NOW.replace(hour=13, minute=0, second=1)
        case.quote['timestamp'] = NOW.replace(hour=12, minute=59, second=30).isoformat()
        report = case.evaluate(now)
        self.assertEqual(report['status'], 'closed', '开盘宽限期内不得生成 error 结果')
        self.assertEqual(report['results'], {})

    def test_1300_boundary_lag_produces_no_push_and_no_state_write(self):
        case = ObserverTests('test_valid_computation_matches_real_gate_and_wilder')
        case.setUp()
        self.addCleanup(case.doCleanups)
        now = NOW.replace(hour=13, minute=0, second=1)
        case.quote['timestamp'] = NOW.replace(hour=12, minute=59, second=30).isoformat()
        self.assertEqual(case.run_watch(now), '', '开盘第一拍不得推送')
        self.assertFalse((case.root / 'intraday-gate-watch/latest.json').exists(),
                         '静默拍不得写观察器状态')

    def test_0931_opening_lag_is_silent(self):
        case = ObserverTests('test_valid_computation_matches_real_gate_and_wilder')
        case.setUp()
        self.addCleanup(case.doCleanups)
        now = NOW.replace(hour=9, minute=31, second=0)
        case.quote['timestamp'] = NOW.replace(hour=9, minute=30, second=30).isoformat()
        self.assertEqual(case.run_watch(now), '')

    def test_outside_grace_cross_session_quote_still_rejected(self):
        """宽限期外的跨时段旧快照必须继续报 quote_session，安全契约不削弱。"""
        case = ObserverTests('test_valid_computation_matches_real_gate_and_wilder')
        case.setUp()
        self.addCleanup(case.doCleanups)
        now = NOW.replace(hour=13, minute=2, second=0)
        case.quote['timestamp'] = NOW.replace(hour=12, minute=59, second=30).isoformat()
        self.assertEqual(case.result(now)['kind'], 'quote_session')

    def test_normal_1315_snapshot_still_works(self):
        case = ObserverTests('test_valid_computation_matches_real_gate_and_wilder')
        case.setUp()
        self.addCleanup(case.doCleanups)
        now = NOW.replace(hour=13, minute=15, second=1)
        case.quote['timestamp'] = NOW.replace(hour=13, minute=15, second=0).isoformat()
        self.assertEqual(case.result(now)['status'], 'ok')

    def test_already_refreshed_1300_snapshot_still_works(self):
        """行情已刷新到 13:00:00 时（真实 11-13 情形），该拍正常观察不被跳过。"""
        case = ObserverTests('test_valid_computation_matches_real_gate_and_wilder')
        case.setUp()
        self.addCleanup(case.doCleanups)
        now = NOW.replace(hour=13, minute=0, second=1)
        case.quote['timestamp'] = NOW.replace(hour=13, minute=0, second=0).isoformat()
        self.assertEqual(case.result(now)['status'], 'ok')

    def test_wrong_day_quote_never_silenced_by_grace(self):
        case = ObserverTests('test_valid_computation_matches_real_gate_and_wilder')
        case.setUp()
        self.addCleanup(case.doCleanups)
        now = NOW.replace(hour=13, minute=0, second=1)
        case.quote['timestamp'] = (NOW - timedelta(days=1)).replace(
            hour=12, minute=59, second=30).isoformat()
        self.assertEqual(case.result(now)['kind'], 'quote_wrong_day')


if __name__ == '__main__':
    unittest.main()
