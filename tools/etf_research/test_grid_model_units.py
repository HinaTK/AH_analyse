"""grid_model.py volume unit bug: shares vs lots 100x mismatch."""
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


def module():
    return importlib.import_module('tools.etf_research.research')


def test_initial_volume_check_compares_shares_to_shares_not_lots():
    """grid_model.py:37 compares core_qty+4*q (shares) against vol[0]*.01 (lots).

    Sina K-line volume is in lots (100 shares). At price ~1.0, core_qty+4*q ~= 29,500 shares.
    With vol=500,000 lots: 1% of lots = 5,000 (wrongly blocks), 1% of shares = 500,000 (correct).
    """
    r = module()
    model = r.get_model()
    d = vshaped(['2026-10-08', '2026-10-09'], first_vol=500000, rest_vol=500000)
    result = model.simulate(d, trace=True)
    assert abs(result['identity_error']) < 1e-6
    assert result['cycles'] > 0


def test_initial_volume_check_159569_real_symptom():
    """159569 first bar vol=1,464,800 lots wrongly rejects ~22,900 shares.

    This symptom is caused by line 37, not lines 76/88: the unfixed threshold
    (14,648) already exceeds the buy qty (~4,800-5,500 shares), so the buy-side
    checks never reject a valid trade here.
    """
    r = module()
    model = r.get_model()
    d = vshaped(['2026-10-08', '2026-10-09'], first_vol=1464800, rest_vol=1464800)
    result = model.simulate(d, trace=True)
    assert abs(result['identity_error']) < 1e-6
    assert result['cycles'] > 0


def test_sell_and_buy_volume_checks_use_share_denominator():
    """grid_model.py:76 and :88 compare share-denominated qty against lot-denominated
    vol[i]*.01. First bar vol is large enough to pass line 37; later bars are low
    enough that the unfixed sell/buy checks reject (~4,800 shares vs 3,000 lots).
    """
    r = module()
    model = r.get_model()
    d = vshaped(['2026-10-08', '2026-10-09', '2026-10-13'],
                first_vol=5000000, rest_vol=300000)
    result = model.simulate(d, trace=True)
    assert abs(result['identity_error']) < 1e-6
    assert result['sales'] > 0
    assert result['cycles'] > 0