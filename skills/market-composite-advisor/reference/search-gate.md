# Search Channel Gate

Use this reference for every normal `盘前分析`, `盘中分析`, `盘后分析`, and `综合分析` run.

## Non-Negotiable Rule

Do not score sectors, select ETFs / stocks, write action advice, or save a normal high-conviction report until this gate is complete or explicitly marked unavailable.

## Required Provider Order

1. Load and attempt `multi-search-engine` first for broad event discovery and cross-engine verification across Chinese and global sources.
2. Load and attempt `firecrawl-search` second for key-source time filtering, news-focused searches, and full-page extraction when snippets are insufficient.
3. Use `google_search`, `websearch`, `webfetch`, browser, or equivalent fallback tools only after both preferred routes have been attempted, are unavailable, fail, are rate-limited, or are insufficient for a specific evidence card.
4. If one provider fails, continue to the next provider in this exact order. Do not jump directly to lower-priority tools because they are more visible or easier to call.
5. `google_search` must never be the first normal search route for composite market analysis.
6. Preferred search providers are skills. If their instructions are not already loaded, call the skill loader before using or declaring them unavailable.

## Search Channel Audit

Every saved report must include a `搜索通道审计` table before evidence scoring:

| 通道 | 是否尝试 | 结果 / 失败原因 | 后续处理 |
| --- | --- | --- | --- |
| `multi-search-engine` | 是/否 | ... | ... |
| `firecrawl-search` | 是/否 | ... | ... |
| `google_search` | fallback only | ... | ... |
| `websearch/webfetch/browser` | fallback only | ... | ... |

If a preferred route is skipped, write why. Acceptable reasons are: skill unavailable, authentication failure, rate limit, tool failure, or evidence insufficient after attempt. `Forgot to load it` is not acceptable.

## Evidence Requirements

Fetch evidence covering, as applicable:

- A股 / 港股 broad market direction, turnover, style, risk appetite.
- Sector and theme price action, abnormal volume, limit-up clusters, ETF flows, index performance.
- International events, geopolitics, rates, FX, commodities, inflation, overseas market clues.
- Domestic policy, regulator, ministry, central-bank, exchange, fiscal / monetary signals.
- Industry news: orders, product prices, capacity, sanctions, technology breakthroughs, earnings guidance, upcoming events.

## Evidence Cards

Convert sources immediately into compact evidence cards. Do not paste raw web pages or full search result dumps into the report.

| 字段 | 要求 |
| --- | --- |
| source | outlet / official body |
| url | exact URL |
| published_at | source date / time if available |
| source_quality | 一级 / 二级 / 三级 |
| key_facts | only facts used in scoring |
| affected_industries | mapped sectors / ETFs, including real sub-industry when stocks are named |
| price_verification | confirmed / needs confirmation / contradicted |
| conflicts | conflicting source or quote if any |

## Confirmation Layer

Official, exchange, regulator, filing, macro, and market-data sources remain the final confirmation layer. Search results identify leads but do not replace price confirmation, turnover, breadth, ETF/index relative strength, fund-flow evidence, or official releases.

## X/Twitter Layer

`x-finance-signal-advisor` is disabled by default. Do not call X/Twitter MCP tools, X search tools, browser navigation to `x.com`, or browser fallback during normal market-analysis runs unless the user explicitly asks to use X/Twitter. If an X audit section is included, state `X早期信号已按用户偏好禁用，未调用X/Twitter工具` and continue with official, market-data, and mainstream-media sources.

## If Evidence Is Unavailable

If all preferred and fallback evidence routes are unavailable or stale, do not produce a normal high-conviction report. Produce a limited-evidence update and ask whether to proceed with stale-background-only analysis.
