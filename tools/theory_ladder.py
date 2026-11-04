# -*- coding: utf-8 -*-
"""理论口径网格阶梯回测（只读分析模块，不接入生产链路）。

复刻《投资理论框架》§4 的破网推演口径（2026-11-01 等比定稿）：

- 账户 100,000；底仓 30,000 在起始日按收盘价建仓（底仓永不卖）
- 网格现金 70,000；每格预算 lot_budget（默认 3,000）；格距 gap 等比
- 买入线 = 起始价 × (1-gap)^k（k=1,2,…）；收盘价跌破某线且现金够 →
  按该线价买入一格（整百份，含费）；同日最多成交一格
- 卖出线 = 买入价 × (1+gap)；收盘价升破某持仓格的卖线 → 按卖线价卖出，
  落袋净利，释放的现金回到网格现金池（可再买更深的格）
- 成交价取触发线价（与理论推演一致的"挂单成交"近似），不计滑点
- 手续费：万一免五、每笔最低 1 元（2026-10-08 起口径）

理论推演的两个刻度（gap=3%、lot=3000）：
  k=20 → 价位 -45.6%、现金剩 10,000（"永远留 1 万现金"规则生效点）
  k=24 → 价位 -51.9%、下一格买不起（现金打光）
本模块用真实日线验证：单边下跌段里这两个刻度是否成立、
期间已实现往返多少、账户最大回撤多少。

明确不做：分红再投、停牌、封板、滑点路径——与理论推演同一组省略，
结果用于对表验证结构，不用于预测收益。
"""
from decimal import Decimal as D

ACCOUNT = D('100000')
CORE_BUDGET = D('30000')


def fee_of(value):
    """万一免五，每笔最低 1 元。"""
    raw = (D(str(value)) * D('0.0001')).quantize(D('0.01'))
    return max(D('1'), raw)


def buy_shares(budget, price):
    """整百份买入；含费不超过预算。返回 (qty, cost)。"""
    price = D(str(price))
    qty = int(budget / (price * 100)) * 100
    while qty > 0 and D(qty) * price + fee_of(D(qty) * price) > budget:
        qty -= 100
    if qty <= 0:
        return 0, D('0')
    return qty, D(qty) * price + fee_of(D(qty) * price)


def simulate_ladder(bars, gap=0.03, lot_budget=3000, account=None, core_budget=None):
    """bars: [{'date','close'}, ...] 升序。返回结果 dict（全部可序列化）。

    account / core_budget 缺省 = 100,000 / 30,000（理论口径）。传入即按真实额度缩放，
    底仓仍按给定金额建仓且永不卖。
    """
    if len(bars) < 2:
        raise ValueError('bars 太少')
    gap = D(str(gap))
    lot = D(str(lot_budget))
    account = D(str(ACCOUNT if account is None else account))
    core_budget = D(str(CORE_BUDGET if core_budget is None else core_budget))
    p0 = D(str(bars[0]['close']))

    core_qty, core_cost = buy_shares(core_budget, p0)
    if core_qty <= 0:
        raise ValueError('底仓买不起一手')
    cash = account - core_cost
    levels = []          # 已买未卖的格：{'k','buy_price','qty','cost','sell_line'}
    next_k = 1
    cycles = []          # 已完成往返：{'buy_date','sell_date','pnl'}
    min_cash = cash
    max_drawdown = D('0')
    peak_equity = account
    worst_price_ratio = D('1')
    deepest_k = 0
    curve = []

    for bar in bars:
        close = D(str(bar['close']))
        # 卖出优先：升破卖线的格全部了结（深格先卖，释放现金）
        for level in sorted(levels, key=lambda x: -x['k']):
            if close >= level['sell_line']:
                proceeds = D(level['qty']) * level['sell_line'] - fee_of(D(level['qty']) * level['sell_line'])
                cash += proceeds
                cycles.append({'buy_date': level['buy_date'], 'sell_date': bar['date'],
                               'k': level['k'], 'pnl': str((proceeds - level['cost']).quantize(D('0.01')))})
                levels.remove(level)
        # 买入：收盘跌破下一格线且现金够 → 成交一格
        line = p0 * (1 - gap) ** next_k
        qty, cost = buy_shares(lot, line)
        if qty and close <= line and cash >= cost:
            cash -= cost
            levels.append({'k': next_k, 'buy_price': line, 'qty': qty, 'cost': cost,
                           'sell_line': line * (1 + gap), 'buy_date': bar['date']})
            deepest_k = max(deepest_k, next_k)
            next_k += 1
        equity = cash + D(core_qty + sum(l['qty'] for l in levels)) * close
        min_cash = min(min_cash, cash)
        peak_equity = max(peak_equity, equity)
        dd = equity / peak_equity - 1
        max_drawdown = min(max_drawdown, dd)
        worst_price_ratio = min(worst_price_ratio, close / p0)
        curve.append({'date': bar['date'], 'close': str(close), 'cash': str(cash.quantize(D('0.01'))),
                      'equity': str(equity.quantize(D('0.01'))), 'open_levels': len(levels)})

    end_close = D(str(bars[-1]['close']))
    end_equity = cash + D(core_qty + sum(l['qty'] for l in levels)) * end_close
    realized = sum((D(c['pnl']) for c in cycles), D('0'))
    return {
        'start': bars[0]['date'], 'end': bars[-1]['date'], 'days': len(bars),
        'p0': str(p0), 'gap': str(gap), 'lot_budget': str(lot),
        'core_qty': core_qty, 'core_cost': str(core_cost.quantize(D('0.01'))),
        'cycles': len(cycles), 'realized': str(realized.quantize(D('0.01'))),
        'deepest_k': deepest_k,
        'worst_price_drop_pct': str(((worst_price_ratio - 1) * 100).quantize(D('0.01'))),
        'min_cash': str(min_cash.quantize(D('0.01'))),
        'max_drawdown_pct': str((max_drawdown * 100).quantize(D('0.01'))),
        'end_equity': str(end_equity.quantize(D('0.01'))),
        'account_pnl': str((end_equity - account).quantize(D('0.01'))),
        'open_levels': len(levels),
        'curve': curve, 'cycle_detail': cycles,
    }
