# Grid EOD Decision Script Overview

The `grid_eod_decision.py` script is the core of the after-close evaluation for the ETF grid trading system.

## Responsibilities
1. Collect verified closing prices from Tencent (via `fetch_daily`)
2. Cross-check with the broker's closing snapshot to ensure data integrity
3. Load the current ledger state (positions, cash, history)
4. Assess each ETF for:
   - Migration status (if applicable)
   - Grid efficiency (via completed cycles analysis)
   - Low inventory triggers for rebase consideration
   - Recent sell/buy patterns to avoid false signals
5. Generate a decision report for each ETF (HOLD_GRID, WAIT_PULLBACK, REVIEW_REBASE, ROTATION_REVIEW, MIGRATION_EXIT)
6. Store the report as a JSON file in `cache/grid-account/eod/YYYY-MM-DD.json`
7. Generate a human-readable preview note for the next trading session

## Key Functions
- `fetch_daily(code)`: Downloads and validates day‑line data
- `assess(code, book, bars, day)`: Core decision logic for a single ETF
- `next_day_note(report, day, phase)`: Formats the preview message sent to Feishu
- `load_for_session(day)`: Loads the previous day's decision report
- `main()`: Entry point scheduled to run at 15:20 on trading days

## Safety Guarantees
- The script is **read‑only** with respect to broker orders; it never sends or modifies any exchange‑facing instructions.
- It only writes to local cache files (EOD reports) and the preview note.
- All ledger modifications (like cleaning unconfirmed orders) are done via separate functions that are explicitly called.