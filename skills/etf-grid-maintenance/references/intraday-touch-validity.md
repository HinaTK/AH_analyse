# Intraday touch validity window (rule set 2026-10-26, commit 5724005)

User rule: **“我说成交之后，价格涨跌到触价才有效”** — an advice is only validated by
price action that occurs after the confirmed fill that generated it.

## Incident timeline (2026-10-26, all real fills)
- 09:33 sell E 9,800@0.821 booked → morning high ≈0.821 belongs to this advice.
- 09:56 rebuy E 9,800@0.809 booked → same-price advice reborn later needed a fresh window.
- 10:38 buy F 10,000@0.797 booked → planner emits new advice “sell F 10,000@0.809”.
- 10:39 minute cron alerted “sell F@0.809 触价” — FALSE: old `monitor()` compared the
  full-day high (0.821, set before 10:38) against the 0.809 trigger.

## Fixed semantics in `confirmed_runtime.monitor()`
- State file `confirmed-intraday-alerts.json` now holds `day`, `alerts` (key
  `day:code:side:price`), and `baselines` (key `code:side:price` → {low, high}).
- First sighting of an advice records the current day low/high as baseline; only
  (a) current price at/through trigger, or (b) a NEW extreme beyond baseline that
  reaches the trigger, alerts. Pregeneration extremes are inert.
- Each run garbage-collects `alerts`/`baselines` whose advice is no longer in the
  alive action set (fill booked ⇒ advice gone ⇒ window cleared), so a reborn
  same-price advice may alert again. Old day+price dedup swallowed these.
- Quote fallback: when a quote lacks usable high/low (`NaN`), baseline uses `last`;
  first-sighting then only validates via current price.

## TDD recipe
- RED: `test_intraday_validity.py` — 5 tests: morning-extreme no-trigger,
  new-extreme-after-birth valid, first-sighting current-price touch valid,
  reborn-advice re-alert, buy-side new-low valid. All failed against old code
  for the intended reason (false positive reproduced) before the fix.
- Legacy `test_confirmed_runtime.py::test_quote_gating_and_extrema_dedup_per_day`
  asserted the OLD behavior (full-day extremes trigger). Updated to new semantics
  with explicit comments — when the user changes a rule, rewrite tests that
  encoded the old rule; never leave both.
- Watch for Python scoping in list-comprehension cleanups: two comprehension
  loops reusing one variable name (`stale`) raised UnboundLocalError in the same
  function; use distinct names per comprehension.

## Deployment notes
- Minute cron `ef9a27327990` (盘中检查) runs `scripts/grid_weixin_intraday.py`,
  which only does `sys.path.insert` + `from confirmed_runtime import ...` — the
  repo module IS the deployed code; a push to `confirmed_runtime.py` is live on
  the next cron tick with no copy step.
- Verify live: run the launcher manually (silence outside execute phase is
  expected), then confirm the next intraday alert text carries
  “建议生成后日内最高/最低=…（基准…）” evidence.