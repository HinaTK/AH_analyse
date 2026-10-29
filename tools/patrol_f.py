# -*- coding: utf-8 -*-
"""F方案巡检模块 — 独立于现行门控的并行判定 (2026-10-28 用户指令: 不改原代码)。

规则 (全池回测定稿, 283只/10405日/7634次接格机会):
    暂停新格买入 = 五线全破 (收盘 < ma5/10/20/30/60 全部)
               OR  ATR扩张 (ATR5/ATR20 > 1.15)
    卖出永不拦截; 数据不足 fail-open。

回测依据:
    F 避损 +317.1k vs 现行五线 +251.9k (增量 65.2k, 680次全部避损, 均-95.9元);
    代价: 震荡日捕获 56.9%→47.4%。589720 实证: 9-23/24 (ATR 1.27→1.43) 提前于
    五线全破拦截, 避开国庆前连跌。

设计铁律 (用户 2026-10-28 明确):
    1. 独立脚本, 不 import gate_check/confirmed_runtime/entry_timing 的判定逻辑
       — 与生产门控并行运行, 互不干扰, 随时可整体摘除。
    2. 判定自包含: 均线和 ATR 自己算, 只吃日线 DataFrame。
    3. 输出与 RegimeGate 兼容的形状 (blocks_buy/reason), 方便将来合并。

用法:
    from tools.patrol_f import patrol
    verdict = patrol(daily_df)   # daily_df: date/open/high/low/close
    # verdict: dict(blocks_buy, reason, reason_tag, five_break, atr_ratio,
    #               sells_allowed, close, ma, atr5, atr20)
"""
from __future__ import annotations

import pandas as pd

ATR_EXPAND_TH = 1.15          # 回测定稿阈值, 勿随手改 (test_patrol_f 钉死)
MA_PERIODS = (5, 10, 20, 30, 60)
ATR_FAST, ATR_SLOW = 5, 20
MIN_ROWS = 65                 # ma60 + 缓冲; 不足则 fail-open


def _true_range(df: pd.DataFrame) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    prev = c.shift(1)
    return pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)


def patrol(df: pd.DataFrame) -> dict:
    """对单只 ETF 的日线做 F 方案判定。df 需含 date/open/high/low/close。"""
    out = df.copy()
    if 'date' not in out.columns and 'time' in out.columns:
        out = out.rename(columns={'time': 'date'})

    close = float(out['close'].iloc[-1])
    ma = {p: float(out['close'].rolling(p).mean().iloc[-1]) for p in MA_PERIODS}
    tr = _true_range(out)
    atr5 = float(tr.rolling(ATR_FAST).mean().iloc[-1])
    atr20 = float(tr.rolling(ATR_SLOW).mean().iloc[-1])

    insufficient = (
        len(out) < MIN_ROWS
        or any(pd.isna(v) for v in ma.values())
        or pd.isna(atr5) or pd.isna(atr20)
        or atr20 <= 0
    )
    if insufficient:
        return dict(
            blocks_buy=False, sells_allowed=True,
            reason='数据不足，fail-open 不拦截（F方案巡检）',
            reason_tag='insufficient', five_break=None, atr_ratio=None,
            close=close, ma=None, atr5=None, atr20=None,
        )

    five_break = all(close < ma[p] for p in MA_PERIODS)
    atr_ratio = atr5 / atr20
    atr_expand = atr_ratio > ATR_EXPAND_TH

    if five_break:
        blocks = True
        reason = (f'F方案巡检：五线全破（收盘 {close:.3f} 低于 5/10/20/30/60 日线 '
                  f'{ma[5]:.3f}/{ma[10]:.3f}/{ma[20]:.3f}/{ma[30]:.3f}/{ma[60]:.3f}），'
                  f'暂停新格买入，卖出保留')
        tag = 'five_break'
    elif atr_expand:
        blocks = True
        reason = (f'F方案巡检：波动扩张（ATR5/ATR20 = {atr_ratio:.2f} > {ATR_EXPAND_TH}），'
                  f'疑似单边启动，暂停新格买入，卖出保留；波动回落后自动解除')
        tag = 'atr_expand'
    else:
        blocks = False
        reason = (f'F方案巡检：未触发（五线未全破，ATR比 {atr_ratio:.2f}），网格正常')
        tag = 'ok'

    return dict(
        blocks_buy=blocks, sells_allowed=True,
        reason=reason, reason_tag=tag,
        five_break=five_break, atr_ratio=atr_ratio,
        close=close, ma=ma, atr5=atr5, atr20=atr20,
    )


def main(argv=None):
    """命令行: 对持仓三票跑 F 方案巡检并打印 (供手动验证/将来 cron 接入)。"""
    import argparse
    import json
    import sys as _sys
    _sys.path.insert(0, 'D:/Code/AH_analyse')
    _sys.path.insert(0, 'D:/Code/AH_analyse/tools')
    from market_phase_check import fetch_kline
    from datetime import datetime, timezone, timedelta

    parser = argparse.ArgumentParser(description='F方案巡检 (五线全破 OR ATR扩张>15%)')
    parser.add_argument('--codes', default='sh589720,sz159363,sz159992',
                        help='逗号分隔的持仓代码')
    args = parser.parse_args(argv)

    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime('%Y-%m-%d')
    for code in args.codes.split(','):
        secid = ('1.' if code.startswith('sh') else '0.') + code[-6:]
        try:
            rows = fetch_kline(secid, lmt=300, klt='101')
            if now.hour < 15:  # 盘中丢弃今日未收K, 与生产门控同口径
                rows = [r for r in rows if r['date'] != today]
            df = pd.DataFrame(rows)
            v = patrol(df)
            state = '⛔ 暂停买入' if v['blocks_buy'] else '✅ 放行'
            print(f"{code} {state} [{v['reason_tag']}] {v['reason']}")
        except Exception as exc:
            print(f"{code} 巡检失败 (fail-open): {exc}")


if __name__ == '__main__':
    main()
