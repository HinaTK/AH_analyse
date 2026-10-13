# -*- coding: utf-8 -*-
"""Compute profit for multiple scenarios on 159612."""
import sys, os, importlib.util, math

spec = importlib.util.spec_from_file_location("grid_tool", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "grid_tool.py"))
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

code = "159612"
kline = gt.fetch_kline(code, datalen=400)
dates, opens, closes, highs, lows, vols = kline
cur = closes[-1]

# --- Scenario A: Box mode (default) 1% spacing ---
ub_a, lb_a = 2.160, 2.066
span_a = (ub_a - lb_a) / lb_a * 100
step_a = 1.0
n_a = max(2, round(span_a / step_a))

# --- Scenario B: Golden 0.809/0.236 window=40, 1% ---
gtop, gbot, _ = gt.golden_top_bottom(highs, lows, 40, 3)
ub_b = gtop - (gtop - gbot) * (1.0 - 0.809)
lb_b = gbot + (gtop - gbot) * 0.236
span_b = (ub_b - lb_b) / lb_b * 100
step_b = 1.0
n_b = max(2, round(span_b / step_b))

# --- Scenario C: Golden 0.618/0.382 window=150, 1% ---
gtop_c, gbot_c, _ = gt.golden_top_bottom(highs, lows, 150, 3)
ub_c = gtop_c - (gtop_c - gbot_c) * (1.0 - 0.618)
lb_c = gbot_c + (gtop_c - gbot_c) * 0.382
span_c = (ub_c - lb_c) / lb_c * 100
step_c = 1.0
n_c = max(2, round(span_c / step_c))

# --- Scenario D: Golden 0.618/0.382 window=150, 0.6% ---
step_d = 0.6
n_d = max(2, round(span_c / step_d))

# --- Scenario E: Box 0.6% ---
span_e = span_a
step_e = 0.6
n_e = max(2, round(span_e / step_e))

scenarios = [
    ("A: 箱体 1%", ub_a, lb_a, step_a, n_a),
    ("B: 黄金0.809/0.236 1%", ub_b, lb_b, step_b, n_b),
    ("C: 黄金0.618/0.382 1%", ub_c, lb_c, step_c, n_c),
    ("D: 黄金0.618/0.382 0.6%", ub_c, lb_c, step_d, n_d),
    ("E: 箱体 0.6%", ub_a, lb_a, step_e, n_e),
]

print(f"Current price: {cur}")
print()

for name, ub, lb, step, n in scenarios:
    span = (ub - lb) / lb * 100
    step_price = lb * step / 100
    
    print(f"=== {name} ===")
    print(f"  Bounds: {lb:.4f} ~ {ub:.4f} | Span: {span:.1f}% | Step: {step}% | Grids: {n}")
    
    # Build levels
    levels = [round(lb + i * step_price, 4) for i in range(n + 1)]
    
    for lot in [6000, 8000]:
        total_net = 0
        total_gross = 0
        rounds = 0
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
            total_gross += gross
            total_net += net
            rounds += 1
        avg_net = total_net / rounds if rounds else 0
        print(f"  Lot {lot}: {rounds} rounds, gross={total_gross:.2f}, net={total_net:.2f}, avg/round={avg_net:.2f}")
    print()

# Monthly projection
print("=== Monthly projection (23/30 days crossing) ===")
for name, ub, lb, step, n in scenarios:
    step_price = lb * step / 100
    levels = [round(lb + i * step_price, 4) for i in range(n + 1)]
    for lot in [6000, 8000]:
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
            gross = sc - bc
            cb = max(bc * 0.0001, 1.0)
            cs = max(sc * 0.0001, 1.0)
            net = gross - cb - cs
            total_net += net
            rounds += 1
        daily = total_net * 23 / 30
        monthly = daily * 30
        print(f"  {name} Lot {lot}: est monthly net = {monthly:.2f} CNY")