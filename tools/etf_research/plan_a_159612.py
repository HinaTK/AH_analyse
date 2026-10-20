"""Isolated 159612 Plan-A *counterfactual*; does not place orders or alter grid_model.

Fixed 2.105 anchor and box are known only at the 2026-10-13 decision. Running
on earlier bars is a hindsight sensitivity exercise, not an out-of-sample test.
Signals use the prior 5m close; execution uses next open with adverse slippage.
No intrabar high/low fill, no assumed human response to a semi-automatic alert.
"""
import argparse
import json
import math
from pathlib import Path

from .engine import fetch_bars, validate
from .grid_model import fee, price, purchase


def simulate(frame, *, anchor=2.105, lower=2.066, upper=2.160,
             gap=.01, lot_budget=8000, capital=40000, slip=.0005,
             start_cash=40000, max_slots=5):
    if not (0 < lower < anchor < upper and 0 < gap < 1 and 0 < lot_budget <= capital
            and start_cash >= capital and max_slots > 0):
        raise ValueError('invalid research parameters')
    frame = validate(frame).reset_index(drop=True)
    if len(frame) < 2:
        raise ValueError('too few bars')
    rows = frame.to_dict('records')
    cash = float(start_cash)
    lots = []
    events = []
    equity = []
    next_buy = anchor / (1 + gap)
    # Capital cost is the entry outlay of *currently held* lots, not lifetime buys.
    cost_held = 0.
    peak_cost = 0.
    cycle_net = 0.
    cycles = 0
    blocked = 0
    cancelled = 0
    for i, bar in enumerate(rows):
        day = str(bar['time'])[:10]
        if i:
            signal = float(rows[i - 1]['close'])
            # Flat with the buy level outside the box: fall back to the anchor entry rule.
            if not lots and not lower <= next_buy <= upper:
                next_buy = anchor / (1 + gap)
            # Inventory pool is T+1 by default. One action at most per 5m bar.
            sellable = [x for x in lots if x['date'] < day and signal >= x['target']]
            if sellable:
                lot = min(sellable, key=lambda x: x['target'])
                p = price(float(bar['open']), False, slip)
                if p >= lot['target'] and lot['qty'] <= float(bar['volume']) * .01:
                    proceeds = lot['qty'] * p - fee(lot['qty'] * p)
                    profit = proceeds - lot['cost']
                    cash += proceeds
                    cost_held -= lot['cost']
                    lots.remove(lot)
                    cycle_net += profit
                    cycles += 1
                    events.append(dict(side='sell', time=bar['time'], qty=lot['qty'], price=p,
                                       pnl=profit, buy_time=lot['time']))
                    # Returning one free slot is not a mandate to rebuy above box.
                    next_buy = p / (1 + gap)
                else:
                    cancelled += 1
            elif any(signal >= x['target'] for x in lots):
                blocked += 1
            elif len(lots) < max_slots and lower <= next_buy <= upper and signal <= next_buy:
                p = price(float(bar['open']), True, slip)
                if lower <= p <= min(next_buy, upper) and cost_held < capital:
                    qty, cost = purchase(lot_budget, p)
                    if qty and cost <= cash and cost_held + cost <= capital and qty <= float(bar['volume']) * .01:
                        lots.append(dict(qty=qty, cost=cost, date=day, time=bar['time'],
                                         target=math.ceil(p * (1 + gap) / .001 - 1e-9) * .001))
                        cash -= cost
                        cost_held += cost
                        next_buy = p / (1 + gap)
                        events.append(dict(side='buy', time=bar['time'], qty=qty, price=p, cost=cost))
                    else:
                        cancelled += 1
                else:
                    cancelled += 1
        peak_cost = max(peak_cost, cost_held)
        inventory = sum(x['qty'] for x in lots)
        if cash < -1e-6 or cost_held > capital + 1e-6 or len(lots) > max_slots:
            raise AssertionError('cash/capital/slot invariant')
        equity.append(cash + inventory * float(bar['close']))
    peak = start_cash
    worst = 0.
    for value in equity:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    inventory_pnl = sum(x['qty'] for x in lots) * float(rows[-1]['close']) - cost_held
    account_pnl = equity[-1] - start_cash
    if abs(account_pnl - cycle_net - inventory_pnl) > 1e-5:
        raise AssertionError('PnL reconciliation failure')
    return dict(start=rows[0]['time'], end=rows[-1]['time'], bars=len(rows),
                sessions=len({str(x['time'])[:10] for x in rows}), cycles=cycles,
                cycle_net=round(cycle_net, 2), inventory_pnl=round(inventory_pnl, 2),
                account_pnl=round(account_pnl, 2), account_return_pct=round(account_pnl/start_cash*100, 3),
                max_drawdown_pct=round(worst*100, 3), peak_cost=round(peak_cost, 2),
                end_cash=round(cash, 2), end_qty=sum(x['qty'] for x in lots),
                blocked_settlement=blocked, cancelled_signals=cancelled,
                events=events)


def main():
    parser = argparse.ArgumentParser(description='159612 Plan-A 5m counterfactual; no trading')
    parser.add_argument('--asof', default='2026-10-13', help='completed session only')
    parser.add_argument('--start', default='2026-09-01')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    frame = fetch_bars('sz159612')
    frame = frame[(frame.time.str[:10] >= args.start) & (frame.time.str[:10] <= args.asof)].copy()
    groups = frame.groupby(frame.time.str[:10])
    if frame.empty or frame.time.iloc[-1][:10] != args.asof or any(
            len(group) != 48 or not group.time.iloc[-1].endswith('15:00:00')
            for _, group in groups):
        raise ValueError('incomplete or stale five-minute history')
    result = simulate(frame)
    result['assumptions'] = dict(symbol='sz159612', anchor=2.105, lower=2.066,
                                  upper=2.160, gap=.01, lot_budget=8000,
                                  max_inventory_cost=40000, cash=40000,
                                  starting_shares=0, slip=.0005, volume_cap=.01,
                                  commissions='max(1 yuan, turnover*0.0001) per side',
                                  fixed_levels_known='2026-10-13; earlier simulation is hindsight')
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'events'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
