# -*- coding: utf-8 -*-
"""双窗口榜单：63 日与近 20 日多锚点中位往返次数在同一张表同时显示。

2026-11-12 Master「后面 60 日跟 20 日都要显示出来吧，不要等我问题」——
固化为生产产物，由 engine.run_research 默认写出 dual-window-ranking.md，
并进入 result.json，不再依赖 .cache 临时渲染脚本或人工追问。

边界：展示层模块，不改排名判据、不改账本/持仓/参数/任务状态。
"""
from pathlib import Path

import pandas as pd

LONG_LABEL = '63日中位往返'
RECENT_LABEL = '近20日中位往返'
TOP_N = 10
COLUMNS = ['名次', '代码', '名称', LONG_LABEL, '63日名次', RECENT_LABEL,
           '近20日名次', '近期状态', '63日净差价']


def _fmt(v, digits=0):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '不可用'
    try:
        return ('%.*f' % (digits, float(v))).rstrip('0').rstrip('.') if digits else '%g' % float(v)
    except (TypeError, ValueError):
        return '不可用'


def build(rank, top_n=TOP_N):
    """取「63日中位前 N」与「近20日中位前 N」的并集，一行同时给两窗口数值与名次。

    只取四窗口齐全、非持仓的候选；两榜名次各自独立，未进前 N 记 None。
    """
    eligible = rank[(rank.has_all_four_windows == True) & (rank.holding == False)].copy()
    long_col = 'median_full_cycles'
    recent_col = 'recent_median_cycles'
    if long_col not in eligible.columns:
        eligible[long_col] = pd.NA
    if recent_col not in eligible.columns:
        eligible[recent_col] = pd.NA

    long_sorted = eligible[eligible[long_col].notna()].sort_values(
        [long_col, 'full_cycle_net', 'code'], ascending=[False, False, True])
    recent_sorted = eligible[eligible[recent_col].notna()].sort_values(
        [recent_col, 'recent20_cycle_net', 'code'], ascending=[False, False, True])
    long_rank = {c: i for i, c in enumerate(long_sorted.code, 1)}
    recent_rank = {c: i for i, c in enumerate(recent_sorted.code, 1)}

    wanted = list(dict.fromkeys(list(long_sorted.code[:top_n]) + list(recent_sorted.code[:top_n])))
    rows = []
    for c in wanted:
        x = eligible[eligible.code == c].iloc[0]
        rows.append(dict(
            **{'名次': None, '代码': c, '名称': x.get('name', ''),
               LONG_LABEL: x.get(long_col), '63日名次': long_rank.get(c),
               RECENT_LABEL: x.get(recent_col), '近20日名次': recent_rank.get(c),
               '近期状态': x.get('recent_state', '近期数据不足'),
               '63日净差价': x.get('full_cycle_net')}))
    df = pd.DataFrame(rows, columns=COLUMNS)
    # 展示次序：按 63 日中位降序（缺失排末尾），名次列仅作展示编号
    df['_k'] = pd.to_numeric(df[LONG_LABEL], errors='coerce').fillna(-1)
    df = df.sort_values(['_k', '代码'], ascending=[False, True]).drop(columns=['_k']).reset_index(drop=True)
    df['名次'] = range(1, len(df) + 1)
    return df


def render(rank, asof, top_n=TOP_N):
    """Markdown 表格（中文表头）。飞书内直接以表格正文输出，不包代码块。"""
    df = build(rank, top_n=top_n)
    lines = [
        '【ETF 双窗口轮换榜·63日与近20日同时显示】',
        f'数据截止 {asof}｜格距 1.5%（与生产一致）｜两窗口均为多锚点 5 起点的中位往返次数（起点平移 0/-1/-2/-3/-4 交易日）',
        '读法：63 日看稳定性、近 20 日看当下活跃度；两窗口长度不同，绝对次数不可直接比，以「近期状态」的日均密度判据为准。',
        f'取「63日中位前{top_n}」与「近20日中位前{top_n}」的并集，按 63 日中位降序展示；名次列为各榜独立名次。',
        '',
        '| ' + ' | '.join(COLUMNS) + ' |',
        '| ' + ' | '.join(['---'] * len(COLUMNS)) + ' |',
    ]
    for x in df.itertuples(index=False):
        d = dict(zip(COLUMNS, x))
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            d['名次'], d['代码'], d['名称'], _fmt(d[LONG_LABEL]),
            d['63日名次'] if d['63日名次'] is not None else '—',
            _fmt(d[RECENT_LABEL]),
            d['近20日名次'] if d['近20日名次'] is not None else '—',
            d['近期状态'], _fmt(d['63日净差价'], 1)))
    lines += ['', '说明：数值来自 5 分钟模拟（最低佣金 1 元、T+1、滑点 0.05%），非真实成交；',
              '「不可用」表示该窗口有效起点不足，未静默丢弃；历史 2% 单锚点口径榜单与本期不可直接比名次。']
    return '\n'.join(lines)


def write_report(rank, out, asof, top_n=TOP_N):
    """由真实入口调用，默认写出，不依赖人工追问。"""
    p = Path(out) / 'dual-window-ranking.md'
    p.write_text(render(rank, asof, top_n=top_n), encoding='utf-8')
    return p
