"""Sina 5m `volume` is in shares (股): its daily sum equals Tencent 手 x 100.

The model's 1% participation cap must therefore compare share quantities with
1% of the bar's share volume, without any lots->shares multiplier.
"""
import importlib
import pandas as pd
import pytest


def _times():
    return (pd.date_range('2000-01-01 09:35', '2000-01-01 11:30', freq='5min').strftime('%H:%M:%S').tolist()
            + pd.date_range('2000-01-01 13:05', '2000-01-01 15:00', freq='5min').strftime('%H:%M:%S').tolist())


def vshaped(days, first_vol, rest_vol):
    """Day 1 declines 1.02->0.90 (crosses buy grid), later days rise 0.90->1.10
    (cross sell grid). first_vol on bar 0 only, rest_vol everywhere else."""
    times = _times()
    n = len(times)
    rows = []
    for di, day in enumerate(days):
        for i, hour in enumerate(times):
            if di == 0:
                price = 1.02 - (1.02 - 0.90) * i / (n - 1)
            else:
                price = 0.90 + (1.10 - 0.90) * i / (n - 1)
            vol = first_vol if (di == 0 and i == 0) else rest_vol
            rows.append(dict(time=f'{day} {hour}', open=price, high=price, low=price, close=price, volume=vol))
    return pd.DataFrame(rows)


def model():
    return importlib.import_module('tools.etf_research.research').get_model()


def test_initial_orders_rejected_above_one_percent_of_share_volume():
    # Initial core+4 lots ~= 29,400 shares at ~1.02; 1% of 2,000,000 shares = 20,000.
    d = vshaped(['2026-10-08', '2026-10-09'], first_vol=2_000_000, rest_vol=10_000_000)
    with pytest.raises(ValueError, match='1% first bar volume'):
        model().simulate(d)


def test_initial_orders_accepted_within_one_percent_of_share_volume():
    d = vshaped(['2026-10-08', '2026-10-09'], first_vol=5_000_000, rest_vol=10_000_000)
    result = model().simulate(d, trace=True)
    assert abs(result['identity_error']) < 1e-6
    assert result['cycles'] > 0


def test_grid_orders_cancelled_above_one_percent_of_share_volume():
    # ~4,900-share lots vs 1% of 300,000 shares = 3,000: every grid order is capped.
    d = vshaped(['2026-10-08', '2026-10-09', '2026-10-13'], first_vol=100_000_000, rest_vol=300_000)
    result = model().simulate(d, trace=True)
    assert result['sales'] == 0 and result['cycles'] == 0
    assert result['cancelled_signals'] > 0
    assert [e['side'] for e in result['events'] if not e['initial']] == []


def test_grid_orders_fill_within_one_percent_of_share_volume():
    d = vshaped(['2026-10-08', '2026-10-09', '2026-10-13'], first_vol=100_000_000, rest_vol=10_000_000)
    result = model().simulate(d, trace=True)
    assert abs(result['identity_error']) < 1e-6
    assert result['sales'] > 0 and result['cycles'] > 0


def test_cycle_return_is_on_initial_trading_lots_cost():
    d = vshaped(['2026-10-08', '2026-10-09'], first_vol=5_000_000, rest_vol=10_000_000)
    result = model().simulate(d, lot_budget=5000)
    assert 'cycle_return_on_40k_pct' not in result
    lots_cost = result['initial_lots_cost']
    assert 19_000 < lots_cost <= 20_000
    assert result['cycle_return_on_initial_lots_pct'] == pytest.approx(result['cycle_net'] / lots_cost * 100)
