# -*- coding: utf-8 -*-
"""TDD: 买入类信号被闸门静默时不得误推「触发已解除」噪音。

事故（2026-11-23 09:00）：11-20 日经第二档触发写入 state['active']=['nikkei_t2']；
11-23 09:00 因「盘中不推买入」时段闸门，本轮 fires 为空，main() 用
prev_active - now_active 判定「触发已解除」并推送 ℹ️ 噪音。买入类文案按
overseas_grid_rules.json 只是观察提示、不是状态机，解除通知一律不推。
"""
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy_scripts' / 'overseas_trigger_monitor.py'


def _load():
    spec = importlib.util.spec_from_file_location('otm_release_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDate:
    current = '2026-11-20'

    @classmethod
    def today(cls):
        return cls

    @classmethod
    def isoformat(cls):
        return cls.current


class TestNoBuyReleaseNoise(unittest.TestCase):
    def setUp(self):
        self.otm = _load()
        self.otm.date = FakeDate
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.otm.STATE = self.root / 'overseas-triggers.json'
        self.otm.PAUSE_FLAG = self.root / 'overseas-buy-pause.json'
        self.otm.check_nasdaq = lambda: ([], dict(prem=14.8, dd=-14.9))
        # 11-20 15:xx：第二档触发，persistent=True 进 active
        self.otm.check_nikkei = lambda: (
            [('nikkei_t2', '👀 159866 现价 1.428 进入第二档', True)],
            dict(price=1.428, low=1.427, 溢价状态='已通过', 时段状态='收盘后观察窗口'))
        FakeDate.current = '2026-11-20'

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.otm.main()
        return buf.getvalue()

    def test_time_gate_silence_must_not_push_release_noise(self):
        """11-23 09:00 时段闸门静默 → 不得推「触发已解除」。"""
        out_first = self._run()
        self.assertIn('进入第二档', out_first)
        FakeDate.current = '2026-11-23'
        self.otm.check_nikkei = lambda: (
            [], dict(price=1.411, low=1.405, 溢价状态='已通过',
                     时段状态='盘中不推买入（净值滞后，收盘后再给观察提示）'))
        try:
            out = self._run()
            self.assertNotIn('触发已解除', out)
            self.assertEqual(out, '')
        finally:
            FakeDate.current = '2026-11-20'

    def test_premium_gate_silence_must_not_push_release_noise(self):
        """溢价超闸门静默同样不得误判为解除。"""
        self._run()
        FakeDate.current = '2026-11-23'
        self.otm.check_nikkei = lambda: (
            [], dict(price=1.411, low=1.405, 溢价状态='超闸门静默'))
        try:
            out = self._run()
            self.assertNotIn('触发已解除', out)
        finally:
            FakeDate.current = '2026-11-20'

    def test_nasdaq_buy_signal_also_no_release_noise(self):
        """纳指买入类信号同样不推解除噪音。"""
        self.otm.check_nasdaq = lambda: (
            [('nasdaq_premium', '👀 513300 溢价回到启动线', True)],
            dict(prem=2.1, dd=-4.2))
        self._run()
        FakeDate.current = '2026-11-23'
        self.otm.check_nasdaq = lambda: ([], dict(prem=11.0, dd=-4.2))
        try:
            out = self._run()
            self.assertNotIn('触发已解除', out)
        finally:
            FakeDate.current = '2026-11-20'


if __name__ == '__main__':
    unittest.main()
