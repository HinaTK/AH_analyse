# -*- coding: utf-8 -*-
"""修两处：①夹具 max_grid 与 depth 一致性（1笔买入→depth=1→max_grid='A'，
但我们要 F 格 → 给 6 笔买入 A-F）；②reanchor_price 里 D(str) 转换（spot 可能是 str）。"""
from pathlib import Path

p = Path('D:/Code/AH_analyse/confirmed_runtime.py')
text = p.read_text(encoding='utf-8')

old = """    if old_next is None or spot is None or spot <= 0:
        return None
    deviation = abs(old_next / spot - 1)
    if deviation <= REANCHOR_DEVIATION:
        return None
    return price(spot * (1 - GAP))"""
new = """    if old_next is None or spot is None:
        return None
    old_next = D(str(old_next))
    spot = D(str(spot))
    if spot <= 0:
        return None
    deviation = abs(old_next / spot - 1)
    if deviation <= REANCHOR_DEVIATION:
        return None
    return price(spot * (1 - GAP))"""
assert old in text
text = text.replace(old, new, 1)
p.write_text(text, encoding='utf-8')
import ast
ast.parse(text)
print('reanchor_price 类型修复 ✓')

# 夹具：6笔买入 A~F，max_grid='F'
t = Path('D:/Code/AH_analyse/test_reanchor.py')
tx = t.read_text(encoding='utf-8')
old_f = """        def state(code, last_price, lot):
            n = 6 if code == 'sh589720' else 4
            trades = [dict(id=f'{code}-00{i}', sequence=i, code=code, side='buy',
                           qty=10000, price=last_price, lot=lot, date='2026-10-26')
                      for i in range(1, 2)]
            return dict(code=code, name=code, qty=10000, sellable_qty=10000,
                        max_grid=lot, net_invested=str(int(float(last_price) * 10000)),
                        trades=trades,
                        open_grid_positions=[dict(t) for t in trades])"""
new_f = """        def state(code, prices):
            # prices: 每格买价列表 A,B,C...；max_grid 由 depth 推导
            lots = [chr(65 + i) for i in range(len(prices))]
            trades = [dict(id=f'{code}-0{i+1:02d}', sequence=i + 1, code=code, side='buy',
                           qty=10000, price=str(prices[i]), lot=lots[i], date='2026-10-26')
                      for i in range(len(prices))]
            return dict(code=code, name=code, qty=10000 * len(prices), sellable_qty=10000 * len(prices),
                        max_grid=lots[-1], net_invested=str(int(sum(float(x) for x in prices) * 10000)),
                        trades=trades,
                        open_grid_positions=[dict(t) for t in trades])"""
assert old_f in tx
tx = tx.replace(old_f, new_f, 1)

old_call = """        # 三只：589720 F格0.797（重锚主角），另两只浅层不触发
        Path(td, 'confirmed-589720.json').write_text(json.dumps(state('sh589720', '0.797', 'F')), encoding='utf-8')
        Path(td, 'confirmed-159363.json').write_text(json.dumps(state('sz159363', '1.000', 'D')), encoding='utf-8')
        Path(td, 'confirmed-159992.json').write_text(json.dumps(state('sz159992', '0.800', 'B')), encoding='utf-8')
        return td"""
new_call = """        # 三只：589720 六格 A~F（末格0.797，重锚主角），另两只浅层
        Path(td, 'confirmed-589720.json').write_text(
            json.dumps(state('sh589720', ['0.877', '0.859', '0.833', '0.821', '0.809', '0.797'])), encoding='utf-8')
        Path(td, 'confirmed-159363.json').write_text(
            json.dumps(state('sz159363', ['1.100', '1.080', '1.060', '1.040']))), encoding='utf-8') if False else None
        Path(td, 'confirmed-159363.json').write_text(
            json.dumps(state('sz159363', ['1.100', '1.080', '1.060', '1.040'])), encoding='utf-8')
        Path(td, 'confirmed-159992.json').write_text(
            json.dumps(state('sz159992', ['0.850', '0.800'])), encoding='utf-8')
        return td"""
assert old_call in tx
tx = tx.replace(old_call, new_call, 1)
t.write_text(tx, encoding='utf-8')
import ast as ast2
ast2.parse(tx)
print('夹具6格修复 ✓')
