# Candidate Evaluation Outside the Main 5-Minute Engine

## Status: ACTIVE (updated 2026-10-14)

The `initial orders exceed 1% first bar volume` blocker was a **unit bug**, now fixed.
See `references/grid-model-volume-unit-fix.md` for the root cause and fix.

The 5-minute engine now works for low-volume ETFs (159569 verified, full suite passes).

## When to use the daily K-line method

The daily K-line crossing analysis remains useful as a **lightweight profitability screen** when:

- The 5-minute engine is unavailable for other reasons (network, coverage gaps, etc.)
- You need a quick estimate before running the full 321-pool research
- You're evaluating a candidate outside the 321 eligibility snapshot

## Daily K-line crossing analysis

1. Build grid levels from `etf-grid-screener` parameters (lower, upper, gap, LOT_BUDGET)
2. Calculate per-round net: `sell proceeds − buy costs − 2× commission`
   (commission = `max(1.0, value × 0.0001)`, 万一免五)
3. Fetch daily K-lines: `grid_tool.fetch_kline(code, 63)` returns
   `(dates, opens, closes, highs, lows, vols)` or `None`
4. Count days where `prev_close < sell_level ≤ high` for any grid level
5. Conservative estimate: `crossings × 0.5` round trips over the window
6. Monthly estimate: `round_trips / 63 × 21 × avg_net_per_round`

**Caveat**: This is a reference range, not a prediction. It assumes every
crossing leads to a completed round trip. Real results will be lower.

## Critical: Verify box bounds against actual price range

`etf-grid-screener` reports box bounds from an 80-day window. Always cross-check
against the actual 63-day price range before trusting the grid levels.

Example (159569, 2026-07-09 → 2026-10-14):
- Screener box: 1.378 – 1.480
- Actual range: 1.280 – 1.445
- Upper bound 1.480 **never touched**; lower bound 1.378 **breached**
- Only 73.4% of days closed inside the reported box

If the reported bounds don't match actual price action, re-derive grid levels
from the actual range before estimating profitability.

## Tool: `tools/etf_research/run_single.py`

Standalone single-ETF simulation that doesn't depend on BASE baseline window
selection. Handles the 1% volume constraint gracefully.

bash
python -m tools.etf_research.run_single <code> [gap] [sessions] [slip]


### Usage notes

- Pass bare 6-digit code (e.g. `159569`); the script auto-prefixes `sh`/`sz`
- Default: 2% gap, 63 sessions, 0.05% slippage
- Output saved to `cache/grid-research/single_<code>.json`
- If the volume constraint still blocks, the script reports it and exits cleanly
  rather than crashing

## Test suite for grid_model.py fixes

When patching `grid_model.py`, run the full test suite to verify no regressions:

bash
cd D:/Code/AH_analyse
python -m pytest tools/etf_research/ -q


Current status (2026-10-14): **56 passed** across 6 test files.

Key test files:
- `test_grid_model_units.py` (3 tests) — volume unit fix regression tests
- `test_research.py` (9 tests) — research pipeline, window selection, ranking
- `test_pair_review.py` (39 tests) — per-holding pair review logic
- `test_entrypoints.py` (2 tests) — CLI entrypoints
- `test_plan_a_159612.py` (3 tests) — 159612 plan validation

### Writing regression tests for unit bugs

When fixing a unit mismatch or similar comparison bug:

1. **Write one test per occurrence** — one per line in the source, not one per symptom
2. **Each test must go RED with the bug present** — revert the fix temporarily and
   confirm the test fails. A test that passes with the bug is not a regression test
3. **Name tests after the line they cover**, not after the symptom. Example: a test
   for line 88 should be named `test_line88_*`, not `test_159569_*` (the 159569
   symptom is caused by line 37, not line 88)
4. **Use separate volume levels per fixture** — `first_vol` on bar 0 for line 37,
   `rest_vol` on later bars for lines 76/88, so each line can be exercised independently
