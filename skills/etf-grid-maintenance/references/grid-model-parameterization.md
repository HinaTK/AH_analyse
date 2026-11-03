# Grid Model Parameterization — 2026-10-15

## What happened

`grid_model.py` had three places where the per-lot budget was hardcoded:

| Location | Code | Issue |
|----------|------|-------|
| Line 34 (core position) | `purchase(10000, initial_p)` | Should be `lot_budget * 2` |
| Line 35 (trading lots) | `purchase(5000, initial_p)` | Should be `lot_budget` |
| Line 100 (rebuy) | `purchase(5000, p)` | Should be `lot_budget` |

And `engine.py` line 126 had `gap=.02` hardcoded in the caller.

## Fix pattern

1. Add the parameter to `simulate()` signature with a backward-compatible default:
   `def simulate(frame, gap=.02, t0=False, slip=.0005, trace=False, lot_budget=5000)`

2. Replace all internal hardcoded values with the parameter:
   - Core position: `purchase(lot_budget * 2, initial_p)`
   - Trading lots: `purchase(lot_budget, initial_p)`
   - Rebuy: `purchase(lot_budget, p)`

3. Add the parameter to `run_research()` in `engine.py`:
   `def run_research(..., lot_budget=5000, gap=0.02)`

4. Pass through to `simulate()`:
   `model.simulate(f, gap=gap, t0=False, slip=.0005, trace=w=='full', lot_budget=lot_budget)`

## Lessons

- **Check every call site, not just the obvious one.** The rebuy path (line 100) was missed in the first pass because it's in a different branch of the simulation loop.
- **Two files, two hardcodings.** The `gap` was in `engine.py`, the `lot_budget` was in `grid_model.py`. Both needed changing.
- **Default values must preserve backward compatibility.** `lot_budget=5000` and `gap=0.02` keep existing callers working without modification.
- **The `cycle_return_on_40k_pct` metric name still says 40k** even though the denominator is now `4*c` (actual trading-lot capital). The name is a legacy artifact; the value is correct. Renaming the key would break downstream consumers that read it from CSV.

## Verification

bash
python -c "compile(open('grid_model.py').read(), 'grid_model.py', 'exec')"
python -m pytest tools/etf_research/test_research.py -q
python -m tools.etf_research.run_single 159363 0.015 63 0.0005


