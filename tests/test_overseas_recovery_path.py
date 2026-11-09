# -*- coding: utf-8 -*-
"""TDD：跨境买入恢复路径第 1-3 步（2026-11-09 Master 授权「按恢复路径走」）。

第 4 步解除暂停不在本文件范围（需 Master 单独确认，本轮不动 paused 标志）。

契约（均按 Master 已批准的四项拍板倾向）：
1. 数据口径：盘中一律不推买入；收盘后才给「观察提示（非执行指令）」，
   明确标注净值日期、滞后天数、非实时 IOPV；不接实时 IOPV 数据源。
2. 状态唯一写入者：副本链状态文件独立，暂停标志仍共享；
   首次运行从旧状态继承去重状态，避免重复推送。
3. 市况门控：净值连续 N 日下行 → 不开新档（最简形式）。
4. 止损锚点：改用首档买入成本固定，加仓后止损线不再下移。
5. 预算口径：预算为硬上限，超出即静默买入并留痕；份额按资金口径给参考值。
6. 文案降级：买入类信号一律「观察提示（非执行指令）」，不写「买入30%」。
7. 回归：暂停闸门、止损信号、配置缺失 fail-closed 全部保持。
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


def _load(name='otm_recovery'):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDate:
    current = '2026-11-09'

    @classmethod
    def today(cls):
        return cls

    @classmethod
    def isoformat(cls):
        return cls.current


def _quote(price, low, hhmm='1030'):
    return dict(price=price, high=price + 0.01, low=low,
                quote_time='20261109' + hhmm + '00')


def _navs_flat(n=8, v=1.52):
    return [('2026-10-%02d' % (20 + i), v) for i in range(n)]


def _navs_down(n=8):
    return [('2026-10-%02d' % (20 + i), 1.60 - i * 0.02) for i in range(n)]


def _positions(root, *, qty=9000, unit_cost='1.6002', total_cost='14401.44',
               budget='30000', extra_lot=None):
    lots = [{'tranche': 1, 'date': '2026-11-03', 'side': 'buy', 'qty': 9000,
             'price': '1.600', 'total_cost': '14401.44'}]
    if extra_lot:
        lots.append(extra_lot)
    p = root / 'overseas-positions.json'
    p.write_text(json.dumps({'sz159866': dict(qty=qty, unit_cost=unit_cost,
                                              total_cost=total_cost, budget=budget,
                                              lots=lots)}), encoding='utf-8')
    return p


class Fixture(unittest.TestCase):
    def setUp(self):
        self.otm = _load('otm_rec_' + self.id().split('.')[-1])
        self.otm.date = FakeDate
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.otm.STATE = self.root / 'overseas-triggers-dsh.json'
        self.otm.PAUSE_FLAG = self.root / 'overseas-buy-pause.json'
        self.otm.POSITIONS = _positions(self.root)
        self.otm._LAST_PREMIUM_META = dict(净值日期='2026-11-06', 溢价口径='滞后净值',
                                           数据源='东财已发布净值', 净值序列=_navs_flat())

    def tearDown(self):
        self._tmp.cleanup()


class TestDataBasisDowngrade(Fixture):
    """第 1 步：盘中不推买入，收盘后观察提示并要求人工复核。"""

    def test_intraday_buy_silenced(self):
        self.otm._quote = lambda sym: _quote(1.51, 1.505, '1030')
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 1.0
        fires, data = self.otm.check_nikkei()
        self.assertEqual(fires, [])
        self.assertIn('盘中', str(data.get('时段状态', '')))

    def test_after_close_emits_observation_not_order(self):
        self.otm._quote = lambda sym: _quote(1.51, 1.505, '1530')
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 1.0
        fires, _ = self.otm.check_nikkei()
        self.assertEqual(len(fires), 1)
        msg = fires[0][1]
        self.assertIn('观察提示', msg)
        self.assertIn('非执行指令', msg)
        self.assertNotIn('买入30%', msg)
        self.assertIn('非实时', msg)
        self.assertIn('2026-11-06', msg)

    def test_nasdaq_intraday_buy_silenced(self):
        self.otm.RULES = dict(self.otm.RULES)
        self.otm._nav_series = lambda code, n=250: [('2026-11-06', 2.0)]
        self.otm._spot = lambda sym: 2.01  # +0.5%，低于启动线
        fires, data = self.otm.check_nasdaq()
        self.assertEqual(fires, [])
        self.assertIn('盘中', str(data.get('时段状态', '')))

    def test_stale_nav_days_recorded(self):
        self.otm._quote = lambda sym: _quote(1.51, 1.505, '1530')
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 1.0
        _, data = self.otm.check_nikkei()
        self.assertEqual(data.get('净值滞后天数'), 3)


class TestStateWriterIsolation(Fixture):
    """第 2 步：副本链状态文件独立，暂停标志仍共享。"""

    def test_state_file_is_chain_specific(self):
        fresh = _load('otm_state_path')
        self.assertEqual(fresh.STATE.name, 'overseas-triggers-dsh.json')
        self.assertEqual(fresh.PAUSE_FLAG.name, 'overseas-buy-pause.json')
        self.assertEqual(fresh.STATE.parent, fresh.PAUSE_FLAG.parent)

    def test_first_run_inherits_dedup_state(self):
        legacy = self.root / 'overseas-triggers.json'
        legacy.write_text(json.dumps({'active': [], 'touch': {'nikkei_t2': '2026-11-06'}}),
                          encoding='utf-8')
        self.otm.check_nasdaq = lambda: ([], dict(prem=16.0))
        self.otm.check_nikkei = lambda: ([], dict(price=1.51))
        with redirect_stdout(io.StringIO()):
            self.otm.main()
        state = json.loads(self.otm.STATE.read_text(encoding='utf-8'))
        self.assertEqual(state.get('touch', {}).get('nikkei_t2'), '2026-11-06')


class TestMarketRegime(Fixture):
    """第 3 步之一：连续下跌不开新档。"""

    def test_consecutive_down_blocks_tranche(self):
        self.otm._LAST_PREMIUM_META = dict(净值日期='2026-11-06', 溢价口径='滞后净值',
                                           数据源='东财已发布净值', 净值序列=_navs_down())
        self.otm._quote = lambda sym: _quote(1.51, 1.505, '1530')
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 1.0
        fires, data = self.otm.check_nikkei()
        self.assertEqual(fires, [])
        self.assertIn('单边下跌', str(data.get('市况状态', '')))

    def test_flat_nav_allows_observation(self):
        self.otm._quote = lambda sym: _quote(1.51, 1.505, '1530')
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 1.0
        fires, _ = self.otm.check_nikkei()
        self.assertEqual(len(fires), 1)


class TestStopAnchor(Fixture):
    """第 3 步之二：止损锚定首档成本，加仓不下移。"""

    def test_stop_unchanged_after_second_tranche(self):
        otm = self.otm
        base = otm._nikkei_stop_price()
        self.otm.POSITIONS = _positions(
            self.root, qty=18000, unit_cost='1.5561', total_cost='28081.44',
            extra_lot={'tranche': 2, 'date': '2026-11-06', 'side': 'buy',
                       'qty': 9000, 'price': '1.52', 'total_cost': '13680.00'})
        after = otm._nikkei_stop_price()
        self.assertEqual(base, after, '加仓后止损线随成本下移 → 锚点未修')
        self.assertAlmostEqual(after, 1.2002, places=4)

    def test_stop_works_without_lots(self):
        p = self.root / 'overseas-positions.json'
        p.write_text(json.dumps({'sz159866': {'qty': 9000, 'unit_cost': '1.6002',
                                              'total_cost': '14401.44', 'budget': '30000'}}),
                     encoding='utf-8')
        self.otm.POSITIONS = p
        self.assertAlmostEqual(self.otm._nikkei_stop_price(), 1.2002, places=4)

    def test_intraday_stop_still_fires_when_buy_silenced(self):
        self.otm._quote = lambda sym: _quote(1.19, 1.188, '1030')
        self.otm._nikkei_prem = lambda p: None
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_stop'])


class TestBudgetHardCap(Fixture):
    """第 3 步之三：预算硬上限，份额按资金口径给参考值。"""

    def test_budget_exceeded_silences_buy(self):
        # 预算压到 20,000：已投 14,401.44 + 二档 9,000×1.52=13,680 → 28,081.44 超预算
        self.otm.POSITIONS = _positions(self.root, budget='20000')
        self.otm._quote = lambda sym: _quote(1.51, 1.505, '1530')
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 1.0
        fires, data = self.otm.check_nikkei()
        self.assertEqual(fires, [])
        self.assertTrue(data.get('预算状态', '').startswith('超预算'))

    def test_budget_headroom_shows_reference_shares(self):
        self.otm._quote = lambda sym: _quote(1.51, 1.505, '1530')
        self.otm._nikkei_stop_price = lambda: None
        self.otm._nikkei_prem = lambda p: 1.0
        fires, _ = self.otm.check_nikkei()
        self.assertEqual(len(fires), 1)
        self.assertIn('参考份额', fires[0][1])


class TestConfigAndPauseRegression(Fixture):
    """配置真源与暂停闸门不得回退。"""

    def test_rules_record_new_decisions(self):
        cfg = json.loads(RULES.read_text(encoding='utf-8'))
        self.assertEqual(cfg['文案模式'], '观察提示')
        self.assertTrue(cfg['预算硬拦截'])
        self.assertEqual(cfg['止损锚点'], '首档成本')
        self.assertTrue(cfg['市况门控启用'])
        self.assertEqual(cfg['买入观察起始时间'], '1500')
        self.assertFalse(cfg['接入实时估值'])

    def test_pause_still_suppresses_buy_in_main(self):
        self.otm.PAUSE_FLAG.write_text('{"paused": true}', encoding='utf-8')
        self.otm.check_nasdaq = lambda: ([('nasdaq_premium', 'BUY', True)], dict(prem=1.0))
        self.otm.check_nikkei = lambda: ([], dict(price=1.51))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.otm.main()
        self.assertNotIn('BUY', buf.getvalue())

    def test_missing_rules_keeps_stop(self):
        self.otm.RULES = None
        self.otm._quote = lambda sym: _quote(1.19, 1.188, '1030')
        self.otm._nikkei_prem = lambda p: None
        fires, _ = self.otm.check_nikkei()
        self.assertEqual([f[0] for f in fires], ['nikkei_stop'])


if __name__ == '__main__':
    unittest.main()
