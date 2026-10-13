# -*- coding: utf-8 -*-
"""Clean monthly ROI for 159612 grid scenarios."""
import sys, os, importlib.util, math

spec = importlib.util.spec_from_file_location("grid_tool", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "grid_tool.py"))
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

kline = gt.fetch_kline("159612", datalen=400)
dates, opens, closes, highs, lows, vols = kline
cur = closes[-1]
CROSS_DAYS = 23  # days per month with enough movement

S = [
    ("A: 箱体 1%",       2.160, 2.066, 1.0),
    ("B: 黄金0.809 1%",  2.109, 2.053, 1.0),
    ("C: 黄金0.618 1%",  1.963, 1.860, 1.0),
    ("D: 黄金0.618 0.6%", 1.963, 1.860, 0.6),
    ("E: 箱体 0.6%",     2.160, 2.066, 0.6),
]

print(f"现价={cur}  穿越率={CROSS_DAYS}/30天  费率=万一免五(0.01%,最低1元)")
print()

for name, ub, lb, step in S:
    span = (ub - lb) / lb * 100
    step_price = lb * step / 100
    n = max(2, round(span / step))
    levels = [round(lb + i * step_price, 4) for i in range(n + 1)]
    
    inside = "✅箱体内" if lb <= cur <= ub else ("❌价格在上界上方" if cur > ub else "❌价格在下界下方")
    
    for lot in [6000, 8000]:
        total_cap = 0; total_net = 0; rounds = 0
        round_nets = []
        for i in range(n):
            bp = levels[i]; sp = levels[i+1]
            sh = math.floor(lot / bp / 100) * 100
            if sh == 0: continue
            bc = sh * bp; sc = sh * sp
            total_cap += bc
            gross = sc - bc
            cb = max(bc * 0.0001, 1.0); cs = max(sc * 0.0001, 1.0)
            net = gross - cb - cs
            total_net += net
            round_nets.append(net)
            rounds += 1
        
        avg_round = total_net / rounds if rounds else 0
        # Model: on each crossing day, ~1 round trip completes
        monthly = avg_round * CROSS_DAYS
        roi_m = monthly / total_cap * 100 if total_cap else 0
        
        print(f"{name} | {lot}元/格 | {n}档 | 全仓={total_cap:,.0f} | "
              f"每轮净={avg_round:.1f} | 月净={monthly:,.0f} | "
              f"月ROI={roi_m:.1f}% | 年化={roi_m*12:.0f}% | {inside}")
    print()