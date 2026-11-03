# Authoritative replacement fixture: economic grid accounting

Use as a deterministic arithmetic fixture, NOT current holdings or inferred dates.
User-supplied order for one ETF:
1. buy 9,200 @ 0.877 (A)
2. buy 9,400 @ 0.859 (B)
3. buy 9,600 @ 0.829 (C cycle 1)
4. sell 9,600 @ 0.846 (closes C cycle 1)
5. buy 9,600 @ 0.833 (C cycle 2, remains open)
6. buy 9,900 @ 0.806 (D)
7. buy 10,000 @ 0.794 (E)
8. sell 10,000 @ 0.806 (closes E)
9. sell 9,900 @ 0.818 (closes D)

Fee = max(turnover × 0.0001, 1 yuan); all nine fees are 1 yuan. Decimal calculation and isolated-module test verified:
- Shares: 28,200.
- Net invested: 23,746.80; net-invested unit cost: 0.84208511.
- Completed economic-grid cycles: C 161.20 net; E 118.00; D 116.80. Gross 402.00, allocated round-trip fees 6.00, net 396.00.
- Open economic grid purchase costs including fees: A 8,069.40; B 8,075.60; C cycle 2 7,997.80; total 24,142.80, unit cost 0.85612766.
- Conservation check: open economic purchase cost minus completed net profits = net invested.
- Pair references by sequence: 003→004, 007→008, 006→009. Sequence 005 must not be paired to sale 004.

No execution dates were supplied: dates and sellable quantity must remain unknown. These grid assignments describe economic matching, not which settled shares physically funded each sale.

## Safety and evidence findings
Calling production seed() during a dry-run overwrote an existing ledger. A later backup captured the damaged state. This is not evidence that the original history never existed. Whole-ticket success counts cannot count all real fills: explicit partial_fills/filled_action and user confirmations are separate evidence. Conversely, partial archive status cannot confirm every action in the archive.

## Verified scope versus unfinished scope
An isolated replacement JSON was written/read back and a pure-builder RED→GREEN test passed. Live ledger integration, T+1 verification, other ETF recovery, and automatic suggestion integration were NOT established by that test. Do not describe them as repaired. A trusted full-account cash balance cannot be derived from this one-ETF fixture alone.
