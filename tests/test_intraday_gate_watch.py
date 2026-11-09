"""Standalone intraday observer: deterministic, temp-ledger TDD contracts."""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from confirmed_589720 import build
from confirmed_calendar import is_session
from tools.etf_research.gate_check import gate
from tools import intraday_gate_watch as watch


CN = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 5, 10, 15, tzinfo=CN)
CODE = 'sh589720'


def history_for(day=NOW.date(), count=80):
    days = []
    cursor = day - timedelta(days=1)
    while len(days) < count:
        if is_session(cursor):
            days.append(cursor)
        cursor -= timedelta(days=1)
    rows = []
    for i, day in enumerate(reversed(days)):
        close = round(1.0 + i * 0.002 + (i % 5) * 0.001, 4)
        rows.append(dict(date=day.isoformat(), open=close - 0.002,
                         high=close + 0.01, low=close - 0.01, close=close))
    return rows


def quote_for(rows, now=NOW, price=None):
    last = rows[-1]['close'] + 0.01 if price is None else price
    return dict(open=last, high=last + 0.02, low=last - 0.02,
                last=last, prev=rows[-1]['close'], timestamp=now.isoformat())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'account'
        self.root.mkdir()
        environment = patch.dict('os.environ', {'HERMES_HOME': str(self.root.parent)})
        environment.start()
        self.addCleanup(environment.stop)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('fixture tests forbid real network'))
        network.start()
        self.addCleanup(network.stop)
        self.rows = history_for()
        self.quote = quote_for(self.rows)
        self.holdings = {CODE: dict(name='测试ETF', active=True)}
        self.save_holdings()
        self.add_ledger(CODE)
        self.set_official('pause_buy', True)
        self.history = Mock(side_effect=lambda code: copy.deepcopy(self.rows))
        self.quotes = Mock(side_effect=lambda code: copy.deepcopy(self.quote))

    def save_holdings(self):
        write_json(self.root / 'holdings.json', {'holdings': self.holdings})

    def add_ledger(self, code, qty=100):
        inputs = [('buy', qty, '1.000')] if qty else []
        state = build(inputs, code=code, name='测试ETF')
        state['sellable_qty'] = state['qty']
        write_json(self.root / f'confirmed-{code[-6:]}.json', state)

    def set_official(self, level, blocked, asof='2026-11-04', code=CODE):
        path = self.root / 'regime-cache.json'
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        data[code] = dict(level=level, blocks_buy=blocked, asof=asof, reason='正式原因')
        write_json(path, data)

    def evaluate(self, now=NOW):
        return watch.evaluate(self.root, now=now, history_fn=self.history, quote_fn=self.quotes)

    def run_watch(self, now=NOW):
        return watch.run(self.root, now=now, history_fn=self.history, quote_fn=self.quotes)

    def latest(self):
        return json.loads((self.root / 'intraday-gate-watch/latest.json').read_text(encoding='utf-8'))

    def result(self, now=NOW):
        return self.evaluate(now)['results'][CODE]

    def test_valid_computation_matches_real_gate_and_wilder(self):
        result = self.result()
        synthetic = dict(date='2026-11-05', open=self.quote['open'], high=self.quote['high'],
                         low=self.quote['low'], close=self.quote['last'])
        rows = self.rows + [synthetic]
        from tools.market_phase_check import wilder_adx
        adx, pdi, mdi = wilder_adx(rows)
        expected = gate(pd.DataFrame(rows), dict(adx=adx, pdi=pdi, mdi=mdi))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['provisional'], expected)
        self.assertEqual(result['completed_bars'], 80)
        self.assertEqual((result['adx'], result['pdi'], result['mdi']), (adx, pdi, mdi))
        self.assertFalse((self.root / 'intraday-gate-watch').exists(), 'evaluate is read-only')

    def test_today_rows_are_replaced_once_and_future_is_excluded(self):
        expected = self.result()
        self.rows += [dict(date='2026-11-05', open=99, high=99, low=99, close=99)] * 2
        self.rows += [dict(date='2026-11-06', open=99, high=99, low=99, close=99)]
        actual = self.result()
        self.assertEqual(actual['provisional'], expected['provisional'])
        self.assertEqual(actual['completed_bars'], 80)
        self.assertEqual(actual['adx'], expected['adx'])

    def test_65_completed_bars_required_before_adding_today(self):
        self.rows = self.rows[-64:]
        self.assertEqual(self.result()['kind'], 'history_insufficient')
        self.rows = history_for(count=65)
        self.quote = quote_for(self.rows)
        self.assertEqual(self.result()['status'], 'ok')

    def test_history_must_end_on_previous_exchange_session(self):
        self.rows.pop()
        self.assertEqual(self.result()['kind'], 'history_stale')

    def test_duplicate_completed_day_rejected(self):
        self.rows.append(copy.deepcopy(self.rows[-1]))
        self.assertEqual(self.result()['kind'], 'history_invalid')

    def test_invalid_history_prices_rejected(self):
        for value in (float('nan'), float('inf'), 0, -1):
            with self.subTest(value=value):
                original = self.rows[0]['high']
                self.rows[0]['high'] = value
                self.assertEqual(self.result()['kind'], 'history_invalid')
                self.rows[0]['high'] = original

    def test_quote_stale_future_wrongday_and_prior_session_rejected(self):
        for stamp, now, kind in [
            (NOW - timedelta(seconds=181), NOW, 'quote_stale'),
            (NOW + timedelta(seconds=1), NOW, 'quote_future'),
            (NOW - timedelta(days=1), NOW, 'quote_wrong_day'),
            (NOW.replace(hour=12, minute=59), NOW.replace(hour=13, minute=0), 'quote_session'),
            (NOW.replace(hour=9, minute=30), NOW.replace(hour=9, minute=31), 'quote_session'),
        ]:
            with self.subTest(stamp=stamp):
                self.quote['timestamp'] = stamp.isoformat()
                self.assertEqual(self.result(now)['kind'], kind)
        self.quote['timestamp'] = (NOW - timedelta(seconds=180)).isoformat()
        self.assertEqual(self.result()['status'], 'ok')

    def test_quote_finite_positive_ohlc_range_and_prev_close_validated(self):
        original = copy.deepcopy(self.quote)
        for key, value in [('last', float('nan')), ('high', float('inf')), ('open', 0),
                           ('low', -1), ('last', 10), ('high', 0.5), ('prev', 0)]:
            with self.subTest(key=key, value=value):
                self.quote = dict(original, **{key: value})
                self.assertEqual(self.result()['kind'], 'quote_invalid')
        self.quote = dict(original, prev=original['prev'] + 0.003)
        self.assertEqual(self.result()['kind'], 'prev_close_mismatch')
        self.quote = dict(original, prev=original['prev'] + 0.002)
        self.assertEqual(self.result()['status'], 'ok')

    def test_history_can_include_previous_year_without_claiming_calendar_coverage(self):
        self.rows.insert(0, dict(date='2025-12-31', open=0.9, high=0.91, low=0.89, close=0.9))
        self.assertEqual(self.result()['status'], 'ok')

    def test_malformed_official_and_observer_state_are_diagnostics(self):
        self.set_official([], False)
        self.assertEqual(self.result()['kind'], 'official_invalid')
        self.set_official('normal', False)
        self.run_watch()
        path = self.root / 'intraday-gate-watch/latest.json'
        bad_state = dict(trade_day='2026-11-04', codes={CODE: None})
        write_json(path, bad_state)
        original = path.read_bytes()
        self.assertIn('observer_invalid', self.run_watch())
        self.assertEqual(path.read_bytes(), original)

    def test_live_clock_advances_for_quote_validation_and_stops_at_close(self):
        later = NOW + timedelta(seconds=2)
        ticks = iter([NOW, later])
        clock = lambda value=None: value if value is not None else next(ticks, later)
        self.quote['timestamp'] = (NOW + timedelta(seconds=1)).isoformat()
        with patch.object(watch, '_now', side_effect=clock):
            result = watch.evaluate(self.root, history_fn=self.history, quote_fn=self.quotes)
        self.assertEqual(result['results'][CODE]['status'], 'ok')
        closing = NOW.replace(hour=14, minute=59, second=59)
        after_close = closing + timedelta(seconds=2)
        self.history.reset_mock()
        ticks = iter([closing, after_close])
        clock = lambda value=None: value if value is not None else next(ticks, after_close)
        with patch.object(watch, '_now', side_effect=clock):
            result = watch.run(self.root, history_fn=self.history, quote_fn=self.quotes)
        self.assertEqual(result, '')
        self.history.assert_not_called()
        self.assertFalse((self.root / 'intraday-gate-watch').exists())

    def test_missing_bad_timestamp_rejected(self):
        for value in (None, '', 'garbage'):
            with self.subTest(value=value):
                self.quote['timestamp'] = value
                self.assertEqual(self.result()['kind'], 'quote_invalid')

    def test_direct_tencent_snapshot_fields_and_symbol_check(self):
        fields = [''] * 40
        for index, value in {1: '测试ETF', 2: '589720', 3: '1.05', 4: '1.00', 5: '1.01',
                             30: '20261105101500', 33: '1.06', 34: '0.99'}.items():
            fields[index] = value
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = ('v_sh589720="' + '~'.join(fields) + '";').encode('gbk')
        with patch('urllib.request.urlopen', return_value=response) as upstream:
            quote = watch.fetch_quote(CODE)
        self.assertEqual(quote['last'], 1.05)
        self.assertEqual(quote['open'], 1.01)
        self.assertEqual(quote['prev'], 1.0)
        self.assertEqual(quote['timestamp'], NOW.isoformat())
        self.assertIn('qt.gtimg.cn', upstream.call_args.args[0].full_url)
        fields[2] = '159363'
        response.read.return_value = ('v_sh589720="' + '~'.join(fields) + '";').encode('gbk')
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaises(ValueError):
                watch.fetch_quote(CODE)

    def test_market_helper_preserves_callers_environment(self):
        import os
        watch._market_module()  # First import is isolated by the temporary HERMES_HOME.
        with patch.dict('os.environ', {}, clear=True):
            watch._market_module()
            self.assertNotIn('HERMES_HOME', os.environ)
        with patch.dict('os.environ', {'HERMES_HOME': ''}):
            watch._market_module()
            self.assertEqual(os.environ['HERMES_HOME'], '')

    def test_history_adapter_uses_existing_tencent_fetch(self):
        with patch('tools.market_phase_check.fetch_tencent_kline', return_value=self.rows) as fetch:
            self.assertEqual(watch.fetch_history(CODE), self.rows)
        fetch.assert_called_once_with('1.589720', lmt=300, klt='101')

    def test_official_missing_stale_today_or_invalid_is_error_not_allowed(self):
        for entry, kind in [
            (None, 'official_missing'),
            (dict(level='normal', blocks_buy=False, asof='2026-11-03'), 'official_stale'),
            (dict(level='normal', blocks_buy=False, asof='2026-11-05'), 'official_stale'),
            (dict(level='normal', blocks_buy='false', asof='2026-11-04'), 'official_invalid'),
            (dict(level='unknown', blocks_buy=False, asof='2026-11-04'), 'official_invalid'),
            (dict(level='pause_buy', blocks_buy=False, asof='2026-11-04'), 'official_invalid'),
        ]:
            with self.subTest(entry=entry):
                write_json(self.root / 'regime-cache.json', {CODE: entry} if entry else {})
                result = self.result()
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['kind'], kind)
                self.assertNotIn('provisional', result)

    def test_non_legacy_official_gate_is_method_mismatch(self):
        """正式门控若不是 legacy 口径 → 拒绝比较（F 移除后的通用防御）。"""
        self.assertEqual(self.result()['provisional_method'], 'legacy_daily_gate')
        cache = json.loads((self.root / 'regime-cache.json').read_text(encoding='utf-8'))
        for metadata in [dict(reason_tag='five_break'),
                         dict(reason_tag='atr_expand'), dict(mode='f'),
                         dict(method='unknown_gate')]:
            with self.subTest(metadata=metadata):
                entry = dict(cache[CODE], **metadata)
                write_json(self.root / 'regime-cache.json', {CODE: entry})
                result = self.result()
                self.assertEqual(result['kind'], 'official_method_mismatch')
                self.assertNotIn('provisional', result)

    def test_active_and_positive_validated_qty_only_own_root(self):
        self.holdings.update({
            'sz159363': dict(active=False, name='退出'),
            'sh512980': dict(active=True, name='空仓'),
            'sz159866': dict(active=True, name='新增持仓'),
        })
        self.save_holdings()
        self.add_ledger('sz159363')
        self.add_ledger('sh512980', 0)
        self.add_ledger('sz159866')
        self.set_official('normal', False, code='sz159866')
        results = self.evaluate()['results']
        self.assertEqual(set(results), {CODE, 'sz159866'})
        self.assertEqual({c.args[0] for c in self.history.call_args_list}, {CODE, 'sz159866'})

    def test_missing_or_corrupt_active_ledger_diagnostic_without_network(self):
        path = self.root / 'confirmed-589720.json'
        path.unlink()
        self.assertEqual(self.result()['kind'], 'state_invalid')
        self.history.assert_not_called()
        self.add_ledger(CODE)
        state = json.loads(path.read_text(encoding='utf-8'))
        state['qty'] += 1
        write_json(path, state)
        self.assertEqual(self.result()['kind'], 'state_invalid')
        self.history.assert_not_called()

    def test_missing_holdings_never_falls_back(self):
        (self.root / 'holdings.json').unlink()
        result = self.evaluate()
        self.assertEqual(result['results']['_account']['kind'], 'holdings_invalid')
        self.history.assert_not_called()
        self.quotes.assert_not_called()

    def test_default_home_is_dsh_and_environment_is_honored(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(watch.default_root(), Path('D:/Code/AH_analyse/.cache/grid-home/cache/grid-account'))
        with patch.dict('os.environ', {'HERMES_HOME': str(self.root.parent)}):
            self.assertEqual(watch.default_root(), self.root.parent / 'cache/grid-account')

    def test_closed_sessions_weekend_holiday_no_network_no_writes(self):
        for now in [NOW.replace(hour=9, minute=30), NOW.replace(hour=11, minute=31),
                    NOW.replace(hour=12), NOW.replace(hour=15, minute=0),
                    NOW.replace(day=7), NOW.replace(month=10, day=1),
                    NOW.replace(month=10, day=10)]:
            with self.subTest(now=now):
                self.assertEqual(self.run_watch(now), '')
                self.assertEqual(self.evaluate(now)['status'], 'closed')
        self.history.assert_not_called()
        self.quotes.assert_not_called()
        self.assertFalse((self.root / 'intraday-gate-watch').exists())

    def test_open_boundaries_and_previous_day_over_holiday_weekend(self):
        for hour, minute in [(9, 31), (11, 30), (13, 0), (14, 59)]:
            now = NOW.replace(hour=hour, minute=minute, second=59)
            self.quote['timestamp'] = now.isoformat()
            self.assertEqual(self.result(now)['status'], 'ok')
        for current, previous in [(date(2026, 10, 8), date(2026, 9, 30)),
                                  (date(2026, 11, 9), date(2026, 11, 6))]:
            self.assertEqual(watch.previous_session(current), previous)

    def test_first_diff_alert_then_unchanged_price_metrics_silent_snapshots_each_run(self):
        output = self.run_watch()
        self.assertTrue(output.startswith('【盘中门控观察：仅预估，不切换正式门控】'))
        for text in ('589720', '测试ETF', '现价', '10:15',
                     '正式 ' + watch.LEVEL_LABELS['pause_buy'],
                     '盘中预估（均线/DMI口径） ' + watch.LEVEL_LABELS['normal'],
                     'ADX', '+DI', '-DI',
                     '未收盘确认，正式门控未切换；不构成可执行买单。'):
            self.assertIn(text, output)
        for i in (1, 2):
            self.quote['last'] += 0.001
            self.quote['timestamp'] = (NOW + timedelta(minutes=i)).isoformat()
            self.assertEqual(self.run_watch(NOW + timedelta(minutes=i)), '')
        snapshots = list((self.root / 'intraday-gate-watch/snapshots/2026-11-05').glob('*.json'))
        self.assertEqual(len(snapshots), 3)
        self.assertEqual(self.latest()['codes'][CODE]['last_success']['status'], 'ok')

    def test_first_equal_silent_reversal_and_official_transition_alert(self):
        self.set_official('normal', False)
        self.assertEqual(self.run_watch(), '')
        self.quote = quote_for(self.rows, price=0.8)
        self.assertIn(watch.LEVEL_LABELS['no_entry'], self.run_watch())
        self.assertEqual(self.run_watch(), '')
        self.quote = quote_for(self.rows)
        self.assertIn('盘中预估（均线/DMI口径） ' + watch.LEVEL_LABELS['normal'], self.run_watch())
        self.set_official('pause_buy', True)
        self.assertIn('正式 ' + watch.LEVEL_LABELS['pause_buy'], self.run_watch())

    def test_trade_day_scoped_next_day_compares_official_again(self):
        self.assertTrue(self.run_watch())
        tomorrow = NOW + timedelta(days=1)
        self.rows = history_for(tomorrow.date())
        self.quote = quote_for(self.rows, tomorrow)
        self.set_official('pause_buy', True, asof='2026-11-05')
        self.assertTrue(self.run_watch(tomorrow))
        self.assertEqual(self.latest()['trade_day'], '2026-11-06')

    def test_error_dedup_stable_kind_preserves_last_good_and_recovery_is_quiet(self):
        self.assertTrue(self.run_watch())
        before = self.latest()['codes'][CODE]['last_success']
        self.history.side_effect = OSError('network failure one')
        output = self.run_watch()
        self.assertIn('⚠️取数/状态未验证', output)
        self.assertNotIn('✅', output)
        self.assertEqual(self.latest()['codes'][CODE]['last_success'], before)
        self.history.side_effect = OSError('network failure two')
        self.assertEqual(self.run_watch(), '')
        self.history.side_effect = lambda code: copy.deepcopy(self.rows)
        self.assertEqual(self.run_watch(), '')
        self.assertIsNone(self.latest()['codes'][CODE]['error_kind'])

    def test_error_first_never_marks_success_and_recovered_difference_alerts(self):
        self.quotes.side_effect = ValueError('bad upstream')
        self.assertIn('⚠️取数/状态未验证', self.run_watch())
        self.assertIsNone(self.latest()['codes'][CODE]['last_success'])
        self.quotes.side_effect = lambda code: copy.deepcopy(self.quote)
        self.assertIn('盘中预估', self.run_watch())

    def test_buy_paused_is_independent_warning_never_release_instruction(self):
        self.holdings[CODE]['buy_paused'] = True
        self.save_holdings()
        output = self.run_watch()
        self.assertIn('用户暂停买入', output)
        self.assertIn('独立生效', output)
        self.assertNotIn('解除用户', output)
        self.assertTrue(self.latest()['codes'][CODE]['last_success']['buy_paused'])

    def test_source_hashes_unchanged_and_writes_confined_to_observer(self):
        write_json(self.root / 'confirmed-intraday-alerts.json', {'untouched': True})
        def hashes():
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.glob('*.json')}
        before = hashes()
        self.run_watch()
        self.history.side_effect = OSError('failure')
        self.run_watch()
        self.assertEqual(hashes(), before)
        self.assertEqual({p.name for p in self.root.iterdir()}, set(before) | {'intraday-gate-watch'})
        snapshot_paths = list((self.root / 'intraday-gate-watch/snapshots').rglob('*.json'))
        self.assertEqual(len(snapshot_paths), 2, 'same timestamp runs must not overwrite diagnostics')
        diagnostics = [json.loads(p.read_text(encoding='utf-8')) for p in snapshot_paths]
        self.assertEqual({d['results'][CODE]['status'] for d in diagnostics}, {'ok', 'error'})

    def test_entrypoint_closed_fixed_clock_is_silent_and_has_no_side_effects(self):
        output = io.StringIO()
        with patch('sys.stdout', output):
            self.assertEqual(watch.main(root=self.root, now=NOW.replace(hour=15),
                                        history_fn=self.history, quote_fn=self.quotes), 0)
        self.assertEqual(output.getvalue(), '')
        self.history.assert_not_called()
        self.quotes.assert_not_called()
        self.assertFalse((self.root / 'intraday-gate-watch').exists())


if __name__ == '__main__':
    unittest.main()
