# Composite Analysis Ambush Output Design

## Objective

Restore the previously documented requirement that every normal pre-market, intraday, and post-market composite analysis identifies actionable advance-layout directions instead of reporting only same-day strength.

## Required Output Layers

Each saved report and compact final response must distinguish:

1. `当前主攻` or current tradable direction.
2. `未来1~3个月主投` direction.
3. `可小仓底仓 / 可埋伏 / 等待触发 / 降级观察` direction.
4. `回避 / 撤退` direction when price invalidates the thesis.

Each layer must include ETF code and name, evidence, status, validity window, entry/confirmation trigger, add-on trigger, and invalidation or exit condition.

## Ambush Reliability Gate

`可埋伏` cannot be assigned merely because a sector is cheap or has fallen. It requires improving 1-3 month slow-variable evidence, a non-disorderly price structure or nearby objective stop, no fresh thesis-breaking event, a pilot cap of 10%-30% of the intended final direction allocation, and explicit add-on and cut-loss triggers. Broken trend or relative strength forces `等待触发` or `降级观察`.

## Mode Semantics

- Pre-market: provide scenarios and open-confirmation conditions; do not claim current-session confirmation.
- Intraday: use a current snapshot and distinguish chase candidates from pullback/advance-layout candidates.
- Post-market: use close-confirmed behavior to identify next-session or 1-3 month advance-layout directions.

## Current Report Correction

Add `提前布局判断 / 可埋伏方向` to `docs/analyse/market-composite-analysis-20260810-115134.md`. For the current snapshot, classify A/H healthcare as the current/medium-term conditional direction, A/H financial/high-dividend as a small pilot-position candidate only with explicit limits, and CPO/semiconductor as avoid/exit until price repair.

## Verification

Assert that repository instructions, the active skill, the current report, and final-chat requirements all contain the required layer labels, reliability gate, pilot cap, right-side add-on trigger, and invalidation semantics.
