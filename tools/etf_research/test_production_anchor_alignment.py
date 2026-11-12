# -*- coding: utf-8 -*-
"""TDD：研究榜必须用生产对齐口径 + 多锚点中位往返次数（2026-11-12 Master 授权）。

三个口径断裂：
  1. 研究引擎默认格距 2% vs 生产 GAP 1.5%
  2. 单锚点往返次数是 5 起点里的下界，不该直接进最终榜单
  3. 轮换排序与资格判据仍读单锚点值
本测试钉死：单一真源常量、中位列、排序键、守门导入。
"""
from decimal import Decimal

import pytest


def test_default_gap_single_source_matches_production():
    """研究引擎/CLI/锚点诊断的默认格距必须等于生产 GAP。"""
    from confirmed_runtime import GAP
    from tools.etf_research import research, engine, anchor_sensitivity as a

    assert Decimal(str(research.DEFAULT_GAP)) == GAP, '研究 CLI 默认格距须与生产一致'
    from tools.etf_research.engine import run_research
    import inspect
    assert Decimal(str(inspect.signature(run_research).parameters['gap'].default)) == GAP
    assert Decimal(str(a.GAP)) == GAP, '多锚点诊断格距须与主引擎一致'


def test_metrics_emits_median_full_cycles_and_spread():
    """ranking 每行须带多锚点中位往返次数与极差；缺省时显式为 None 而非静默丢弃。"""
    from tools.etf_research import engine
    import pandas as pd
    import numpy as np

    pool = pd.DataFrame([dict(code='sh589720', name='甲'),
                         dict(code='sh999999', name='乙')])
    runs = {}
    for c in pool.code:
        for w in engine.WINDOWS:
            runs[(c, w)] = dict(cycles=12, cycle_net=1000., avg_cost=20000.,
                                cycle_net_per_avg_cost_pct=5., max_corr=0.5)
    holds = {c: [] for c in pool.code}
    rank = engine.metrics(pool, runs, holds, {},
                          anchor_cycles={'sh589720': dict(median=21., spread=12., ok=5),
                                         'sh999999': dict(median=None, spread=None, ok=0)})
    assert 'median_full_cycles' in rank.columns
    assert 'anchor_spread' in rank.columns
    assert 'anchor_windows_ok' in rank.columns
    row = rank[rank.code == 'sh589720'].iloc[0]
    assert row['median_full_cycles'] == 21.
    assert row['anchor_spread'] == 12.
    missing = rank[rank.code == 'sh999999'].iloc[0]
    assert missing['median_full_cycles'] is None or np.isnan(missing['median_full_cycles'])


def test_rotation_and_qualification_use_median_not_single_anchor():
    """轮换排序键与资格判据须用中位往返次数，不再用单锚点下界。"""
    from tools.etf_research import engine

    assert engine.ROTATION_SORT_KEY == 'median_full_cycles'
    assert 'median_full_cycles' in engine.QUALIFICATION_CYCLE_KEY
    assert engine.QUALIFICATION_CYCLE_KEY == 'median_full_cycles'


def test_production_entrypoints_import_clean():
    """守门：改动后生产链路导入不抛 NameError（模块级常量定义先于引用）。"""
    import importlib
    for name in ('confirmed_runtime', 'tools.etf_research.research',
                 'tools.etf_research.engine', 'tools.etf_research.anchor_sensitivity',
                 'tools.etf_research.multi_anchor_rank', 'tools.etf_research.entry_rank'):
        importlib.import_module(name)
