"""日频波动扩张预警（2026-11-06 Master 授权，只读观察任务）。

规则：3 个交易日内 ≥2 日「日振幅≥4% 且 量比≥1.5」→ 提示波动扩张。
用绝对阈值组合，不用相对扩张比（基数抬高后相对阈值会钝化）。
只读：不改账本、不生成买卖建议、不自动建仓；无触发时不输出（wrapper 静默）。
"""
import importlib.util
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO / 'deploy_scripts' / 'volatility_expansion_watch.py'


def _api():
    spec = importlib.util.spec_from_file_location('volatility_watch_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _day(date, amp=1.0, vol=100.0, close=1.0):
    """构造一行日线：振幅 amp%，成交量 vol。"""
    return dict(date=date, open=close, high=close * (1 + amp / 200),
                low=close * (1 - amp / 200), close=close, volume=vol)


def _history(n=25, amp=1.0, vol=100.0):
    return [_day(f'2026-10-{i:02d}', amp, vol) for i in range(1, n + 1)]


class RuleTests(unittest.TestCase):
    def test_rule_b_triggers_on_two_qualifying_days(self):
        api = _api()
        rows = _history(22) + [_day('2026-11-02', 5.0, 300.0),
                               _day('2026-11-03', 1.0, 100.0),
                               _day('2026-11-04', 6.0, 250.0)]
        out = api.evaluate('sz159206', '卫星ETF测试', rows)
        self.assertTrue(out['triggered'])
        self.assertEqual(out['hit_days'], 2)

    def test_single_qualifying_day_does_not_trigger(self):
        api = _api()
        rows = _history(22) + [_day('2026-11-02', 5.0, 300.0),
                               _day('2026-11-03', 1.0, 100.0),
                               _day('2026-11-04', 1.0, 100.0)]
        self.assertFalse(api.evaluate('sz159206', '卫星ETF测试', rows)['triggered'])

    def test_amplitude_without_volume_does_not_trigger(self):
        api = _api()
        rows = _history(22) + [_day('2026-11-02', 5.0, 100.0),
                               _day('2026-11-04', 6.0, 100.0)]
        self.assertFalse(api.evaluate('sz159206', '卫星ETF测试', rows)['triggered'])

    def test_absolute_rule_survives_elevated_baseline(self):
        """规则A（5日均振幅≥前20日1.5倍）在高基数会钝化；规则B仍须触发。"""
        api = _api()
        rows = (_history(10, 5.0, 200.0) + _history(10, 5.0, 200.0)
                + [_day('2026-11-02', 6.0, 400.0), _day('2026-11-04', 6.0, 400.0)])
        # 用唯一日期，避免重复 date 影响窗口
        rows = [dict(r, date=f'2026-09-{i + 1:02d}') for i, r in enumerate(rows[:22])] + [
            _day('2026-11-02', 6.0, 400.0), _day('2026-11-03', 5.0, 200.0),
            _day('2026-11-04', 6.0, 400.0)]
        out = api.evaluate('sz159206', '卫星ETF测试', rows)
        self.assertTrue(out['triggered'], '绝对阈值规则不得因波动基数抬高而失效')
        self.assertGreaterEqual(out['amp20_mean'], 4.0)

    def test_insufficient_history_fails_closed(self):
        api = _api()
        out = api.evaluate('sz159206', '卫星ETF测试', _history(8, 8.0, 500.0))
        self.assertFalse(out['triggered'])
        self.assertIn('数据不足', out['reason'])

    def test_metrics_are_computed_not_hardcoded(self):
        api = _api()
        rows = _history(22) + [_day('2026-11-04', 8.0, 300.0)]
        out = api.evaluate('sz159206', '卫星ETF测试', rows)
        self.assertAlmostEqual(out['latest_amp'], 8.0, places=2)
        self.assertAlmostEqual(out['latest_volume_ratio'], 3.0, places=2)


class RenderTests(unittest.TestCase):
    def _signal(self):
        api = _api()
        rows = _history(22) + [_day('2026-11-02', 5.0, 300.0),
                               _day('2026-11-03', 1.0, 100.0),
                               _day('2026-11-04', 6.0, 250.0)]
        return api.evaluate('sz159206', '卫星ETF测试', rows)

    def test_render_has_no_trade_advice(self):
        api = _api()
        text = api.render([self._signal()])
        for banned in ('建议买入', '建议卖出', '挂单', '下单', '建仓'):
            self.assertNotIn(banned, text, f'预警不得含交易动作：{banned}')

    def test_render_carries_disclaimer_and_observation_fields(self):
        api = _api()
        text = api.render([self._signal()])
        self.assertIn('仅观察', text)
        self.assertIn('sz159206', text)
        self.assertIn('振幅', text)
        self.assertIn('量比', text)
        self.assertIn('失效信号', text)

    def test_to_secid_normalizes_all_universe_formats(self):
        """观察池混用 holdings 的纯6位与榜单的 sh/sz 前缀；取数前必须统一。"""
        api = _api()
        self.assertEqual(api.to_secid('589720'), '1.589720')
        self.assertEqual(api.to_secid('159363'), '0.159363')
        self.assertEqual(api.to_secid('sh589720'), '1.589720')
        self.assertEqual(api.to_secid('sz159206'), '0.159206')
        self.assertEqual(api.to_secid('1.000001'), '1.000001')

    def test_fetch_failures_are_disclosed_not_silent(self):
        """取数失败不得伪装成「无触发」，必须披露缺口。"""
        import tempfile
        api = _api()
        def broken(code):
            raise OSError('network down')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'cache' / 'grid-account'
            root.mkdir(parents=True)
            (root / 'holdings.json').write_text(json.dumps(
                {'holdings': {'589720': {'active': True, 'name': '测试ETF'}}}), encoding='utf-8')
            text = api.run(account_root=Path(td), fetch=broken)
        self.assertIn('取数失败', text)

    def test_no_signal_returns_empty_output(self):
        api = _api()
        self.assertEqual(api.render([]), '')


class ReadOnlyTests(unittest.TestCase):
    def test_main_does_not_write_into_account_root(self):
        """预警任务只读账本根：confirmed-*.json / holdings.json 哈希前后不变。"""
        import hashlib
        import tempfile
        api = _api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'grid-account'
            root.mkdir()
            ledger = root / 'confirmed-589720.json'
            ledger.write_text(json.dumps({'qty': 47700}), encoding='utf-8')
            holdings = root / 'holdings.json'
            holdings.write_text(json.dumps({'holdings': {}}), encoding='utf-8')
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (ledger, holdings)}
            fixture = root / 'fixture.json'
            fixture.write_text(json.dumps({'sz159206': _history(22) + [
                _day('2026-11-02', 5.0, 300.0), _day('2026-11-03', 1.0, 100.0),
                _day('2026-11-04', 6.0, 250.0)]}), encoding='utf-8')
            out = api.run(fixture_path=fixture, account_root=root)
            after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (ledger, holdings)}
            self.assertEqual(before, after)
            self.assertIn('sz159206', out)


class JobRegistrationTests(unittest.TestCase):
    def _wrapper(self):
        spec = importlib.util.spec_from_file_location(
            'run_and_push_jobs_under_test', REPO / 'deploy_scripts' / 'run_and_push.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_volatility_job_registered_inside_ah_analyse(self):
        module = self._wrapper()
        self.assertIn('volatility_watch', module.JOBS)
        path = Path(module.resolve_script('volatility_watch')).resolve()
        self.assertTrue(str(path).lower().startswith(str(REPO).lower()))
        self.assertTrue(path.is_file(), f'脚本不存在：{path}')

    def test_volatility_job_is_push_on(self):
        module = self._wrapper()
        self.assertEqual(module.JOBS['volatility_watch']['push'], 'on')


if __name__ == '__main__':
    unittest.main()
