"""RED tests for the persisted holdings list."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal as D

import holdings as H


class HoldingsListTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.home = Path(self.folder.name) / 'home'
        (self.home / 'cache/grid-account').mkdir(parents=True)
        os.environ['HERMES_HOME'] = str(self.home)

    def tearDown(self):
        os.environ.pop('HERMES_HOME', None)
        self.folder.cleanup()

    def test_default_three_etfs_loaded(self):
        held = H.held_codes()
        self.assertEqual(set(held), {'sh589720', 'sz159363', 'sz159992'})

    def test_inactive_etf_is_not_active(self):
        self.assertFalse(H.is_active('sz159992'))
        self.assertTrue(H.is_active('sh589720'))

    def test_lot_budget_none_for_inactive(self):
        budgets = H.lot_budgets()
        self.assertEqual(budgets['sh589720'], D('8000'))
        self.assertEqual(budgets['sz159363'], D('6000'))
        self.assertIsNone(budgets['sz159992'])

    def test_persist_and_reload(self):
        H.save_holdings(H.load_holdings())
        reloaded = H.load_holdings()
        self.assertEqual(reloaded['sz159992']['name'], '创新药ETF银华')
        self.assertFalse(reloaded['sz159992']['active'])

    def test_unknown_code_not_added_automatically(self):
        held = H.held_codes()
        self.assertNotIn('sh000000', held)

    def test_explicit_register_only_on_request(self):
        H.save_holdings({**H.load_holdings(),
                         'sh000000': {'name': '测试ETF', 'lot_budget': '5000', 'active': True}})
        self.assertIn('sh000000', H.held_codes())