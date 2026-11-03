# EOD enumeration acceptance

## Verified root cause and completed repair (2026-10-14)
Scheduled 15:20 response reported `行情或状态未验证：不生成执行建议；'sz159992'`. Job b3097b45fafa output at 15:20:29 matched the screenshot. States and snapshots enumerated three holdings, while eod_main fetched daily bars using legacy CODES containing only sh589720 and sz159363. Missing bar key sz159992 caused report assembly to abort; this was not evidence of network outage or corrupt ledger.

The later authorized repair replaced that fetch loop with H.held_codes(). test_eod_holdings_regression invoked real eod_main with isolated HTTP responses, holdings and output directory: original code reproduced KeyError, patched code fetched all three symbols, assembled all decisions and saved identical JSON with executable=false. The independent reviewer approved the fix and recommended freezing the test clock; final test used a fixed 2026-10-14 15:30 Beijing time to avoid time-of-day fragility. Final grid suite: 37 passed; separate retirement regression: 1 passed. Scoped commit cf55496 was pushed and remote hash verified; unrelated 159612 research changes were excluded.

The deployed managed scripts/grid_eod_decision.py was actually rerun. Exact cache/grid-account/eod/2026-10-14.json was read back and contained all three holdings. All three confirmed ledger SHA256 values were unchanged before/after. Quotes were cross-checked against same-day daily closes; no fabricated fills or broker actions were used. This establishes actual entrypoint success and saved output, not a subsequent scheduled delivery.

## Reusable acceptance procedure
1. Inspect exact scheduled output; compare required state symbols with fetched snapshot/bar symbols before blaming the feed.
2. Make production valuation input enumeration consistent with persisted holdings, including inactive holdings. Ideally snapshot that enumeration once per operation; do not claim this architectural hardening was implemented by the one-line fix.
3. Reproduce through the fetch-and-assembly entrypoint in temp scope; complete handwritten bar dictionaries alone cannot catch a fetch-loop omission.
4. Freeze time explicitly after close. Mocking phase() alone leaves separate hour/minute gates active.
5. Verify decisions cover expected holdings, persisted JSON equals returned output and executable remains false. Missing input must not become fabricated zero holdings or silently dropped ETFs.
6. Exercise deployed entrypoint with real feed, read exact saved report, and compare authoritative ledger hashes before/after. Report a feed blocker honestly if actual rerun fails.
7. Independent review and scoped commit/push; preserve unrelated dirty files, data and logs.

## Completion and notification boundaries
A generic fail-closed exception is failed report generation, not completed risk checking. A report can succeed while recent-window efficiency, baseline rebase and rotation remain explicitly unverified; do not infer those from the task title. Original failure delivery and manual rerun success are distinct artifacts.

Late delegation messages describe the child at its completion time, not necessarily final parent state. Compare scope/version first: implementation may say uncommitted after parent already committed; review may run a smaller suite than final acceptance. Incorporate new blockers if real, but do not duplicate fills, rerun completed work unnecessarily or repeat an entire completion narrative.
