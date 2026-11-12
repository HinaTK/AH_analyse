# -*- coding: utf-8 -*-
"""TDD：榜单默认必须同时显示 63 日与近 20 日（Master 2026-11-12「不要等我问题」）。

要求：①产物自带合并表（不是靠临时脚本）；②一行同时有两个窗口的数值与名次；
③中文表头、不裸写英文字段名；④真实入口默认写出报告文件，无需额外开关。
"""
import pandas as pd
import pytest


def _rank():
    return pd.DataFrame([
        dict(code='A', name='甲ETF', holding=False, has_all_four_windows=True,
             median_full_cycles=33., recent_median_cycles=6., recent_state='近期降温',
             full_cycle_net=3000., recent20_cycle_net=500.),
        dict(code='B', name='乙ETF', holding=False, has_all_four_windows=True,
             median_full_cycles=15., recent_median_cycles=31., recent_state='近期升温',
             full_cycle_net=1500., recent20_cycle_net=2800.),
        dict(code='C', name='丙ETF', holding=False, has_all_four_windows=True,
             median_full_cycles=28., recent_median_cycles=12., recent_state='近期升温',
             full_cycle_net=2600., recent20_cycle_net=1200.),
        dict(code='D', name='丁ETF', holding=False, has_all_four_windows=True,
             median_full_cycles=10., recent_median_cycles=3., recent_state='近期降温',
             full_cycle_net=900., recent20_cycle_net=200.),
        dict(code='E', name='戊ETF', holding=True, has_all_four_windows=True,
             median_full_cycles=40., recent_median_cycles=20., recent_state='近期平稳',
             full_cycle_net=4000., recent20_cycle_net=2000.),
    ])


def test_dual_window_view_has_both_windows_and_ranks_in_one_row():
    from tools.etf_research import dual_window_rank as d
    out = d.build(_rank(), top_n=3)
    assert len(out) >= 3
    for col in ('63日中位往返', '近20日中位往返', '近期状态', '63日名次', '近20日名次'):
        assert col in out.columns, '缺列: ' + col
    # 长期第一 A 与近期第一 B 必须都在表里（并集，不是只取一个榜）
    codes = set(out['代码'])
    assert 'A' in codes and 'B' in codes
    a = out[out['代码'] == 'A'].iloc[0]
    assert a['63日中位往返'] == 33. and a['近20日中位往返'] == 6.
    b = out[out['代码'] == 'B'].iloc[0]
    assert b['63日中位往返'] == 15. and b['近20日中位往返'] == 31.
    # 持仓不进候选
    assert 'E' not in codes


def test_render_has_chinese_headers_and_no_bare_english_columns():
    from tools.etf_research import dual_window_rank as d
    text = d.render(_rank(), asof='2026-11-11', top_n=3)
    for word in ('63日中位往返', '近20日中位往返', '近期状态', '双窗口'):
        assert word in text, '缺表头/标题: ' + word
    for banned in ('median_full_cycles', 'recent_median_cycles', 'full_cycles', 'score'):
        assert banned not in text
    assert '|' in text and '---' in text, '须为 Markdown 表格'


def test_default_report_switch_is_on():
    """默认必须开启，防止以后被关掉又要 Master 来问。"""
    from tools.etf_research import engine
    assert engine.DUAL_WINDOW_REPORT is True
    assert engine.DUAL_WINDOW_FILENAME == 'dual-window-ranking.md'


def test_window_labels_are_disclosed():
    from tools.etf_research import dual_window_rank as d
    text = d.render(_rank(), asof='2026-11-11', top_n=3)
    assert '63' in text and '20' in text
    assert '多锚点' in text or '起点' in text


def test_production_entrypoints_import_clean():
    import importlib
    for name in ('confirmed_runtime', 'tools.etf_research.research',
                 'tools.etf_research.engine', 'tools.etf_research.dual_window_rank',
                 'tools.etf_research.entry_rank', 'tools.etf_research.weekly'):
        importlib.import_module(name)
