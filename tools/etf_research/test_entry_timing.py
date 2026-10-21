from datetime import datetime

import pandas as pd

from tools.etf_research.entry_timing import MARKET_TZ, drop_unclosed_bar, judge_entry, prefix_code


def bars(closes, lows=None, highs=None, start='2026-01-05'):
    closes = list(closes)
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'open': closes,
        'high': highs if highs is not None else [close * 1.01 for close in closes],
        'low': lows if lows is not None else [close * 0.99 for close in closes],
        'close': closes,
    })


def test_extended_uptrend_near_prior_high_is_rejected():
    result = judge_entry(bars([10 * 1.01 ** i for i in range(120)]))
    assert result['verdict'] == 'reject'
    assert any('追高' in reason for reason in result['reasons'])


def test_breakout_well_above_prior_high_is_still_rejected():
    result = judge_entry(bars([10.0] * 80 + [10.5]))
    assert result['verdict'] == 'reject'


def test_extended_above_the_20_day_below_prior_high_cannot_be_an_entry():
    closes = [10.0] * 70 + [13.0]
    highs = [10.1] * 60 + [15.0] + [10.1] * 9 + [13.2]
    lows = [9.9] * 70 + [12.8]
    result = judge_entry(bars(closes, lows, highs))
    assert result['verdict'] == 'no_entry'
    assert any('20日线' in reason for reason in result['reasons'])


def test_pullback_to_the_20_day_in_an_uptrend_is_not_rejected():
    closes = [10 * 1.003 ** i for i in range(120)]
    closes[-1] = closes[-2] * 0.985
    lows = [close * 0.99 for close in closes]
    lows[-1] = sum(closes[-20:]) / 20
    result = judge_entry(bars(closes, lows))
    assert result['verdict'] == 'full'


def test_falling_knife_under_the_60_day_waits_instead_of_probing():
    result = judge_entry(bars([2 - i * 0.01 for i in range(80)]))
    assert result['verdict'] == 'wait'
    assert result['exit_price'] is None
    assert any('尚未止跌' in reason for reason in result['reasons'])


def test_stabilized_bounce_under_a_falling_60_day_is_a_probe_with_exit_below_close():
    closes = [12 - 0.03 * i for i in range(80)] + [9.5, 9.7]
    frame = bars(closes)
    result = judge_entry(frame)
    assert result['verdict'] == 'probe_only'
    assert result['exit_price'] == frame['low'].iloc[-21:-1].min()
    assert result['exit_price'] < result['close']
    assert any('仍在下行' in reason for reason in result['reasons'])


def test_stabilized_dip_under_a_rising_60_day_is_also_a_probe():
    closes = [10 + 0.02 * i for i in range(90)] + [11.0, 10.8, 10.6, 10.5, 10.9]
    result = judge_entry(bars(closes))
    assert result['verdict'] == 'probe_only'
    assert any('未下行' in reason for reason in result['reasons'])


def test_full_position_requires_a_held_60_day_reclaim_and_a_20_day_pullback():
    closes = [10.0] * 65 + [9.0] * 5 + [10.5] * 5 + [10.0]
    lows = [close * 0.99 for close in closes]
    lows[-1] = 9.90
    result = judge_entry(bars(closes, lows))
    assert result['verdict'] == 'full'
    assert any('连续' in reason for reason in result['reasons'])


def test_one_day_reclaim_is_not_held():
    result = judge_entry(bars([10.0] * 65 + [9.0] * 5 + [10.0]))
    assert result['verdict'] == 'wait'
    assert any('需至少3日' in reason for reason in result['reasons'])


def test_flat_price_waits():
    result = judge_entry(bars([10.0] * 80))
    assert result['verdict'] == 'wait'


def test_short_history_is_insufficient():
    result = judge_entry(bars([1.0] * 10))
    assert result['verdict'] == 'insufficient'


def test_unclosed_bar_is_dropped_only_during_the_session():
    frame = bars([10.0] * 3, start='2026-10-19')
    during = datetime(2026, 10, 21, 10, 30, tzinfo=MARKET_TZ)
    after = datetime(2026, 10, 21, 15, 5, tzinfo=MARKET_TZ)
    assert drop_unclosed_bar(frame, now=during)['date'].iloc[-1] == '2026-10-20'
    assert drop_unclosed_bar(frame, now=after)['date'].iloc[-1] == '2026-10-21'


def test_prefix_code_routes_exchanges():
    assert prefix_code('510300') == 'sh510300'
    assert prefix_code('159363') == 'sz159363'
    assert prefix_code('830799') == 'bj830799'
