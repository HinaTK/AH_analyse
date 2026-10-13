# -*- coding: utf-8 -*-
"""Debug: call evaluate() directly and trace each filter."""
import sys, os, types, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

# load grid_tool as module
import importlib.util
spec = importlib.util.spec_from_file_location("grid_tool", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "grid_tool.py"))
gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gt)

code = "159612"
kline = gt.fetch_kline(code, datalen=400)
dates, opens, closes, highs, lows, vols = kline
print(f"KLINE: {len(closes)} days, last close={closes[-1]}")

# Build args matching --bounds golden --gold_window 60 --gold_lag 3
# We need to construct args namespace
args = types.SimpleNamespace()
args.bounds = "golden"
args.gold_window = 60
args.gold_lag = 3
args.gold_upper = 0.618
args.gold_lower = 0.382
args.gold_pressure_window = 250
args.gold_pressure_tol = 5.0
args.gold_pressure_min_gap = 1.0
args.gold_correct_near = 4.0
args.gold_bin_frac = 0.004
args.gold_min_touches = 3
args.gold_min_ma20_cross = 0
args.conv = 6.0
args.amp20 = 8.0
args.amp40 = 12.0
args.vol = 30.0
args.trend_max = 5.0
args.box_window = 80
args.box_min_days = 20
args.box_max_stale_days = 50
args.box_min_alternations = 3
args.lower_rail_stale = 40
args.upper_buffer = 1.5
args.box_min_grids = 3
args.box_tol = 1.0
args.adr_mult = 1.0
args.adr_window = 20
args.step = 0.0
args.grids = 0
args.min_amount = 20000000.0
args.min_amount_a = 100000000.0
args.min_amount_ystd = 100000000.0
args.liquid_all = False
args.max_premium = 10.0
args.no_dedup = True
args.no_fill = True
args.max_results = 15
args.min_results = 10
args.top = 9999
args.no_a_share = False
args.refresh_a_pool = False
args.pool_max_age = 30
args._now = "2026-10-13 14:30"

cand, err = gt.evaluate(code, "标普500ETF国泰", "跨境", kline, args)
if err:
    print(f"EVAL FAILED: {err}")
else:
    print(f"EVAL OK: score={cand['score']:.1f}, upper={cand['upper']:.4f}, lower={cand['lower']:.4f}")
    print(f"  cur={cand['cur']}, step={cand['step_pct']}%, grids={cand['grids']}")
    print(f"  drift={cand['drift']:.1f}%, conv={cand['conv']:.1f}%")
    print(f"  amp20={cand['amp20']:.1f}%, amp40={cand['amp40']:.1f}%, vol={cand['ann_vol']:.1f}%")
    print(f"  _box_high={cand['_box_high']:.4f}, _box_low={cand['_box_low']:.4f}")
    print(f"  _ma20_cross={cand['_ma20_cross']}")
    print(f"  _making_new_low={cand['_making_new_low']}")
    print(f"  gold_top={cand['gold_top']:.4f}, gold_bottom={cand['gold_bottom']:.4f}")

# Now test passes() at each stage
for i, st in enumerate(gt.STAGES):
    ok, reason = gt.passes(cand, args, st)
    print(f"  Stage {i}: {'PASS' if ok else 'FAIL - ' + reason}")