# -*- coding: utf-8 -*-
"""统一建仓/买入门控：entry_timing（位置）× ADX（动能）合并为单一四级判定。

背景 2026-10-26：榜单禁入（entry_timing）与 EOD 暂停买入（RegimeGate）
两套判定重复且打架（实测 589720 五线全破但 ADX 17.3 放行）。合并规则：

    暂停买入  收盘 < ma5/10/20/30/60 全部（五线全破）      → 拦
    暂停买   ADX>=25 且 -DI>+DI 且收盘 < ma60（强动能跌势）  → 拦
    试错仓   破 1-4 条线（配 20 日最低退出价）              → 不拦，标注
    正常     收盘 >= ma60（防追高等细分由 entry_timing 负责） → 不拦

从严者胜：五线全破 > 强动能跌势 > 试错仓 > 正常。行情缺失 fail-open：无 ADX
不触发暂停买（沿用 RegimeGate 语义），均线缺失不判禁入。

设计铁律：均线判定不在此重新实现——直接调用 entry_timing.judge_entry，
保证榜单口径与 EOD 口径同源，单一事实。
"""
from .entry_timing import judge_entry, LABELS

PAUSE_ADX = 25.0

LEVEL_ORDER = ('no_entry', 'pause_buy', 'probe_only', 'normal')


def blocked_buy_days(m5_frame, min_rows=65):
    """回测引擎用的逐日买入门控（2026-10-27 用户要求：回测过程也要符合规则）。

    对每个交易日 D：用截至 D-1 收盘的日线（date/open/high/low/close）跑
    生产统一判定 gate()——与 confirmed_runtime.RegimeGate 同一事实源。
    D 日判定所需历史不足 min_rows 根 → fail-open 不拦（生产语义）。

    Args:
        m5_frame: 5 分钟 K 线 DataFrame（time/open/high/low/close/volume）。
        min_rows: 单日判定所需最少日线根数（entry_timing MIN_ROWS=65）。

    Returns:
        dict {date_str: bool}，True=该日新格买入被拦截。
        只覆盖能聚合出日线的日期；缺失历史的前 min_rows-1 日不拦。
    """
    df = m5_frame.copy()
    if 'date' not in df.columns:
        df['date'] = df['time'].astype(str).str.slice(0, 10)
    daily = df.groupby('date', as_index=False).agg(
        open=('open', 'first'), high=('high', 'max'),
        low=('low', 'min'), close=('close', 'last'))

    from .entry_timing import prepare
    daily = prepare(daily).reset_index(drop=True)

    try:
        from market_phase_check import wilder_adx
    except ImportError:  # 引擎环境无该模块 → 仅均线判定（fail-open 语义）
        wilder_adx = None

    blocked = {}
    for i in range(1, len(daily)):
        day = daily['date'].iloc[i]
        history = daily.iloc[:i]  # 截至 D-1：无前视
        if len(history) < min_rows:
            blocked[day] = False
            continue
        regime = None
        if wilder_adx is not None:
            rows = history[['high', 'low', 'close']].to_dict('records')
            result = wilder_adx(rows)
            regime = dict(zip(('adx', 'pdi', 'mdi'), result)) if result else None
        verdict = gate(history, regime=regime)
        blocked[day] = bool(verdict['blocks_buy'])
    return blocked


def gate(frame, regime=None):
    """对单只 ETF 输出统一四级判定。

    Args:
        frame: 日线 DataFrame（date/open/high/low/close 至少 65 根）。
        regime: 市况 dict {adx, mdi, pdi}；None/缺 adx = fail-open。

    Returns:
        dict(level, blocks_buy, reason, exit_price, entry_verdict)
        entry_verdict 为 entry_timing 原判定（供仓位资格展示）。
    """
    judged = judge_entry(frame)
    regime = regime or {}
    adx = regime.get('adx')
    close = judged['close']
    ma = judged.get('ma') or {}
    ma60 = ma.get(60)
    ma5 = ma.get(5)

    level = 'normal'
    reason = ''
    blocks_buy = False
    exit_price = None

    if judged['verdict'] == 'no_entry':
        # entry_timing 的 no_entry 目前只对应五线全破（其余 no_entry 情形
        # 是均线上方防追高，blocks_buy 无意义——那不是"下跌拦截"场景）
        below_count = judged.get('below_count')
        if below_count is not None and below_count >= 5:
            level = 'no_entry'
            blocks_buy = True
            reason = judged['reasons'][0] + '；' + judged['reasons'][1] if len(judged['reasons']) > 1 else judged['reasons'][0]
    elif judged['verdict'] in ('probe_only',):
        level = 'probe_only'
        exit_price = judged.get('exit_price')
        reason = f"破线未全破（试错仓），退出价 {exit_price}；5日线 {ma5}"
        # ADX 强动能且方向向下（-DI>+DI，用户 10-26 原始规则）才升级为暂停买；
        # 强动能但 +DI 主导 = 上涨/反弹动能，不属于"单边下跌"，不拦
        mdi = regime.get('mdi')
        pdi = regime.get('pdi')
        if (adx is not None and adx >= PAUSE_ADX
                and ma60 is not None and close < ma60
                and mdi is not None and pdi is not None and mdi > pdi):
            level = 'pause_buy'
            blocks_buy = True
            reason = (f"ADX={adx:.1f}>=25 且 -DI {mdi:.0f} > +DI {pdi:.0f}，"
                      f"收盘 {close:.3f} 在 60日线 {ma60:.3f} 下方，"
                      f"强动能跌势，暂停新格买入，卖出保留")
    else:
        # 均线上方的 reject/no_entry(追高)/wait/full：不属于下跌拦截，
        # 但强动能破 60 日线的组合理论不可能出现于该分支，保持 normal。
        reason = f"收盘 {close:.3f} 在 60日线上方或盘整，门控不拦截"

    # 顶层兜底：entry_timing 判了 probe/no_entry 但 regime 显示强动能破位
    # （例如均线上方分支遗漏），从严者胜已在上面处理；此处仅保证
    # no_entry 分支同样接受 ADX 强化展示。
    if level == 'no_entry' and adx is not None and adx >= PAUSE_ADX:
        reason += f"；ADX={adx:.1f} 强动能（双重确认）"

    return {
        'level': level,
        'blocks_buy': blocks_buy,
        'reason': reason,
        'exit_price': exit_price,
        'entry_verdict': judged['verdict'],
        'close': close,
        'adx': adx,
    }
