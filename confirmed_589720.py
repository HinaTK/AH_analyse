"""User-confirmed isolated subledger. No guessed dates, no legacy tickets."""
from decimal import Decimal as D
import json
from pathlib import Path
import argparse

INPUT = [('buy',9200,'0.877'),('buy',9400,'0.859'),('buy',9600,'0.829'),('sell',9600,'0.846'),('buy',9600,'0.833'),('buy',9900,'0.806'),('buy',10000,'0.794'),('sell',10000,'0.806'),('sell',9900,'0.818')]

def build(inputs=None):
    trades, records, opened = [], [], {}
    qty = 0
    invested = D(0)
    depth = 0
    for seq,(side,n,p) in enumerate(INPUT if inputs is None else inputs,1):
        if side not in ('buy', 'sell') or n <= 0 or D(p) <= 0:
            raise ValueError('非法成交')
        if side == 'buy':
            if depth >= 26:
                raise ValueError('超出Z格，禁止生成非法标签')
            depth += 1
            grid = chr(64 + depth)
        else:
            if depth == 0:
                raise ValueError('没有可匹配的网格买入')
            grid = chr(64 + depth)
            depth -= 1
        price = D(p)
        amount = n*price
        fee = max(D('1'),amount*D('0.0001')).quantize(D('0.01'))
        ident = f'589720-{seq:03d}'
        trade = dict(id=ident,sequence=seq,code='sh589720',side=side,qty=n,price=p,lot=grid,date=None,fee=str(fee),amount=f'{amount:.2f}',source='user_confirmed_replacement')
        trades.append(trade)
        qty += n if side=='buy' else -n
        invested += amount+fee if side=='buy' else -(amount-fee)
        if side=='buy':
            if grid in opened:
                raise ValueError('存在未平仓同格，须显式指定买入批次')
            opened[grid]=trade
        else:
            buy=opened.pop(grid)
            if buy['qty']!=n:
                raise ValueError('部分成交需要独立分摊手续费，禁止猜配')
            gross=(price-D(buy['price']))*n
            fees=fee+D(buy['fee'])
            records.append(dict(lot=grid,buy_id=buy['id'],sell_id=ident,qty=n,buy_price=buy['price'],sell_price=p,gross=f'{gross:.2f}',fees=f'{fees:.2f}',net=f'{gross-fees:.2f}'))
    remaining=sum(D(x['amount'])+D(x['fee']) for x in opened.values())
    return dict(code='sh589720',name='科创创新药ETF国泰',trades=trades,qty=qty,sellable_qty=None,date_status='交易日期未提供；禁止推导T+1或作为自动出票依据',net_invested=f'{invested:.2f}',max_grid=chr(64+depth) if depth else None,net_unit_cost=f'{invested/qty:.8f}' if qty else None,remaining_buy_cost=f'{remaining:.2f}',remaining_unit_cost=f'{remaining/qty:.8f}' if qty else None,open_grid_positions=list(opened.values()),t_records=records,t_net=f"{sum(D(x['net']) for x in records):.2f}",supersedes='589720全部旧票据和旧成交推导；不代表其他ETF或账户现金已对账')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=build()
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        backup=target.with_suffix('.previous.json')
        backup.write_bytes(target.read_bytes())
    tmp=target.with_suffix('.tmp')
    tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(target)
    assert json.loads(target.read_text(encoding='utf-8'))==result
    print(json.dumps(result,ensure_ascii=False,indent=2))
