# Multi-ETF confirmed-history regression and script-only reporting

## Verified fixture: 159363
User-supplied order (price × quantity):
1. buy 1.28 × 4600
2. buy 1.273 × 4700
3. buy 1.197 × 4800
4. buy 1.169 × 5100
5. sell 1.193 × 5100
6. buy 1.156 × 5100
7. sell 1.180 × 5100
8. buy 1.157 × 5100
9. buy 1.142 × 5200
10. buy 1.120 × 4600
11. buy 1.093 × 5400
12. sell 1.115 × 5400
13. buy 1.103 × 5400

Generated labels: A,B,C,D,D,D,D,D,E,F,G,G,G. IDs: 159363-001 through 159363-013. Date fields null, not sequential invented trading dates.
Verified output using Decimal and max(turnover × 0.0001, 1 yuan) per execution:
- qty 34,400; max_grid G
- net invested 40,213.40; net unit cost 1.16899419
- remaining economic-grid buy cost 40,571.00; unit cost 1.17938953
- D cycle 004→005: gross 122.40, fees 2.00, net 120.40
- D cycle 006→007: gross 122.40, fees 2.00, net 120.40
- G cycle 011→012: gross 118.80, fees 2.00, net 116.80
- completed T net 357.60
These are fixture expectations, not future live balances. Do not import old prices (especially 1.192 versus supplied 1.193, or 1.157 versus supplied 1.156) or replace F quantity 4600 with a suggested budget quantity.

## Actual artifacts and boundaries
Session implementation: repo builders confirmed_589720.py and confirmed_159363.py; state mutation grid_state.py; persisted targets cache/grid-account/confirmed-589720.json and confirmed-159363.json. Existing midnight script grid_midnight_rollover.py was extended to enumerate both targets. Job ed9d5c85e0c4 uses daily 1 0 * * * in UTC+8, pure script, local delivery. Rediscover current configuration before asserting these details remain active.
New ETF parameter support was exercised RED (unexpected code keyword), then GREEN; related suite had four tests. This proves the tested builder behavior, not main-ledger/09:31 integration or overnight execution. Scheduler target expansion must be verified separately; editing a launcher is not proof of scheduler completion.

## Reporting trap seen in this session
589720 temporary-file CLI rollover produced qty=sellable_qty=28200, but live confirmed-589720.json still had sellable_qty=null when read for reporting. Correct answer reports null and explains initialization has not occurred; never promote temporary test output into live state. Read-only reporting independently rebuilt qty, max_grid, net invested, unit cost and T links from the persisted transaction list and asserted equality.

## Acceptance checklist
- Read exact persisted file and validate counts/IDs with code.
- Recompute accounting from stored trades; show disagreements before making claims.
- Preserve unrelated ETF state; do not seed the whole account.
- Separate user inputs, automated labels and calculated fee assumptions.
- Parameterize ETF identity through both rebuild and incremental mutation.
- Re-read each newly written target; avoid double append on rerun.
- Register new authoritative targets with the existing daily job.
- State whether midnight initialization and main-ledger integration actually occurred.
