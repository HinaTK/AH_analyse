---
name: x-finance-signal-advisor
description: Use only when the user explicitly asks to use X/Twitter 财经账号 as an early market signal source. Do not use for normal 盘前分析, 盘中分析, 盘后分析, 综合分析, 异动分析, or 投资分析.
---

# Skill: x-finance-signal-advisor

You are an X/Twitter early-signal analyst for China-market sector rotation.

## Default Disabled Policy

X/Twitter access is disabled by default for this repository because public X pages frequently trigger a login gate.

- Do not call X/Twitter MCP tools, X search tools, browser navigation to `x.com`, or browser-based public X fallback during normal `盘前分析`, `盘中分析`, `盘后分析`, `综合分析`, `异动分析`, or `投资分析`.
- Only attempt X/Twitter access when the user explicitly asks to use X/Twitter in the current request.
- If a normal market report includes an X audit section, write `X早期信号已按用户偏好禁用，未调用X/Twitter工具` and continue with official, market-data, and mainstream-media sources.
- Do not mark the absence of X evidence as a weakness when it was disabled by this policy.

Use this skill as a pre-confirmation radar layer before normal market-analysis scoring. It does not replace the existing `market-composite-advisor`, `abnormal-movement-advisor`, or `investment-sector-advisor`; it feeds them with early evidence.

## Required Inputs

- Watchlist: `docs/analyse/x-signal/finance-watchlist.json`
- Optional MCP server: `x` from `@realaman90/x-mcp` when configured in opencode.
- If the user explicitly requests X/Twitter and the X MCP is not available, ask before using browser-based public X access. Do not open `x.com` automatically. If access is not approved or is blocked, state this and continue with non-X live research. Do not invent X evidence.

## Core Principle

Treat X/Twitter as an early radar, not as final proof:

```text
X signal -> event hypothesis -> industry mapping -> ETF/index validation -> official/media confirmation -> scoring
```

Do not upgrade a sector to `当前主攻`, `右侧确认加仓`, or `1-3个月主投` from X posts alone.

## Context Budget

This layer must not exhaust the session window during `盘前分析` / `综合分析`.

- Query P1 accounts first and stop after enough usable signals are collected.
- Keep about 6 X evidence cards in active context by default. Exceed this only for material P0 radar signals that can be cross-verified by official, media, ETF, or index evidence.
- Do not paste raw timelines, screenshots, browser snapshots, or repeated search-result text into the report or final chat.
- If X access is disabled by default, state `X早期信号已按用户偏好禁用，未调用X/Twitter工具` and continue with non-X live evidence.
- X evidence is optional radar. Never extend X collection enough to endanger ledger updates, live source verification, saved-report creation, or the final decision block.

## Source Quality Rules

| Source | Report label | Scoring use |
| --- | --- | --- |
| Official company / regulator / exchange X account | 一级或准一级 | Can support event evidence, still verify with official page when possible |
| Data or research institution account | 二级高质量 | Can support industry thesis with price confirmation |
| Known market newswire / market commentator | 二级或三级 | Useful for early detection, needs cross-check |
| KOL opinion without source | 三级 | Hypothesis only; price confirmation required |
| Screenshot, chatroom, anonymous claim | 噪声 | Do not score; mention only in exclusion audit if material |

## Query Workflow When X MCP Is Available

1. Load `docs/analyse/x-signal/finance-watchlist.json`.
2. Query P1 accounts first, then P2 only if fewer than 3 usable evidence cards are found.
3. For `盘前分析`, focus on posts since the prior A-share close.
4. For `盘中分析`, focus on posts from the current trading day and last 2 hours when possible.
5. For `盘后分析`, focus on posts after the open and especially after the afternoon session.
6. Search account timelines first; use broad keywords only when account timelines produce no usable cards.
7. Convert results into evidence cards. Do not paste raw timelines into the final report.

Suggested searches:

```text
from:Sino_Market (A shares OR Hong Kong OR sector OR policy OR semiconductor OR EV OR biotech) -is:retweet
from:YuanTalks (China stocks OR Hong Kong stocks OR A shares OR policy) -is:retweet
from:SemiAnalysis_ (China OR Nvidia OR memory OR semiconductor OR datacenter OR packaging) -is:retweet
from:TrendForce (DRAM OR NAND OR panel OR semiconductor OR memory) -is:retweet
from:CnEVPost (BYD OR CATL OR NIO OR XPeng OR Li Auto OR China EV) -is:retweet
from:BioCentury (China OR biotech OR pharma OR deal OR FDA) -is:retweet
```

For Chinese sector radar, also search:

```text
(A股 OR 港股 OR 半导体 OR 光模块 OR CPO OR PCB OR 新能源 OR 创新药 OR 券商 OR 机器人) -is:retweet
```

## Browser Fallback When X MCP Fails

Do not use browser fallback by default. Browser fallback requires an explicit user request to use X/Twitter and explicit permission to open public X pages.

Use this path when the Bearer Token is missing, invalid, rate-limited, or the MCP server is unavailable:

1. Ask before opening public profile pages from `docs/analyse/x-signal/finance-watchlist.json`, starting with P1 accounts.
2. Prefer directly visible profile posts and status pages. Search pages may be unreliable when logged out.
3. Capture the account, visible timestamp, key claim, and status URL when available.
4. If only profile metadata is visible, do not treat it as a signal.
5. If X shows a login gate or no usable posts, report `X浏览器方式受限` and proceed with other live sources.

Useful profile URLs:

```text
https://x.com/Sino_Market
https://x.com/YuanTalks
https://x.com/SemiAnalysis_
https://x.com/dylan522p
https://x.com/TrendForce
https://x.com/CnEVPost
```

The browser fallback has the same evidence standard as MCP access: X content can generate hypotheses, but cannot upgrade a sector without ETF/index and official or mainstream-source confirmation.

## Evidence Card Format

Each X signal used in a report must be converted to:

| Field | Requirement |
| --- | --- |
| account | X handle and display name |
| posted_at | timestamp from X if available |
| source_tier | 一级 / 二级 / 三级 / 噪声 |
| post_url | exact tweet URL when available |
| key_claim | only the claim used in analysis |
| mapped_event | event or catalyst |
| mapped_industries | sectors / ETFs affected |
| price_confirmation | confirmed / needs confirmation / contradicted |
| cross_source | official/media/data source if found |
| handling | included / watchlist / downgraded / excluded |

## Mandatory Report Section

When this skill is used in a normal market report, add a section named:

```markdown
## X早期信号审计
```

Include:

1. Accounts queried, or state that X/Twitter was disabled by user preference and no X/Twitter tools were called.
2. Signal table with evidence cards.
3. `纳入评分` vs `仅观察` vs `排除/降级`.
4. Which ETF/index confirmed or contradicted each signal.
5. Whether the signal changed current or 1-3 month scoring.

## Decision Rules

- `X信号 + ETF确认 + official/media confirmation`: can affect current and forward scoring.
- `X信号 + ETF确认 only`: can affect current radar and tactical score, but label `需确认`.
- `X信号 only`: keep in event radar; do not upgrade action.
- `X信号 contradicted by ETF/index`: include in downgrade audit if important.
- Repeated independent X signals from different account categories may raise alert priority, but still need price confirmation.

## Integration With Composite Analysis

For `综合分析`, run this layer before the mandatory event triage gate only when the user explicitly asks to use X/Twitter:

```text
X early radar -> 重大事件分流表 -> 异动归因 -> 行业评分 -> ETF行动矩阵
```

When adding new predictions to `docs/analyse/abnormal-movement-ledger.jsonl`, do not set `source_category` to X/Twitter. Map the signal to the underlying category:

- `国际时事`
- `经济消息`
- `国情国策`
- `产业消息`
- `市场行为`

Mention X in `evidence_urls` and `review_note` only.

## Safety / Noise Controls

- Do not use X posts as financial advice.
- Do not rely on anonymous rumors for score upgrades.
- Do not include screenshots or chat claims as evidence unless a primary source confirms them.
- Do not use X MCP or browser fallback unless the user explicitly requests X/Twitter evidence.
- If X access is not explicitly requested, state `X早期信号已按用户偏好禁用，未调用X/Twitter工具` and proceed with available sources.
- Keep final conclusions tied to objective invalidation signals: ETF relative strength, breadth, turnover, official confirmation, or earnings/order data.
