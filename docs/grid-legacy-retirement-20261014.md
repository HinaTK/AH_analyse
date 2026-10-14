# Legacy grid retirement — 2026-10-14

Actual quarantine: `D:/Hermes Agent CN Desktop/data/hermes-home/archives/retired-grid/2026-10-14_103636/`.

135 files moved reversibly: 33 managed scripts/bytecode, 100 old account files (ledger/migration/tickets, historical confirmed snapshots and legacy message/trend evidence), 2 untracked repository scratch scripts (`test_grid_runtime_guard.py`, `register_fills.py`). Nothing irreversibly deleted; the empty tickets directory was removed. Archived files and trading history are not committed here.

`manifest.json` records every original/destination path, byte size and SHA-256, plus 18 protected file hashes and the 7 cron references. `verification.json` records initial verified counts. Every archived file was read back and matched its source hash; every source was absent. To restore individual evidence, copy the explicit manifest destination to a non-runtime examination directory. Restoring obsolete runtime paths requires a separate authorization; do not replay archived scripts or tickets.

## Protected active paths

- Only authoritative `confirmed-589720.json`, `confirmed-159363.json`, `confirmed-159992.json`, and active `confirmed-intraday-alerts.json` remain as confirmed JSON files. Runtime locks stay.
- Seven confirmed-grid deployed launchers remain byte-identical, along with all new runtime modules.
- `grid_weekly_rotation.py`, `run_rotation.py`, `grid_rotation_review.py`, `grid_intraday_bars.py` and all research tools/caches remain. Historical EOD/rotation evidence is retained.
- Confirmed holdings remain 589720 **38000 / D**, saved sellable 28200; 159363 **34400 / G**, saved sellable 29000. No transaction was processed.

Exact authoritative hashes before/after tests and actual read-only entry execution:

| File | SHA-256 |
|---|---|
| confirmed-589720.json | `7bbb1bbebe1bda481eb38e2af247a5cf19e22eaf694207c635fff33d82034eb7` |
| confirmed-159363.json | `a8127e5b165aeaea47ec2fa139cf5680266ce687b820923f48705962f2c00837` |
| confirmed-159992.json | `f5513958c820a5f5e47e3700ebf016a839589ff71986bbba7e7cf13794189864` |

## Verified

- Inspected actual managed `cron/jobs.json`: seven jobs reference new runtime launchers, unified weekly research, or daily Git push; none requires a retired consumer. No cron changes/pause needed or performed.
- Retirement regression failed while legacy live modules existed, then passed after quarantine.
- `python -m pytest test_confirmed_runtime.py test_grid_state.py test_frozen_grid_calendar.py test_confirmed_589720.py test_confirmed_159363.py -q`: **23 passed**.
- `python -m pytest tools/etf_research -q`: **50 passed**.
- Managed `grid_weixin_execute.py` actually fetched timestamped 2026-10-14 live Tencent quotes and rendered current authoritative holdings. Only conditional advice; no orders/fills.
- Managed `grid_eod_decision.py` actually refused pre-close evaluation.
- Text scan of every remaining managed Python script and the new runtime modules found no `grid_account`, `grid_migration`, `grid_runtime_guard`, `ledger.json`, or `migration.json` reference. Research tests' temporary ledger fixtures are not live consumers; existing archived research-unification evidence is intentionally untouched.
- All protected hashes matched again after actual execution. New transactions, midnight inventory rollover and intraday alert writes were not invoked.

The one-time operation script is `tools/confirmed_grid/retire_legacy.py`; it explicitly validates scheduled targets before moving, creates a dated hash manifest, and verifies moved bytes. The managed-home regression is `tools/confirmed_grid/test_retirement.py` (requires this configured managed home; it is not a portable synthetic fixture).
