# -*- coding: utf-8 -*-
"""实盘参数档核对（只读分析，不改任何生产参数）。

1. 复核 Chief 改进报告的三处数字：2015 段单格金额补充表、价格峰谷 -52.97%、
   实盘档（1.5%/6000、1.5%/8000）的 100k 口径外推。
2. 按 per-ETF 真实额度跑同一段行情（底仓仍按 30% 比例，显式标注）。
3. 从账本读出当前弹药：剩余额度还够几格、再跌多少耗尽。
"""
import json
import sys
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, 'D:/Code/AH_analyse')
sys.path.insert(0, 'D:/Code/AH_analyse/tools')

from theory_ladder import simulate_ladder
import confirmed_runtime as rt

CACHE = Path(r'C:\Users\Administrator\.dsh\bot\workspace\回测缓存\1_510300.json')
ROOT = Path(r'D:\Hermes Agent CN Desktop\data\hermes-home\cache\grid-account')

bars = sorted(json.loads(CACHE.read_text(encoding='utf-8')), key=lambda b: b['date'])


def win(s, e):
    return [b for b in bars if s <= b['date'] <= e]


W = {'2015': ('2015-06-01', '2016-02-29'),
     '2018': ('2018-01-01', '2018-12-31'),
     '2022': ('2022-01-01', '2022-12-31')}

print('== 复核：2015 段 单格金额补充表（回撤% / 最低现金）==')
for gap in ('0.03', '0.045', '0.06'):
    row = []
    for lot in (2000, 3000, 5000):
        r = simulate_ladder(win(*W['2015']), gap=gap, lot_budget=lot)
        row.append(f'{lot}:{r["max_drawdown_pct"]}/{r["min_cash"]}')
    print(f'  gap {gap}:', '  '.join(row))

print('\n== 复核：价格峰谷（收盘）==')
peak = D(0)
peak_date = None
trough = None
worst = D(0)
for b in bars:
    c = D(str(b['close']))
    if c > peak:
        peak, peak_date = c, b['date']
    if peak > 0:
        dd = c / peak - 1
        if dd < worst:
            worst, trough = dd, (b['date'], c, peak_date, peak)
print(f'  最大回撤 {worst * 100:.2f}%：峰值 {trough[2]} {trough[3]} -> 谷底 {trough[0]} {trough[1]}')

print('\n== 复核：实盘档 100k 口径（回撤% / 最低现金 / 往返）==')
for lot in (6000, 8000):
    for name, se in W.items():
        r = simulate_ladder(win(*se), gap='0.015', lot_budget=lot)
        print(f'  1.5%/{lot} {name}: {r["max_drawdown_pct"]} / {r["min_cash"]} / {r["cycles"]}')

print('\n== 纯算术：70000 现金、1.5% 格距耗尽深度 ==')
for lot in (8000, 6000, 3000):
    n = 70000 // lot
    drop = (D('0.985') ** n - 1) * 100
    print(f'  每格 {lot}: {n} 格后买不起下一格，价格 {drop:.2f}%')

print('\n== per-ETF 真实额度（底仓=30% 额度，格距 1.5%，每格按实盘）==')
for quota, lot, label in ((66227, 8000, '589720 额度66227/每格8000'),
                          (30000, 8000, '512980 额度30000/每格8000')):
    core = D(quota) * D('0.3')
    print(f'  {label} 底仓预算 {core:.0f}')
    for name, se in W.items():
        r = simulate_ladder(win(*se), gap='0.015', lot_budget=lot,
                            account=quota, core_budget=core)
        print(f'    {name}: 回撤 {r["max_drawdown_pct"]} 最低现金 {r["min_cash"]} '
              f'往返 {r["cycles"]} 最深格 {r["deepest_k"]} 底仓成本 {r["core_cost"]}')

def ladder(net, anchor, entry, lot, quota, close, cap=40):
    """按 plan() 语义逐格下推：首格用 entry，其后为上一格价/(1+GAP)。

    停在额度用尽、买价落到现价、或 cap 格（无额度标的的安全上限，实盘无此限制）。
    返回 (逐格列表, 累计投入, 是否被 cap 截断)。
    """
    out = []
    price = D(str(anchor)) if anchor is not None else None
    spent = D(str(net))
    first = price is None
    for _ in range(cap):
        raw = D(str(entry)) if first else price / (1 + rt.GAP)
        px = D(str(rt.price(raw)))
        qty = int(D(str(lot)) / (px * 100)) * 100
        if qty <= 0:
            return out, spent, False
        cost = px * qty
        if quota is not None and spent + cost > D(str(quota)):
            return out, spent, False
        out.append((str(px), qty, str(cost)))
        spent += cost
        price = px
        first = False
        if close is not None and px <= D(str(close)):
            return out, spent, False
    return out, spent, True


print('\n== 账本弹药（脚本读回）==')
hold = json.loads((ROOT / 'holdings.json').read_text(encoding='utf-8'))['holdings']
cache = json.loads((ROOT / 'regime-cache.json').read_text(encoding='utf-8'))
print(f'  实盘 GAP = {rt.GAP}')
for code6 in ('589720', '159363', '512980'):
    d = json.loads((ROOT / f'confirmed-{code6}.json').read_text(encoding='utf-8'))
    key = ('sh' if code6.startswith(('5', '6', '9')) else 'sz') + code6
    h = hold.get(key, {})
    pos = d.get('open_grid_positions') or []
    prices = [str(p.get('price')) for p in pos]
    close = cache.get(key, {}).get('close')
    print(f'  {code6}: qty={d.get("qty")} net={d.get("net_invested")} '
          f'max_grid={d.get("max_grid")} entry={d.get("entry_price")} '
          f'quota={h.get("quota")} lot={h.get("lot_budget")} paused={h.get("buy_paused")}')
    print(f'    持仓格价(从早到晚): {prices}')
    print(f'    regime 收盘 {close} asof {cache.get(key, {}).get("asof")}')
    anchor = prices[-1] if prices else None
    # 159363 无额度：给 200 格上限只为看跌到现价需要多少格，实盘没有这个上限
    buys, spent, capped = ladder(d.get('net_invested') or 0, anchor, d.get('entry_price'),
                                 h.get('lot_budget'), h.get('quota'), None, cap=200)
    to_now = [b for b in buys if D(b[0]) > D(str(close))]
    print(f'    现价上方待买 {len(to_now)} 格，买完累计投入 {D(str(d.get("net_invested") or 0)) + sum((D(b[2]) for b in to_now), D(0))}')
    if h.get('quota') is not None:
        print(f'    额度耗尽共 {len(buys)} 格（含现价以下），末格 {buys[-1][0] if buys else "无"}，累计 {spent}')
    else:
        print(f'    无额度：跌到现价需 {len(to_now)} 格、再往下模型未设上限（截断={capped}）')
