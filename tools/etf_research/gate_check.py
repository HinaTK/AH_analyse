# -*- coding: utf-8 -*-
"""统一建仓/买入门控：entry_timing（位置）× ADX（动能）合并为单一四级判定。

背景 2026-10-26：榜单禁入（entry_timing）与 EOD 暂停买入（RegimeGate）
两套判定重复且打架（实测 589720 五线全破但 ADX 17.3 放行）。合并规则：

    暂停买入  收盘 < ma5/10/20/30/60 全部（五线全破）      → 拦
    暂停买   ADX>=25 且收盘 < ma60（强动能 + 仍在跌势）     → 拦
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
        # ADX 强动能升级为暂停买（从严者胜）
        if adx is not None and adx >= PAUSE_ADX and ma60 is not None and close < ma60:
            level = 'pause_buy'
            blocks_buy = True
            reason = (f"ADX={adx:.1f}>=25 且收盘 {close:.3f} 在 60日线 {ma60:.3f} 下方，"
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
