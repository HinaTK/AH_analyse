# Rebuild Authority Rule (2026-10-13)

## The problem

When asked to rebuild the grid ledger "from the beginning" (从建仓开始入库),
the local ticket directory (`TICKETS/*.json`) contains **78 files**, but only
7 have `status="成功"`. The other 71 are `pending` or `preview`. Worse, some
pending tickets **conflict with each other** — e.g. two different tickets on
2026-09-24 both sell `sz159992 A 9,100份 @ 0.888`. They cannot both be real.

Meanwhile `ledger.json → history` has 33 entries claiming successful trades,
but only 2 of those (the 09-23 seed buys) have corresponding `status="成功"`
tickets. The rest were written by `apply()` calls that succeeded locally but
whose source tickets were never confirmed by the user.

## The rule

**Never rebuild a ledger from local ticket files without an authoritative
source.** The local `status` field is not proof of a broker fill. Pending
tickets may be unconfirmed, partially filled, or superseded by later tickets.

Before any rebuild:

1. **Ask the user for the broker statement** (银河证券交割单) — date, code,
   direction, quantity, and average fill price for every trade.
2. **Do not assume** `pending` = unfilled, `成功` = filled, or `history`
   entries = confirmed trades.
3. **Do not silently skip** conflicting tickets — flag them to the user.
4. **Present the conflict** explicitly: "These two tickets both sell A lot
   9,100 shares on the same day — which one (if any) actually filled?"

## Why this happened

The `apply()` function was called with `result="成功"` on tickets that the
user had not yet confirmed. The function wrote to `history` and updated
positions, creating a ledger that looked complete but was built on
unconfirmed data. When the user later asked to rebuild from scratch, the
agent discovered the mismatch.

## User reaction

User was extremely angry: "我踏马？？我就说你记录有问题，我就不该信你".
They had noticed the problem earlier and were right to distrust the ledger.

## Prevention

- `apply()` should **not** write to `history` unless the ticket's `status`
  is already `"成功"` (user-confirmed).
- The `status` field on the ticket file is the **only** valid signal that a
  trade actually happened.
- When the user says "入库", first check: does this ticket have
  `status="成功"`? If not, ask for the broker confirmation before writing.
