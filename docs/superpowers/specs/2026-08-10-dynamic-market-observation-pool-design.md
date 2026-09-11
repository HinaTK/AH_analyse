# Dynamic Market Observation Pool Design

## Objective

Every pre-market, intraday, and post-market composite analysis must rebuild its 4-6 stock observation pool from the current A-share and Hong Kong market snapshot. Previous reports and pre-market lists are comparison inputs only; they are never the default candidate pool.

## Selection Flow

1. Scan current A-share and Hong Kong sector leaders, laggards, turnover expansion, session highs, resilient stocks, and positive-catalyst laggards.
2. Build a candidate set covering the five intraday questions: leader, volume confirmation, new-high confirmation, resilience, and catalyst/price divergence.
3. Rank candidates using current relative return, turnover confirmation, position within the intraday range, catalyst/price consistency, and cross-market representativeness.
4. Select 4-6 stocks from the current ranking. A previous-pool stock survives only when it independently requalifies in the new scan.
5. Record the scan timestamp, selection basis, and notable exclusions in the saved report.

## Failure Handling

If a sufficiently broad current-market scan is unavailable, the report must label the result `有限样本观察池`, disclose the missing coverage, and must not describe the pool as dynamic or market-wide.

## Current Report Correction

The six-stock pool in `docs/analyse/market-composite-analysis-20260810-115134.md` is invalid because it was inherited from the pre-market list. It must be replaced after a fresh A/H scan; HSBC Holdings is evidence of the omission, not a one-for-one manual patch.

## Verification

- Repository instructions explicitly require dynamic rebuilding and prohibit automatic carry-over.
- The market-composite skill repeats the requirement at both evidence-collection and observation-pool stages.
- The corrected report contains a dynamic-scan audit, 4-6 newly selected stocks, scan timestamps, inclusion reasons, exclusions, and failure/trigger levels.
