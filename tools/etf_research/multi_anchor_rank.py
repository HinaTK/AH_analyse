# -*- coding: utf-8 -*-
"""多锚点稳健排名：把 5 个起点的模拟结果真正用于「重排前 20」。

2026-11-06 Master 指出「方案落实了却不用」——此前只做了单只标的的观察报告，
最终交付的排行榜仍用单锚点口径。本模块补上缺失的一环：对本期可建仓榜入选池
的每只标的跑多个起点窗口，用「稳健往返次数」（默认中位数）重新排序，给出
新旧名次对照，让排名不再被单一首根锚价绑架。

边界：本模块提供独立的多锚点重排报告；**主榜已接入多锚点中位往返次数**（2026-11-12 Master 授权）。
本模块自身仍不叠加市况门控、
不重算综合评分、不推进连续周状态、不改动账本/持仓/任务状态；同窗模拟非真实成交。
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

import pandas as pd

from . import anchor_sensitivity as a
from .entry_rank import rank_entries
from .rotation_top2 import major_theme

REPO = Path(r'D:\Code\AH_analyse')
DEFAULT_DIR = REPO / '.cache' / 'grid-home' / 'cache' / 'grid-research' / '20261106-152501-510377'
SHIFTS = (0, -1, -2, -3, -4)
SESSIONS = 63
RECENT_SESSIONS = 20


def _key_label(key):
    return {'mean_cycles': '多起点平均往返次数',
            'recent_median': '近20日多起点中位往返次数'}.get(key, '多起点中位往返次数')


def recent_state(long_median, recent_median):
    """近期状态：比较「日均往返密度」而非绝对次数（窗口长度不同，绝对值不可比）。

    长期日均 = 63日中位往返 / 63；近期日均 = 近20日中位往返 / 20。
    """
    if long_median is None or recent_median is None or long_median <= 0:
        return '近期数据不足'
    ratio = (recent_median / RECENT_SESSIONS) / (long_median / SESSIONS)
    if ratio > 1.3:
        return '近期升温'
    if ratio < 0.7:
        return '近期降温'
    return '近期平稳'


def rank_stable(rows, key='median_cycles'):
    """按稳健值降序重排；失败标的排末尾且不分配稳健名次（不静默丢弃）。"""
    good = [r for r in rows if r.get(key) is not None]
    bad = [r for r in rows if r.get(key) is None]
    good.sort(key=lambda r: (-r[key], -(r.get('median_net') or 0), r['code']))
    for i, r in enumerate(good, 1):
        r['stable_rank'] = i
    for r in bad:
        r['stable_rank'] = None
    return good + bad


def cap_display(rows, limit=5):
    """每题材最多展示 limit 只（名称粗分）；只影响展示，不改稳健名次。"""
    used, shown = {}, []
    for r in rows:
        theme = major_theme(r.get('name', '')) or ('未识别:' + r['code'])
        n = used.get(theme, 0)
        if n >= limit:
            continue
        used[theme] = n + 1
        shown.append(r)
    return dict(rows=shown, dropped=len(rows) - len(shown), limit=limit)


def render(rows, asof, key='median_cycles', top_n=20, cap=5):
    """Markdown 表格（中文表头）——飞书内直接以表格正文输出，禁止包代码块。"""
    label = _key_label(key)
    shown = cap_display(rows, limit=cap)
    view = [r for r in shown['rows'] if r.get('stable_rank') is not None][:top_n]
    failed = [r for r in rows if r.get('stable_rank') is None]
    lines = ['【多锚点稳健排名·前20（离线诊断口径，不替换生产排行榜）】',
             f"数据截止 {asof}｜排序依据：{label}｜起点平移 {', '.join(str(s) for s in SHIFTS)} 个交易日｜"
             f"长期窗口 {SESSIONS} 日 + 近期窗口 {RECENT_SESSIONS} 日｜"
             f"每题材最多展示 {cap} 只（跳过 {shown['dropped']} 只，名次不受影响）",
             '',
             f'| 稳健名次 | 原名次 | 名次变化 | 代码 | 名称 | {label} | 单锚点往返次数 | '
             '近20日中位往返次数 | 近期状态 | 长期极差 | 有效窗口 | 备注 |',
             '|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|---|']
    for r in view:
        delta = r['source_rank'] - r['stable_rank']
        delta_text = f"↑{delta}" if delta > 0 else (f"↓{-delta}" if delta < 0 else '持平')
        recent = r.get('recent_median')
        state = r.get('recent_state') or recent_state(r.get('median_cycles'), recent)
        spread = r.get('spread')
        single = r.get('single_cycles')
        lines.append(
            f"| {r['stable_rank']} | {r['source_rank']} | {delta_text} | {r['code']} | "
            f"{r.get('name', '')} | {r[key]:g} | "
            f"{'不可用' if single is None else f'{single:g}'} | "
            f"{'不可用' if recent is None else f'{recent:g}'} | {state} | "
            f"{'不可用' if spread is None else f'{spread:g}'} | "
            f"{r['runs_ok']}/{r['runs_total']} | {'正常' if not r['errors'] else '⚠️ 部分窗口失败'} |")
    if failed:
        lines += ['', f'⚠️ 未能参与排序 {len(failed)} 只（模拟失败或行情不足），不静默丢弃：']
        for r in failed[:8]:
            lines.append(f"　{r['code']} {r.get('name', '')}｜原名次 {r['source_rank']}｜"
                         f"原因：{'；'.join(str(e) for e in r['errors'][:2]) or '稳健值不可用'}")
        if len(failed) > 8:
            lines.append(f"　……另有 {len(failed) - 8} 只，详见完整数据文件。")
    lines += ['',
              '读法：稳健名次按「多个窗口起点各跑一次同参数网格模拟」的中位数（或平均值）重排；'
              '名次变化为相对原单锚点榜单的位次移动；长期极差越大说明排名越依赖窗口首根。',
              '近期判断：另用近 20 日窗口跑同样 5 个起点，「近期状态」比较日均往返密度'
              '（近20日中位/20 对 63日中位/63），>1.3 倍记升温、<0.7 倍记降温，'
              '用于识别「长期排名高但近期已熄火」与「长期一般但近期转活跃」；'
              '两个窗口长度不同，绝对次数不可直接比。',
              '',
              '口径说明：本表**不叠加市况门控**（生产排名带门控），绝对值与生产不可直接比；'
              '**不替换生产口径**、不重算综合评分、不推进连续周状态、不改动账本/持仓/任务状态；'
              '同窗模拟非真实成交，不构成操作依据。']
    return '\n'.join(lines)


def build(research_dir, sessions=SESSIONS, shifts=SHIFTS, limit=None,
          recent_sessions=RECENT_SESSIONS):
    """读本期研究目录：可建仓榜入选池 + 逐只 bars 跑多起点模拟。"""
    d = Path(research_dir)
    report = rank_entries(d)
    pool = report['rows']
    if limit:
        pool = pool[:limit]
    out = []
    for r in pool:
        code = r['code']
        rec = dict(code=code, name=r.get('name', ''), source_rank=r['rank'],
                   single_cycles=r.get('full_cycles'), label=r.get('label', ''),
                   regime20=r.get('regime20', ''), median_cycles=None,
                   mean_cycles=None, median_net=None, spread=None, pstdev=None,
                   recent_median=None, recent_spread=None, recent_state='近期数据不足',
                   runs_ok=0, runs_total=len(shifts), errors=[])
        path = d / 'bars' / f'{code}-m5.csv'
        if not path.exists():
            rec['errors'].append('行情文件缺失')
            out.append(rec)
            continue
        try:
            diag = a.diagnose(pd.read_csv(path), sessions=sessions, shifts=shifts)
        except Exception as exc:
            rec['errors'].append(f'{type(exc).__name__}: {exc}')
            out.append(rec)
            continue
        cycles = [x['cycles'] for x in diag['runs'] if x['cycles'] is not None]
        nets = [x['cycle_net'] for x in diag['runs'] if x['cycle_net'] is not None]
        rec['runs_ok'] = len(cycles)
        rec['spread'] = diag['spread']
        rec['pstdev'] = diag['pstdev']
        rec['errors'] = [str(x['error']) for x in diag['runs'] if x['error']]
        if cycles:
            rec['median_cycles'] = statistics.median(cycles)
            rec['mean_cycles'] = statistics.fmean(cycles)
        if nets:
            rec['median_net'] = statistics.median(nets)
        # 近期窗口：同样 5 个起点，窗口长度 20 日；独立诊断，失败显式记录
        try:
            rdiag = a.diagnose(pd.read_csv(path), sessions=recent_sessions, shifts=shifts)
            rcycles = [x['cycles'] for x in rdiag['runs'] if x['cycles'] is not None]
            if rcycles:
                rec['recent_median'] = statistics.median(rcycles)
            rec['recent_spread'] = rdiag['spread']
            rfail = [str(x['error']) for x in rdiag['runs'] if x['error']]
            if rfail:
                rec['errors'].extend('近期窗口：' + e for e in rfail)
        except Exception as exc:
            rec['errors'].append(f'近期窗口 {type(exc).__name__}: {exc}')
        rec['recent_state'] = recent_state(rec['median_cycles'], rec['recent_median'])
        out.append(rec)
    return rank_stable(out)


def main(argv=None):
    p = argparse.ArgumentParser(description='多锚点稳健排名（离线诊断，不替换生产）')
    p.add_argument('--dir', default=str(DEFAULT_DIR))
    p.add_argument('--asof', default='2026-11-06')
    p.add_argument('--key', choices=('median_cycles', 'mean_cycles', 'recent_median'),
                   default='median_cycles', help='排序依据：长期中位/长期平均/近20日中位')
    p.add_argument('--recent-sessions', type=int, default=RECENT_SESSIONS,
                   help='近期窗口交易日数（默认 20）')
    p.add_argument('--limit', type=int, help='限制参与标的数（调试用）')
    p.add_argument('--output', help='报告写入路径')
    args = p.parse_args(argv)
    rows = rank_stable(build(args.dir, limit=args.limit,
                             recent_sessions=args.recent_sessions), key=args.key)
    text = render(rows, args.asof, key=args.key)
    print(text)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    return text


if __name__ == '__main__':
    main()
