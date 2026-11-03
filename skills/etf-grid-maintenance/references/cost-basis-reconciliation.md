# Cost Basis Reconciliation (2026-10-09)

When the user asks to reconcile cost basis, they independently compute
`sum(buy含费) − sum(sell净回笼)` and compare against `pos["cost_cash"]`.
The agent must do the same, trade by trade, presenting every line.

## Two cost models — do not mix them

| Model | Formula | When correct |
|---|---|---|
| **Net invested** (user's model) | `Σ buy含费 − Σ sell净回笼` | Always — this is what `cost_cash` must hold |
| Remaining-lot cost | `Σ (lot.qty × lot.price + fee)` for lots with qty > 0 | Only valid when no pooled T+1 sells have happened |

The old `apply()` used the second model after a sell, which understated the
basis and produced a phantom "浮盈". The user caught it by computing the first
model directly.

## Reconciliation procedure

1. Pull every action from `book["history"]` for the target code.
2. For each buy: `notional = qty × price`, `cost = notional + fee(notional)`.
3. For each sell: `notional = qty × price`, `proceeds = notional − fee(notional)`.
4. `net = Σ buy_cost − Σ sell_proceeds`.
5. Compare `net` to `pos["cost_cash"]`. If they differ, the sell-side path
   in `apply()` is wrong — rebuild `cost_cash` from history and fix the code.
6. Then verify `pos["qty"] == Σ lot["qty"]`. If not, call `sync_qty(pos)`.

## Pooled T+1 sell mechanics (correct)

- A sell hits a grid price (target lot). The target lot's `qty` is **not**
  consumed — it identifies which grid price was triggered.
- Shares are drawn from the T+1 pool: `available_from <= today`, oldest
  `bought` date first (FIFO).
- After consuming, call `sync_qty(pos)` so `pos["qty"]` matches lot sum.
- `cost_cash` is reduced by `proceeds`, not by `take × source.price`.

## Example: 589720 (2026-10-09)

| # | Date | Side | Lot | Qty | Price | Notional | Fee | 含费/回笼 |
|---|------|------|-----|-----|-------|----------|-----|-----------|
| 1 | 10/08 | buy | A | 9,200 | 0.877 | 8,068.40 | 1.00 | 8,069.40 |
| 2 | 10/08 | buy | B | 9,400 | 0.859 | 8,074.60 | 1.00 | 8,075.60 |
| 3 | 10/09 | buy | C | 9,600 | 0.829 | 7,958.40 | 1.00 | 7,959.40 |
| 4 | 10/09 | sell | C | 9,600 | 0.846 | 8,121.60 | 1.00 | 8,120.60 |

Buy total = 24,104.40. Sell proceeds = 8,120.60. **Net = 15,983.80.**

Sell #4 consumed from T+1 pool: A (9,200) + B (400). C lot qty stays 9,600.
Final: A=0, B=9,000, C=9,600 → total 18,600 shares, cost_cash 15,983.80.

## User's exact check (verbatim from session)

> 0.877 * 9,200 + 1 + 0.859 * 9,400 + 1 + 0.829 * 9,600 +1 - 0.846 * 9,600 +1 = 15,983.80

The agent must answer this exactly, line by line, without reformatting the
arithmetic. The user will correct the agent down to the yuan if any number is
off — including the commission fee() value.
