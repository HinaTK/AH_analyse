# -*- coding: utf-8 -*-
"""Debug: fetch 159612 kline and print golden_top_bottom + evaluate internals."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grid_tool as gt

code = "159612"
kline = gt.fetch_kline(code, datalen=400)
if not kline:
    print("NO KLINE"); sys.exit(1)
dates, opens, closes, highs, lows, vols = kline
print(f"KLINE: {len(closes)} days, first={dates[0]}, last={dates[-1]}")
print(f"Last close: {closes[-1]}")
print(f"Last 5 closes: {closes[-5:]}")
print(f"Last 5 highs: {highs[-5:]}")
print(f"Last 5 lows: {lows[-5:]}")

# golden_top_bottom
gtop, gbot, glines = gt.golden_top_bottom(highs, lows, 150, 3)
print(f"\nGOLDEN: top={gtop:.4f}, bottom={gbot:.4f}")
print(f"Lines: {[f'{x:.4f}' for x in glines]}")

# upper_box at 0.618
ub = gtop - (gtop - gbot) * (1.0 - 0.618)
lb = gbot + (gtop - gbot) * 0.382
print(f"upper_box(0.618)={ub:.4f}, lower(0.382)={lb:.4f}")
print(f"cur={closes[-1]}, cur > ub*1.002? {closes[-1] > ub*1.002}")
print(f"cur < lb*0.998? {closes[-1] < lb*0.998}")

# pressure/support
pressures, supports = gt.pressure_support_levels(highs, lows, 250)
print(f"\nPressures (>cur): {[(f'{p:.4f}', c) for p,c in pressures[:5]]}")
print(f"Supports (<cur): {[(f'{s:.4f}', c) for s,c in supports[:5]]}")

# ma20 cross count
ma20s = []
s = sum(closes[:20])
ma20s.append(s/20)
for i in range(20, len(closes)):
    s += closes[i] - closes[i-20]
    ma20s.append(s/20)
n = len(closes)
start_i = max(20, n - 150 + 1)
cross = 0
for i in range(start_i, n):
    ma_idx = i - 19
    prev_idx = ma_idx - 1
    if prev_idx < 0 or ma_idx >= len(ma20s):
        continue
    if (closes[i] - ma20s[ma_idx]) * (closes[i-1] - ma20s[prev_idx]) < 0:
        cross += 1
print(f"\nMA20 crosses in last 150 days: {cross}")

# box_high/box_low for passes()
box_high = gtop
box_low = gbot
print(f"\n_box_high={box_high:.4f}, _box_low={box_low:.4f}")
print(f"cur > _box_high? {closes[-1] > box_high}")
print(f"cur < _box_low? {closes[-1] < box_low}")