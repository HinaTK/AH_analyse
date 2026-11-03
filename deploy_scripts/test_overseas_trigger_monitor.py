# -*- coding: utf-8 -*-
"""TDD：日经159866 触价判定改用盘中最低价（2026-10-30 设计缺口）。

事故回放（2026-10-30 真实行情）：159866 今开1.598、盘中最低1.595（≤1.600
第一档触发区），随后反弹至1.616。旧 check_nikkei 只判定"取价瞬间现价≤1.600"，
监控 cron 15:40 才跑——触价已回升 → 永不触发 → 用户提问"盘中到价了吗"时
监控毫无记录。

修复语义：
1. 触价判定用 min(现价, 盘中最低)：日低触及但现价回升 → 触价提醒
   （persistent=False，每日最多推一次，不进 active 不产生"已解除"噪音）；
2. 现价仍在建仓区 → 维持原持续触发（persistent=True，走原翻转逻辑）；
3. 触价提醒必须同时给 盘中最低+现价，防止"已回升还当在建仓区"误导追高；
4. 行情脏数据（low=0，开盘前）退化为现价判定，不得误报。
"""
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / 'overseas_trigger_monitor.py'


def _load():
    spec = importlib.util.spec_from_file_location('otm_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDate:
    current = '2026-10-30'

    @classmethod
    def today(cls):
        return cls

    @classmethod
    def isoformat(cls):
        return cls.current


_QT = '20261030143000'  # 当日 14:30 快照时间戳（时间门控放行）


def _quote_f(price, high, low):
    return dict(price=price, high=high, low=low, quote_time=_QT)


class TestNikkeiTouch(unittest.TestCase):
    """2026-11-03 一档已成交(9,000@1.600)，监控切二档≤1.52/三档≤1.42。"""

    def setUp(self):
        self.otm = _load()
        self.otm.date = FakeDate

    def test_intraday_low_touches_t2_even_if_price_rebounded(self):
        """盘中最低1.515≤1.52、现价1.55已回升 → 必须触发二档触价提醒。"""
        self.otm._quote = lambda sym: _quote_f(1.55, 1.56, 1.515)
        fires, data = self.otm.check_nikkei()
        keys = [f[0] for f in fires]
        self.assertIn('nikkei_t2', keys)
        msg = [f[1] for f in fires if f[0] == 'nikkei_t2'][0]
        self.assertIn('盘中最低', msg)
        self.assertIn('1.515', msg)
        self.assertIn('1.55', msg, '触价提醒必须同时给现价，防止误导追高')

    def test_no_touch_no_fire(self):
        """日低1.610未及1.52 → 不触发。"""
        self.otm._quote = lambda sym: _quote_f(1.616, 1.617, 1.610)
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], [])

    def test_current_in_t2_zone_is_persistent(self):
        """现价1.51仍在二档区 → 持续触发，必须带persistent=True。"""
        self.otm._quote = lambda sym: _quote_f(1.51, 1.517, 1.505)
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_t2'])
        self.assertTrue(fires[0][2], '现价在建仓区属持续触发，必须标记persistent')

    def test_touch_only_is_not_persistent(self):
        """触价已回升 → persistent=False，不进active。"""
        self.otm._quote = lambda sym: _quote_f(1.55, 1.56, 1.515)
        fires, _ = self.otm.check_nikkei()
        self.assertFalse(fires[0][2])

    def test_deep_touch_fires_t2_first(self):
        """日低1.41同时触及三档，但二档未成交 → 只推二档（break优先级）。"""
        self.otm._quote = lambda sym: _quote_f(1.55, 1.56, 1.41)
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_t2'])

    def test_low_invalid_falls_back_to_price(self):
        """脏数据 low=0（开盘前）→ 退化为现价判定，不得误报触价。"""
        self.otm._quote = lambda sym: _quote_f(1.616, 0.0, 0.0)
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], [])

    def test_data_records_low(self):
        """快照数据必须记录盘中最低，供排查与解除消息引用。"""
        self.otm._quote = lambda sym: _quote_f(1.55, 1.56, 1.515)
        _, data = self.otm.check_nikkei()
        self.assertEqual(data.get('low'), 1.515)


class TestTouchPushDedup(unittest.TestCase):
    """main() 层：触价每日一次、跨日重推、不产生解除噪音。"""

    def setUp(self):
        self.otm = _load()
        self.otm.date = FakeDate
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / 'overseas-triggers.json'
        self.otm.STATE = self.state_path
        self.otm.check_nasdaq = lambda: ([], dict(prem=11.0, dd=-4.2))
        self.otm.check_nikkei = lambda: (
            [('nikkei_t1', '⚠️ 159866 盘中最低 1.595 已触及第一档 1.600，现价 1.616 已回升', False)],
            dict(price=1.616, low=1.595))

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.otm.main()
        return buf.getvalue()

    def test_touch_pushes_once_per_day_then_silent(self):
        out1 = self._run()
        self.assertIn('盘中最低', out1)
        out2 = self._run()
        self.assertEqual(out2, '', '同日重跑不得重复推触价提醒')

    def test_new_day_new_touch_pushes_again(self):
        """次交易日再次触价必须再推（旧flip逻辑只推第一次）。"""
        self._run()
        FakeDate.current = '2026-11-02'
        try:
            out = self._run()
            self.assertIn('盘中最低', out)
        finally:
            FakeDate.current = '2026-10-30'

    def test_touch_key_not_in_active_no_release_noise(self):
        """触价键不进active：次日未再触价时不得推'已解除'噪音。"""
        self._run()
        FakeDate.current = '2026-11-02'
        self.otm.check_nikkei = lambda: ([], dict(price=1.640, low=1.630))
        try:
            out = self._run()
            self.assertEqual(out, '')
        finally:
            FakeDate.current = '2026-10-30'


if __name__ == '__main__':
    unittest.main()
