# Recommendation evidence upgrade implementation plan

**Goal:** Implement all seven improvements agreed in conversation, comparing pinned reference source before each change and iterating on failures. A passing software test does not prove investment performance.

**Architecture:** Retain the deterministic candidate pipeline and event-only LLM authority. Add point-in-time factor evidence and separate portfolio/forward validation utilities, then wire validated results into reports and calibration. Keep API fields compatible where their semantics remain valid; explicitly version changed scores and verification methodology.

**Tech stack:** Python, pandas, unittest; no frontend build. Work in the existing user-modified checkout without resetting unrelated changes.

**Reference manifest:** `docs/analyse/reference-repositories-20260910.json`. Record exact source paths and assumptions with each completed task. User has authorized implementation and iterative testing.

## Acceptance and scope
- [ ] 1. Validate factor IC and cross-correlation on dated cross-sections; prevent duplicated momentum being described as independent relative strength. Missing benchmark evidence stays missing.
- [ ] 2. Add profitability/growth/cash-flow/debt quality inputs with units, provenance and announcement-time checks through collection, scoring and report evidence. Missing quality data cannot become fabricated neutral quality.
- [ ] 3. Implement chronological rolling selection/calibration with training-only fitting, validation-only parameter selection and untouched out-of-sample evaluation; purge overlapping forward outcomes. AlphaEvo signal partition diagnostics are not a substitute for retraining.
- [ ] 4. Verify benchmark-aligned net excess return, turnover and portfolio drawdown, keeping observation returns distinct from executable strategy returns.
- [ ] 5. Simulate entry/exit timing, buy/sell fees, slippage, A-share T+1, suspension and board-specific limits on the actual execution bar. Missing execution data must not imply a fill.
- [ ] 6. Classify market regimes using only information available on signal date, apply exposure/selection gating and report outcomes by regime.
- [ ] 7. Calibrate weights and selection threshold from sufficient dated samples, compare against unchanged baseline, persist version/as-of/sample audit, and reject unproven/out-of-sample-degrading updates.
- [ ] End-to-end integration, reference boundary checks, full unittest suite, independent review and fixes, scorecard with measured software readiness and separately stated unproven profitability.

## Execution sequence
1. Baseline full suite; pin reference revisions. Confirm existing edits before touching files.
2. Add `stock_recommend/execution_validation.py` and `tests/test_execution_validation.py`: pure deterministic entry/exit validator with injectable frames, benchmark and cost settings. Test next-open timing, execution-day suspension/limits, T+1, finite data, cost arithmetic, aligned benchmark and delayed exits. Compare Qlib `backtest/exchange.py` and AlphaEvo `backtest/engine.py`, `rules.py`; do not copy known assumptions blindly.
3. Integrate validation in `backtest_verify.py`: keep old preview-return compatibility separately, add explicit executable net outcomes and status. Reject mock/stale evaluation for calibration. Add pending-horizon retry and avoid permanent partial ledger results. Tests use actual synthetic OHLCV, not mocked output formulas.
4. Add point-in-time quality/relative strength scoring and data adapters; test future-announcement exclusion, missing fields, cash units, sector differences and benchmark lag. Compare Ryan `signal_engine.py` but omit placeholder bonuses and invented targets.
5. Add statistical factor evaluation and rolling calibration; compare AlphaEvo `alpha_factory/validator.py` and Qlib `contrib/rolling/base.py`. Test highly correlated factors, flipped predictive direction, same-day split leakage, overlapping outcomes and future-data invariance.
6. Wire regime policy, versioned calibration and report diagnostics into run/selector/reweight; run focused integration tests and full suite. Preserve top-five cap and P0 veto.
7. Save source comparison, tests, realistic data availability and scoring evidence under `docs/analyse/`; rerun only affected tests after fixes, then full verification once stable. Do not claim live alpha from synthetic fixtures.

## Commands
From `ah_recommendation_system/backend`, set `$env:PYTHONPATH='D:/Code/AH_analyse'` and `$env:PYTHONDONTWRITEBYTECODE='1'`.
`python -m unittest tests.test_execution_validation -v`
`python -m unittest discover -s tests -p 'test_*.py'`
Use isolated temporary output directories for mock integration; do not overwrite live stored reports or send pushes.

## 2026-09-10 resumed implementation checkpoint

All seven code paths now exist and are wired through the pipeline/verifier/weekly job. Final full suite: **273 tests passed, 110.396s**, log `backend/.tmp-recommend-upgrade-acceptance.log`. Independent review identified eight correctness gaps and repairs have regression coverage. Source comparison, explicit limitations and provisional engineering rubric are in `docs/analyse/recommendation-upgrade-source-audit-20260910.md`.

Acceptance boxes above are deliberately not all marked complete: true out-of-sample effectiveness needs a sufficiently long live saved candidate panel; annual financial enrichment currently covers 30 scan candidates; corporate-action total-return accounting, full account lot sizing and BSE coverage remain limitations. Current implementation rejects unsupported evidence instead of inventing fills or promoting unproven weights. Engineering rubric is 79/100; no claim of a high-scoring profitable production strategy.

The first full suite exposed existing mock pipeline tests writing their normal report path; those tests were subsequently isolated by patching save_report. No live push or production weight promotion was performed.
