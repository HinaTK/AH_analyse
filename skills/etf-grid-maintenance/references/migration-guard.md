# Migration Guard — Error Surface & Recovery

`grid_migration.py` implements a hard safety gate for the 159992 → 589720 ETF migration. It is **not** a bug — it is a deliberate guard that prevents the migration from proceeding on a config-only switch.

## `load_policy()` Error Conditions

Located at `scripts/grid_migration.py:7-17`. Three exit paths:

| Condition | Behavior | Message |
|---|---|---|
| `migration.json` missing or `enabled: false` | Returns `None` (no error, migration inactive) | — |
| `source != "sz159992"` or `target != "sh589720"` | Raises `ValueError` | `迁移标的配置无效，停止生成操作建议` |
| `target_buy_enabled: true` | Raises `ValueError` | `589720迁入须先核对银河委托并单独启用，不可仅改配置开关` |

## Crash Propagation Path

```
cron: ef9a27327990 (网格盘中检查, every 10min weekdays)
  → grid_weixin_intraday.py:main()
  → grid_weixin_intraday.py:trend_alert()          [line 31]
  → grid_migration.py:guard_ticket()               [line 20]
  → grid_migration.py:load_policy()                [line 7]
  → ValueError raised at line 14 or line 16
  → cron job exits with code 1
```

The trigger condition: a pending ticket exists for the day AND the migration policy has `target_buy_enabled: true`. The `trend_alert()` function calls `guard_ticket()` unconditionally at its entry point (line 34), so any intraday check while a pending ticket exists will hit this guard.

## Recovery Steps

1. **Find `migration.json`** — it lives at `TICKETS.parent / "migration.json"`, NOT in `scripts/`. `TICKETS` is defined in `grid_account.py`; check that module for the actual path.
2. **Set `target_buy_enabled` to `false`** to silence the guard temporarily.
3. **For permanent resolution**: manually verify the broker orders for 589720 in 银河证券, then explicitly enable `target_buy_enabled` only after confirmation — do not flip the switch without the manual check.
4. **While the guard is active**, the `ef9a27327990` cron job will keep failing. Pause it via `cronjob(action='pause', job_id='ef9a27327990')` until the migration state is resolved.

## Related Files

- `scripts/grid_migration.py` — guard implementation
- `scripts/grid_weixin_intraday.py` — caller that triggers the guard
- `scripts/grid_account.py` — defines `TICKETS` path and `load()`/`plan()`
- `scripts/migration.json` — migration policy (location: `TICKETS.parent / "migration.json"`)

## Regression Note

This guard is a **positive safety control**, not a defect. Do not "fix" it by removing the check. The correct fix is always: verify broker state manually → then flip the switch explicitly.
