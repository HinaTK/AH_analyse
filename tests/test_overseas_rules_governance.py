# -*- coding: utf-8 -*-
"""TDD：跨境线审核 9 项问题中的治理/可观测性修复（2026-11-06）。

只覆盖不改交易阈值、不改三档方案、不动暂停闸门的修复：
- 规则单一真源（R1/R2）：结构化配置 + 一致性护栏，脚本不再硬编码阈值。
- 闸门 fail-closed（M1）：净值源不可用时买入信号静默，且溢价留痕标注口径。
- 异常告警（M5）：check_* 抛异常不再静默。
- 预算只读校验（M4）：账本额度不足时留痕告警（不拦截，拦截需拍板）。

不覆盖（需 Master 拍板）：市况门控(M2)、止损锚点(M3)、预算是否拦截、文案是否降级。
"""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'deploy_scripts' / 'overseas_trigger_monitor.py'
RULES = REPO / 'deploy_scripts' / 'overseas_grid_rules.json'


def _load(name='otm_gov_under_test'):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDate:
    current = '2026-11-06'

    @classmethod
    def today(cls):
        return cls

    @classmethod
    def isoformat(cls):
        return cls.current


QT = '20261106103000'


def _quote(price, low):
    return dict(price=price, high=price + 0.01, low=low, quote_time=QT)


class TestRulesSingleSource(unittest.TestCase):
    """R1/R2：阈值必须来自唯一配置，且配置值与现行规则一致（不动阈值）。"""

    def test_rules_file_exists_and_has_required_fields(self):
        self.assertTrue(RULES.exists(), '缺少唯一真源配置文件')
        cfg = json.loads(RULES.read_text(encoding='utf-8'))
        self.assertIn('溢价上限百分比', cfg)
        self.assertIn('日经禁买溢价百分比', cfg)
        self.assertIn('纳指启动溢价百分比', cfg)
        self.assertIn('纳指加仓回撤百分比', cfg)
        self.assertIn('止损比例', cfg)
        self.assertIn('预算总额', cfg)

    def test_rules_values_match_current_policy(self):
        """护栏：阈值必须仍是现行值，防止有人借「修复」偷偷放宽。"""
        cfg = json.loads(RULES.read_text(encoding='utf-8'))
        self.assertEqual(cfg['溢价上限百分比'], 3.0)
        self.assertEqual(cfg['日经禁买溢价百分比'], 2.0)
        self.assertEqual(cfg['纳指启动溢价百分比'], 3.0)
        self.assertEqual(cfg['纳指加仓回撤百分比'], -8.0)
        self.assertEqual(cfg['止损比例'], 0.75)
        self.assertEqual(cfg['预算总额'], 30000)

    def test_script_reads_rules_not_hardcoded(self):
        """改配置值应改变判定行为，证明脚本真读配置而非硬编码。"""
        otm = _load('otm_rules_behavior')
        otm.date = FakeDate
        otm._nikkei_stop_price = lambda: None
        otm._quote = lambda sym: _quote(1.51, 1.505)
        otm._nikkei_prem = lambda p: 2.5
        otm.RULES = dict(otm.RULES)
        otm.RULES['日经禁买溢价百分比'] = 3.0  # 放宽到 3%（仅测试注入）
        fires, _ = otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_t2'], '配置改了但行为没变 → 仍是硬编码')

    def test_nasdaq_uses_configured_start_threshold(self):
        otm = _load('otm_rules_nasdaq')
        otm.RULES = dict(otm.RULES)
        otm.RULES['纳指启动溢价百分比'] = 1.0
        otm._nav_series = lambda code, n=250: [('2026-11-06', 2.0)]
        otm._spot = lambda sym: 2.05  # +2.5%
        fires, _ = otm.check_nasdaq()
        self.assertNotIn('nasdaq_premium', [f[0] for f in fires])

    def test_missing_rules_keeps_stop_signal(self):
        """配置缺失只能静默买入，绝不静默止损（风控卖出任何时候都要响）。"""
        otm = _load('otm_rules_missing_stop')
        otm.date = FakeDate
        otm.RULES = None
        otm._quote = lambda sym: _quote(1.19, 1.188)
        otm._nikkei_prem = lambda p: None
        with tempfile.TemporaryDirectory() as folder:
            pos = Path(folder) / 'overseas-positions.json'
            pos.write_text(json.dumps({'sz159866': {'unit_cost': '1.6002', 'total_cost': '14401.44',
                                                    'budget': '30000'}}), encoding='utf-8')
            otm.POSITIONS = pos
            fires, data = otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_stop'])
        self.assertEqual(data.get('规则状态'), '规则配置缺失（止损用兜底比例）')

    def test_missing_rules_file_blocks_buy_signals(self):
        """配置缺失（唯一真源丢了）→ 买入静默 + 告警，不得用散落兜底值继续交易。"""
        otm = _load('otm_rules_missing')
        otm.date = FakeDate
        otm.RULES = None
        otm._nikkei_stop_price = lambda: None
        otm._quote = lambda sym: _quote(1.51, 1.505)
        otm._nikkei_prem = lambda p: 1.0
        fires, data = otm.check_nikkei()
        self.assertEqual(fires, [])
        self.assertIn('规则配置缺失', str(data.get('规则状态', '')))


class TestPremiumFailClosed(unittest.TestCase):
    """M1：净值源不可用必须 fail-closed，且溢价口径要留痕。"""

    def setUp(self):
        self.otm = _load('otm_failclosed_' + self.id().split('.')[-1])
        self.otm.date = FakeDate
        self.otm._nikkei_stop_price = lambda: None
        self.otm._quote = lambda sym: _quote(1.51, 1.505)

    def test_nav_unavailable_suppresses_buy(self):
        self.otm._nikkei_prem = lambda p: None
        fires, data = self.otm.check_nikkei()
        self.assertEqual(fires, [], '净值拉不到仍推买入 → fail-open 未修')
        self.assertEqual(data.get('溢价状态'), '数据不可用')

    def test_nav_unavailable_keeps_stop_signal(self):
        self.otm._nikkei_stop_price = lambda: 1.2002
        self.otm._quote = lambda sym: _quote(1.19, 1.188)
        self.otm._nikkei_prem = lambda p: None
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_stop'], 'fail-closed 不得拦止损')

    def test_premium_basis_is_recorded(self):
        """11-06 实证：滞后净值会算出假折价，必须标注净值日期与口径。"""
        self.otm._nikkei_prem = lambda p: 1.0
        self.otm._LAST_PREMIUM_META = dict(净值日期='2026-11-05', 溢价口径='滞后净值', 数据源='东财')
        fires, data = self.otm.check_nikkei()
        self.assertEqual(data.get('净值日期'), '2026-11-05')
        self.assertEqual(data.get('溢价口径'), '滞后净值')

    def test_push_text_warns_about_stale_basis(self):
        self.otm._nikkei_prem = lambda p: 1.0
        self.otm._LAST_PREMIUM_META = dict(净值日期='2026-11-05', 溢价口径='滞后净值', 数据源='东财')
        fires, _ = self.otm.check_nikkei()
        msg = fires[0][1]
        self.assertIn('非实时', msg)
        self.assertIn('2026-11-05', msg)


class TestErrorAlert(unittest.TestCase):
    """M5：check_* 抛异常不再静默；异常与「未触发」必须可区分。"""

    def setUp(self):
        self.otm = _load('otm_alert_' + self.id().split('.')[-1])
        self.otm.date = FakeDate
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.otm.STATE = self.root / 'overseas-triggers.json'
        self.otm.PAUSE_FLAG = self.root / 'overseas-buy-pause.json'

    def tearDown(self):
        self._tmp.cleanup()

    def test_check_exception_produces_alert(self):
        def boom():
            raise ValueError('上游超时')
        self.otm.check_nasdaq = boom
        self.otm.check_nikkei = lambda: ([], dict(price=1.5))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.otm.main()
        self.assertIn('数据异常', buf.getvalue())
        self.assertIn('纳指', buf.getvalue())

    def test_exception_recorded_in_state(self):
        def boom():
            raise ValueError('上游超时')
        self.otm.check_nasdaq = boom
        self.otm.check_nikkei = lambda: ([], dict(price=1.5))
        with redirect_stdout(io.StringIO()):
            self.otm.main()
        state = json.loads(self.otm.STATE.read_text(encoding='utf-8'))
        self.assertIn('检查异常', state)

    def test_no_false_alert_when_normal(self):
        self.otm.check_nasdaq = lambda: ([], dict(prem=12.0, dd=-5.0))
        self.otm.check_nikkei = lambda: ([], dict(price=1.5))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.otm.main()
        self.assertNotIn('数据异常', buf.getvalue())
        self.assertEqual(buf.getvalue(), '')

    def test_alert_deduped_within_same_day(self):
        """每 10 分钟跑一次，异常告警当天只推一次，不刷屏。"""
        def boom():
            raise ValueError('上游超时')
        self.otm.check_nasdaq = boom
        self.otm.check_nikkei = lambda: ([], dict(price=1.5))
        with redirect_stdout(io.StringIO()):
            self.otm.main()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.otm.main()
        self.assertNotIn('数据异常', buf.getvalue())


class TestBudgetReadOnlyCheck(unittest.TestCase):
    """M4：预算与档位份额的缺口要留痕；本轮只读告警，不拦截（拦截需拍板）。"""

    def setUp(self):
        self.otm = _load('otm_budget_' + self.id().split('.')[-1])
        self.otm.date = FakeDate
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.otm.STATE = self.root / 'overseas-triggers.json'
        self.otm.PAUSE_FLAG = self.root / 'overseas-buy-pause.json'
        self.otm.check_nasdaq = lambda: ([], dict(prem=12.0, dd=-5.0))
        self.otm.check_nikkei = lambda: ([], dict(price=1.5))

    def tearDown(self):
        self._tmp.cleanup()

    def test_budget_shortfall_recorded(self):
        pos = self.root / 'overseas-positions.json'
        pos.write_text(json.dumps({'sz159866': {'qty': 9000, 'total_cost': '14401.44',
                                                'unit_cost': '1.6002', 'budget': '30000'}}), encoding='utf-8')
        self.otm.POSITIONS = pos
        with redirect_stdout(io.StringIO()):
            self.otm.main()
        state = json.loads(self.otm.STATE.read_text(encoding='utf-8'))
        self.assertTrue(state.get('预算校验', {}).get('三档全建超额'), '缺口未留痕')
        self.assertFalse(state.get('预算校验', {}).get('已拦截'), '本轮不得擅自拦截')

    def test_no_shortfall_when_budget_sufficient(self):
        pos = self.root / 'overseas-positions.json'
        pos.write_text(json.dumps({'sz159866': {'qty': 9000, 'total_cost': '14401.44',
                                                'unit_cost': '1.6002', 'budget': '60000'}}), encoding='utf-8')
        self.otm.POSITIONS = pos
        with redirect_stdout(io.StringIO()):
            self.otm.main()
        state = json.loads(self.otm.STATE.read_text(encoding='utf-8'))
        self.assertFalse(state.get('预算校验', {}).get('三档全建超额'))


class TestPauseStillWorks(unittest.TestCase):
    """回归：本轮治理修复不得破坏昨夜的暂停闸门。"""

    def test_pause_flag_still_suppresses_buy(self):
        otm = _load('otm_pause_regression')
        otm.date = FakeDate
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            otm.STATE = root / 'overseas-triggers.json'
            otm.PAUSE_FLAG = root / 'overseas-buy-pause.json'
            otm.PAUSE_FLAG.write_text('{"paused": true}', encoding='utf-8')
            otm.check_nasdaq = lambda: ([('nasdaq_premium', 'BUY', True)], dict(prem=1.0))
            otm.check_nikkei = lambda: ([], dict(price=1.5))
            buf = io.StringIO()
            with redirect_stdout(buf):
                otm.main()
            self.assertNotIn('BUY', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
