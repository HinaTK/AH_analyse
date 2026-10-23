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

    # 每个数字单元格必须原样出现在输出中（格式化后的字符串）
    assert '| sh588010 |' in text
    assert '| sh589720 |' in text
    assert '37' in text and '5,628.80' in text, 'full_cycles 与 full_cycle_net 来自 rows'
    assert '29' in text and '4,028.40' in text
    assert '12' in text, 'recent20_cycles=12 必须如实渲染（不是手写0或其他值）'
    assert '0' in text, 'recent20_cycles=0 也要如实渲染'
    # 标签
    assert '持仓' in text
    assert '试错' in text or '整仓' in text


def test_render_markdown_respects_top_n(tmp_path):
    rows = [
        {'code': f'sz1599{i:02d}', 'name': f'票{i}', 'has_all_four_windows': True,
         'full_cycles': float(30 - i), 'full_cycle_net': 1000.0 - i, 'full_cycle_net_per_avg_cost_pct': 5.0,
         'recent20_cycles': 1.0, 'recent20_cycle_net_per_avg_cost_pct': 0.5}
        for i in range(15)
    ]
    output = make_output(tmp_path, rows, holdings=set())
    report = entry_rank.rank_entries(output)
    text = entry_rank.render_markdown(report, top_n=10)
    data_lines = [ln for ln in text.splitlines() if ln.startswith('|') and '---' not in ln and '名次' not in ln]
    assert len(data_lines) == 10, f'top_n=10 只渲染10行, got {len(data_lines)}'
