# Ranking delivery rules (user rules 2026-10-20/22/23, consolidated 2026-10-26)

The user asks for ETF rankings repeatedly and has burned the assistant on the same
mistakes three separate times. The contract below is now mandatory for ANY ranking
request (“前10”/“排名”/“最新排名”).

## The four-part ranking contract
1. **Sort by complete round trips (`full_cycles`) descending** — never by composite
   `score`. Same-count ties: `full_cycle_net` descending, then code ascending.
   The composite leaderboard is a DIFFERENT list (it excludes holdings by default);
   passing it off as the round-trip ranking is the user's #1 complaint.
2. **Filter by entry eligibility BEFORE ranking.** Run
   `python -m tools.etf_research.entry_rank <latest-research-dir>` which calls
   `entry_timing.judge_entry` per candidate: 可建仓=full（可以整仓）、试错建仓=
   probe_only（仅试错仓）; everything else and four-window-incomplete rows are
   dropped. Do NOT hand-roll this filter from result.json — the module existed
   since 10-21 (commit 10d479d) and was twice bypassed to deliver an unfiltered
   table the user rejected.
3. **Holdings are NEVER excluded from the ranking.** The user explicitly wants to
   know what rank each held ETF holds. entry_rank (commit 0176cb5) keeps holding
   rows in the same ranked table with a `holding` column and label “持仓”;
   holdings also skip the eligibility drop (they're already in-position — the
   timing verdict is informational only for them).
4. **Provenance header on every delivered table:** engine/model, window start→end,
   universe size, admitted/excluded counts, fee assumptions, whether HK-linked
   ETFs are included, and that figures are an independent simulated account — not
   the user's ledger. Same-day multiple research runs: use the LATEST output dir.

## Known behavior of the eligibility filter
- In a weak tape almost everything above MA60 is 'reject/near-high' and almost
  everything below is `probe_only`; `full` is rare (2026-10-23: 239 probe_only,
  1 full — and the only `full` had just 8 cycles, rank 139). Delivering “top 10 by
  cycles” after the filter will therefore usually be all-试错仓; say so plainly
  rather than quietly mixing in rejected rows.
- entry_timing judgment calls (conservative by design, confirmed by review
  2026-10-26): steady climbers that never pull back to MA20 never reach `full`;
  ANY close below MA60 is `probe_only` regardless of whether MA60 is still rising;
  the 3-day touch window can miss a breakout on day 4 (self-corrects next bar);
  entry_rank feeds research-cache m5 bars aggregated to daily (unadjusted) while
  standalone runs use Sina daily — both paths agreed on test cases, but
  distribution/split events would distort MAs.

## Annualization & PnL answers must be module-sourced
- 汇总/总盈亏/年化：run `grid_summary.py` (`summarize_account`,
  `account_total_pnl`) — never mental arithmetic, never one-off scripts
  (user-escalated high-priority principle, 2026-10-22).
- Total P&L has ONE formula: market_value − net_invested; t_net is ALREADY inside
  net_invested via sell inflow — adding it again is double-counting (2026-10-22
  error, caught by the user with an external model check).
- Annualized T-yield: pick the denominator deliberately and disclose it — current
  net_invested flatters after sells (589720 read 59% annualized on a 38k denominator
  but ~33% on the 62.6k peak-occupancy denominator). State single vs compound,
  calendar-day vs trading-day bases. Never annualize a “today did 3 rounds” day.
