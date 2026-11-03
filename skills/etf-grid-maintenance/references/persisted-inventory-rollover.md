# Persisted sellable inventory: implementation evidence and boundaries

## User correction
The user rejected calling sellable inventory a “口径”: it is a persisted per-ETF variable editable by scripts. They also rejected hardcoded grid labels: incremental fills must read stored max_grid. Both corrections belong in state management, not merely report wording.

## Verified session pattern
- Superpowers-derived test-driven-development loaded; new midnight test failed because grid_state module was absent, then passed after implementation.
- A second RED exposed missing record(); subsequent GREEN covered buy leaving sellable unchanged, sell decrementing both balances, pointer persistence, and insufficient inventory rejecting without a write.
- Combined targeted suite: 3 tests passed. Actual CLI execution on a temporary file plus JSON readback confirmed qty=sellable_qty=28,200 and max_grid=C. This did NOT execute the production cron wrapper or prove first overnight firing.
- Implemented repo files: grid_state.py and test_grid_state.py; commit 648bc43. The configured wrapper was grid_midnight_rollover.py in managed Hermes scripts.
- Created/read back task ed9d5c85e0c4, cron `1 0 * * *`, no_agent=true, deliver=local, enabled=true; next run was 2026-10-14 00:01 +08:00. These are historical deployment handles, not IDs to reuse without live discovery.

## Coverage at session end
Only confirmed-589720.json was targeted. Original main ledger and 09:31 fill/suggestion integration were NOT connected; other ETFs were not reconciled. Production sellable initialization awaited the overnight task. Do not present this as whole-system completion.

## Acceptance tests for future work
1. Persist/load per-ETF qty, sellable_qty, max_grid; no report-only derivation.
2. Rollover validates authoritative transaction IDs and nonnegative running inventory; atomically saves qty and sellable_qty.
3. Same-date retry after an intraday sale leaves reduced sellable inventory untouched; older-date invocations cannot rewind state.
4. Confirmed buy keeps sellable unchanged; confirmed sell validates pooled sellable, updates both, and persists transaction/cycle identifiers together.
5. Rejected operations leave the original file byte-equivalent; unrelated ETFs/fields remain intact.
6. Midnight and fill paths share a concurrency-safe write mechanism; no lost updates between reading and replacing JSON.
7. Cron wrapper uses a registered state-file list for every reconciled ETF rather than silently hardcoding one forever. Test the deployed wrapper on isolated fixtures before declaring operational integration.
8. Never treat replay build() output with sellable_qty=null as an incremental overwrite of a live initialized state. Keep replay/reconciliation separate from ongoing updates.
