"""Isolated fill date/identity regressions; never access managed live books."""
import json
from pathlib import Path
import tempfile
import unittest

import confirmed_589720
import grid_state


class FillIdentityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'state.json'
        state = confirmed_589720.build()
        state['sellable_qty'] = state['qty']
        self.path.write_text(json.dumps(state), encoding='utf-8')

    def test_delayed_midnight_receive_uses_beijing_message_date(self):
        state = grid_state.record(self.path, 'buy', 100, '0.8',
                                  execution_id='received-1',
                                  received_at='2026-10-12T15:59:59+00:00')
        trade = state['trades'][-1]
        self.assertEqual(trade['date'], '2026-10-12')
        self.assertEqual(trade['received_at'], '2026-10-12T15:59:59+00:00')
        self.assertEqual(trade['date_source'], 'received_at_beijing')

    def test_default_date_captures_local_ingestion_not_original_message(self):
        from datetime import datetime, timezone, timedelta
        state = grid_state.record(self.path, 'buy', 100, '0.8', execution_id='local-1')
        trade = state['trades'][-1]
        stamp = datetime.fromisoformat(trade['received_at'])
        self.assertEqual(trade['date'], stamp.astimezone(timezone(timedelta(hours=8))).date().isoformat())
        self.assertEqual(trade['date_source'], 'local_ingestion_beijing')

    def test_future_and_out_of_order_dates_reject_without_mutation(self):
        grid_state.record(self.path, 'buy', 100, '0.8', '2026-10-13', execution_id='first')
        before = self.path.read_bytes()
        for day in ('2099-01-01', '2026-10-12'):
            with self.subTest(day=day), self.assertRaises(ValueError):
                grid_state.record(self.path, 'buy', 100, '0.8', day, execution_id='invalid')
            self.assertEqual(self.path.read_bytes(), before)


    def test_auto_ids_increase_across_buy_sell_and_recurring_letter(self):
        bought = grid_state.record(self.path, 'buy', 100, '0.8', '2026-10-14', message_id='m1')
        sold = grid_state.record(self.path, 'sell', 100, '0.82', '2026-10-14', message_id='m2')
        rebought = grid_state.record(self.path, 'buy', 100, '0.8', '2026-10-14', message_id='m3')
        self.assertEqual([s['trades'][-1]['id'] for s in (bought, sold, rebought)],
                         ['589720-010', '589720-011', '589720-012'])
        self.assertEqual([s['trades'][-1]['lot'] for s in (bought, sold, rebought)], ['D', 'D', 'D'])
        self.assertEqual(sold['t_records'][-1]['buy_id'], '589720-010')
        self.assertEqual(sold['t_records'][-1]['sell_id'], '589720-011')


    def test_same_message_retry_is_noop_and_conflict_never_mutates(self):
        state = grid_state.record(self.path, 'buy', 100, '0.8', message_id='same',
                                  received_at='2026-10-13T23:59:59+08:00', fill_item_key='a')
        before = self.path.read_bytes()
        retry = grid_state.record(self.path, 'buy', 100, '0.8', message_id='same', fill_item_key='a')
        self.assertEqual(retry, state)
        self.assertEqual(self.path.read_bytes(), before)
        for extra in ({'price': '0.9'}, {'day': '2026-10-12'}, {'execution_id': 'different'},
                      {'received_at': '2026-10-14T00:00:00+08:00'}):
            args = dict(price='0.8', message_id='same', fill_item_key='a')
            args.update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                grid_state.record(self.path, 'buy', 100, **args)
            self.assertEqual(self.path.read_bytes(), before)

    def test_separate_messages_and_items_with_identical_fill_are_new(self):
        for message, item in [('one', 'a'), ('two', 'a'), ('two', 'b')]:
            grid_state.record(self.path, 'buy', 100, '0.8', message_id=message, fill_item_key=item)
        state = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(state['trades']), 12)
        self.assertEqual(state['qty'], 28500)
        self.assertEqual([t['id'] for t in state['trades'][-3:]],
                         ['589720-010', '589720-011', '589720-012'])


    def test_installed_launcher_defaults_date_id_and_retries_safely(self):
        import os
        import subprocess
        import sys
        import confirmed_runtime
        from tools.confirmed_grid.deploy import deploy
        home = Path(self.folder.name) / 'home'
        root = home / 'cache/grid-account'
        root.mkdir(parents=True)
        (home / 'scripts').mkdir()
        for code in confirmed_runtime.CODES:
            state = confirmed_589720.build(code=code, name=code)
            state['sellable_qty'] = state['qty']
            (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state), encoding='utf-8')
        deploy(home)
        env = dict(os.environ, HERMES_HOME=str(home), PYTHONIOENCODING='utf-8')
        command = [sys.executable, str(home / 'scripts/grid_weixin_confirm.py'), '成功',
                   '--code', 'sh589720', '--side', 'buy', '--qty', '100', '--price', '0.8',
                   '--message-id', 'adapter-1']
        result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('现在的剩余操作建议', result.stdout)
        self.assertIn(confirmed_runtime.render(confirmed_runtime.plan(root)), result.stdout)
        path = root / 'confirmed-589720.json'
        before = path.read_bytes()
        saved = json.loads(before)
        self.assertEqual(saved['trades'][-1]['id'], '589720-010')
        self.assertEqual(saved['trades'][-1]['date_source'], 'local_ingestion_beijing')
        retry = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(path.read_bytes(), before)
        unsafe = subprocess.run(command[:-2], env=env, capture_output=True)
        self.assertEqual(unsafe.returncode, 2)
        self.assertEqual(path.read_bytes(), before)
        print('Installed temp CLI: date/id omitted, ID=589720-010; retry byte-identical; rendered plan verified')


    def test_auto_id_uses_max_sequence_even_with_legacy_custom_ids(self):
        grid_state.record(self.path, 'buy', 100, '0.8', execution_id='legacy-custom')
        state = grid_state.record(self.path, 'buy', 100, '0.8', message_id='next')
        self.assertEqual(state['trades'][-1]['id'], '589720-011')

    def test_future_received_timestamp_and_naive_stamp_reject(self):
        before = self.path.read_bytes()
        from datetime import datetime, timezone, timedelta
        future = (datetime.now(timezone(timedelta(hours=8))) + timedelta(minutes=5)).isoformat()
        for stamp in (future, '2026-10-13T10:00:00'):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                grid_state.record(self.path, 'buy', 100, '0.8', message_id='bad', received_at=stamp)
            self.assertEqual(self.path.read_bytes(), before)

    def test_delayed_message_before_rollover_rejects_without_mutation(self):
        state = json.loads(self.path.read_text(encoding='utf-8'))
        state['sellable_updated_on'] = '2026-10-14'
        self.path.write_text(json.dumps(state), encoding='utf-8')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            grid_state.record(self.path, 'buy', 100, '0.8', message_id='delayed',
                              received_at='2026-10-13T23:59:59+08:00')
        self.assertEqual(self.path.read_bytes(), before)

    def test_concurrent_auto_ids_and_message_retry_have_no_lost_updates(self):
        import subprocess
        import sys
        command = "import grid_state,sys;grid_state.record(sys.argv[1],'buy',100,'0.8',message_id=sys.argv[2])"
        processes = [subprocess.Popen([sys.executable, '-c', command, str(self.path), key])
                     for key in ('a', 'b', 'c', 'a', 'b')]
        for process in processes:
            self.assertEqual(process.wait(timeout=30), 0)
        state = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(state['qty'], 28500)
        self.assertEqual([t['id'] for t in state['trades'][-3:]],
                         ['589720-010', '589720-011', '589720-012'])
        self.assertEqual(len(state['trades']), 12)


    def test_explicit_id_cannot_alias_different_message_identity(self):
        grid_state.record(self.path, 'buy', 100, '0.8', execution_id='explicit', message_id='one')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            grid_state.record(self.path, 'buy', 100, '0.8', execution_id='explicit', message_id='two')
        self.assertEqual(self.path.read_bytes(), before)

    def test_auto_id_uses_highest_existing_suffix_per_etf(self):
        grid_state.record(self.path, 'buy', 100, '0.8', execution_id='589720-040')
        state = grid_state.record(self.path, 'buy', 100, '0.8', message_id='next')
        self.assertEqual(state['trades'][-1]['id'], '589720-041')
        other = Path(self.folder.name) / 'other.json'
        fixture = confirmed_589720.build(code='sz159363')
        fixture['sellable_qty'] = fixture['qty']
        other.write_text(json.dumps(fixture), encoding='utf-8')
        self.assertEqual(grid_state.record(other, 'buy', 100, '0.8', message_id='next')['trades'][-1]['id'],
                         '159363-010')


if __name__ == '__main__':
    unittest.main()
