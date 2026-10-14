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

class CorruptPriorStateTests(unittest.TestCase):
    def test_record_rejects_corrupt_prior_state_without_changing_pool(self):
        import grid_state
        mutations = {
            'lot': lambda s: s['trades'][0].update(lot='Z'),
            'cycle_link': lambda s: s['t_records'][0].update(buy_id='forged'),
            'forged_quantity_and_pool': lambda s: s.update(qty=999999, sellable_qty=999999),
            'open_record': lambda s: s['open_grid_positions'][0].update(id='forged'),
            'total': lambda s: s.update(net_invested='0.00'),
            'duplicate_id': lambda s: s['trades'][1].update(id=s['trades'][0]['id']),
            'blank_id': lambda s: s['trades'][0].update(id=' '),
            'sellable_bounds': lambda s: s.update(sellable_qty=999999),
            'remaining_unit_cost': lambda s: s.update(remaining_unit_cost='0'),
        }
        for label, mutate in mutations.items():
            with self.subTest(corruption=label), tempfile.TemporaryDirectory() as folder:
                p = Path(folder) / 'state.json'
                state = json.loads(json.dumps(source.build()))
                state['sellable_qty'] = state['qty']
                mutate(state)
                p.write_text(json.dumps(state), encoding='utf-8')
                before = p.read_bytes()
                with self.assertRaises(ValueError):
                    grid_state.record(p, 'buy', 9900, '0.806', '2026-10-14', execution_id='new-buy')
                self.assertEqual(p.read_bytes(), before)

    def test_rollover_rejects_corruption_before_settling_or_noop(self):
        import grid_state
        mutations = {
            'lot': lambda s: s['trades'][0].update(lot='Z'),
            'cycle_link': lambda s: s['t_records'][0].update(buy_id='forged'),
            'quantity': lambda s: s.update(qty=999999),
            'sellable': lambda s: s.update(sellable_qty=999999),
            'open_record': lambda s: s['open_grid_positions'][0].update(id='forged'),
        }
        for label, mutate in mutations.items():
            for stamp in ('2026-10-13', '2026-10-14'):
                with self.subTest(corruption=label, stamp=stamp), tempfile.TemporaryDirectory() as folder:
                    p = Path(folder) / 'state.json'
                    state = json.loads(json.dumps(source.build()))
                    state.update(sellable_qty=state['qty'], sellable_updated_on=stamp)
                    mutate(state)
                    p.write_text(json.dumps(state), encoding='utf-8')
                    before = p.read_bytes()
                    with self.assertRaises(ValueError):
                        grid_state.rollover(p, '2026-10-14')
                    self.assertEqual(p.read_bytes(), before)

    def test_duplicate_fill_still_validates_prior_state(self):
        import grid_state
        for corruption in ('lot', 'cycle', 'pool'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as folder:
                p = Path(folder) / 'state.json'
                state = source.build()
                state.update(sellable_qty=state['qty'])
                p.write_text(json.dumps(state), encoding='utf-8')
                grid_state.record(p, 'buy', 9900, '0.806', '2026-10-14', execution_id='same-fill')
                state = json.loads(p.read_text(encoding='utf-8'))
                if corruption == 'lot':
                    state['trades'][0]['lot'] = 'Z'
                elif corruption == 'cycle':
                    state['t_records'][0]['buy_id'] = 'forged'
                else:
                    state['sellable_qty'] = 999999
                p.write_text(json.dumps(state), encoding='utf-8')
                before = p.read_bytes()
                with self.assertRaises(ValueError):
                    grid_state.record(p, 'buy', 9900, '0.806', '2026-10-14', execution_id='same-fill')
                self.assertEqual(p.read_bytes(), before)

    def test_reader_rejects_corrupt_remaining_unit_cost(self):
        import confirmed_runtime
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for code in confirmed_runtime.CODES:
                state = source.build(code=code)
                state.update(sellable_qty=state['qty'], remaining_unit_cost='0')
                (root / f'confirmed-{code[-6:]}.json').write_text(json.dumps(state), encoding='utf-8')
            with self.assertRaises(ValueError):
                confirmed_runtime.load_states(root)

    def test_uninitialized_pool_requires_rollover_and_late_rollover_preserves_metadata(self):
        import grid_state
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'state.json'
            state = source.build()
            p.write_text(json.dumps(state), encoding='utf-8')
            before = p.read_bytes()
            with self.assertRaises(ValueError):
                grid_state.record(p, 'buy', 9900, '0.806', '2026-10-14', execution_id='late-buy')
            self.assertEqual(p.read_bytes(), before)
            initialized = grid_state.rollover(p, '2026-10-13')
            bought = grid_state.record(p, 'buy', 9900, '0.806', '2026-10-14', execution_id='late-buy')
            self.assertEqual(bought['trades'][:len(state['trades'])], state['trades'])
            settled = grid_state.rollover(p, '2026-10-14')
            self.assertEqual(settled['sellable_qty'], initialized['qty'])
            self.assertEqual(settled['trades'], bought['trades'])
            self.assertEqual(grid_state.rollover(p, '2026-10-15')['sellable_qty'], bought['qty'])

if __name__ == '__main__':
    unittest.main()
