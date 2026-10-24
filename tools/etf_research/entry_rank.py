"""Rank complete grid runs by round trips, keeping only entry-eligible names.

可建仓 is verdict full (可以整仓). 试错建仓 is verdict probe_only (仅试错仓).
Current holdings are already owned, so they are not entry candidates.
"""
import json
from pathlib import Path

import pandas as pd

from .entry_timing import judge_entry
from .research import HOLDINGS

ADMITTED = {'full': '可以整仓', 'probe_only': '仅试错仓'}
MIN_RECENT20_CYCLES = 2


def daily_bars(path):
    bars = pd.read_csv(path)
    bars['date'] = bars['time'].astype(str).str.slice(0, 10)
    for column in ('open', 'high', 'low', 'close'):
        bars[column] = pd.to_numeric(bars[column], errors='raise')
    return bars.groupby('date', as_index=False).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'))


def rank_entries(output_dir):
    output_dir = Path(output_dir)
    result = json.loads((output_dir / 'result.json').read_text(encoding='utf-8'))
    admitted = []
    excluded = {'holding': 0, 'incomplete': 0, 'timing': 0, 'recent20': 0, 'no_bars': 0, 'error': 0}
    for row in result['ranking']:
        code = row['code']
        is_holding = code in HOLDINGS or row.get('holding')
        if not row.get('has_all_four_windows'):
            excluded['incomplete'] += 1
            continue
        path = output_dir / 'bars' / f'{code}-m5.csv'
        if not path.exists():
            excluded['no_bars'] += 1
            continue
        try:
            judged = judge_entry(daily_bars(path), asof=result['summary']['asof'])
        except Exception:
            excluded['error'] += 1
            continue
        if judged['verdict'] not in ADMITTED and not is_holding:
            excluded['timing'] += 1
            continue
        if (row.get('recent20_cycles') or 0) < MIN_RECENT20_CYCLES and not is_holding:
            excluded['recent20'] += 1
            continue
        admitted.append({
            'code': code,
            'name': row.get('name') or '',
            'holding': is_holding,
            'verdict': judged['verdict'],
            'label': '持仓' if is_holding else judged['label'],
            'full_cycles': row.get('full_cycles'),
            'full_cycle_net': row.get('full_cycle_net'),
            'full_cycle_net_per_avg_cost_pct': row.get('full_cycle_net_per_avg_cost_pct'),
            'recent20_cycles': row.get('recent20_cycles'),
            'recent20_cycle_net_per_avg_cost_pct': row.get('recent20_cycle_net_per_avg_cost_pct'),
            'close': judged['close'],
            'exit_price': judged['exit_price'],
            'reason': '；'.join(judged['reasons']),
        })
    admitted.sort(key=lambda item: (
        -(item['full_cycles'] or 0),
        -(item['full_cycle_net'] or 0),
        -(item['full_cycle_net_per_avg_cost_pct'] or 0),
        item['code'],
    ))
    for index, item in enumerate(admitted, 1):
        item['rank'] = index
    table = pd.DataFrame(admitted)
    if not table.empty:
        table.to_csv(output_dir / 'entry-ranking.csv', index=False)
    return {'asof': result['summary']['asof'], 'rows': admitted, 'excluded': excluded, 'output': str(output_dir)}


def render_markdown(report, top_n=10):
    """把 rank_entries 的 report 渲染成 markdown 表格。

    铁律：每个单元格的值只能取自 report['rows'] 里对应行的字段，
    禁止引入 rows 之外的任何数字。聊天层交付排名时必须粘贴本函数
    的输出，不允许手写表格（2026-10-23 手写 recent20 列编造数字的
    回归教训）。
    """
    rows = report['rows'][:top_n]
    lines = [
        f"asof {report['asof']} 入选 {len(report['rows'])} 只 排除 {report['excluded']}",
        '',
        '| 名次 | 代码 | 名称 | 资格 | 63日往返 | 净差价 | 近20日往返 | 资金效率% |',
        '|---:|---|---|---|---:|---:|---:|---:|',
    ]
    for row in rows:
        lines.append('| {} | {} | {} | {} | {:g} | {:,.2f} | {:g} | {:.2f} |'.format(
            row['rank'],
            row['code'],
            row['name'],
            row['label'],
            row['full_cycles'] or 0,
            row['full_cycle_net'] or 0.0,
            row['recent20_cycles'] or 0,
            row['full_cycle_net_per_avg_cost_pct'] or 0.0,
        ))
    return '\n'.join(lines)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='按往返次数排列可建仓或试错建仓的ETF')
    parser.add_argument('output_dir')
    parser.add_argument('--render', action='store_true', help='输出可粘贴的 markdown 表格（数字逐格来自数据，禁止手写）')
    args = parser.parse_args(argv)
    report = rank_entries(args.output_dir)
    if args.render:
        print(render_markdown(report))
        return report
    print(f"asof {report['asof']} 入选 {len(report['rows'])} 只 排除 {report['excluded']}")
    for row in report['rows'][:20]:
        print(f"{row['code']} {row['name']} {row['label']} 往返{row['full_cycles']} 净差价{row['full_cycle_net']}")
    return report


if __name__ == '__main__':
    main()
