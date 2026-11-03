# Market-data source failover (session 2026-10-23)

## Incident (dated observation, not a permanent claim)
- `https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,80,qfq` returned **HTTP 501 Not Implemented** for the afternoon of 2026-10-23 (reproduced directly, not a transient blip). It had worked the day before; status may change again — that is exactly why the fix is a fallback chain, not a URL swap.
- Symptom: cron job `网格15:20收盘效率与轮换检查` (b3097b45fafa, script `grid_eod_decision.py`) delivered `行情或状态未验证：不生成执行建议；HTTP Error 501: Not Implemented` — the fail-closed label from `confirmed_runtime.safe_entrypoint`, correct behavior given no daily bars.

## Endpoint-level impact map (verified by direct probes, 15:2x)
| Consumer | Endpoint | State |
|---|---|---|
| 15:20 EOD daily bars (`confirmed_runtime.eod_main`) | ifzq fqkline | ❌ HTTP 501 → broke |
| 09:20 pre-market + minute intraday jobs | `qt.gtimg.cn/q=...` real-time | ✅ OK |
| `grid_intraday_bars.py` minute bars | ifzq `kline/mkline` | ✅ OK |
| 15:35 market phase monitor | eastmoney `push2his` | ✅ unrelated |

Lesson: same host, three endpoints, one broken. Always probe per-URL and map cron job → endpoint before claiming scope. Same-host failure ≠ host down.

## Working mirror (adopted as primary)
`https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param={code},day,,,80,qfq`
- Payload shape identical: `data[code]['qfqday'] or ['day']`, close at `row[2]`.
- Cross-validated: returned 81 bars ending `2026-10-23` with close `0.813` for sh589720, matching the live snapshot last `0.813` — passes the EOD close-vs-quote consistency gate.
- Note: it returns one MORE bar than requested (81 for param 80) — harmless for the last-bar check, but do not assert exact bar counts against the param.

## Implemented pattern (commit d44e33f, repo AH_analyse)
`confirmed_runtime.py`:
- Module-level ordered tuple:
  ```python
  DAILY_BAR_SOURCES = (
      'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param={code},day,,,80,qfq',
      'https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,80,qfq',
  )
  ```
- `fetch_daily_bars(code)`: iterate sources; per source, `code != 0` payload or empty rows raises locally; catch `(OSError, ValueError, KeyError, IndexError)`, collect `f'{url}: {error}'`; after the loop raise `ValueError('行情源全部失败：' + '; '.join(errors))` so the aggregated diagnostics surface in the Feishu label.
- `eod_main` call site reduced to `bars[code] = fetch_daily_bars(code)` — no other behavior change.

## Verification recipe (reusable)
1. Reproduce outside the app: direct `urllib.request` GET of the failing URL (isolates app logic from upstream).
2. Candidate probes: try mirror hosts and sibling endpoints BEFORE patching; note payload shapes.
3. Cross-validate mirror last bar vs live quote snapshot (date + close tolerance).
4. TDD: `test_eod_daily_bars_source.py` — 4 tests (mirror-first order asserted on request URL; fallback when mirror raises OSError; all-fail → `行情源全部失败` in message; non-zero `code` payload from mirror falls through to legacy). All with `urllib.request.urlopen` patched.
5. Full suite: 543 tests — 6 failures classified as pre-existing via `git stash push -- confirmed_runtime.py` + re-run + `git stash pop` (same 5 failures + 1 error without the change; located in `ah_recommendation_system.backend.tests` frontend/Feishu/installer areas, unrelated).
6. Re-run the deployed launcher `scripts/grid_eod_decision.py` manually → complete readable EOD report regenerated and saved under `cache/grid-account/eod/<date>.json`.
7. Numbers differing from the last snapshot (qty 47,700 vs 67,700, max_grid E vs G) were explained by two intraday confirmed sells (589720-028, -029) — verified against the persisted state file trade list and arithmetic (qty/sellable/net_invested/t_net all reconciled), NOT state corruption.
