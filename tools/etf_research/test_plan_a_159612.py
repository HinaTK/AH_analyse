import pandas as pd

from tools.etf_research.plan_a_159612 import simulate


def frame(prices):
    rows = []
    for day, time, p in prices:
        rows.append(dict(time=f'{day} {time}', open=p, close=p, high=p, low=p, volume=1e8))
    return pd.DataFrame(rows)


def test_completed_cycle_and_reconciliation():
    bars = frame([('2026-10-08', '09:35:00', 2.080),
                  ('2026-10-08', '09:40:00', 2.080),
                  ('2026-10-09', '09:35:00', 2.110),
                  ('2026-10-09', '09:40:00', 2.110)])
    result = simulate(bars)
    assert result['cycles'] == 1
    assert result['end_qty'] == 0
    assert result['cycle_net'] == result['account_pnl']
    assert result['peak_cost'] <= 40000
    assert [e['side'] for e in result['events']] == ['buy', 'sell']


def test_no_same_day_sell_and_no_buy_outside_box():
    bars = frame([('2026-10-08', '09:35:00', 2.080),
                  ('2026-10-08', '09:40:00', 2.080),
                  ('2026-10-08', '09:45:00', 2.110),
                  ('2026-10-08', '09:50:00', 2.110),
                  ('2026-10-09', '09:35:00', 2.040),
                  ('2026-10-09', '09:40:00', 2.040)])
    result = simulate(bars)
    assert result['cycles'] == 0
    assert result['blocked_settlement'] >= 1
    assert [e['side'] for e in result['events']] == ['buy']
    assert result['inventory_pnl'] < 0


def test_cap_and_no_lifetime_reinvestment_above_cap():
    bars = frame([('2026-10-08', '09:35:00', 2.080),
                  ('2026-10-08', '09:40:00', 2.080),
                  ('2026-10-08', '09:45:00', 2.057),
                  ('2026-10-09', '09:35:00', 2.070),
                  ('2026-10-09', '09:40:00', 2.070)])
    result = simulate(bars, capital=8000, start_cash=8000, max_slots=1)
    assert result['peak_cost'] <= 8000
    assert len([e for e in result['events'] if e['side'] == 'buy']) == 1
