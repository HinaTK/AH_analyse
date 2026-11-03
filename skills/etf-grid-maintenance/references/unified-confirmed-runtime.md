# Unified confirmed runtime deployed 2026-10-14

Repo D:/Code/AH_analyse: confirmed_runtime.py + grid_state.py. Managed home D:/Hermes Agent CN Desktop/data/hermes-home. tools/confirmed_grid/deploy.py installs seven same-name scripts and verifies hashes/bytes, no cron edits. Only confirmed-589720.json and confirmed-159363.json are registered; 159992 and account funds remain unverified.

All live preview/execute/ops/intraday/confirmation/EOD/midnight now use these states, not grid_account.load/plan/apply. Bare 成功 is rejected. Explicit confirmation: grid_weixin_confirm.py 成功 --code {sh589720,sz159363} --side {buy,sell} --qty ACTUAL --price ACTUAL --date YYYY-MM-DD --id UNIQUE_EXPLICIT_ID. 失败 is no-op. Never create a fake successful fill in live home. record API requires explicit ID; duplicate same payload no-op, conflicting ID rejected. Partial economic-grid sale rejected.

Next buy anchors current max open-grid purchase /1.015, not latest sale while other grids remain. Sell anchors same max buy *1.015. Budgets8000/6000,100-share floor;159363 recommended sells retain4600 core, actual fills still truthfully booked. Quotes same day >=09:30, <=180sec old, not future; <=2026 verified calendar, continuous session >=09:31. Touch notifications dedup day/code/side/price, no touch-as-fill. Confirm prints remaining advice immediately.

OS-held locks and atomic fsynced unique temp writes protect midnight/fill race. Repeat same-day midnight cannot restore sold inventory, late invocation excludes dated same-day buys. Historical null dates preserved. Initial importer cannot overwrite existing589720 book.

Tests: python -m unittest test_confirmed_runtime test_grid_state test_confirmed_589720 test_confirmed_159363 -v. All fill tests tmp. EOD live morning must report unconfirmed close; real closing-feed acceptance must wait for after-close. Full repository unittest discovery can hit unrelated upstream/network tests and time out; do not call scoped regression a full suite.
