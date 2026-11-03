# Summary module (grid_summary.py) and annualization conventions

Created 2026-10-22 after the user caught two arithmetic failures in one day: (1) a hand-derived
wrong cash-flow formula produced a fake 102-yuan "gap" between two consistent ledgers; (2) the
total P&L was reported as `pnl + t_net = -7,750.60`, double-counting realized T profit already
reflected in net_invested via sell inflow (GLM cross-check caught it; correct answer -9,879.60).
The user then elevated a general rule: **a task likely to be asked repeatedly and implementable
as a script MUST be solved by a persistent module — mental arithmetic and one-off scripts are
forbidden.**

## Canonical module

`D:/Code/AH_analyse/grid_summary.py` (commit e702249) + `account_total_pnl()` (c1645bb),
tests `test_grid_summary.py`, `test_grid_summary_edge.py`, `test_total_pnl.py` (13 green).

- `summarize_account(dir)` — per-ETF and totals, all money as 2-dp Decimal strings. Runs three
  consistency checks on EVERY trade and flags, never repairs: `cashflow_matches_ledger`
  (cash net = buy_amt + buy_fees − sell_amt + sell_fees must equal the stored net_invested),
  `amount_consistent` (amount == qty×price), `fee_consistent` (fee == max(amount×万一, 1元)).
- `count_trading_days(start, end)` — A-share calendar: weekends + statutory holidays; makeup
  Saturday workdays (e.g. 2026-10-10) are NOT sessions.
- `account_total_pnl(summary, last_prices)` — the ONLY total-P&L formula:
  `total = market_value − net_invested`, computed once. `t_net` is returned separately with
  `t_net_added: False` and a note field; never add it again.
- `summarize_account(dir)['daily']` (commit a756048) — per-day completed rounds. A round lands
  on the SELL trade's date; a rebuy without a matching sell is a half-cycle and never counts.
  "Today N rounds / today's PnL" must come from here, never hand-assembled (2026-10-26: chat
  claimed 3 rounds/+349.20 counting an E rebuy as a round; ledger truth 2/+233.60).

## Delivery rules

- "汇总一下" → run `summarize_account` on the live grid-account dir. The 合计 section must
  include trading window, natural days, trading days (holiday-adjusted), trade counts,
  buy/sell amounts, fees, net invested total, holding/sellable shares, T rounds/gross/fees/net.
- Two windows exist and must not be conflated: the user's fixed window (2026-09-23 → today,
  holiday-adjusted session count) vs the module's data-window (first dated trade → last).
  Label which is which.
- T net profit and total account P&L are PARALLEL metrics, never added. Annualization is
  computed on t_net/base for grid efficiency only, with the caveat stated below.

## Per-day T-round stats (2026-10-26 incident → `daily` field, commit a756048)

The user asked for a daily recap after three same-day fills; the assistant hand-assembled
"3 rounds / +349.20" in chat — counting an E-grid REBUY (sell E → buy E back, no matching
sell) as a completed round. Ledger truth: **2 rounds / +233.60**. User: "是不是傻 今天哪来的三轮".

- `summarize_account()['daily']` now returns per-day `{rounds, t_net, n_buys, n_sells,
  buy_amount, sell_amount}`. A round LANDS ON THE SELL TRADE'S DATE (a cycle completes when
  the sell fills). A rebuy without a matching sell is a half-cycle and NEVER counts. Null
  dates are skipped.
- Rule: "today N rounds / today's PnL" style questions are cross-trade aggregates — they are
  exactly as forbidden to hand-assemble as table cells. Run the module's `daily` output.
  Derived facts from the daily series (e.g. single-day record = 3 rounds on 10-21 and
  10-23) also come from the script, not memory of earlier chat claims.
- Tests: `test_daily_rounds.py` (3 RED-first, includes the exact 10-26 incident replay).

## Annualization conventions (折算年化)

Given period return r over N natural days (or T trading sessions):

- natural-day compound: `(1+r)^(365/N) − 1`  ← default headline figure
- natural-day simple: `r × 365/N`
- trading-day compound: `(1+r)^(250/T) − 1`; simple: `r × 250/T`

Denominator honesty (the trap that inflated 589720 to "59% annualized"):

- Current `net_invested` is a POST-SALE trough: after several grids sell off, the denominator
  shrinks while cumulative t_net stays — ratio explodes. For single-ETF efficiency use the
  PEAK invested capital observed while grids were open (e.g. 62,612.10 for 589720) and report
  the current-denominator figure only as an explicitly-labeled optimistic bound.
- Always attach the standing caveats: one month of range-bound tape is not a sustainable
  annual rate; single-trend regimes collapse grid annualization; a 100%-win 20-round record is
  structural (buy-low/sell-high triggers), not skill alpha.
