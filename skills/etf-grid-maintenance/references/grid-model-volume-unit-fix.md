# Volume unit fix verification recipe

## Symptom
`grid_model.py` had three volume checks (lines 37, 76, 88) comparing share-denominated
quantities against lot-denominated `vol[i]*.01`. Sina K-line `volume` is in lots
(1 lot = 100 shares); the model internally uses shares. The 100x mismatch silently
rejects any ETF whose first-bar volume is below ~2.3M shares.

## Why the first fix was incomplete
The initial fix applied `*100` to lines 37 and 76 but missed line 88 (the buy-side
check). An independent reviewer caught it because the existing tests did not
exercise line 88:

- `test_initial_volume_check_compares_shares_to_shares_not_lots` used `vol=500,000`.
  The unfixed sell-side threshold (5,000) happened to equal the buy qty (~5,000
  shares), so the comparison was borderline and never rejected.
- `test_unit_mismatch_blocks_low_volume_real_etf_159569` used `vol=1,464,800`.
  The symptom there (~22,900 shares vs 14,648 unfixed threshold) is caused by
  line 37 only; the buy-side threshold (14,648) far exceeds the buy qty
  (~4,800–5,500 shares), so line 88 never rejects a valid trade in that scenario.

## Verification recipe
1. Write one test per occurrence (one per line), each with a fixture where the
   **unfixed** threshold rejects a valid trade.
2. For the buy-side check (line 88), use a later bar with `rest_vol` low enough
   that `qty > vol[i]*.01` but `qty <= vol[i]*.01*100`. Example: `rest_vol=300,000`
   gives unfixed threshold 3,000 vs buy qty ~4,800.
3. **Revert the fix temporarily and confirm the test goes red.** A test that
   passes with the bug present is not a regression test.
4. Name tests after the line they cover, not after the symptom. The 159569
   symptom is caused by line 37; claiming a test covers "the 159569 bug" when it
   only exercises line 37 overclaims.

## Fixture pattern
V-shaped price: day 1 declines 1.02→0.90 (crosses buy grid), later days rise
0.90→1.10 (cross sell grid). Flat high=low=close so signal equals next open.
`first_vol` on bar 0 only, `rest_vol` everywhere else — this lets line 37 and
lines 76/88 be exercised with different volume levels in one fixture.

## Scope
Fix only the three `vol[i]*.01` occurrences. Do not change purchase sizing,
slippage, account scale, or the 1% threshold semantics. Full suite must stay at
56 passed with 321-pool comparability preserved.

## Additional fixes applied 2026-10-14 (same session, independent review)

### `cycle_return_on_40k_pct` denominator was hardcoded
Line 125 used `cycle_pnl/40000*100` as the denominator. The actual trading-lot
capital is `4*c` (4 × `purchase(5000, initial_p)` cost, ≈20,000 CNY), not 40,000.
This understated the return-on-capital metric by ~2x. Fixed to
`cycle_pnl/(4*c)*100 if c else 0.0`.

### Initial invariant assertions were missing
Lines 59-67 now check `cash >= 50000` and `cost_held <= 50000` immediately
after initial position setup, rather than waiting for the first bar's loop
assertion (line 110). Catches parameter regressions earlier.

### T+1 settlement logic verified correct
The `available` pool resets to `qty_total` at each new trading day (line 70),
but new buys do NOT add to `available` when `t0=False` (line 102). This means
today's buys cannot be sold today — genuine T+1. Earlier criticism of this
pattern was incorrect; the reset is for overnight settlement, not a bug.
