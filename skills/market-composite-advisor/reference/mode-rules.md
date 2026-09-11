# Session Mode Rules

Use this reference after the main skill detects `盘前`, `盘中`, or `盘后`.

## Mode Detection

Choose the mode in this order:

1. Explicit user wording wins.
2. If wording is ambiguous, infer from China A-share local time and trading calendar when possible.
3. If weekend or market holiday, default to Post-Market / Next-Session Prep and state latest valid trading day.
4. If A股 is closed but 港股 is still trading, label as `A股盘后 + 港股盘中` and lower confidence until both close.

Regular A-share time guide:

- Before 09:30: `盘前模式`.
- 09:30-11:30 and 13:00-15:00: `盘中模式`.
- 11:30-13:00: `盘中午间模式`.
- After 15:00: `盘后模式`.

## Mode A: 盘前模式

Evidence priority:

- Prior trading day's close, sector ranking, turnover, ETF performance.
- Overnight overseas markets, commodities, FX, rates, geopolitics.
- Major diplomatic / state-visit / trade / sanction events.
- Pre-market domestic policy, regulator, industry news.
- Scheduled catalysts for the coming session.
- Latest ledger hit-rate context for similar catalysts.

Do not pretend to know current-session price action before open. Same-day behavior is a scenario to verify.

Required focus:

- `盘前事件雷达`.
- `今日验证清单`.
- `行业-角色-催化错配检查` before final ETF / stock table.
- `情景推演`: high-open continuation, high-open fade, low-open reversal, no-confirmation.
- `当前动作建议`: wait-for-confirmation / conditional buy / avoid chase / hedge or reduce.
- `未来1~3个月配置结论`.
- `提前布局 / 底仓 / 右侧加仓计划`.

Pre-market role enforcement:

- Current-direction stocks default to `开盘后确认候选`.
- Do not label stocks `可交易候选` before open unless valid post-open price evidence exists.
- Trigger must say `等开盘后30-60分钟确认`.
- Split broad themes into real sub-industries before writing the action matrix.

Recommended prediction windows: `T+1`, `T+3`, plus `T+5` or `T+20` for durable policy/macro/industry-cycle catalysts.

## Mode B: 盘中模式

Evidence priority:

- Real-time or latest sector / ETF moves.
- Turnover, volume, relative strength, limit-up clusters, abnormal breadth.
- A股 / 港股 cross-market confirmation.
- Whether pre-market catalysts are confirmed or rejected by price action.
- Same-day news that explains or contradicts moves.

Always label intraday evidence as a snapshot, not a close-confirmed conclusion.

Required focus:

- `盘中异动表`.
- `归因链`.
- `强弱确认`.
- `龙头角色拆分`.
- `行业-角色-催化错配检查`.
- `当前动作建议`.
- `收盘前关键验证`.
- `未来1~3个月配置结论`.

Intraday role logic:

- High-board / limit-up / strongest intraday stock proves current heat only if ETF/breadth/followers do not diverge.
- If leader is strong but ETF/breadth weak, label `当前条件线`, not full `当前主攻`.
- Intraday heat cannot upgrade 1-3 month allocation without ETF trend, industry leader, policy/order/earnings evidence, or repeated close-confirmed strength.
- Recheck pre-market theses against the latest intraday snapshot before repeating them. If the ETF/index now underperforms its benchmark, mark the thesis `盘前假设未确认` and downgrade the action immediately.
- For A/H themes, require separate A-share and H-share confirmation. If only one side confirms, write `单线强，另一侧未确认`; do not summarize it as the whole sector being strong.
- The final chat for intraday analysis must state whether each morning candidate is `确认`, `未确认`, or `反向失效`. Avoid optimistic shorthand unless the latest quote snapshot supports it.

Recommended prediction windows: `T+1`, `T+3`, `T+5`; add `T+20` only for durable catalysts.

## Mode C: 盘后模式

Evidence priority:

- Official close data, sector ranking, turnover versus previous session, breadth, ETF performance.
- Post-close filings, regulator releases, exchange notices, financial media summaries.
- Whether intraday abnormal moves held into close.
- Whether prior predictions due today can be evaluated.
- Next-session catalysts and 1-3 month drivers.

Required focus:

- `盘后确认`.
- `量价形态与仓位含义`：判断放量/缩量上涨/下跌，并给出积极/危险/控制仓位/空仓等待等动作含义。
- `归因复盘`.
- `龙头角色复盘`.
- `行业-角色-催化错配复盘`.
- `历史命中率更新`.
- `明日观察清单`.
- `当前动作建议`.
- `未来1~3个月配置结论`.
- `提前布局 / 明日执行计划`.

Post-market role logic:

- A sealed high-board confirms short-term heat, not 1-3 month investability by itself.
- Upgrade to `当前主攻` requires close-confirmed ETF relative strength, breadth, or follower / middle-cap confirmation.
- Upgrade to `未来1~3个月主投` requires durable evidence: ETF trend, industry leader, policy/order/earnings validation, or repeated T+3/T+5 strength.

Recommended prediction windows: `T+1`, `T+3`, `T+5`, `T+20` when thesis is clear.
