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
    excluded = {'holding': 0, 'incomplete': 0, 'timing': 0, 'no_bars': 0, 'error': 0}
    for row in result['ranking']:
        code = row['code']
        if code in HOLDINGS or row.get('holding'):
            excluded['holding'] += 1
            continue
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
        if judged['verdict'] not in ADMITTED:
            excluded['timing'] += 1
            continue
        admitted.append({
            'code': code,
            'name': row.get('name') or '',
            'verdict': judged['verdict'],
            'label': judged['label'],
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
    table = pd.DataFrame(admitted)
    if not table.empty:
        table.insert(0, 'rank', range(1, len(table) + 1))
        table.to_csv(output_dir / 'entry-ranking.csv', index=False)
    return {'asof': result['summary']['asof'], 'rows': admitted, 'excluded': excluded, 'output': str(output_dir)}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='按往返次数排列可建仓或试错建仓的ETF')
    parser.add_argument('output_dir')
    args = parser.parse_args(argv)
    report = rank_entries(args.output_dir)
    print(f"asof {report['asof']} 入选 {len(report['rows'])} 只 排除 {report['excluded']}")
    for row in report['rows'][:20]:
        print(f"{row['code']} {row['name']} {row['label']} 往返{row['full_cycles']} 净差价{row['full_cycle_net']}")
    return report


if __name__ == '__main__':
    main()
