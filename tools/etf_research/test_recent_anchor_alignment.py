# -*- coding: utf-8 -*-
"""TDD：主榜必须同时具备 63 日与近 20 日多锚点中位往返次数 + 近期状态。

Master 2026-11-12 指出「etf 排序只有 63 天的，没有近期的」。
既有 multi_anchor_rank.py 已有 recent_state（日均密度口径），但只用于离线诊断，
主榜 ranking.csv 只有 recent20_cycles（单锚点）。本测试钉死主榜补齐。
"""
import pandas as pd
import pytest


def _pool_runs(engine):
    pool = pd.DataFrame([dict(code='sh589720', name='甲'),
                         dict(code='sh999999', name='乙')])
    runs = {}
    for c in pool.code:
        for w in engine.WINDOWS:
            runs[(c, w)] = dict(cycles=12, cycle_net=1000., avg_cost=20000.,
                                cycle_net_per_avg_cost_pct=5.)
    return pool, runs


def test_metrics_emits_recent_median_and_state():
    """主榜每行须带近20日多锚点中位、极差、有效窗口数与近期状态。"""
    from tools.etf_research import engine
    pool, runs = _pool_runs(engine)
    rank = engine.metrics(
        pool, runs, {c: [] for c in pool.code}, {},
        anchor_cycles={'sh589720': dict(median=21., spread=12., ok=5),
                       'sh999999': dict(median=30., spread=3., ok=5)},
        recent_anchor_cycles={'sh589720': dict(median=3., spread=2., ok=5),
                              'sh999999': dict(median=20., spread=1., ok=5)})
    for col in ('recent_median_cycles', 'recent_anchor_spread',
                'recent_anchor_windows_ok', 'recent_state'):
        assert col in rank.columns, '缺列: ' + col
    a = rank[rank.code == 'sh589720'].iloc[0]
    b = rank[rank.code == 'sh999999'].iloc[0]
    assert a['recent_median_cycles'] == 3.
    assert a['recent_state'] == '近期降温'      # 3/20 远低于 21/63
    assert b['recent_median_cycles'] == 20.
    assert b['recent_state'] == '近期升温'      # 20/20 远高于 30/63


def test_recent_state_uses_daily_density_not_absolute_counts():
    """两窗口长度不同，必须按日均密度比判据，不能拿绝对次数直接比。"""
    from tools.etf_research import engine
    # 63日中位 21（日均 0.333），近20日中位 7（日均 0.35）→ 平稳
    assert engine.recent_state(21., 7.) == '近期平稳'
    assert engine.recent_state(21., 12.) == '近期升温'
    assert engine.recent_state(21., 2.) == '近期降温'
    assert engine.recent_state(None, 5.) == '近期数据不足'


def test_recent_sort_key_declared():
    """近期视图排序键须显式声明，避免又只按 63 日排。"""
    from tools.etf_research import engine
    assert engine.RECENT_SORT_KEY == 'recent_median_cycles'
    assert engine.RECENT_SESSIONS == 20
    assert engine.LONG_SESSIONS == 63


def test_recent_anchor_shifts_do_not_exceed_data_need():
    """近20日 × 5 起点所需交易日 = 24，常量须与之匹配。"""
    from tools.etf_research import engine
    need = engine.RECENT_SESSIONS + max(0, -min(engine.ANCHOR_SHIFTS))
    assert need == 24
    assert len(engine.ANCHOR_SHIFTS) == 5


def test_production_entrypoints_import_clean():
    """守门：改动后生产链路导入不抛 NameError。"""
    import importlib
    for name in ('confirmed_runtime', 'tools.etf_research.research',
                 'tools.etf_research.engine', 'tools.etf_research.multi_anchor_rank',
                 'tools.etf_research.entry_rank', 'tools.etf_research.weekly'):
        importlib.import_module(name)
