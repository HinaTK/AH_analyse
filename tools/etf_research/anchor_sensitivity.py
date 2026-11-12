# -*- coding: utf-8 -*-
"""窗口锚点位移披露 + 多起点稳健性诊断（2026-11-06 Master 授权）。

只读诊断模块：消费已有的两期研究数据与 5 分钟 bars，**不替换生产口径**。
生产排名仍用单一窗口首根建锚；本模块只回答两个问题：
  1) 本期窗口首根相对上期位移了多少、相当于几个格距（披露）；
  2) 把窗口起点前后移动若干交易日，63 日往返次数会散到什么范围（稳健性）。

约束：不联网、不写账本/持仓/连续周状态、不改 research/engine/grid_model，
不带市况门控（生产 gate_days 属另一个口径），结果只用于观察，不生成买卖建议。
"""
from statistics import median, pstdev

from . import grid_model as model
from .research import DEFAULT_GAP

GAP = DEFAULT_GAP
SLIP = 0.0005
LOT_BUDGET = 5000


def anchor_of_first_open(first_open, start=None):
    """窗口首根开盘价 → 初始买入价与首档买卖价（规则与 grid_model 一致）。"""
    p = model.price(float(first_open), True, SLIP)
    return dict(start=start, first_open=float(first_open), initial_buy=p,
                first_sell=p * (1 + GAP), first_buy=p / (1 + GAP))


def shift_summary(prev, curr):
    pct = (curr['initial_buy'] / prev['initial_buy'] - 1) * 100
    return dict(pct=pct, grids=abs(pct) / (GAP * 100),
                prev_initial=prev['initial_buy'], curr_initial=curr['initial_buy'])


def disclosure_lines(prev, curr, prev_asof, curr_asof):
    """周报头部披露行：中文、单行、明确「仅披露不改口径」。"""
    s = shift_summary(prev, curr)
    line = (f"⚠️ 锚价位移披露：{prev_asof} 完整窗口首根开 {prev['first_open']:.3f} → "
            f"{curr_asof} 首根开 {curr['first_open']:.3f}；初始买入价 "
            f"{s['prev_initial']:.3f} → {s['curr_initial']:.3f}（{s['pct']:+.1f}%），"
            f"相当于 {s['grids']:.1f} 个 {GAP * 100:g}% 格距；网格线整体平移，"
            f"本期排名对窗口起点敏感，仅披露不改口径，请结合稳健性诊断解读。")
    return [line]


def _dates(frame):
    return list(dict.fromkeys(str(x)[:10] for x in frame['time']))


def diagnose(frame, sessions=63, shifts=(0, -1, -2, -3, -4), simulate=None):
    """同一标的，窗口起点按 shifts 平移（每个窗口长度恒为 sessions 个交易日）。

    simulate 可注入（测试）；默认调用 grid_model.simulate，参数与 engine.full 一致，
    但不带 gate_days（见模块 docstring）。单窗口失败记 error，不静默丢弃。
    """
    run = simulate or (lambda f, **kw: model.simulate(
        f, gap=GAP, t0=False, slip=SLIP, trace=False, lot_budget=LOT_BUDGET, gate_days=None))
    dates = _dates(frame)
    need = sessions + max(0, -min(shifts)) if shifts else sessions
    if len(dates) < need:
        raise ValueError(f'交易日不足：需要≥{need}天，实际{len(dates)}天')
    base_end = len(dates) - 1
    runs = []
    for shift in shifts:
        end = base_end + shift
        start = end - sessions + 1
        window = dates[start:end + 1]
        sub = frame[frame['time'].astype(str).str[:10].isin(window)].reset_index(drop=True)
        rec = dict(shift=shift, start=window[0], end=window[-1], days=len(window),
                   first_open=float(sub['open'].iloc[0]), cycles=None,
                   cycle_net=None, error=None)
        try:
            out = run(sub, gap=GAP, t0=False, slip=SLIP, lot_budget=LOT_BUDGET)
            rec['cycles'] = out['cycles']
            rec['cycle_net'] = out['cycle_net']
        except Exception as exc:
            rec['error'] = f'{type(exc).__name__}: {exc}'
        runs.append(rec)
    good = [r['cycles'] for r in runs if r['cycles'] is not None]
    return dict(runs=runs, ok=len(good), failed=len(runs) - len(good),
                spread=(max(good) - min(good)) if good else None,
                median_cycles=median(good) if good else None,
                pstdev=pstdev(good) if len(good) > 1 else 0.0,
                min_cycles=min(good) if good else None,
                max_cycles=max(good) if good else None)


def render(disclosure, diagnosis, code, name, prev_asof, curr_asof):
    """生成可推送的 Markdown 报告（中文表头、含免责）。"""
    lines = ['【锚点敏感性离线诊断·仅观察，不替换生产口径】',
             f'标的：{code} {name}　｜　对照两期：{prev_asof} / {curr_asof}（只读已有研究数据）',
             '', '## 一、本期锚价位移披露']
    lines.extend(disclosure)
    lines += ['', '## 二、多起点稳健性诊断',
              '判据：窗口长度恒为固定交易日数，仅把起点平移；各自独立跑一次同参数网格模拟。格距与生产 GAP 一致（1.5%）。',
              '',
              '| 起点平移(交易日) | 窗口起 | 窗口止 | 首根开盘价 | 63日往返次数 | 净差价元 | 备注 |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    for r in diagnosis['runs']:
        cyc = '不可用' if r['cycles'] is None else f"{r['cycles']:g}"
        net = '不可用' if r['cycle_net'] is None else f"{r['cycle_net']:,.2f}"
        note = '正常' if not r['error'] else f'⚠️ {r["error"]}'
        lines.append(f"| {r['shift']:+d} | {r['start']} | {r['end']} | "
                     f"{r['first_open']:.3f} | {cyc} | {net} | {note} |")
    lines += ['', '## 三、离散度',
              f"有效窗口 {diagnosis['ok']} 个、失败 {diagnosis['failed']} 个；"
              f"63日往返次数最少 {diagnosis['min_cycles']} 次、最多 {diagnosis['max_cycles']} 次、"
              f"极差 {diagnosis['spread']} 次、中位数 {diagnosis['median_cycles']:g} 次、"
              f"总体标准差 {diagnosis['pstdev']:.2f} 次。",
              '',
              '口径说明：诊断**不叠加市况门控**（生产排名带 gate_days），绝对值与生产不可直接比；',
              '只用于观察「窗口起点换一天，往返次数会散到多大」，**不替换生产口径**、不重算综合评分、',
              '不推进连续周状态、不改动账本/持仓/任务状态；同窗模拟非真实成交，不构成操作依据。']
    return '\n'.join(lines)
