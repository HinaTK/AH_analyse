# plan() output and open issues (updated 2026-10-09)

## plan() return shape

`plan(book, quotes)` returns a **single ticket dict**, not a list. Iterating
it as a list causes `TypeError: string indices must be integers, not 'str'`
when you access `t["code"]` — the first element is the string `"date"`.

The ticket has these top-level keys:

| Key | Content |
|---|---|
| `actions` | primary buy/sell actions for the day |
| `withdrawal_actions` | secondary actions (e.g. migration target buys) |
| `migration` | `{source, target, stage, broker_cancel_confirmed}` |
| `note` | human-readable summary string |
| `quotes` | the quote snapshot used |

## Quotes are strings

`fetch_quotes()` returns `last`, `prev`, `open`, `high`, `low` as strings.
Always `float()` before arithmetic. The first error in this session
(`ValueError: Unknown format code 'f' for object of type 'str'`) came from
formatting a string directly.

## next_sell_lot() — actionable filter (added 2026-10-09)

`next_sell_lot()` now filters eligible lots by `int(lot["qty"]) <= sellable`
where `sellable = available(pos, d)`. Previously it picked the lowest sell
price regardless of whether the pooled T+1 balance could cover it.

**Why this matters**: 589720 C格 had sell=0.846 (lower than B格 0.876) but
C格 was T+0 (bought 10/09, available_from 10/10). The pooled T+1 balance was
only 9,000 (B格), not enough to cover C格's 9,600. Without the filter,
`plan()` would emit a sell for C格 @ 0.846 that the T+1 pool cannot fund.

The filter is applied **after** the capacity check (core qty, migration
release), so 159992 exit sells still work.

## Migration guard — 589720 buy/sell enabled (2026-10-09)

`grid_migration.py:guard_ticket()` previously blocked **all** buys on both
`source` and `target`. After 589720 auto-sell was enabled, the guard was
patched to allow target buys when both conditions hold:

```python
and not (a.get("code") == policy["target"]
         and policy.get("target_buy_enabled")
         and policy.get("target_buy_authorized_by_user"))
```

`migration_note()` was also split into two modes: active migration vs.
pending migration, so the note text matches the current stage.

## Stale state after 2026-10-09 fixes

1. **159363 G格 sell re-appears in `plan()`** — the G格 sell (5,400 @ 1.115)
   already filled on 10/09, but `pos["rebuy"]` still contained the pending
   rebuy entry, so `plan()` regenerates both the sell and the rebuy. The
   sell action gets `"resting": true`. **Fix**: clear `pos["rebuy"]` after
   the corresponding fill is confirmed. This is an end-of-day cleanup task.

2. **589720 C格 sell target stale** — C格 sell was 0.846, already hit. After
   the fill, the sell target must move up: `lot["sell"] = round(0.846 * 1.02, 3)`
   → 0.863. Otherwise `next_sell_lot()` keeps returning a price that can
   never be a new sell target.

3. **Lot notes accumulate stale fill records** — when a lot is involved in
   multiple fills, `lot["note"]` gets appended with old fill info that
   confuses later reads. Keep notes concise; trim after reconciliation.

## Rebuy vs. down-grid priority

`plan()` checks `pos["rebuy"]` before `next_sell_lot()`. A completed sell
creates a rebuy entry; if the rebuy doesn't fill, the sell action is
regenerated as `resting`. This is correct behaviour — but the rebuy entry
must be cleared once the user confirms the rebuy failed (end of day).