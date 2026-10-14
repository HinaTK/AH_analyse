import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
import confirmed_589720

class RuntimeTests(unittest.TestCase):
    def test_planner_reads_only_confirmed_state_with_two_conditional_sides(self):
        self.assertIsNotNone(importlib.util.find_spec('confirmed_runtime'), 'unified runtime missing')
        import confirmed_runtime as runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for code in runtime.CODES:
                state = confirmed_589720.build(code=code, name=code)
                state['sellable_qty'] = state['qty']
                (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state))
            ticket = runtime.plan(root)
            self.assertEqual({a['code'] for a in ticket['actions']}, set(runtime.CODES))
            self.assertEqual(len(ticket['actions']), 4)
            self.assertFalse(ticket['executable'])
            self.assertIsNone(ticket['cash'])
            sale = next(a for a in ticket['actions'] if a['side'] == 'sell')
            self.assertEqual((sale['price'], sale['qty'], sale['lot']), ('0.845', 9600, 'C'))
            buy = next(a for a in ticket['actions'] if a['side'] == 'buy')
            self.assertEqual((buy['price'], buy['lot']), ('0.821', 'D'))
            self.assertFalse((root / 'ledger.json').exists())

    def test_launchers_use_unified_runtime_without_legacy_imports(self):
        import ast
        launchers = Path(__file__).parent / 'tools' / 'confirmed_grid' / 'launchers'
        self.assertTrue((launchers / 'grid_weixin_ops.py').exists(), 'live launcher replacement missing')
        for name in ('grid_weixin_ops.py', 'grid_weixin_intraday.py', 'grid_weixin_confirm.py', 'grid_eod_decision.py'):
            tree = ast.parse((launchers / name).read_text(encoding='utf-8'))
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertNotIn('grid_account', imports)
            self.assertIn('confirmed_runtime', imports)

    def test_quote_gating_and_extrema_dedup_per_day(self):
        import confirmed_runtime as runtime
        self.assertTrue(hasattr(runtime, 'monitor'), 'same-state monitor missing')
        now = datetime(2026, 10, 14, 10, tzinfo=timezone(timedelta(hours=8)))
        quotes = {code: dict(last='0.8', high='0.9', low='0.7', time='20261014100000') for code in runtime.CODES}
        self.assertTrue(runtime.quotes_are_live(quotes, now))
        quotes['sz159363']['time'] = '20261014092900'
        self.assertFalse(runtime.quotes_are_live(quotes, now))
        quotes['sz159363']['time'] = '20261014100000'
        ticket = dict(actions=[dict(code='sh589720',side='sell',price='0.850',qty=9600,lot='C')])
        state = {}
        self.assertIn('触价不等于成交', runtime.monitor(ticket, quotes, state, '2026-10-14'))
        self.assertEqual(runtime.monitor(ticket, quotes, state, '2026-10-14'), '')
        self.assertTrue(runtime.monitor(ticket, quotes, state, '2026-10-15'))
        self.assertNotIn('trades', state)
        self.assertEqual(runtime.phase(datetime(2026,10,1,10,tzinfo=now.tzinfo)), 'closed')
        self.assertEqual(runtime.phase(datetime(2026,10,14,12,tzinfo=now.tzinfo)), 'closed')

    def test_stale_quote_calendar_core_and_spot_fallback(self):
        import confirmed_runtime as runtime
        now = datetime(2026,10,14,10,tzinfo=timezone(timedelta(hours=8)))
        quotes = {code:dict(last='0.9',time='20261014093000') for code in runtime.CODES}
        self.assertFalse(runtime.quotes_are_live(quotes,now))
        self.assertEqual(runtime.phase(datetime(2026,2,18,10,tzinfo=now.tzinfo)),'closed')
        self.assertEqual(runtime.phase(datetime(2027,1,4,10,tzinfo=now.tzinfo)),'closed')
        ticket = dict(actions=[dict(code='sh589720',side='sell',price='0.850',qty=9600,lot='C')])
        self.assertTrue(runtime.monitor(ticket,quotes,{},'2026-10-14'))
        message = runtime.monitor(ticket,quotes,{},'2026-10-14')
        self.assertIn('现价',message)
        self.assertNotIn('日内极值',message)
        quotes['sh589720']['high'] = 'NaN'
        self.assertTrue(runtime.monitor(ticket,quotes,{},'2026-10-14'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for code in runtime.CODES:
                state = confirmed_589720.build([('buy',4600,'1.28')],code=code,name=code)
                state['sellable_qty'] = 4600
                (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state))
            ticket = runtime.plan(root)
            self.assertFalse(any(a['code']=='sz159363' and a['side']=='sell' for a in ticket['actions']))

    def test_state_corruption_is_rejected_without_write(self):
        import confirmed_runtime as runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for code in runtime.CODES:
                state = confirmed_589720.build(code=code,name=code)
                state.update(qty=1,sellable_qty=1)
                (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                runtime.plan(root)

    def test_corrupt_cycle_link_and_saved_trade_label_are_rejected(self):
        import confirmed_runtime as runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for code in runtime.CODES:
                state = confirmed_589720.build(code=code,name=code)
                state['sellable_qty'] = state['qty']
                (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state))
            path = root / 'confirmed-589720.json'
            clean = json.loads(path.read_text())
            bad = json.loads(path.read_text())
            bad['t_records'][0]['buy_id'] = 'nonexistent'
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                runtime.plan(root)
            clean['trades'][0]['lot'] = 'Z'
            path.write_text(json.dumps(clean))
            with self.assertRaises(ValueError):
                runtime.plan(root)

    def test_feed_outage_is_labelled_without_periodic_traceback(self):
        import confirmed_runtime as runtime
        from unittest.mock import patch
        import urllib.error
        import io
        from contextlib import redirect_stdout
        self.assertTrue(hasattr(runtime,'safe_entrypoint'))
        def outage():
            raise urllib.error.URLError('offline')
        stream = io.StringIO()
        with redirect_stdout(stream):
            runtime.safe_entrypoint(outage)
        self.assertIn('不生成执行建议',stream.getvalue())
        self.assertNotIn('Traceback',stream.getvalue())

    def test_initial_fixture_cli_cannot_overwrite_existing_state(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'state.json'
            target.write_text('{"marker":"must preserve"}')
            before = target.read_bytes()
            result = subprocess.run([sys.executable,'confirmed_589720.py','--output',str(target)],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(target.read_bytes(),before)

    def test_eod_requires_current_close_and_stores_same_state_fingerprint(self):
        import confirmed_runtime as runtime
        self.assertTrue(hasattr(runtime, 'eod_report'), 'confirmed EOD consumer missing')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for code in runtime.CODES:
                state = confirmed_589720.build(code=code,name=code)
                state['sellable_qty'] = state['qty']
                (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state))
            now = datetime(2026,10,14,15,20,tzinfo=timezone(timedelta(hours=8)))
            quotes = {code:dict(time='20261014150000',last='0.8',high='0.9',low='0.7') for code in runtime.CODES}
            bars = {code:[dict(date='2026-10-14',close='0.8')] for code in runtime.CODES}
            report = runtime.eod_report(root,now,quotes,bars)
            self.assertFalse(report['executable'])
            self.assertEqual(set(report['state_hashes']),set(runtime.CODES))
            self.assertEqual(report['decisions']['sh589720']['t_net'], state['t_net'])
            quotes['sh589720']['time'] = '20261013150000'
            with self.assertRaises(ValueError):
                runtime.eod_report(root,now,quotes,bars)

class FillTests(unittest.TestCase):
    def test_concurrent_fill_and_midnight_do_not_lose_updates(self):
        import subprocess, sys
        import grid_state
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            state = confirmed_589720.build()
            state.update(sellable_qty=28200,sellable_updated_on='2026-10-13')
            path.write_text(json.dumps(state))
            command = "import grid_state,sys;grid_state.record(sys.argv[1],'sell',9600,'0.850','2026-10-14',execution_id='race-1')"
            fill = subprocess.Popen([sys.executable,'-c',command,str(path)])
            sync = subprocess.Popen([sys.executable,'-c',"import grid_state,sys;grid_state.rollover(sys.argv[1],'2026-10-14')",str(path)])
            self.assertEqual(fill.wait(),0)
            self.assertEqual(sync.wait(),0)
            saved = json.loads(path.read_text())
            self.assertEqual((saved['qty'],saved['sellable_qty'],saved['max_grid']),(18600,18600,'B'))
            self.assertEqual(saved['trades'][-1]['id'],'race-1')
            self.assertEqual(grid_state.rollover(path,'2026-10-14'),saved)

    def test_record_requires_explicit_id_instead_of_synthesizing_fill(self):
        import grid_state
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            state = confirmed_589720.build()
            state['sellable_qty'] = state['qty']
            path.write_text(json.dumps(state))
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                grid_state.record(path,'buy',100,'0.8','2026-10-14')
            self.assertEqual(path.read_bytes(),before)

    def test_explicit_cli_fill_prints_remaining_advice_and_bare_success_fails(self):
        import os, subprocess, sys
        import confirmed_runtime as runtime
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / 'cache/grid-account'
            root.mkdir(parents=True)
            for code in runtime.CODES:
                state = confirmed_589720.build(code=code,name=code)
                state.update(sellable_qty=28200,sellable_updated_on='2026-10-14')
                (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state))
            env = dict(os.environ,HERMES_HOME=str(home),PYTHONIOENCODING='utf-8')
            launcher = Path(__file__).parent / 'tools/confirmed_grid/launchers/grid_weixin_confirm.py'
            bare = subprocess.run([sys.executable,str(launcher),'成功'],env=env,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(bare.returncode,2)
            filled = subprocess.run([sys.executable,str(launcher),'成功','--code','sh589720','--side','sell','--qty','9600','--price','0.850','--date','2026-10-14','--id','cli-1'],env=env,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(filled.returncode,0,filled.stderr)
            self.assertIn('现在的剩余操作建议',filled.stdout)
            self.assertIn('条件买',filled.stdout)
            self.assertIn('条件卖',filled.stdout)

    def test_explicit_id_is_idempotent_and_rollover_cannot_restore_sold_inventory(self):
        import grid_state
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            state = confirmed_589720.build()
            state.update(sellable_qty=28200, sellable_updated_on='2026-10-14')
            path.write_text(json.dumps(state))
            self.assertIn('execution_id', __import__('inspect').signature(grid_state.record).parameters)
            updated = grid_state.record(path, 'sell', 9600, '0.850', '2026-10-14', execution_id='broker-explicit-1')
            self.assertEqual(updated['trades'][-1]['id'], 'broker-explicit-1')
            self.assertEqual(updated['t_records'][-1]['sell_id'], 'broker-explicit-1')
            self.assertEqual(grid_state.record(path, 'sell', 9600, '0.850', '2026-10-14', execution_id='broker-explicit-1'), updated)
            self.assertEqual(grid_state.rollover(path, '2026-10-14'), updated)
            with self.assertRaises(ValueError):
                grid_state.record(path, 'sell', 9600, '0.851', '2026-10-14', execution_id='broker-explicit-1')
            self.assertEqual(json.loads(path.read_text()), updated)
            self.assertEqual(updated['trades'][:9], state['trades'])

if __name__ == '__main__':
    unittest.main()
