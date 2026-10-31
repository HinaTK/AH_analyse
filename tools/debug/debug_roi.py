# -*- coding: utf-8 -*-
"""Compute monthly ROI for all 159612 scenarios."""
import sys, os, importlib.util, math

spec = importlib.util.spec_from_file_location("grid_tool", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "grid_tool.py"))
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

code = "159612"
kline = gt.fetch_kline(code, datalen=400)
dates, opens, closes, highs, lows, vols = kline
cur = closes[-1]

# --- Scenarios ---
# A: box 1%
ub_a, lb_a = 2.160, 2.066
# B: golden 0.809/0.236 w=40 1%
gtop_b, gbot_b, _ = gt.golden_top_bottom(highs, lows, 40, 3)
ub_b = gtop_b - (gtop_b - gbot_b) * (1.0 - 0.809)
lb_b = gbot_b + (gtop_b - gbot_b) * 0.236
# C: golden 0.618/0.382 w=150 1%
gtop_c, gbot_c, _ = gt.golden_top_bottom(highs, lows, 150, 3)
ub_c = gtop_c - (gtop_c - gbot_c) * (1.0 - 0.618)
lb_c = gbot_c + (gtop_c - gbot_c) * 0.382
# D: golden 0.618/0.382 w=150 0.6%
# E: box 0.6%

scenarios = [
    ("A: 箱体 1%", ub_a, lb_a, 1.0),
    ("B: 黄金0.809/0.236 1%", ub_b, lb_b, 1.0),
    ("C: 黄金0.618/0.382 1%", ub_c, lb_c, 1.0),
    ("D: 黄金0.618/0.382 0.6%", ub_c, lb_c, 0.6),
    ("E: 箱体 0.6%", ub_a, lb_a, 0.6),
]

CROSS_DAYS = 23  # out of 30

print(f"Current price: {cur}")
print(f"Crossing frequency: {CROSS_DAYS}/30 days")
print()

for name, ub, lb, step in scenarios:
    span = (ub - lb) / lb * 100
    step_price = lb * step / 100
    n = max(2, round(span / step))
    levels = [round(lb + i * step_price, 4) for i in range(n + 1)]
    
    print(f"=== {name} ===")
    print(f"  Bounds: {lb:.4f} ~ {ub:.4f} | Span: {span:.1f}% | Step: {step}% | Grids: {n}")
    print(f"  Current position: {'inside' if lb <= cur <= ub else 'OUTSIDE (above)' if cur > ub else 'OUTSIDE (below)'}")
    
    for lot in [6000, 8000]:
        total_capital = 0  # max capital deployed if all cells filled
        total_net = 0
        rounds = 0
        for i in range(n):
            bp = levels[i]
            sp = levels[i + 1]
            shares = math.floor(lot / bp / 100) * 100
            if shares == 0:
                continue
            bc = shares * bp
            sc = shares * sp
            total_capital += bc  # accumulate buy cost
            gross = sc - bc
            cb = max(bc * 0.0001, 1.0)
            cs = max(sc * 0.0001, 1.0)
            net = gross - cb - cs
            total_net += net
            rounds += 1
        
        monthly_net = total_net * CROSS_DAYS / 30
        # ROI: monthly profit / max capital deployed
        roi_monthly = monthly_net / total_capital * 100
        # Annualized
        roi_annual = roi_monthly * 12
        
        # Also: capital efficiency - profit per 10k deployed
        profit_per_10k = monthly_net / total_capital * 10000
        
        print(f"  Lot {lot}: max capital={total_capital:,.0f} | monthly net={monthly_net:,.0f} | "
              f"ROI月={roi_monthly:.1f}% | ROI年={roi_annual:.1f}% | 每万={profit_per_10k:,.0f}")
    print()

# Also compute: what if you only deploy partial capital?
print("=== 按实际占用资金算（非全仓）===")
print("假设：价格在中枢附近，约一半格子有持仓")
for name, ub, lb, step in scenarios:
    span = (ub - lb) / lb * 100
    step_price = lb * step / 100
    n = max(2, round(span / step))
    levels = [round(lb + i * step_price, 4) for i in range(n + 1)]
    center = (ub + lb) / 2
    
    for lot in [6000, 8000]:
        total_net = 0
        rounds = 0
        deployed = 0
        for i in range(n):
            bp = levels[i]
            sp = levels[i + 1]
            shares = math.floor(lot / bp / 100) * 100
            if shares == 0:
                continue
            bc = shares * bp
            sc = shares * sp
            gross = sc - bc
            cb = max(bc * 0.0001, 1.0)
            cs = max(sc * 0.0001, 1.0)
            net = gross - cb - cs
            total_net += net
            rounds += 1
            # Assume ~half the cells are filled at any time
            if i < n / 2:
                deployed += bc
        
        monthly_net = total_net * CROSS_DAYS / 30
        # If only half deployed on average
        avg_deployed = deployed if deployed > 0 else total_capital / 2
        roi_monthly = monthly_net / avg_deployed * 100 if avg_deployed > 0 else 0
        
        print(f"  {name} Lot {lot}: 月净利={monthly_net:,.0f} | 半仓≈{avg_deployed:,.0f} | ROI月≈{roi_monthly:.1f}%")