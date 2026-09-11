# Context, Snapshot, and Ledger Rules

Use this reference to keep composite analysis window-safe without weakening analytical obligations.

## Context Slimming Principle

- Do not rely on chat memory for facts. Final judgments must come from files, live sources, computed summaries, or market data.
- Slim raw context, not obligations. The saved report must still include mandatory modules.
- Treat summaries as navigation. If a summary item drives a conclusion, verify the exact row, section, quote, or web source.
- Do not keep raw web pages, raw X timelines, full search-result dumps, or full prior reports in active context. Convert them into evidence cards.
- Do not read companion skill files wholesale during a composite run. Use exact reference files or exact sections only.

## Default Context Budget

| Item | Default cap |
| --- | --- |
| Compact helper output | one latest report per family, 8 recent ledger rows, 6 section-preview lines |
| Live evidence cards | start with 12 total; normally no more than 2 per major event or sector |
| X/Twitter evidence cards | 0 by default; only collect when the user explicitly asks to use X/Twitter |
| Prior report deep reads | only exact sections needed for trigger / invalidation / conclusion-change audit |
| Final chat response | saved report path + complete decision block; do not paste the full report |

## Required Local Commands

Start with the compact context helper from the repository root:

```powershell
python tools/analyse_context_summary.py --latest-reports 1 --recent-rows 8 --section-lines 6
```

Use the market snapshot script as the compact quote / board packet:

```powershell
python tools/fetch_market_snapshot.py --format json --output docs/analyse/runtime/market_snapshot_YYYYMMDD.json
```

If final stock candidates are named, rerun with exact candidate codes:

```powershell
python tools/fetch_market_snapshot.py --format json --no-config --skip-boards --a-code "600276=恒瑞医药" --hk-code "rt_hk01801=信达生物" --output docs/analyse/runtime/stock_candidate_snapshot_YYYYMMDD.json
```

Run the deterministic theme-fit checker before final ETF / stock tables:

```powershell
python tools/validate_theme_fit.py --mode 盘前 --theme "AI能源/电网/绿电" --candidate "560270=电力ETF工银,159326=电网设备ETF华夏,600900=长江电力"
```

## Automatic Candidate Failure Fallback

If `stock_candidates` is empty because automatic board discovery failed, do not conclude that no individual-stock candidates exist.

Fallback sequence:

1. Build a candidate pool from `docs/analyse/reference/stock_industry_map.jsonl`, mapped ETFs, and live event evidence.
2. Fetch exact quotes with `fetch_market_snapshot.py --a-code / --hk-code --skip-boards`.
3. Run `tools/validate_theme_fit.py` for every named final ETF and stock candidate.
4. Only after these fail or candidates fail validation may the report write `最终个股：无，等待确认`.

## Ledger and Stats

Because composite analysis includes abnormal movement attribution, update the prediction tracking files before creating new predictions:

- Ledger: `docs/analyse/abnormal-movement-ledger.jsonl`
- Stats: `docs/analyse/abnormal-movement-stats.md`

If the ledger does not exist, create it and state there is not enough history for meaningful hit probability.

Do not read the full ledger unless the helper reports JSON errors, duplicate IDs, missing fields, or unresolved statistics. Read exact lines or row IDs only.

## Trigger Backcheck

Before deciding whether a sector, ETF, or action trigger has fired, backcheck:

- Ledger rows for prior theses, due-date evaluations, excess returns, hit/miss/noise status.
- Recent `market-composite-analysis-*.md` and `abnormal-movement-analysis-*.md` sections for trigger wording and conclusion-change audit.
- Latest available price only after historical trigger audit.

Distinguish:

| Trigger layer | Meaning |
| --- | --- |
| `底仓触发` | Prior evidence justified a small, risk-defined pilot / bottom position |
| `右侧加仓触发` | ETF/index relative strength, breadth, and confirmation support adding |
| `当前追涨 / 主攻触发` | Current-session strength supports tactical attack |

If a trigger was previously met but latest quotes weaken, write `已触发后的回踩复核 / 升级失败 / 降级观察`, not `从未触发`.
