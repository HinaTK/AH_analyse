"""RED tests for confirmed_runtime integration with the holdings list."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal as D

import confirmed_runtime as runtime
import grid_state
import holdings as H
import confirmed_589720


def _fixture(code, name, fills):
    state = confirmed_589720.build(fills, code=code, name=name)
    state['sellable_qty'] = state['qty']
    state['sellable_updated_on'] = '2026-10-13'
    return state


class RuntimeHoldingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.home = Path(self.folder.name) / 'home'
        root = self.home / 'cache/grid-account'
        root.mkdir(parents=True)
        (self.home / 'scripts').mkdir()
        os.environ['HERMES_HOME'] = str(self.home)
        self.root = root
        for code, name, fills in [
            ('sh589720', '科创创新药ETF国泰',
             [('buy', 9200, '0.877'), ('buy', 9400, '0.859'), ('buy', 9600, '0.829'),
              ('sell', 9600, '0.846'), ('buy', 9600, '0.833')]),
            ('sz159363', '创业板人工智能ETF华宝',
             [('buy', 4600, '1.28'), ('buy', 4700, '1.273'), ('buy', 4800, '1.197'),
              ('buy', 5100, '1.169'), ('sell', 5100, '1.193'), ('buy', 5100, '1.156')]),
            ('sz159992', '创新药ETF银华',
             [('buy', 9100, '0.871'), ('buy', 9200, '0.863'), ('buy', 9400, '0.846'),
              ('sell', 9400, '0.863'), ('buy', 9400, '0.846'), ('sell', 9400, '0.863')]),
        ]:
            (root / f'confirmed-{code[-6:]}.json').write_text(
                json.dumps(_fixture(code, name, fills), ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        os.environ.pop('HERMES_HOME', None)
        self.folder.cleanup()

    def test_midnight_rollover_covers_all_three(self):
        from datetime import datetime, timezone, timedelta
        day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        for code in H.held_codes():
            state = grid_state.rollover(self.root / f'confirmed-{code[-6:]}.json', day)
            self.assertEqual(state['sellable_qty'], state['qty'])
            self.assertEqual(state['sellable_updated_on'], day)

    def test_plan_never_sells_inactive_etf(self):
        ticket = runtime.plan(self.root)
        codes = {a['code'] for a in ticket['actions'] if a['side'] == 'sell'}
        self.assertNotIn('sz159992', codes)

    def test_inactive_sell_record_rejected(self):
        path = self.root / 'confirmed-159992.json'
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            grid_state.record(path, 'sell', 9400, '0.863', message_id='probe')
        self.assertEqual(path.read_bytes(), before)

    def test_render_marks_inactive_exit(self):
        ticket = runtime.plan(self.root)
        rendered = runtime.render(ticket)
        self.assertIn('sz159992', rendered)
        self.assertIn('迁移退出', rendered)