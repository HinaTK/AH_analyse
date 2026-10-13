import unittest
import importlib.util
from pathlib import Path

class ConfirmedTradesTests(unittest.TestCase):
    def test_authoritative_rebuild(self):
        p = Path(__file__).with_name('confirmed_589720.py')
        self.assertTrue(p.exists(), '缺少无副作用的已确认成交重建模块')
        spec = importlib.util.spec_from_file_location('confirmed', p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        r = m.build()
        self.assertEqual(len(r['trades']), 9)
        self.assertEqual(r['qty'], 28200)
        self.assertEqual(r['net_invested'], '23746.80')
        self.assertEqual(r['t_net'], '396.00')
        self.assertEqual(len(r['t_records']), 3)
        self.assertTrue(all(t['date'] is None for t in r['trades']))
        self.assertIsNone(r['sellable_qty'])
        self.assertEqual([(x['buy_id'], x['sell_id']) for x in r['t_records']], [('589720-003','589720-004'),('589720-007','589720-008'),('589720-006','589720-009')])
        self.assertEqual(m.build(), r)
        self.assertEqual([t['lot'] for t in r['trades']], list('ABCC CDEED'.replace(' ', '')))
        self.assertEqual(r['max_grid'], 'C')
        self.assertTrue(all(len(row) == 3 for row in m.INPUT))
        repeated = m.build([('buy',100,'1'),('sell',100,'1.1'),('buy',100,'0.9'),('sell',100,'1'),('buy',100,'0.8'),('sell',100,'0.9')])
        self.assertEqual([t['lot'] for t in repeated['trades']], ['A']*6)
        self.assertEqual([(t['buy_id'],t['sell_id']) for t in repeated['t_records']], [('589720-001','589720-002'),('589720-003','589720-004'),('589720-005','589720-006')])
        self.assertIsNone(repeated['max_grid'])

if __name__ == '__main__':
    unittest.main()
