"""TDD for entry_rank: holdings stay visible with their rank, not dropped.

User rule 2026-10-23: 排名不排除持仓，需要知道持仓排名第几。
So rank_entries must (1) include holding rows in the same ranked table and
(2) tag them so they can be told apart from fresh entry candidates.
"""
from pathlib import Path
import json

import pandas as pd

from tools.etf_research import entry_rank
from tools.etf_research.entry_timing import judge_entry


def make_output(tmp_path, rows, holdings):
    """Build a minimal research output dir: result.json + bars csvs."""
    bars_dir = tmp_path / 'bars'
    bars_dir.mkdir()
    n = 120
    # business days ending exactly on the asof date 2026-10-23
    dates = pd.bdate_range(end='2026-10-23', periods=n).strftime('%Y-%m-%d')
    for row in rows:
        code = row['code']
        closes = [10 * 1.003 ** i for i in range(n)]
        lows = [close * 0.99 for close in closes]
        lows[-1] = sum(closes[-20:]) / 20
        frame = pd.DataFrame({
            'time': [f'{date} 10:00' for date in dates],
            'open': closes,
            'high': [close * 1.01 for close in closes],
            'low': lows,
            'close': closes,
        })
        frame.to_csv(bars_dir / f'{code}-m5.csv', index=False)
    result = {
        'summary': {'asof': '2026-10-23'},
        'ranking': [dict(row, holding=row['code'] in holdings) for row in rows],
    }
    (tmp_path / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    return tmp_path


def test_holdings_are_ranked_and_tagged_not_excluded(tmp_path):
    (entry_rank.HOLDINGS if hasattr(entry_rank, 'HOLDINGS') else None)
    rows = [
        {'code': 'sh589720', 'name': '持仓A', 'has_all_four_windows': True, 'full_cycles': 29.0, 'full_cycle_net': 4028.4, 'full_cycle_net_per_avg_cost_pct': 10.0, 'recent20_cycles': 5.0, 'recent20_cycle_net_per_avg_cost_pct': 2.0},
        {'code': 'sz159363', 'name': '持仓B', 'has_all_four_windows': True, 'full_cycles': 21.0, 'full_cycle_net': 3408.7, 'full_cycle_net_per_avg_cost_pct': 8.0, 'recent20_cycles': 4.0, 'recent20_cycle_net_per_avg_cost_pct': 1.5},
        {'code': 'sh588010', 'name': '新候选', 'has_all_four_windows': True, 'full_cycles': 37.0, 'full_cycle_net': 5628.8, 'full_cycle_net_per_avg_cost_pct': 12.0, 'recent20_cycles': 6.0, 'recent20_cycle_net_per_avg_cost_pct': 2.5},
    ]
    output = make_output(tmp_path, rows, holdings={'sh589720', 'sz159363'})
    report = entry_rank.rank_entries(output)
    codes = [row['code'] for row in report['rows']]
    assert 'sh589720' in codes, '持仓必须保留在榜内'
    assert 'sz159363' in codes, '持仓必须保留在榜内'
    ranked = {row['code']: row for row in report['rows']}
    assert ranked['sh588010']['rank'] == 1
    assert ranked['sh589720']['rank'] == 2, '持仓按往返次数正常参与排名'
    assert ranked['sz159363']['rank'] == 3
    assert ranked['sh589720']['holding'] is True
    assert ranked['sh589720']['label'] == '持仓'
    assert ranked['sh588010']['holding'] is False
    assert report['excluded'].get('holding') == 0, '持仓不再被计入排除'


def test_holding_without_entry_verdict_still_shows(tmp_path):
    """持仓即使时机判定不满足建仓资格也要展示——它已在场内，位置判定只是参考。"""
    rows = [
        {'code': 'sh589720', 'name': '持仓A', 'has_all_four_windows': True, 'full_cycles': 29.0, 'full_cycle_net': 4028.4, 'full_cycle_net_per_avg_cost_pct': 10.0, 'recent20_cycles': 5.0, 'recent20_cycle_net_per_avg_cost_pct': 2.0},
        {'code': 'sh588010', 'name': '新候选', 'has_all_four_windows': True, 'full_cycles': 37.0, 'full_cycle_net': 5628.8, 'full_cycle_net_per_avg_cost_pct': 12.0, 'recent20_cycles': 6.0, 'recent20_cycle_net_per_avg_cost_pct': 2.5},
    ]
    output = make_output(tmp_path, rows, holdings={'sh589720'})
    # 589720 现价远低于60日线 → judge_entry 会给 probe_only，仍应入榜
    report = entry_rank.rank_entries(output)
    codes = [row['code'] for row in report['rows']]
    assert 'sh589720' in codes


def test_candidates_below_two_recent20_cycles_are_excluded(tmp_path):
    """近20日往返 <2 的候选不得入榜（2026-10-23 用户新增限制）。

    历史次数高但近20日零成交的票（如科创100系列）进不了排行。
    持仓不受此限——持仓要留在榜里可见（由 is_holding 豁免）。
    """
    rows = [
        {'code': 'sh588010', 'name': '零活跃候选', 'has_all_four_windows': True, 'full_cycles': 37.0, 'full_cycle_net': 5628.8, 'full_cycle_net_per_avg_cost_pct': 18.5, 'recent20_cycles': 0.0, 'recent20_cycle_net_per_avg_cost_pct': 0.0},
        {'code': 'sz159615', 'name': '一活跃候选', 'has_all_four_windows': True, 'full_cycles': 9.0, 'full_cycle_net': 1020.8, 'full_cycle_net_per_avg_cost_pct': 6.26, 'recent20_cycles': 1.0, 'recent20_cycle_net_per_avg_cost_pct': 0.5},
        {'code': 'sz159363', 'name': '持仓零活跃', 'has_all_four_windows': True, 'full_cycles': 21.0, 'full_cycle_net': 3408.7, 'full_cycle_net_per_avg_cost_pct': 8.0, 'recent20_cycles': 0.0, 'recent20_cycle_net_per_avg_cost_pct': 0.0},
    ]
    output = make_output(tmp_path, rows, holdings={'sz159363'})
    report = entry_rank.rank_entries(output)
    codes = {row['code'] for row in report['rows']}
    assert 'sh588010' not in codes, '近20日0次的候选必须出榜'
    assert 'sz159615' not in codes, '近20日1次的候选必须出榜（少于2不含2）'
    assert 'sz159363' in codes, '持仓豁免近20日门槛，必须留在榜里'
    assert report['excluded'].get('recent20') == 2, '出榜数计入 recent20 排除项'


def test_candidate_with_exactly_two_recent20_cycles_stays(tmp_path):
    """边界：近20日恰好2次（含2）——门槛是"少于2次不进入"，2次要入。"""
    rows = [
        {'code': 'sh588760', 'name': '两次候选', 'has_all_four_windows': True, 'full_cycles': 26.0, 'full_cycle_net': 3423.6, 'full_cycle_net_per_avg_cost_pct': 8.39, 'recent20_cycles': 2.0, 'recent20_cycle_net_per_avg_cost_pct': 0.53},
    ]
    output = make_output(tmp_path, rows, holdings=set())
    report = entry_rank.rank_entries(output)
    assert 'sh588760' in {row['code'] for row in report['rows']}, '恰好2次必须入榜'


def test_rank_entries_writes_csv_with_holding_column(tmp_path):
    rows = [
        {'code': 'sh589720', 'name': '持仓A', 'has_all_four_windows': True, 'full_cycles': 29.0, 'full_cycle_net': 4028.4, 'full_cycle_net_per_avg_cost_pct': 10.0, 'recent20_cycles': 5.0, 'recent20_cycle_net_per_avg_cost_pct': 2.0},
    ]
    output = make_output(tmp_path, rows, holdings={'sh589720'})
    entry_rank.rank_entries(output)
    table = pd.read_csv(output / 'entry-ranking.csv')
    assert 'holding' in table.columns
    assert bool(table.loc[table['code'] == 'sh589720', 'holding'].iloc[0])


def test_render_markdown_contains_only_row_values(tmp_path):
    """渲染表格的每个数字必须来自 rows 数据本身——禁止聊天层手写数字。

    回归背景 2026-10-23：助手在交付 TOP10 时手写"近20日往返"列，
    编造了 CSV 中不存在的数字。本测试规定：render_markdown() 的输出
    只能由 report['rows'] 逐格生成，任何单元格都能在 rows 里找到出处。
    """
    rows = [
        {'code': 'sh588010', 'name': '候选X', 'has_all_four_windows': True, 'full_cycles': 37.0, 'full_cycle_net': 5628.8, 'full_cycle_net_per_avg_cost_pct': 18.5, 'recent20_cycles': 0.0, 'recent20_cycle_net_per_avg_cost_pct': 0.0},
        {'code': 'sh589720', 'name': '持仓A', 'has_all_four_windows': True, 'full_cycles': 29.0, 'full_cycle_net': 4028.4, 'full_cycle_net_per_avg_cost_pct': 10.6, 'recent20_cycles': 12.0, 'recent20_cycle_net_per_avg_cost_pct': 3.9},
    ]
    output = make_output(tmp_path, rows, holdings={'sh589720'})
    report = entry_rank.rank_entries(output)
    text = entry_rank.render_markdown(report, top_n=10)
    # sh588010 是近20日0次的候选，按 2026-10-23 门槛出榜；
    # 渲染只对 sh589720（持仓豁免）一行，数字仍须逐格来自 rows
    assert '| sh588010 |' not in text, '近20日<2 的候选已出榜'
    assert '| sh589720 |' in text
    assert '29' in text and '4,028.40' in text
    assert '12' in text, 'recent20_cycles=12 必须如实渲染（不是手写0或其他值）'
    assert '持仓' in text


def test_render_markdown_renders_every_row_cell_from_rows(tmp_path):
    """候选行也全量入榜时（近20日≥2），每格数字来自 rows。"""
    rows = [
        {'code': 'sh588010', 'name': '候选X', 'has_all_four_windows': True, 'full_cycles': 37.0, 'full_cycle_net': 5628.8, 'full_cycle_net_per_avg_cost_pct': 18.5, 'recent20_cycles': 8.0, 'recent20_cycle_net_per_avg_cost_pct': 3.0},
        {'code': 'sh589720', 'name': '持仓A', 'has_all_four_windows': True, 'full_cycles': 29.0, 'full_cycle_net': 4028.4, 'full_cycle_net_per_avg_cost_pct': 10.6, 'recent20_cycles': 12.0, 'recent20_cycle_net_per_avg_cost_pct': 3.9},
    ]
    output = make_output(tmp_path, rows, holdings={'sh589720'})
    report = entry_rank.rank_entries(output)
    text = entry_rank.render_markdown(report, top_n=10)
    assert '| sh588010 |' in text
    assert '| sh589720 |' in text
    assert '37' in text and '5,628.80' in text
    assert '29' in text and '4,028.40' in text
    assert '8' in text, 'recent20_cycles=8 如实渲染'
    assert '12' in text


def test_render_markdown_respects_top_n(tmp_path):
    rows = [
        {'code': f'sz1599{i:02d}', 'name': f'票{i}', 'has_all_four_windows': True,
         'full_cycles': float(30 - i), 'full_cycle_net': 1000.0 - i, 'full_cycle_net_per_avg_cost_pct': 5.0,
         'recent20_cycles': float(5 + i), 'recent20_cycle_net_per_avg_cost_pct': 0.5}
        for i in range(15)
    ]
    output = make_output(tmp_path, rows, holdings=set())
    report = entry_rank.rank_entries(output)
    text = entry_rank.render_markdown(report, top_n=10)
    data_lines = [ln for ln in text.splitlines() if ln.startswith('|') and '---' not in ln and '名次' not in ln]
    assert len(data_lines) == 10, f'top_n=10 只渲染10行, got {len(data_lines)}'


def test_regime_label_computed_from_last20_bars(tmp_path):
    """2026-10-28 用户要求：榜单加"近20日行情性质"列（震荡/阴跌/单边）。

    判据（与 F 方案巡检同族，用 20 日窗口收盘价）：
    - 单边: ER>=0.45（效率比高）
    - 阴跌: ER<0.35 且净位移<=-5%（低效率但方向向下）
    - 震荡: 其余
    数字来自 bars 本身逐格计算，禁止手写。
    """
    rows = [
        {'code': 'sh589720', 'name': '持仓A', 'has_all_four_windows': True, 'full_cycles': 29.0, 'full_cycle_net': 4028.4, 'full_cycle_net_per_avg_cost_pct': 10.6, 'recent20_cycles': 12.0, 'recent20_cycle_net_per_avg_cost_pct': 3.9},
    ]
    output = make_output(tmp_path, rows, holdings={'sh589720'})
    report = entry_rank.rank_entries(output)
    # 夹具: 缓慢单调爬升 (1.003^i) → ER≈1.0 → 判'单边' (判定器正确识别单调路径)
    row = report['rows'][0]
    assert 'regime20' in row, 'rank_entries 必须为每行计算 regime20'
    assert row['regime20'] == '单边', '单调爬升 ER≈1, 应判单边'
    assert 'net20_pct' in row and 'er20' in row, '判定依据数字必须入 rows (禁止手写标签)'

    # 真震荡夹具: 上下交替 → ER 低 → 震荡
    daily = pd.DataFrame({'close': [10.0 + (0.3 if i % 2 == 0 else -0.3) for i in range(25)]})
    label, _net, _er = entry_rank.regime20_label(daily)
    assert label == '震荡'

    # 阴跌夹具: 低效率慢跌
    daily = pd.DataFrame({'close': [10.0 - 0.08 * i + (0.15 if i % 3 == 0 else -0.1) for i in range(25)]})
    label, net, er = entry_rank.regime20_label(daily)
    assert label == '阴跌', f'慢跌夹具应判阴跌, got {label} net={net} er={er}'


def test_render_markdown_contains_regime_column(tmp_path):
    """渲染表头含"近20日形态"列，每行标签逐格来自 rows['regime20']。"""
    rows = [
        {'code': 'sh589720', 'name': '持仓A', 'has_all_four_windows': True, 'full_cycles': 29.0, 'full_cycle_net': 4028.4, 'full_cycle_net_per_avg_cost_pct': 10.6, 'recent20_cycles': 12.0, 'recent20_cycle_net_per_avg_cost_pct': 3.9},
    ]
    output = make_output(tmp_path, rows, holdings={'sh589720'})
    report = entry_rank.rank_entries(output)
    text = entry_rank.render_markdown(report, top_n=10)
    assert '近20日形态' in text, '表头必须含近20日形态列'
    assert '单边' in text, '持仓行渲染其 regime20 标签(单调爬升夹具=单边)'
