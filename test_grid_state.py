import unittest
import tempfile
import json
from pathlib import Path
import confirmed_589720 as source

class StateTests(unittest.TestCase):
    def test_midnight_persists_recomputed_quantity(self):
        import grid_state
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'state.json'
            state = source.build()
            state['qty'] = 1
            p.write_text(json.dumps(state), encoding='utf-8')
            grid_state.rollover(p, '2026-10-14')
            saved = json.loads(p.read_text(encoding='utf-8'))
            self.assertEqual(saved['qty'], 28200)
            self.assertEqual(saved['sellable_qty'], 28200)
            self.assertEqual(saved['max_grid'], 'C')
            grid_state.rollover(p, '2026-10-14')
            self.assertEqual(json.loads(p.read_text(encoding='utf-8')), saved)

    def test_buy_sell_persist_inventory_and_pointer(self):
        import grid_state
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'state.json'
            s = source.build()
            s['sellable_qty'] = 28200
            p.write_text(json.dumps(s), encoding='utf-8')
            grid_state.record(p, 'buy', 9900, '0.806', '2026-10-14', execution_id='test-buy')
            bought = json.loads(p.read_text(encoding='utf-8'))
            self.assertEqual((bought['qty'], bought['sellable_qty'], bought['max_grid']), (38100,28200,'D'))
            grid_state.record(p, 'sell', 9900, '0.818', '2026-10-14', execution_id='test-sell')
            sold = json.loads(p.read_text(encoding='utf-8'))
            self.assertEqual((sold['qty'], sold['sellable_qty'], sold['max_grid']), (28200,18300,'C'))
            self.assertEqual(sold['trades'][-1]['lot'], 'D')
            with self.assertRaises(ValueError):
                grid_state.record(p, 'sell', 20000, '0.9', '2026-10-14')
            self.assertEqual(json.loads(p.read_text(encoding='utf-8')), sold)

if __name__ == '__main__':
    unittest.main()
