# -*- coding: utf-8 -*-
"""Compute golden ratio grid params for 159612 at various window sizes."""
import sys, os, importlib.util

spec = importlib.util.spec_from_file_location("grid_tool", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "grid_tool.py"))
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

code = "159612"
kline = gt.fetch_kline(code, datalen=400)
dates, opens, closes, highs, lows, vols = kline
cur = closes[-1]
print(f"Current price: {cur}")
print(f"Data: {len(closes)} days, {dates[0]} to {dates[-1]}")
print()

for w in [30, 40, 50, 60, 80, 100, 120, 150]:
    gtop, gbot, glines = gt.golden_top_bottom(highs, lows, w, 3)
    ub = gtop - (gtop - gbot) * (1.0 - 0.618)
    lb = gbot + (gtop - gbot) * 0.382
    span = (ub - lb) / lb * 100
    n_grids = max(2, round(span / 1.0))  # rough estimate with 1% step
    above_ub = cur > ub * 1.002
    below_lb = cur < lb * 0.998
    status = "REJECT" if (above_ub or below_lb) else "OK"
    print(f"window={w:3d}: top={gtop:.4f} bot={gbot:.4f} | 0.618={ub:.4f} 0.382={lb:.4f} | span={span:.1f}% | cur_pos={(cur-gbot)/(gtop-gbot)*100:.1f}% | {status}")
    
    # Also compute with 0.809/0.236 (wider)
    ub2 = gtop - (gtop - gbot) * (1.0 - 0.809)
    lb2 = gbot + (gtop - gbot) * 0.236
    span2 = (ub2 - lb2) / lb2 * 100
    status2 = "REJECT" if (cur > ub2 * 1.002 or cur < lb2 * 0.998) else "OK"
    print(f"         0.809={ub2:.4f} 0.236={lb2:.4f} | span={span2:.1f}% | {status2}")
    
    # Pressure/support correction
    pressures, supports = gt.pressure_support_levels(highs, lows, min(w+50, 250))
    if pressures:
        nearest_p = pressures[0]
        print(f"         nearest pressure above: {nearest_p[0]:.4f} ({nearest_p[1]} touches)")
    if supports:
        nearest_s = supports[0]
        print(f"         nearest support below: {nearest_s[0]:.4f} ({nearest_s[1]} touches)")
    print()