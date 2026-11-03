# Grid Gap Change Procedure (2026-10-12)

When the user changes `GAP` (e.g. 2% → 1.5%), three things must be
recalculated. Missing any one produces wrong prices.

## 1. Sell prices on existing lots

For every lot with `qty > 0`:

python
lot["sell"] = round(lot["price"] * (1 + GAP), 3)


`lot["price"]` is the **buy price**, not the previous sell price. Recompute
from the buy price so the new gap is applied consistently.

## 2. Rebuy prices (critical — easy to get wrong)

A rebuy entry exists when a sell has filled but the replacement buy has not.

**Correct formula (user-confirmed 2026-10-12):**

python
rebuy["price"] = round(previous_grid_buy_price / (1 + GAP), 3)


The rebuy price is the **previous grid's buy price** divided by (1+GAP),
NOT the actual executed sell price, and NOT the sold grid's own buy price.

Example: 159363 G格 sold, previous grid is F (buy 1.120).
Rebuy = 1.120 / 1.015 = **1.103**.

**Wrong approaches (both committed 2026-10-12, both corrected by user):**

1. `sold_grid_buy_price / (1+GAP)` → 1.093/1.015 = 1.077 ✗
   (used the wrong grid's buy price)
2. `actual_sell_price / (1+GAP)` → 1.115/1.015 = 1.099 ✗
   (user: "不应该用上一个格子的买入价去除吗" — should use previous grid's buy price)

**How to find the previous grid's buy price:** look at the lot immediately
above the sold grid in the grid sequence. For G格, that is F格.
Use `lot["price"]` of that previous lot, not its sell price.

## 3. Lot quantities

**Do not change.** Quantities are determined by `LOT_BUDGET[code] / buy_price`,
which is independent of `GAP`. Only prices change.

## Procedure checklist

1. [ ] Update `GAP` constant in `grid_account.py`
2. [ ] Recompute `lot["sell"]` for every lot with `qty > 0`
3. [ ] Recompute `rebuy["price"]` from actual executed sell price (from history)
4. [ ] Leave `lot["qty"]` unchanged
5. [ ] Run `plan()` and verify one buy + one sell per ETF
6. [ ] Verify sell prices are above current market price (a sell below market
      is a stale target, not an actionable order)

## Common mistake: rebuy price from buy price

The rebuy entry stores `from_lot` (which grid was sold) and `price` (the
limit at which to rebuy). After a gap change, `price` must track the actual
sell price, not the lot's buy price. If the user asks "where did 1.093 come
from?", check whether you divided the buy price instead of the sell price.

