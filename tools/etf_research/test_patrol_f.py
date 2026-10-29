# -*- coding: utf-8 -*-
"""F方案巡检模块 patrol_f 的 TDD 测试。

F方案 (2026-10-28 全池回测定稿, 用户确认独立落地不改原代码):
  暂停新格买入 = 五线全破 (收盘 < ma5/10/20/30/60 全部)
             OR  ATR扩张 (ATR5/ATR20 > 1.15)
  卖出永不拦截; 数据缺失 fail-open (不拦)。

回测依据 (283只, 2026-07~10, 7,634次接格机会):
  F 避损 +317.1k vs 现行五线 +251.9k; F 多拦的680次全部避损(均-95.9元);
  代价: 震荡日捕获 56.9%→47.4%。

独立模块铁律: 不 import gate_check / confirmed_runtime / entry_timing 的
判定逻辑, 判定自包含 (均线/ATR 自己算), 与生产门控并行运行互不干扰。
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from tools.patrol_f import patrol, ATR_EXPAND_TH  # noqa: E402


def daily_frame(closes, hi_pct=1.004, lo_pct=0.996):
    """日收盘序列 → 日线 DataFrame (带日内振幅保证 ATR>0)。"""
    cal = pd.bdate_range('2026-01-05', periods=len(closes)).strftime('%Y-%m-%d').tolist()
    rows = []
    for day, c in zip(cal, closes):
        rows.append(dict(date=day, open=round(c * lo_pct, 4),
                         high=round(c * hi_pct, 4), low=round(c * lo_pct, 4),
                         close=c))
    return pd.DataFrame(rows)


def test_atr_expand_threshold_constant():
    """回测定稿的阈值必须是 1.15, 防止后人随手改。"""
    assert ATR_EXPAND_TH == 1.15


def test_five_line_full_break_blocks_buy():
    """五线全破 → 拦截 (与现行门控同源行为)。"""
    # 75根横盘后急跌: 收盘低于全部五条均线
    closes = [10.0] * 75 + [9.0, 8.8, 8.6, 8.4, 8.2, 8.0, 7.8, 7.6]
    v = patrol(daily_frame(closes))
    assert v['blocks_buy'] is True
    assert v['reason_tag'] == 'five_break'


def test_atr_expand_blocks_buy_even_above_moving_averages():
    """ATR扩张>15% 但价格仍在均线上方 → 也要拦 (F方案的核心增量)。

    构造: 80根低波动横盘 (ATR基线小), 然后8根大振幅上涨日
    (收盘持续走高保证在均线上方, 日内 high/low ±5% 拉爆 ATR5)。
    """
    cal = pd.bdate_range('2026-01-05', periods=88).strftime('%Y-%m-%d').tolist()
    rows = []
    for i, day in enumerate(cal):
        if i < 80:
            c = 10.0
            hi, lo = round(c * 1.004, 4), round(c * 0.996, 4)
        else:
            # 大振幅上涨日: 收盘持续走高 (10.3, 10.6, ...), 日内 ±5%
            c = 10.0 + 0.3 * (i - 79)
            hi, lo = round(c * 1.05, 4), round(c * 0.95, 4)
        rows.append(dict(date=day, open=lo, high=hi, low=lo, close=round(c, 4)))
    frame = pd.DataFrame(rows)
    v = patrol(frame)
    assert v['five_break'] is False, '夹具: 持续上涨不应全破五线'
    assert v['atr_ratio'] > ATR_EXPAND_TH, f'夹具: ATR比应>1.15, 实际 {v["atr_ratio"]:.2f}'
    assert v['blocks_buy'] is True
    assert v['reason_tag'] == 'atr_expand'


def test_quiet_sideways_market_allows_buy():
    """平静震荡 (ATR未扩张 + 均线上方) → 放行 (网格正常跑)。"""
    closes = [10.0] * 90
    v = patrol(daily_frame(closes))
    assert v['blocks_buy'] is False
    assert v['reason_tag'] == 'ok'


def test_insufficient_history_fails_open():
    """历史不足 (均线/ATR 算不出) → fail-open 不拦, 与生产门控语义一致。"""
    closes = [10.0 - 0.1 * i for i in range(30)]  # 单边急跌但数据不足
    v = patrol(daily_frame(closes))
    assert v['blocks_buy'] is False
    assert v['reason_tag'] == 'insufficient'


def test_sell_never_blocked():
    """F方案只拦买入: 判定结果里显式声明 sells_allowed=True。"""
    closes = [10.0] * 75 + [9.0, 8.8, 8.6, 8.4, 8.2, 8.0, 7.8, 7.6]
    v = patrol(daily_frame(closes))
    assert v['sells_allowed'] is True


def test_reason_text_is_human_readable():
    """⛔ 行文案: 含具体数字, 供盘前推送直接引用。"""
    closes = [10.0] * 75 + [9.0, 8.8, 8.6, 8.4, 8.2, 8.0, 7.8, 7.6]
    v = patrol(daily_frame(closes))
    assert '五线全破' in v['reason']
    # ATR 版本: 大振幅上涨日 (同上夹具)
    cal = pd.bdate_range('2026-01-05', periods=88).strftime('%Y-%m-%d').tolist()
    rows = []
    for i, day in enumerate(cal):
        if i < 80:
            c = 10.0
            hi, lo = round(c * 1.004, 4), round(c * 0.996, 4)
        else:
            c = 10.0 + 0.3 * (i - 79)
            hi, lo = round(c * 1.05, 4), round(c * 0.95, 4)
        rows.append(dict(date=day, open=lo, high=hi, low=lo, close=round(c, 4)))
    v2 = patrol(pd.DataFrame(rows))
    assert 'ATR' in v2['reason'] or '波动' in v2['reason']
