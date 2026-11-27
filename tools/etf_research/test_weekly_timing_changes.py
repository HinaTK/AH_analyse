import pandas as pd
from tools.etf_research import weekly


def test_only_lapsed_this_week_not_future_or_current(tmp_path, monkeypatch):
    daily = pd.DataFrame({'date': ['2026-11-20', '2026-11-23', '2026-11-24', '2026-11-25', '2026-11-26', '2026-11-27', '2026-11-30']})
    monkeypatch.setattr(weekly, 'daily_bars', lambda path: daily)
    pool = [{'code': 'sh512890', 'name': '样本', 'has_all_four_windows': True}]
    full_days = {'2026-11-20', '2026-11-24', '2026-11-26', '2026-11-30'}
    calls = []
    def judge(frame, asof):
        calls.append(asof)
        return dict(verdict='full' if asof in full_days else 'wait', label='等待触发', reasons=['收盘情况；收盘跌破20日线1.248'])
    monkeypatch.setattr(weekly, 'judge_entry', judge)
    lines = weekly.weekly_timing_changes(pool, tmp_path, '2026-11-27')
    assert len(lines) == 1 and '周二、周四' in lines[0] and '周五' in lines[0] and '跌破20日线' in lines[0]
    assert not {'2026-11-20','2026-11-30'}.intersection(calls)
    full_days.add('2026-11-27')
    assert weekly.weekly_timing_changes(pool, tmp_path, '2026-11-27') == []
    full_days.clear()
    assert weekly.weekly_timing_changes(pool, tmp_path, '2026-11-27') == []
