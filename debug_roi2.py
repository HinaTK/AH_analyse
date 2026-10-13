# -*- coding: utf-8 -*-
"""Monthly ROI for 159612 grid scenarios."""
import sys, os, importlib.util, math

spec = importlib.util.spec_from_file_location("grid_tool", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "grid_tool.py"))
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

kline = gt.fetch_kline("159612", datalen=400)
dates, opens, closes, highs, lows, vols = kline
cur = closes[-1]
CROSS_DAYS = 23  # per 30 days

# Scenario definitions
S = [
    ("A: 箱体 1%",       2.160, 2.066, 1.0),
    ("B: 黄金0.809 1%",  2.109, 2.053, 1.0),
    ("C: 黄金0.618 1%",  1.963, 1.860, 1.0),
    ("D: 黄金0.618 0.6%", 1.963, 1.860, 0.6),
    ("E: 箱体 0.6%",     2.160, 2.066, 0.6),
]

print(f"现价={cur}  穿越率={CROSS_DAYS}/30天")
print()

for name, ub, lb, step in S:
    span = (ub - lb) / lb * 100
    step_price = lb * step / 100
    n = max(2, round(span / step))
    levels = [round(lb + i * step_price, 4) for i in range(n + 1)]
    
    inside = "✅在内" if lb <= cur <= ub else ("❌上方" if cur > ub else "❌下方")
    
    for lot in [6000, 8000]:
        total_cap = 0; total_net = 0; rounds = 0
        for i in range(n):
            bp = levels[i]; sp = levels[i+1]
            sh = math.floor(lot / bp / 100) * 100
            if sh == 0: continue
            bc = sh * bp; sc = sh * sp
            total_cap += bc
            gross = sc - bc
            cb = max(bc * 0.0001, 1.0); cs = max(sc * 0.0001, 1.0)
            total_net += gross - cb - cs
            rounds += 1
        
        monthly = total_net * CROSS_DAYS / 30
        roi_m = monthly / total_cap * 100 if total_cap else 0
        roi_a = roi_m * 12
        
        print(f"{name} | {lot}元/格 | {n}档 | 全仓={total_cap:,.0f} | 月净={monthly:,.0f} | 月ROI={roi_m:.1f}% | 年化={roi_a:.1f}% | {inside}")
    
    # Also: half-deployed ROI (more realistic)
    for lot in [6000, 8000]:
        total_net = 0; rounds = 0; deployed = 0
        for i in range(n):
            bp = levels[i]; sp = levels[i+1]
            sh = math.floor(lot / bp / 100) * 100
            if sh == 0: continue
            bc = sh * bp; sc = sh * sp
            gross = sc - bc
            cb = max(bc * 0.0001, 1.0); cs = max(sc * 0.0001, 1.0)
            total_net += gross - cb - cs
            rounds += 1
            if i < n // 2:
                deployed += bc
        
        monthly = total_net * CROSS_DAYS / 30
        roi_m = monthly / deployed * 100 if deployed else 0
        print(f"  └ 半仓(≈{deployed:,.0f}): 月净={monthly:,.0f} | 月ROI={roi_m:.1f}% | 年化={roi_m*12:.1f}%")
    print()