# -*- coding: utf-8 -*-
"""追加任务（2026-11-06 Master 授权）：周报紧凑头部之后接入锚价位移披露。

只读消费本次与上一期 result，不联网、不跑研究/回测、不改生产排名数字；
拿不到上期基准时输出「略过」文案，不报错、不编造数字。
父代理维护 anchor_sensitivity.py / test_anchor_sensitivity.py，本文件只测 weekly 接入。
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, r'D:\Code\AH_analyse')

import tools.etf_research.test_pair_review as helper
from tools.etf_research import weekly, research


def _result(asof, first_open, window_start, window_end):
    """构造带「完整窗口首根开盘价」的两期 fixture（只读数据，不触网不跑回测）。"""
    result = helper.fixture()
    result.update(leader=None, errors=[])
    result['summary'].update(
        version=research.VERSION, asof=asof,
        window_start=window_start, window_end=window_end,
        successful_runs=1284, failed_runs=0, attempted_assets=321,
        window_first_open=first_open)
    return result


class WeeklyAnchorDisclosureTests(unittest.TestCase):
    def _run(self, curr, prev_result=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = weekly.run_weekly(
                state_path=root / 'legacy.json', pair_state_path=root / 'pair.json',
                research_runner=lambda **kwargs: curr,
                taxonomy=helper.taxonomy(), prev_result=prev_result)
            return out['report']

    def test_two_period_fixture_reports_disclosure(self):
        curr = _result('2026-11-06', 1.289, '2026-08-04', '2026-11-06')
        prev = _result('2026-11-05', 1.250, '2026-08-03', '2026-11-05')
        report = self._run(curr, prev)
        self.assertIn('锚价位移披露', report)
        self.assertIn('仅披露不改口径', report)
        self.assertTrue(all(len(x) <= 120 for x in report.splitlines()),
                        '周报每行不得超过 120 字符')

    def test_no_prev_result_is_skipped_gracefully(self):
        curr = _result('2026-11-06', 1.289, '2026-08-04', '2026-11-06')
        report = self._run(curr)
        self.assertIn('无可比上期基准', report)
        self.assertIn('锚价位移披露', report)

    def test_prev_result_without_anchor_is_skipped(self):
        curr = _result('2026-11-06', 1.289, '2026-08-04', '2026-11-06')
        prev = _result('2026-11-05', 1.250, '2026-08-03', '2026-11-05')
        prev['summary'].pop('window_first_open')
        report = self._run(curr, prev)
        self.assertIn('无可比上期基准', report)
        self.assertNotIn('仅披露不改口径', report)


if __name__ == '__main__':
    unittest.main()
