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
        self.otm._nikkei_prem = lambda p: 1.0  # 溢价在闸门内（不触网）

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

    def test_normal_path_records_prem(self):
        """未触发时 data 也要带 prem（2026-11-04 验收瑕疵：只有闸门拦截分支带，
        正常分支缺失导致状态文件 nikkei.prem 为空、无法事后审计溢价）。"""
        self.otm._quote = lambda sym: _quote_f(1.55, 1.56, 1.515)
        _, data = self.otm.check_nikkei()
        self.assertEqual(data.get('prem'), 1.0)


class TestPremiumGate(unittest.TestCase):
    """溢价硬闸门（2026-11-04 用户拍板：日经 159866 >2% 不买/不加仓；纳指 513300 >3% 放弃；
    L74 旧启动线 prem<5% 一并改掉——5% 本身就破了 3% 放弃线）。

    闸门语义：溢价超标 → 买入类信号整体静默（不推送），data 里记 prem 供排查；
    止损线不受闸门影响（卖出信号任何时候都要响）。
    """

    def setUp(self):
        self.otm = _load()
        self.otm.date = FakeDate
        # 净值序列：峰值 2.2 → 现值 2.0 = 回撤 -9.1%（≥8% 加仓线）
        self.otm._nav_series = lambda code, n=250: [('2026-01-01', 2.2), ('2026-11-03', 2.0)]

    # ---- 纳指侧 ----

    def test_nasdaq_startup_line_requires_prem_below_3(self):
        """溢价 +3.5%：旧 prem<5% 启动线会推「方案可启动」——新口径必须静默。"""
        self.otm._spot = lambda sym: 2.07  # 2.07/2.0-1 = +3.5%
        fires, _ = self.otm.check_nasdaq()
        self.assertNotIn('nasdaq_premium', [f[0] for f in fires])

    def test_nasdaq_startup_fires_when_prem_below_3(self):
        """溢价 +2.5%：<3% 安全区 → 启动信号照常推。"""
        self.otm._spot = lambda sym: 2.05
        fires, _ = self.otm.check_nasdaq()
        self.assertIn('nasdaq_premium', [f[0] for f in fires])

    def test_nasdaq_drawdown_suppressed_when_prem_above_3(self):
        """回撤 -9.1% 达加仓线，但溢价 +11% → 闸门否决，不推加仓信号。"""
        self.otm._spot = lambda sym: 2.22
        fires, data = self.otm.check_nasdaq()
        self.assertNotIn('nasdaq_drawdown', [f[0] for f in fires])
        self.assertIn('prem', data)

    def test_nasdaq_drawdown_fires_when_prem_below_3(self):
        """回撤 -9.1% 且溢价 +1% → 加仓信号照常推。"""
        self.otm._spot = lambda sym: 2.02
        fires, _ = self.otm.check_nasdaq()
        self.assertIn('nasdaq_drawdown', [f[0] for f in fires])

    # ---- 日经侧（>2% 不买/不加仓） ----

    def test_nikkei_tranche_suppressed_when_prem_above_2(self):
        """现价 1.51 在二档区，但溢价 +2.5% → 闸门否决，不推买入档位。"""
        self.otm._quote = lambda sym: _quote_f(1.51, 1.517, 1.505)
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 2.5
        fires, data = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], [])
        self.assertIn('prem', data)

    def test_nikkei_tranche_fires_when_prem_below_2(self):
        """现价 1.51 在二档区，溢价 +1.5% → 二档信号照常推。"""
        self.otm._quote = lambda sym: _quote_f(1.51, 1.517, 1.505)
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 1.5
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_t2'])

    def test_nikkei_stop_not_gated_by_premium(self):
        """现价破止损线时溢价再高也必须响——卖出信号不受买入闸门约束。"""
        self.otm._quote = lambda sym: _quote_f(1.19, 1.61, 1.188)
        self.otm._nikkei_stop_price = lambda: 1.2002
        self.otm._nikkei_prem = lambda p: 5.0
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_stop'])

    def test_nikkei_prem_fetch_fail_no_silent_block(self):
        """溢价拉不到（None）→ 闸门不放行也不硬拦：信号照常推（fail-open 提示型监控，
        且触价≠成交，用户执行前还有当天实时 IOPV 一道人工闸）。"""
        self.otm._quote = lambda sym: _quote_f(1.51, 1.517, 1.505)
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: None
        fires, data = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_t2'])
        self.assertIsNone(data.get('prem'))


class TestNikkeiStop(unittest.TestCase):
    """止损线代码载体（2026-11-03 收编缺口：账本写明止损=成本×0.75，脚本零执行）。

    规则来源：overseas-positions.json plan 字段"止损=加权成本×0.75"（用户既定）。
    止损价动态取账本 unit_cost×0.75，不写死数字；账本缺失/损坏 → None 不误报。
    止损优先于二/三档买入提醒：盘中破过止损线还提示买入是错误信号。
    """

    def setUp(self):
        self.otm = _load()
        self.otm.date = FakeDate
        self.otm._nikkei_stop_price = lambda: 1.2002
        self.otm._nikkei_prem = lambda p: 1.0  # 止损不受溢价闸门影响，但避免触网

    def test_price_at_stop_fires_persistent(self):
        """现价 1.200 已破止损线 1.2002 → 持续触发 nikkei_stop。"""
        self.otm._quote = lambda sym: _quote_f(1.200, 1.61, 1.198)
        fires, data = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_stop'])
        self.assertTrue(fires[0][2], '止损属持续触发，必须标记 persistent')

    def test_price_above_stop_no_fire(self):
        """现价 1.589 远高于止损线 → 不触发。"""
        self.otm._quote = lambda sym: _quote_f(1.589, 1.60, 1.585)
        fires, _ = self.otm.check_nikkei()
        self.assertNotIn('nikkei_stop', [f[0] for f in fires])

    def test_stop_takes_priority_over_tranches(self):
        """现价 1.19 同时穿二/三档与止损线 → 只推止损，不推买入档位。"""
        self.otm._quote = lambda sym: _quote_f(1.19, 1.61, 1.188)
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_stop'])

    def test_intraday_low_touches_stop_is_touch_alert(self):
        """盘中最低 1.199 破止损线、现价 1.51 回升 → 触价型提醒，且不再提示买入档位。"""
        self.otm._quote = lambda sym: _quote_f(1.51, 1.61, 1.199)
        fires, data = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_stop'])
        self.assertFalse(fires[0][2], '触价回升属 touch 型，不进 active')
        self.assertEqual(data.get('low'), 1.199)

    def test_ledger_missing_no_crash_no_false_alarm(self):
        """账本缺失/损坏 → stop=None → 不触发、不崩溃。"""
        self.otm._nikkei_stop_price = lambda: None
        self.otm._quote = lambda sym: _quote_f(1.200, 1.61, 1.198)
        fires, _ = self.otm.check_nikkei()
        self.assertNotIn('nikkei_stop', [f[0] for f in fires])


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
