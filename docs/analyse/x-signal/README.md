# X Finance Signal Setup

This folder contains the X/Twitter early-radar setup for market analysis.

## Files

- `finance-watchlist.json`: candidate X/Twitter accounts for China-market sector analysis.
- `../../../skills/x-finance-signal-advisor/SKILL.md`: workflow rules for using X signals in reports.
- `../../../opencode.json`: MCP template for `@realaman90/x-mcp`.

## Default Status

X/Twitter lookup is disabled by default for normal market-analysis runs because public X pages frequently trigger a login gate.

- Do not call X MCP tools, X search tools, or browser navigation to `x.com` unless the user explicitly asks to use X/Twitter.
- If a report keeps an audit line, write `X早期信号已按用户偏好禁用，未调用X/Twitter工具` and continue with official, market-data, and mainstream-media sources.
- Browser fallback is not automatic.

## Enable the X MCP Manually

The repository includes an MCP template:

```json
"mcp": {
  "x": {
    "type": "local",
    "command": ["npx", "-y", "@realaman90/x-mcp"],
    "enabled": true,
    "env": {
      "X_BEARER_TOKEN": "${X_BEARER_TOKEN}"
    }
  }
}
```

To enable it:

1. Get a Bearer Token from the X Developer Portal.
2. Set the environment variable before starting opencode:

```powershell
$env:X_BEARER_TOKEN = "your-bearer-token"
```

3. Confirm `enabled` is `true` in `opencode.json`.
4. Quit and restart opencode. If startup fails without a token, temporarily set `enabled` back to `false`.

## Usage in analysis

When MCP access is enabled and the user explicitly asks to use X/Twitter, market-analysis reports should add an `X早期信号审计` section:

1. Query P1 accounts in `finance-watchlist.json` first.
2. Convert posts into evidence cards.
3. Verify each signal with ETF/index price action.
4. Use official documents or mainstream media for cross-source confirmation.
5. Only upgrade action labels when X signal and price confirmation agree.

## Browser fallback

Do not use browser fallback automatically. If the Bearer Token is missing, invalid, rate-limited, or the X MCP is unavailable, ask the user before using normal browser access:

1. Ask before opening public profile pages such as `https://x.com/Sino_Market`.
2. Prefer visible profile posts and exact status URLs over search results, because logged-out search is less reliable.
3. If X shows only a login gate and no usable posts, state `X浏览器方式受限` in the report and continue with non-X live sources.
4. Do not use browser-visible X content as final proof without ETF/index and official or mainstream-source confirmation.

## Important

X/Twitter is an early signal layer, not final proof. Anonymous screenshots, unsourced rumors, or pure KOL opinions must not directly drive sector scores or ETF actions.
