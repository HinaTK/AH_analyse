# -*- coding: utf-8 -*-
"""每日 ETF 轻量快照 TDD（2026-11-06 Master 授权，只读观察任务）。

覆盖：字段完整性与 source_asof、append-only 不覆盖旧文件、只写 daily-snapshots
不写 rerank-*、窗口对齐才算 delta_rank、换窗标 window_shifted 且 delta_rank 为 null、
取数失败披露、无变化静默、render 不含交易动作词、JOBS 注册与路径约束、
只读（账本相关文件哈希不变），以及 volatility_expansion_watch._universe 的
「mtime 最新但不含榜单的目录不丢观察池」联动回归（RED→GREEN）。

全程 tempfile 隔离账本根、注入 fake fetch 与 fixture，禁止真实网络与真实账本写入；
只读核查与哈希比对仅针对 the agent harness 副本根的临时镜像，绝不读取 Hermes 生产根。
"""
import csv
import hashlib
import importlib.util
import json
import os
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO / 'deploy_scripts' / 'grid_daily_snapshot.py'
WATCH_PATH = REPO / 'deploy_scripts' / 'volatility_expansion_watch.py'
RUN_AND_PUSH_PATH = REPO / 'deploy_scripts' / 'run_and_push.py'
DEPLOY_PATH = REPO / 'tools' / 'confirmed_grid' / 'deploy.py'
HERMES_SCRIPTS = Path(r'D:\Hermes Agent CN Desktop\data\hermes-home\scripts')

# 规格 point 3 的 28 个字段（存在才写，缺失写 null 并记 data_gap）。
FIELDS = (
    'asof', 'code', 'name', 'major_theme', 'source_asof',
    'rank_research', 'rank_entry', 'score', 'full_cycles', 'full_cycle_net',
    'recent20_cycles', 'has_all_four_windows', 'degraded', 'latest_claim',
    'window_start', 'window_end', 'recent20_start', 'coverage_signature',
    'window_anchor_price', 'window_shifted', 'delta_reason', 'delta_rank',
    'close', 'amplitude_pct', 'volume_ratio', 'regime20', 'net20_pct', 'er20',
)
BANNED = ('买入', '卖出', '挂单', '下单', '建仓', '加仓', '减仓', '清仓',
          '补仓', '止盈', '止损', '换仓', '委托', '建议买', '建议卖', '可埋伏')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _api():
    return _load('grid_daily_snapshot_under_test', SNAPSHOT_PATH)


def _watch():
    return _load('volatility_watch_link_under_test', WATCH_PATH)


def _wrapper():
    return _load('run_and_push_daily_under_test', RUN_AND_PUSH_PATH)


def _bar(day, close=1.0, amp=2.0, vol=100.0):
    return dict(date=day, open=close, high=close * (1 + amp / 200),
                low=close * (1 - amp / 200), close=close, volume=vol)


def _history(n=25, start='2026-09-01'):
    d0 = date.fromisoformat(start)
    return [_bar((d0 + timedelta(days=i)).isoformat(),
                 close=1.0 + i * 0.001, vol=100.0 + i) for i in range(n)]


def _write_research(root, asof='2026-11-05', window_start='2026-08-03',
                    window_end='2026-11-05', coverage='sig-A',
                    codes=('sz159272', 'sh589720', 'sz159363')):
    """构造最小 rerank-* 研究目录：result.json + entry-ranking.csv。"""
    research = Path(root) / 'cache' / 'grid-research' / 'rerank-20261105-1925'
    research.mkdir(parents=True, exist_ok=True)
    ranking = []
    for i, c in enumerate(codes):
        ranking.append(dict(code=c, name=_NAME.get(c, f'ETF{i}'),
                            score=round(0.9 - i * 0.1, 3),
                            has_all_four_windows=True, full_cycles=22 - i,
                            full_cycle_net=2600.0 - i * 100,
                            recent20_cycles=15 - i,
                            recent20_start='2026-10-09 09:35:00'))
    summary = dict(asof=asof, window_start=window_start, window_end=window_end,
                   latest_claim=False, data_failed_runs=0, fetch_errors=0,
                   production_scope=True, coverage_signature=coverage)
    (research / 'result.json').write_text(
        json.dumps(dict(summary=summary, ranking=ranking), ensure_ascii=False),
        encoding='utf-8')
    with (research / 'entry-ranking.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['code', 'name', 'rank', 'regime20', 'net20_pct', 'er20', 'close'])
        for i, c in enumerate(codes):
            w.writerow([c, _NAME.get(c, f'ETF{i}'), i + 1, '震荡', -1.0 - i, 0.1, 1.0])
    return research


_NAME = {
    'sz159272': '机器人ETF富国',
    'sh589720': '科创创新药ETF国泰',
    'sz159363': '创业板人工智能ETF',
}


def _weekly_row(code='sz159272', **overrides):
    row = dict(code=code, name='机器人ETF富国', major_theme='人工智能机器人',
               source_asof='2026-11-05', rank_research=1, rank_entry=1, score=0.9,
               full_cycles=22, full_cycle_net=2600.0, recent20_cycles=15,
               has_all_four_windows=True, degraded=False, latest_claim=False,
               window_start='2026-08-03', window_end='2026-11-05',
               recent20_start='2026-10-09 09:35:00', coverage_signature='sig-A',
               window_anchor_price=None)
    row.update(overrides)
    return row


def _daily(**overrides):
    row = dict(close=1.024, amplitude_pct=2.0, volume_ratio=1.04,
               net20_pct=2.3, er20=0.31, regime20='震荡')
    row.update(overrides)
    return row


def _hash_tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(root).rglob('*') if p.is_file()}


class FieldIntegrityTests(unittest.TestCase):
    def test_all_28_fields_present_and_weekly_carries_source_asof(self):
        api = _api()
        row = api.evaluate('sz159272', _weekly_row(), _daily(), prev=None,
                           asof='2026-11-06')
        for key in FIELDS:
            self.assertIn(key, row, f'缺字段：{key}')
        self.assertEqual(row['source_asof'], '2026-11-05')
        self.assertEqual(row['asof'], '2026-11-06')
        # 周频字段沿用，不重算
        self.assertEqual(row['rank_research'], 1)
        self.assertEqual(row['full_cycles'], 22)
        self.assertEqual(row['score'], 0.9)
        # 日频观测来自日K
        self.assertEqual(row['close'], 1.024)

    def test_missing_values_are_null_and_recorded_in_data_gap(self):
        api = _api()
        weekly = _weekly_row(score=None, window_anchor_price=None,
                             rank_entry=None, recent20_start=None)
        row = api.evaluate('sz159272', weekly,
                           _daily(volume_ratio=None, er20=None, regime20=None),
                           prev=None, asof='2026-11-06')
        for key in ('score', 'window_anchor_price', 'rank_entry',
                    'recent20_start', 'volume_ratio', 'er20', 'regime20'):
            self.assertIsNone(row[key], f'{key} 缺失应写 null')
            self.assertIn(key, row['data_gap'], f'{key} 应记入 data_gap')
        # 禁止编造数字：缺失项不得变成 0 或其他数值
        self.assertNotIn('rank_research', row['data_gap'])

    def test_source_asof_is_weekly_not_snapshot_date(self):
        api = _api()
        row = api.evaluate('sz159272',
                           _weekly_row(source_asof='2026-10-31'),
                           _daily(), prev=None, asof='2026-11-06')
        self.assertEqual(row['source_asof'], '2026-10-31')
        self.assertEqual(row['asof'], '2026-11-06')


class SecidAndFetchTests(unittest.TestCase):
    def test_to_secid_normalizes_all_universe_formats(self):
        api = _api()
        self.assertEqual(api.to_secid('589720'), '1.589720')
        self.assertEqual(api.to_secid('159363'), '0.159363')
        self.assertEqual(api.to_secid('sh589720'), '1.589720')
        self.assertEqual(api.to_secid('sz159363'), '0.159363')
        self.assertEqual(api.to_secid('1.589720'), '1.589720')
        self.assertEqual(api.to_secid('0.159363'), '0.159363')

    def test_fetch_daily_uses_tencent_kline_101_no_future_end(self):
        api = _api()
        calls = {}

        def fake(secid, lmt=None, klt=None, **kwargs):
            calls.update(secid=secid, lmt=lmt, klt=klt, kwargs=kwargs)
            return _history(25)
        api._get_kline_fetcher = lambda: fake
        rows = api._fetch_daily('589720')
        self.assertEqual(calls['secid'], '1.589720')
        self.assertEqual(calls['klt'], '101')
        self.assertNotIn('end', calls['kwargs'], 'end 必须留空，不得塞未来日期')
        self.assertTrue(rows)

    def test_daily_metrics_computed_from_bars_not_hardcoded(self):
        api = _api()
        bars = _history(25)
        bars[-1] = _bar('2026-09-25', close=1.5, amp=6.0, vol=300.0)
        out = api._daily_metrics(bars)
        self.assertAlmostEqual(out['close'], 1.5, places=3)
        self.assertAlmostEqual(out['amplitude_pct'], 6.0, places=2)
        self.assertIsNotNone(out['net20_pct'])
        self.assertIsNotNone(out['er20'])
        self.assertIn(out['regime20'], ('趋势', '震荡'))

    def test_short_history_yields_null_daily_fields(self):
        api = _api()
        out = api._daily_metrics(_history(5))
        self.assertIsNotNone(out['close'])
        self.assertIsNone(out['net20_pct'])
        self.assertIsNone(out['er20'])


class WindowAlignmentTests(unittest.TestCase):
    def test_aligned_window_computes_delta_rank(self):
        api = _api()
        prev = dict(window_start='2026-08-03', window_end='2026-11-05',
                    coverage_signature='sig-A', rank_research=1, major_theme='人工智能机器人')
        row = api.evaluate('sz159272', _weekly_row(rank_research=1), _daily(),
                           prev=prev, asof='2026-11-06')
        self.assertFalse(row['window_shifted'])
        self.assertIsNotNone(row['delta_rank'])
        self.assertEqual(row['delta_rank'], 0)
        self.assertEqual(row['delta_reason'], 'price')

    def test_shifted_window_sets_window_shifted_and_nulls_delta_rank(self):
        api = _api()
        prev = dict(window_start='2026-07-27', window_end='2026-10-31',
                    coverage_signature='sig-A', rank_research=1, major_theme='人工智能机器人')
        row = api.evaluate('sz159272',
                           _weekly_row(window_start='2026-08-03',
                                       window_end='2026-11-05', rank_research=1),
                           _daily(), prev=prev, asof='2026-11-06')
        self.assertTrue(row['window_shifted'])
        self.assertIsNone(row['delta_rank'], '换窗当日不得把名次差当趋势')
        self.assertEqual(row['delta_reason'], 'window_shift')

    def test_coverage_change_is_not_a_rank_trend(self):
        api = _api()
        prev = dict(window_start='2026-08-03', window_end='2026-11-05',
                    coverage_signature='sig-OLD', rank_research=1, major_theme='人工智能机器人')
        row = api.evaluate('sz159272', _weekly_row(rank_research=1), _daily(),
                           prev=prev, asof='2026-11-06')
        self.assertTrue(row['window_shifted'])
        self.assertIsNone(row['delta_rank'])
        self.assertEqual(row['delta_reason'], 'coverage_change')

    def test_first_run_reason_is_initial_with_null_delta(self):
        api = _api()
        row = api.evaluate('sz159272', _weekly_row(), _daily(), prev=None,
                           asof='2026-11-06')
        self.assertEqual(row['delta_reason'], 'initial')
        self.assertIsNone(row['delta_rank'])
        self.assertFalse(row['window_shifted'])

    def test_delta_reason_within_domain(self):
        api = _api()
        domain = {'price', 'coverage_change', 'window_shift', 'theme_cap', 'initial'}
        self.assertEqual(set(api.DELTA_REASONS), domain)
        rows = [
            api.evaluate('sz159272', _weekly_row(), _daily(), None, '2026-11-06'),
            api.evaluate('sz159272', _weekly_row(), _daily(),
                         dict(window_start='2026-08-03', window_end='2026-11-05',
                              coverage_signature='sig-A', rank_research=1,
                              major_theme='人工智能机器人'), '2026-11-06'),
        ]
        for r in rows:
            self.assertIn(r['delta_reason'], domain)


class PersistenceTests(unittest.TestCase):
    def test_daily_snapshot_path_is_under_daily_snapshots_dir(self):
        api = _api()
        with __import__('tempfile').TemporaryDirectory() as td:
            p = api.daily_snapshot_path(Path(td), '2026-11-06')
            self.assertEqual(p.name, '2026-11-06.jsonl')
            self.assertEqual(p.parent.name, 'daily-snapshots')
            self.assertNotIn('rerank', str(p))

    def test_latest_research_dir_excludes_daily_snapshots_and_needs_result_json(self):
        api = _api()
        with __import__('tempfile').TemporaryDirectory() as td:
            base = Path(td) / 'cache' / 'grid-research'
            research = _write_research(td)  # 含 result.json（较旧）
            snap = base / 'daily-snapshots'  # 较新、无 result.json
            snap.mkdir(parents=True, exist_ok=True)
            (snap / '2026-11-06.jsonl').write_text('{}\n', encoding='utf-8')
            os.utime(research, (1_700_000_000, 1_700_000_000))
            os.utime(snap, (1_800_000_000, 1_800_000_000))
            self.assertEqual(api._latest_research_dir(Path(td)), research)

    def test_append_only_does_not_overwrite_previous_lines(self):
        api = _api()
        with __import__('tempfile').TemporaryDirectory() as td:
            _write_research(td)
            fetch = lambda code: _history(25)
            api.run(account_root=Path(td), fetch=fetch, asof='2026-11-06')
            snap = api.daily_snapshot_path(Path(td), '2026-11-06')
            first = snap.read_text(encoding='utf-8').splitlines()
            self.assertTrue(first)
            api.run(account_root=Path(td), fetch=fetch, asof='2026-11-06')
            second = snap.read_text(encoding='utf-8').splitlines()
            self.assertEqual(second[:len(first)], first, '旧行不得被覆盖')
            self.assertGreater(len(second), len(first), '必须是 append')

    def test_writes_only_into_daily_snapshots_not_rerank_dirs(self):
        api = _api()
        with __import__('tempfile').TemporaryDirectory() as td:
            research = _write_research(td)
            sentinel = research / 'sentinel.txt'
            sentinel.write_text('do-not-touch', encoding='utf-8')
            before = _hash_tree(research)
            api.run(account_root=Path(td), fetch=lambda c: _history(25), asof='2026-11-06')
            after = _hash_tree(research)
            self.assertEqual(before, after, 'rerank-* 目录不得被写入')
            snap = api.daily_snapshot_path(Path(td), '2026-11-06')
            self.assertTrue(snap.is_file())
            rows = [json.loads(x) for x in snap.read_text(encoding='utf-8').splitlines()]
            self.assertTrue(rows)
            for r in rows:
                for key in FIELDS:
                    self.assertIn(key, r)


class ReadOnlyTests(unittest.TestCase):
    def test_ledger_and_weekly_state_hashes_unchanged_after_run(self):
        api = _api()
        with __import__('tempfile').TemporaryDirectory() as td:
            research = _write_research(td)
            account = Path(td) / 'cache' / 'grid-account'
            account.mkdir(parents=True)
            guard = {
                'confirmed-589720.json': {'qty': 37900},
                'holdings.json': {'holdings': {}},
                'regime-cache.json': {'asof': '2026-11-05'},
                'rotation-streak.json': {'consecutive_weeks': 2},
                'weekly-report.txt': '正式周报（不得改动）',
            }
            for name, payload in guard.items():
                p = account / name if name != 'weekly-report.txt' else research / name
                if name.endswith('.txt'):
                    p.write_text(payload, encoding='utf-8')
                else:
                    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            protected = [account / n for n in guard if n != 'weekly-report.txt']
            protected.append(research / 'weekly-report.txt')
            before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
            api.run(account_root=Path(td), fetch=lambda c: _history(25), asof='2026-11-06')
            after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
            self.assertEqual(before, after, '只读任务不得改动账本/持仓/regime/连续周状态/周报')


class RenderTests(unittest.TestCase):
    def _rows(self, api, n=2):
        return [api.evaluate(f'sz15927{i}', _weekly_row(code=f'sz15927{i}'),
                             _daily(), prev=None, asof='2026-11-06') for i in range(n)]

    def test_no_change_returns_empty_output(self):
        api = _api()
        aligned = dict(window_start='2026-08-03', window_end='2026-11-05',
                       coverage_signature='sig-A', rank_research=1,
                       major_theme='人工智能机器人')
        rows = [api.evaluate('sz159272', _weekly_row(rank_research=1), _daily(),
                             prev=aligned, asof='2026-11-06')]
        self.assertEqual(api.render(rows), '')

    def test_first_run_emits_brief_text(self):
        api = _api()
        text = api.render(self._rows(api))
        self.assertTrue(text)
        self.assertIn('2026-11-06', text)

    def test_render_has_no_trade_advice(self):
        api = _api()
        for text in (api.render(self._rows(api)),
                     api.render(self._rows(api), failures=['sz159999'])):
            for banned in BANNED:
                self.assertNotIn(banned, text, f'输出不得含交易动作词：{banned}')

    def test_render_carries_disclaimer(self):
        api = _api()
        text = api.render(self._rows(api))
        self.assertIn('仅观察', text)
        self.assertIn('不构成操作依据', text)
        self.assertIn('不改动持仓、账本与任务状态', text)

    def test_fetch_failures_disclosed_not_silently_swallowed(self):
        api = _api()
        text = api.render([], failures=['sz159999', 'sh589720'])
        self.assertIn('取数失败 2 只', text)
        self.assertIn('有限样本观察池', text)
        self.assertIn('仅观察', text)

    def test_fetch_failure_disclosed_through_run(self):
        api = _api()
        with __import__('tempfile').TemporaryDirectory() as td:
            _write_research(td)

            def broken(code):
                raise OSError('network down')
            text = api.run(account_root=Path(td), fetch=broken, asof='2026-11-06')
        self.assertIn('取数失败', text)
        self.assertIn('有限样本观察池', text)

    def test_significant_delta_rank_emits_change_hint(self):
        api = _api()
        prev = dict(window_start='2026-08-03', window_end='2026-11-05',
                    coverage_signature='sig-A', rank_research=45,
                    major_theme='人工智能机器人')
        rows = [api.evaluate('sz159272', _weekly_row(rank_research=1), _daily(),
                             prev=prev, asof='2026-11-06')]
        text = api.render(rows, prev_rows=[prev])
        self.assertTrue(text)
        self.assertIn('名次', text)


class FixtureAndMainTests(unittest.TestCase):
    def test_fixture_path_offline_run_writes_snapshot(self):
        import tempfile
        api = _api()
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td) / 'fixture.json'
            fixture.write_text(json.dumps({
                'sz159272': _history(25),
                'sh589720': _history(25),
            }), encoding='utf-8')
            text = api.run(fixture_path=fixture, account_root=Path(td),
                           asof='2026-11-06')
            snap = api.daily_snapshot_path(Path(td), '2026-11-06')
            self.assertTrue(snap.is_file())
            self.assertTrue(text)  # 首次运行有简短输出

    def test_main_accepts_all_flags(self):
        import tempfile
        api = _api()
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td) / 'fixture.json'
            fixture.write_text(json.dumps({'sz159272': _history(25)}), encoding='utf-8')
            text = api.main(['--fixture-path', str(fixture),
                             '--account-root', str(Path(td)),
                             '--limit', '3', '--compare'])
            self.assertIsInstance(text, str)


class JobRegistrationTests(unittest.TestCase):
    def test_daily_snapshot_job_registered_inside_ah_analyse(self):
        module = _wrapper()
        self.assertIn('daily_snapshot', module.JOBS)
        path = Path(module.resolve_script('daily_snapshot')).resolve()
        self.assertTrue(str(path).lower().startswith(str(REPO).lower()))
        self.assertTrue(path.is_file(), f'脚本不存在：{path}')
        self.assertNotIn(str(HERMES_SCRIPTS).lower(), str(path).lower())

    def test_daily_snapshot_job_is_push_off_timeout_600(self):
        module = _wrapper()
        spec = module.JOBS['daily_snapshot']
        self.assertEqual(spec['push'], 'off')
        self.assertEqual(spec['timeout'], 600)

    def test_existing_jobs_untouched(self):
        module = _wrapper()
        self.assertEqual(module.JOBS['volatility_watch']['push'], 'on')
        self.assertEqual(module.JOBS['weekly_fri']['timeout'], 2700)
        self.assertEqual(module.JOBS['regime_1530']['timeout'], 1900)

    def test_deploy_manifest_auto_includes_new_script(self):
        module = _load('deploy_manifest_under_test', DEPLOY_PATH)
        manifest = module.manifest(REPO)
        self.assertIn('grid_daily_snapshot.py', manifest)
        self.assertEqual(Path(manifest['grid_daily_snapshot.py']).name,
                         'grid_daily_snapshot.py')


class VolatilityUniverseRegressionTests(unittest.TestCase):
    """批准的最小防御联动：新快照目录 mtime 更新但无 entry-ranking.csv 时，
    volatility_expansion_watch._universe 仍须读到旧 rerank-* 目录的榜单前20。
    未修前会静默丢池。"""

    def test_newer_dir_without_ranking_does_not_drop_observation_pool(self):
        watch = _watch()
        with __import__('tempfile').TemporaryDirectory() as td:
            account = Path(td) / 'cache' / 'grid-account'
            account.mkdir(parents=True)
            research = Path(td) / 'cache' / 'grid-research'
            old = research / 'rerank-20261105-1925'
            old.mkdir(parents=True)
            with (old / 'entry-ranking.csv').open('w', encoding='utf-8', newline='') as fh:
                w = csv.writer(fh)
                w.writerow(['code', 'name', 'rank'])
                w.writerow(['sz159272', '机器人ETF富国', 1])
                w.writerow(['sh589720', '科创创新药ETF国泰', 2])
            newer = research / 'daily-snapshots'
            newer.mkdir()
            (newer / '2026-11-06.jsonl').write_text('{}\n', encoding='utf-8')
            os.utime(old, (1_700_000_000, 1_700_000_000))
            os.utime(newer, (1_800_000_000, 1_800_000_000))
            # volatility_watch._universe 用 f.open() 未关闭（既有代码，不在本任务改动范围），
            # 本回归测试只抑制该既有 ResourceWarning，不改被测脚本。
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', ResourceWarning)
                universe = watch._universe(account)
            codes = [c for c, _ in universe]
            self.assertIn('sz159272', codes, '榜单前20观察池不得因新目录而丢失')
            self.assertIn('sh589720', codes)


if __name__ == '__main__':
    unittest.main()
