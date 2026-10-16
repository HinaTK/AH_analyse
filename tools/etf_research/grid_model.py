"""5m close signal -> next bar open IOC-limit approximation, not real fills.
100k account, 10k core + four 5k initial trading lots, four empty 5k slots.
50k cash reserve. Share-level settlement availability, economic slot accounting.
T+1 allows selling overnight shares against a new economic trading lot, but never
exceeds the whole account's settled shares. No high/low-path assumptions.
"""
import math
import numpy as np


def fee(value): return max(1.0,value*.0001)

def price(p,buy,slip):
    x=p*(1+slip if buy else 1-slip)/.001
    return (math.ceil(x-1e-9) if buy else math.floor(x+1e-9))*.001


def purchase(budget,p):
    qty=int(budget/(p*100))*100
    while qty>0 and qty*p+fee(qty*p)>budget:qty-=100
    return qty,qty*p+fee(qty*p) if qty else 0


def simulate(frame,gap=.02,t0=False,slip=.0005,trace=False,lot_budget=5000):
    rows=frame[['time','open','close','volume']].to_numpy()
    if len(rows)<2:raise ValueError('too few bars')
    times=[str(x) for x in rows[:,0]]
    opens=rows[:,1].astype(float);closes=rows[:,2].astype(float);vol=rows[:,3].astype(float)
    dates=[x[:10] for x in times]
    all_dates=list(dict.fromkeys(dates))
    day_ids={x:i for i,x in enumerate(all_dates)}
    n=len(rows);cash=100000.0;events=[];trades=0;fees=0.0
    initial_p=price(opens[0],True,slip)
    core_qty,core_cost=purchase(lot_budget*2,initial_p)
    q,c=purchase(lot_budget,initial_p)
    if min(core_qty,q)<=0:raise ValueError('price too high for board lot')
    if core_qty+4*q>vol[0]*.01*100:raise ValueError('initial orders exceed 1% first bar volume')
    cash-=core_cost
    slots=[]
    def record(side,i,qty,p,commission,slot,signal=None,initial=False,pnl=0):
        if trace:events.append({'side':side,'index':i,'time':times[i],'qty':qty,'price':p,'fee':commission,'slot':slot,'signal_index':signal,'initial':initial,'pnl':pnl})
    record('buy',0,core_qty,initial_p,fee(core_qty*initial_p),'core',initial=True)
    trades=1;fees=fee(core_qty*initial_p)
    for k in range(8):
        if k<4:
            slots.append({'qty':q,'cost':c,'target':initial_p*(1+gap)**(k+1),'initial':True,'bought_day':0,'bought_index':0})
            cash-=c;fees+=fee(q*initial_p);trades+=1
            record('buy',0,q,initial_p,fee(q*initial_p),k,initial=True)
        else:
            slots.append({'qty':0,'cost':0.0,'target':initial_p/(1+gap)**(k-3),'initial':False,'bought_day':0,'bought_index':0})
    qty_total=core_qty+4*q

    initial_qty=qty_total;initial_cash=cash

    available=qty_total if t0 else 0

    cost_held=core_cost+4*c;max_cost=cost_held;min_cash=cash

    # Initial cash/cost assertion: ensure model invariants hold from the start

    if cash < 50000 - 1e-6 or cost_held > 50000 + 1e-6:

        raise AssertionError('initial capital invariant violated: cash=%s cost_held=%s' % (cash, cost_held))

    if not (available >= 0 and available <= qty_total):

        raise AssertionError('initial availability invariant violated: available=%s qty_total=%s' % (available, qty_total))
    realized=0.0;cycle_pnl=0.0;cycles=0;sales=0;initial_sales=0;blocked=0;cancelled=0
    hold_days=[];cycle_costs=[];sale_dates=set();equities=[];costs=[];cash_series=[]
    for i in range(n):
        if i and dates[i]!=dates[i-1]:available=qty_total
        if i:
            signal=closes[i-1]
            candidate=None
            for k,s in enumerate(slots):
                if s['qty'] and signal>=s['target']:
                    if available>=s['qty']:
                        candidate=('sell',k);break
                    blocked+=1
            if candidate is None:
                for k,s in enumerate(slots):
                    if not s['qty'] and signal<=s['target']:
                        candidate=('buy',k);break
            if candidate:
                side,k=candidate;s=slots[k]
                p=price(opens[i],side=='buy',slip)
                if side=='sell':
                    qty=s['qty']
                    if p+1e-10>=s['target'] and qty<=vol[i]*.01*100:
                        commission=fee(qty*p);proceeds=qty*p-commission;profit=proceeds-s['cost']
                        cash+=proceeds;qty_total-=qty;available-=qty;cost_held-=s['cost'];realized+=profit
                        sales+=1;sale_dates.add(dates[i]);fees+=commission;trades+=1
                        record('sell',i,qty,p,commission,k,i-1,s['initial'],profit)
                        if s['initial']:initial_sales+=1
                        else:
                            cycles+=1;cycle_pnl+=profit;hold_days.append(day_ids[dates[i]]-s['bought_day']);cycle_costs.append(s['cost'])
                        s.update(qty=0,cost=0.0,target=p/(1+gap),initial=False)
                    else:cancelled+=1
                else:
                    qty,cost=purchase(lot_budget,p)
                    if qty and p<=s['target']+1e-10 and qty<=vol[i]*.01*100 and cash-cost>=50000-1e-7 and cost_held+cost<=50000+1e-7:
                        cash-=cost;qty_total+=qty;cost_held+=cost
                        if t0:available+=qty
                        commission=fee(qty*p);fees+=commission;trades+=1
                        s.update(qty=qty,cost=cost,target=p*(1+gap),initial=False,bought_day=day_ids[dates[i]],bought_index=i)
                        record('buy',i,qty,p,commission,k,i-1)
                    else:cancelled+=1
        equity=cash+qty_total*closes[i]
        equities.append(equity);costs.append(cost_held);cash_series.append(cash)
        max_cost=max(max_cost,cost_held);min_cash=min(min_cash,cash)
        if not (available>=0 and available<=qty_total and cash>=50000-1e-6 and cost_held<=50000+1e-6):
            raise AssertionError('settlement/cash/capital invariant violated')
    final=equities[-1];open_pnl=qty_total*closes[-1]-cost_held
    eq=np.array([100000.0]+equities)
    dd=eq/np.maximum.accumulate(eq)-1
    streak=worst_streak=0
    for date in all_dates:
        streak=0 if date in sale_dates else streak+1
        worst_streak=max(streak,worst_streak)
    unclosed=[day_ids[dates[-1]]-s['bought_day'] for s in slots if s['qty'] and not s['initial']]
    # Shared initial exposure buy/hold includes the identical initial purchases.
    bh=initial_cash+initial_qty*closes[-1]
    maxq,maxc=purchase(50000,initial_p)
    maxbh=100000-maxc+maxq*closes[-1]
    result={'gap':gap,'t0':t0,'slip':slip,'start':times[0],'end':times[-1],'days':len(all_dates),'bars':n,'cycles':cycles,'cycle_net':cycle_pnl,'cycle_return_on_40k_pct':cycle_pnl/(4*c)*100 if c else 0.0,'sales':sales,'initial_sales':initial_sales,'realized_total':realized,'inventory_pnl':open_pnl,'inventory_loss':max(0,-open_pnl),'account_pnl':final-100000,'return_pct':(final/100000-1)*100,'max_drawdown_pct':dd.min()*100,'same_exposure_bh_pct':(bh/100000-1)*100,'max_exposure_bh_pct':(maxbh/100000-1)*100,'excess_same_bh_pct':(final-bh)/100000*100,'fees':fees,'trades':trades,'avg_cost':float(np.mean(costs)),'max_cost':max_cost,'end_cost':cost_held,'min_cash':min_cash,'end_cash':cash,'median_cycle_days':float(np.median(hold_days)) if hold_days else None,'p90_cycle_days':float(np.percentile(hold_days,90)) if hold_days else None,'max_unclosed_cycle_days':max(unclosed) if unclosed else 0,'max_no_sale_days':worst_streak,'settlement_blocks':blocked,'cancelled_signals':cancelled,'identity_error':final-100000-realized-open_pnl,'end_slots':sum(s['qty']>0 for s in slots)}
    if trace:
        result['events']=events
        result['equity_curve']=[{'time':t,'equity':e,'cost':c,'cash':ca} for t,e,c,ca in zip(times,equities,costs,cash_series)]
    return result
