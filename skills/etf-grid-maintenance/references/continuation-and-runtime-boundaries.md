# Historical continuation and runtime boundaries

## Verified fixture: 159363 continuation
Start with the authoritative thirteen-trade fixture (max G). Append, in the user's order:
1. Buy 5,600 at 1.061: auto H, ID 159363-014.
2. Sell 5,600 at 1.077: H, ID 159363-015; pair 014→015, net 87.60 at minimum one-yuan commission per side.
3. Sell 5,400 at 1.120: G, ID 159363-016; pair 013 (buy 1.103)→016, net 89.80. Do not reuse 011, which was already paired to 012.

Verified persisted result: sixteen trades, qty 29,000, max F, net invested 34,078.80, net unit cost 1.17513103, five completed cycles with net 535.00. Historical dates remained null. Original thirteen-record prefix and the 589720 file bytes were preserved. Original bytes were backed up before atomic save and exact readback.

## Explicit inventory initialization
User then explicitly requested sellable=holding for both ETFs. Executed the validated rollover function with backups and readback: 589720 qty=sellable_qty=28,200 (max C); 159363 qty=sellable_qty=29,000 (max F). Stored update date was 2026-10-13. All original fields other than inventory/update metadata were checked unchanged. These are historical fixture assertions, not current balances for future sessions.

## Runtime failure and verified mitigation only
Screenshot showed truncated cron traceback for opening and intraday tasks. Direct execution of opening script exposed grid_account.plan reading book['positions']['sh589720'] and raising KeyError. Confirmed subledgers were not the legacy planner's input.

Added a fail-closed guard before legacy planning/confirmation and before stale-ticket intraday monitoring. Opening script emitted a clear non-executable warning; minute monitoring returned silently. Five relevant tests and both entrypoint invocations exited successfully after the mitigation. This proves the guard behavior, NOT a repaired planner or completed shared-state integration. The intraday task's original full traceback was not independently recovered; shared legacy dependencies alone do not establish an identical exception.

The production integration was still unresolved at session end. Do not describe the guard as a recommended permanent trading architecture or claim automatic recommendations resumed. Future integration must explicitly verify a shared source of truth for confirmed fills, midnight persistence, opening tickets and intraday dedup/monitoring. Also verify helper write effects before running entrypoints: load/plan may write live files even during diagnosis.
