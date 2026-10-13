# -*- coding: utf-8 -*-
"""Compute aggressive (0.6% spacing, golden ratio) profit for 159612."""
import sys, os, importlib.util, math

spec = importlib.util.spec_from_file_location("grid_tool", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "grid_tool.py"))
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

code = "159612"
kline = gt.fetch_kline(code, datalen=400)
dates, opens, closes, highs, lows, vols = kline
cur = closes[-1]

# Golden ratio: window=40, 0.809/0.236
gtop, gbot, glines = gt.golden_top_bottom(highs, lows, 40, 3)
upper = gtop - (gtop - gbot) * (1.0 - 0.809)
lower = gbot + (gtop - gbot) * 0.236

# Pressure/support correction
pressures, supports = gt.pressure_support_levels(highs, lows, 250)
if pressures and cur >= upper * (1.0 - 4.0/100.0):
    for p, cnt in pressures:
        gap = (p / upper - 1) * 100.0
        if 1.0 <= gap <= 5.0:
            upper = p
            break

# 0.6% spacing
adr = gt.ma([(highs[i] - lows[i]) / closes[i] for i in range(len(closes)-20, len(closes))], 20)
best_step = max(round(adr * 100 * 0.7, 1), 0.6)
step_pct = best_step  # 0.6%
step_price = lower * step_pct / 100.0
n_grids = max(2, round((upper - lower) / step_price))

print(f"Price: {cur}")
print(f"Golden bounds: lower={lower:.4f}, upper={upper:.4f}")
print(f"Span: {(upper-lower)/lower*100:.1f}%")
print(f"Step: {step_pct}% = {step_price:.5f} per share")
print(f"Grids: {n_grids}")
print()

# Build grid levels
levels = []
for i in range(n_grids + 1):
    price = round(lower + i * step_price, 4)
    levels.append(price)
    if i > 0:
        levels[-1] = round(levels[-2] * (1 + step_pct/100), 4)

print("Grid levels:")
for i, p in enumerate(levels):
    direction = "BUY" if p <= cur else "SELL"
    marker = " <-- current" if abs(p - cur) < 0.005 else ""
    print(f"  Grid {i}: {p:.4f} [{direction}]{marker}")

print()

# Per-round profit with different lot sizes
# User's context: 6000/8000 per cell, 万一免五 (0.01%, min 1)
for lot in [6000, 8000]:
    print(f"=== Lot size: {lot} CNY ===")
    total_gross = 0
    total_net = 0
    round_count = 0
    for i in range(len(levels) - 1):
        buy_price = levels[i]
        sell_price = levels[i + 1]
        shares = math.floor(lot / buy_price / 100) * 100
        if shares == 0:
            continue
        buy_cost = shares * buy_price
        sell_proceeds = shares * sell_price
        gross = sell_proceeds - buy_cost
        comm_buy = max(buy_cost * 0.0001, 1.0)
        comm_sell = max(sell_proceeds * 0.0001, 1.0)
        net = gross - comm_buy - comm_sell
        total_gross += gross
        total_net += net
        round_count += 1
        print(f"  Round {i}: buy {shares} @{buy_price:.4f}={buy_cost:.0f} → sell @{sell_price:.4f}={sell_proceeds:.0f} | gross={gross:.2f} comm={comm_buy+comm_sell:.2f} net={net:.2f}")
    print(f"  Total ({round_count} rounds): gross={total_gross:.2f}, net={total_net:.2f}")
    print(f"  Avg net/round: {total_net/round_count:.2f}")
    print()

# Daily/weekly estimate based on crossing frequency
# Screener says ~23 days in last 30 had >=0.6% range
cross_days = 23
print(f"=== Projection (based on {cross_days}/30 days crossing) ===")
for lot in [6000, 8000]:
    shares_per_round = math.floor(lot / lower / 100) * 100
    gross_per_round = shares_per_round * lower * step_pct / 100
    comm_per_round = 2.0  # min 1 each side
    net_per_round = gross_per_round - comm_per_round
    daily_rounds = cross_days / 30  # ~0.77 rounds/day
    weekly = daily_rounds * 7 * net_per_round
    monthly = daily_rounds * 30 * net_per_round
    print(f"  Lot {lot}: net/round={net_per_round:.2f}, est weekly={weekly:.2f}, est monthly={monthly:.2f}")