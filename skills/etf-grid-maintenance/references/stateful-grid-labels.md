# Stateful labels: authoritative replay and repeated cycles

## Correction captured
The user requires current maximum A–Z sequence per ETF to generate trade labels. Hardcoding A/B/C/D/E into an otherwise numerical input bypasses that requirement, even if the resulting labels happen to be correct.

## Deterministic fixture
Input contains only side, quantity, price, in this supplied order (no dates provided):

| # | Side | Qty | Price | Expected label | Max after |
|---|---|---:|---:|---|---|
|1|buy|9200|0.877|A|A|
|2|buy|9400|0.859|B|B|
|3|buy|9600|0.829|C|C|
|4|sell|9600|0.846|C|B|
|5|buy|9600|0.833|C|C|
|6|buy|9900|0.806|D|D|
|7|buy|10000|0.794|E|E|
|8|sell|10000|0.806|E|D|
|9|sell|9900|0.818|D|C|

Expected: qty 28200; net invested 23746.80; completed cycles C(first), E, D; net profits 161.20, 118.00, 116.80; total 396.00 under max(turnover*0.0001,1) per execution. Remaining economic cycles A/B/C(second). Dates and sellable quantity remain unknown. Next label buy D / sell C is a sequence result, NOT authorization to trade.

## Required tests
- RED before implementation: missing maximum-sequence field / labels supplied as input must fail the intended behavioral assertion.
- Verify final max C and every label above; production input rows have no grid-label argument.
- Three buy/sell cycles at the same letter must produce three distinct buy→sell ID pairs; no reuse of an earlier closed buy.
- Invalid sell at empty state and buy beyond Z fail closed; partial fills require an explicit supported policy.
- Full replay is deterministic and replaces only the named ETF; incremental recording loads that ETF's stored maximum and updates it atomically with trade history.
- Test isolation: importing or running tests never calls live seed/save/apply; no invented trading dates.

## Evidence boundary
A pure isolated builder with stack depth was exercised successfully in this session, with output persisted to an independent 589720 subledger. That validates replay calculations and labels only. It does not demonstrate production grid_account integration, incremental persistence, pooled T+1 enforcement, or full-suite coverage. Do not present those as complete until separately exercised.
