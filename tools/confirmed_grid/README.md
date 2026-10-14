# Unified confirmed ETF runtime

Production home: `D:/Hermes Agent CN Desktop/data/hermes-home`.
Repository: `D:/Code/AH_analyse`.

Only `confirmed-589720.json` and `confirmed-159363.json` are runtime authorities.
Initial INPUT fixtures are historical snapshots, not live books; do not rerun importers over existing state.
The runtime never reads legacy `ledger.json`, tickets, migration policy, or an assumed account cash balance.

Deploy: `python tools/confirmed_grid/deploy.py --home "D:/Hermes Agent CN Desktop/data/hermes-home"`.
Seven same-name launchers are backed up then installed; state SHA256 and launcher bytes are verified.
No cron metadata is edited by the deployment script.

Test: `python -m unittest test_confirmed_runtime test_grid_state test_confirmed_589720 test_confirmed_159363 -v`.
All fill tests write temporary files only. Live opening, intraday, EOD and midnight entrypoints may be run;
never pass a made-up successful fill against live home.

Explicit confirmation schema:
`python "D:/Hermes Agent CN Desktop/data/hermes-home/scripts/grid_weixin_confirm.py" 成功 --code sh589720 --side sell --qty ACTUAL_QTY --price ACTUAL_PRICE --date YYYY-MM-DD --id UNIQUE_CONFIRMED_EXECUTION_ID`
Bare 成功 fails closed. 失败 never mutates state. Duplicate identical ID is a no-op;
conflicting ID, partial economic-grid sell, insufficient saved sellable inventory and pointer mismatch fail closed.
Confirmation immediately prints remaining conditional recommendations.

Policy: 1.5%; 8000/6000 yuan buy budgets rounded down to 100 shares; one buy/sell per ETF.
Current maximum open-grid purchase anchors both next buy and sell; final-grid sale anchors rebuy when empty.
159363 recommendations preserve 4600 shares, but explicit actual fills are recorded truthfully.
Quotes must be same session, >=09:30, not future, and <=180 seconds old; execution advice only during
continuous trading, >=09:31. Calendar uses verified 2026 exchange module, fails closed outside its range.
Intraday uses spot OR day extrema, deduplicated by day/code/side/price, never infers a fill.
OS-held locks serialize midnight/fills; unique fsynced temporary files replace atomically.
Late rollover excludes dated same-day buys and never resets same-day sellable state.

159992, cash, account/ETF caps, broker sellable/frozen inventory and outstanding orders remain external
verification requirements. Output is always conditional, not directly executable and never an automatic order.
EOD verifies same-day Tencent closing bar against quote, stores confirmed-state fingerprints/costs/cycles;
unknown historical dates disable temporal efficiency claims; rebase/rotation remains unverified, not auto-applied.
