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


def regime20_label(daily, window=20, er_th=0.45, drift_th=-0.05):
    """近20日行情性质标签（2026-10-28 用户要求加进榜单）。

    判据（与 F 方案巡检同族，只用收盘价）：
    - 单边: 效率比 ER>=0.45（净位移占总行程比例高）
    - 阴跌: ER<0.35 且净位移<=-5%（低效率但方向向下——589720式磨跌）
    - 震荡: 其余
    返回 (label, net_pct, er)，None 数据不足时 label='数据不足'。
    """
    closes = daily['close'].tail(window + 1).reset_index(drop=True)
    if len(closes) < window:
        return '数据不足', None, None
    closes = closes.tail(window)
    net = closes.iloc[-1] / closes.iloc[0] - 1
    path = closes.diff().abs().sum()
    er = abs(closes.iloc[-1] - closes.iloc[0]) / path if path > 0 else 0.0
    if er >= er_th:
        label = '单边'
    elif er < 0.35 and net <= drift_th:
        label = '阴跌'
    else:
        label = '震荡'
    return label, round(net * 100, 1), round(er, 2)


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
            daily = daily_bars(path)
            judged = judge_entry(daily, asof=result['summary']['asof'])
        except Exception:
            excluded['error'] += 1
            continue
        regime, net20, er20 = regime20_label(daily)
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
            'regime20': regime,
            'net20_pct': net20,
            'er20': er20,
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


MIN_FULL_CYCLES = 10   # 63日高/低线：与 rank_entries 建仓门槛一致
MIN_RECENT20_CYCLES = 2  # 入选过滤线（用户定的及格线）：低于它不入池；空池兜底也用它


def median_r20_threshold(rows):
    """近20日高/低线：当期入选池 recent20_cycles 的中位数（2026-10-26 用户确认）。

    固定 ≥2 是入选过滤线，不能冒充效率分界线；固定绝对数会随市场节奏
    过期。动态中位线保证“✅双高”始终代表当期相对活跃的前一半。
    空池兜底：返回入选过滤线 2，禁止抛异常。
    """
    if not rows:
        return MIN_RECENT20_CYCLES
    values = sorted((r.get('recent20_cycles') or 0) for r in rows)
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


HEADER = '| 名次 | 代码 | 名称 | 资格 | 判断 | 63日往返 | 净差价 | 近20日往返 | 近20日形态 | 资金效率% |'
HEADER_SEP = '|---:|---|---|---|---|---:|---:|---:|---|---:|'


def window_matrix_label(row, r20_threshold):
    """双窗口判断矩阵标注（四档）。

    63日高/低线=MIN_FULL_CYCLES(10)不变；近20日高/低线=r20_threshold
    （由 median_r20_threshold(池) 给出，render_markdown 内部计算）。
    边界含：恰好等于线值算“高”。
    """
    full = row.get('full_cycles') or 0
    r20 = row.get('recent20_cycles') or 0
    full_high = full >= MIN_FULL_CYCLES
    r20_high = r20 >= r20_threshold
    if full_high and r20_high:
        return '✅双高'
    if full_high and not r20_high:
        return '⏳等信号'
    if not full_high and r20_high:
        return '⚠️脉冲'
    return '❌死水'


def render_markdown(report, top_n=10):
    """把 rank_entries 的 report 渲染成 markdown 表格。

    铁律：每个单元格的值只能取自 report['rows'] 里对应行的字段，
    禁止引入 rows 之外的任何数字。聊天层交付排名时必须粘贴本函数
    的输出，不允许手写表格（2026-10-23 手写 recent20 列编造数字的
    回归教训）。
    """
    rows = report['rows'][:top_n]
    threshold = median_r20_threshold(report['rows'])  # 线基于完整入选池，不是只看前N
    lines = [
        f"asof {report['asof']} 入选 {len(report['rows'])} 只 排除 {report['excluded']}",
        f"近20日高/低线={threshold:g}（当期入选池中位）",
        '',
        HEADER,
        HEADER_SEP,
    ]
    for row in rows:
        lines.append('| {} | {} | {} | {} | {} | {:g} | {:,.2f} | {:g} | {} | {:.2f} |'.format(
            row['rank'],
            row['code'],
            row['name'],
            row['label'],
            window_matrix_label(row, threshold),
            row['full_cycles'] or 0,
            row['full_cycle_net'] or 0.0,
            row['recent20_cycles'] or 0,
            row.get('regime20') or '',
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
