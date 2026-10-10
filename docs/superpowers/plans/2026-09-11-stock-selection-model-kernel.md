# Stock Selection Model Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the live ranking key with a purged walk-forward cross-sectional ranker, while keeping the existing pre-market collection, honesty, P0, quality-gate, diversification, defense cap, WATCH-only, and push shell.

**Architecture:** Split universe construction from ranking. `scan_snapshot` becomes a tradability pre-screen that no longer drops or ranks names by heuristic tags. Six-dimension scores remain point-in-time features and explanations, not the official sort key. A daily shadow panel records every tradable name plus later T+1-to-T+5 excess labels. `rolling_calibration.py` is extended from bounded six-weight fitting to train/select a ranker; live `composite` switches only after out-of-sample folds beat the current 0.55 weighted baseline.

**Tech Stack:** Python 3.12, pandas, unittest, existing `stock_recommend` pipeline. Optional `lightgbm` only in Task 5+ and only if already importable or added to `requirements.txt` with a linear-rank fallback. No frontend build. Do not overwrite `backend/data/stock_recommend/latest.json` or send pushes from tests.

**Spec:** This plan is the approved design. Prior conversation constraints are binding: do not rebuild the 08:30 funnel; do not treat shortlist tags as a second six-dimension screen; training labels are T+1 open to T+5 close excess vs CSI 300; empty WATCH lists remain valid; LLM hotspots must not add names.

## Global Constraints

- Default working directory for backend work is `D:\\Code\\AH_analyse\\ah_recommendation_system\\backend`.
- Set `$env:PYTHONPATH='D:\\Code\\AH_analyse'` and `$env:PYTHONDONTWRITEBYTECODE='1'` before tests or pipeline runs.
- Tests use `python -m unittest`; there is no pytest config.
- Do not overwrite live stored reports or send Feishu/WeChat pushes.
- Do not claim live alpha from synthetic fixtures.
- Industry membership is provenance only: never a score, never an admission ticket.
- Official stock action remains `WATCH`. Quality-gate failure still clears `picks` and `etf_picks`.
- Stock count cap remains 5; defense regime still caps official names at 2.
- Missing feature values stay missing; do not fill 0 and then rank that dimension.
- If IC / out-of-sample excess is not stably better than the six-weight baseline, keep the old live ranking key and write the refusal reasons.

## File map

- Modify: `ah_recommendation_system/backend/stock_recommend/dynamic_scanner.py` — tradability pre-screen; tags become sidecar fields.
- Modify: `ah_recommendation_system/backend/stock_recommend/run.py` — stop replacing the full-market rows with a 600-name tagged shortlist; persist a shadow ranking panel.
- Modify: `ah_recommendation_system/backend/stock_recommend/candidate_pool.py` — keep six-dimension features; add `model_score` without changing live sort until promotion.
- Modify: `ah_recommendation_system/backend/stock_recommend/rule_selector.py` — consume `model_score` only when promotion is applied.
- Modify: `ah_recommendation_system/backend/stock_recommend/rolling_calibration.py` — add ranker walk-forward; keep the six-weight fitter as baseline comparator.
- Modify: `ah_recommendation_system/backend/stock_recommend/local_store.py` — persist daily feature/label panel parquet, separate from spot cache.
- Modify: `ah_recommendation_system/backend/stock_recommend/backtest_verify.py` — attach T+1..T+5 excess labels onto the full tradable panel, not only official picks.
- Create: `ah_recommendation_system/backend/stock_recommend/cross_section.py` — missing-aware cross-sectional rank/zscore.
- Create: `ah_recommendation_system/backend/stock_recommend/rank_model.py` — train/predict with linear ranker first, LightGBM rank if available.
- Tests: `tests/test_evidence_recommendation.py`, `tests/test_cross_section.py`, `tests/test_rank_model.py`, `tests/test_ranking_labels.py`, `tests/test_rolling_calibration.py`, `tests/test_stock_recommend_pipeline.py`.
- Do not modify Feishu/WeChat pushers or ETF quality gates. Do not weaken `quality_gate.py` blockers.

---

### Task 1: Tradability pre-screen, tags are sidecar only

**Files:**
- Modify: `ah_recommendation_system/backend/stock_recommend/dynamic_scanner.py`
- Modify: `ah_recommendation_system/backend/tests/test_evidence_recommendation.py`
- Modify: `ah_recommendation_system/backend/stock_recommend/run.py` (scan call site around lines 430-441)

**Interfaces:**
- Consumes: snapshot rows with `code`, `name`, `price`, `amount`.
- Produces: `scan_snapshot(rows, *, focus_industries=None, activity_rows=None, limit: int | None = None) -> list[dict]`.
- Keep every tradable name when `limit is None`.
- Drop only: non-6-digit code, missing/non-positive price, ST/退/暂停/B股 name patterns, amount missing or `< 100_000_000`.
- Write heuristic tags into `source_tags_sidecar`. Do not `continue` when tags are empty.
- Sort by `amount` descending, then code. Do not sort by tag count.
- `focus_industry` is provenance only.

- [ ] **Step 1: Write the failing test**

```python
def test_scan_snapshot_keeps_untagged_tradable_names(self):
    from ah_recommendation_system.backend.stock_recommend.dynamic_scanner import scan_snapshot
    rows = [
        {"code": "000001", "name": "平安银行", "price": 10.0, "amount": 200_000_000, "change_pct": 0.2},
        {"code": "000002", "name": "ST示例", "price": 10.0, "amount": 500_000_000, "change_pct": 5.0},
        {"code": "000003", "name": "无成交", "price": 10.0, "amount": 1_000_000, "change_pct": 4.0},
        {"code": "000004", "name": "无价格", "amount": 200_000_000, "change_pct": 4.0},
    ]
    seeds = scan_snapshot(rows, limit=None)
    codes = [row["code"] for row in seeds]
    self.assertEqual(codes, ["000001"])
    self.assertIn("source_tags_sidecar", seeds[0])
```

Also change existing tests:
- `test_dynamic_scanner_adds_price_volume_and_new_high_tags`: sidecar may still contain `market_leader` / `volume_expansion` / `new_high`, but those tags are not required for inclusion.
- `test_scanner_uses_cross_sectional_liquidity_when_history_is_absent`: `limit=None` returns all 200 liquid rows; `limit=80` returns top 80 by amount, not by tag count.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_evidence_recommendation.TestEvidenceRecommendation.test_scan_snapshot_keeps_untagged_tradable_names -v`

Expected: FAIL because untagged rows are still dropped.

- [ ] **Step 3: Write minimal implementation**

Replace the `if not tags: continue` branch and the tag-count sort. Keep current tag builders, assign them to `source_tags_sidecar`. Admission uses only tradability. Default `limit=None`. `run.py` must call `scan_snapshot(..., limit=None)` so live pre-market no longer truncates to 600 by tags. If a caller still passes `limit=600`, that is amount-based truncation only.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_evidence_recommendation -v`

- [ ] **Step 5: Commit**

```bash
git add ah_recommendation_system/backend/stock_recommend/dynamic_scanner.py ah_recommendation_system/backend/stock_recommend/run.py ah_recommendation_system/backend/tests/test_evidence_recommendation.py
git commit -m "feat: treat scanner tags as sidecar, keep tradable universe"
```

### Task 2: Cross-sectional transforms that skip missing values

**Files:**
- Create: `ah_recommendation_system/backend/stock_recommend/cross_section.py`
- Create: `ah_recommendation_system/backend/tests/test_cross_section.py`

**Interfaces:**
- `cross_sectional_ranks(rows: list[dict], key: str, *, higher_is_better: bool = True) -> list[float | None]`
- `cross_sectional_zscores(rows: list[dict], key: str) -> list[float | None]`
- Missing or non-finite values return `None` and are excluded from mean/std/rank denominator.

- [ ] **Step 1: Write the failing test**

```python
class TestCrossSection(unittest.TestCase):
    def test_missing_values_do_not_fill_zero(self):
        from ah_recommendation_system.backend.stock_recommend.cross_section import (
            cross_sectional_ranks, cross_sectional_zscores,
        )
        rows = [{"x": 1.0}, {"x": None}, {"x": 3.0}]
        ranks = cross_sectional_ranks(rows, "x")
        z = cross_sectional_zscores(rows, "x")
        self.assertEqual(ranks[1], None)
        self.assertEqual(z[1], None)
        self.assertGreater(ranks[2], ranks[0])
        self.assertAlmostEqual(sum(v for v in z if v is not None), 0.0, places=6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cross_section -v`

Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

Percentile ranks on finite values only, average ties. Z-score uses finite mean and population std; if n < 2 or std is 0, return None for all rather than fabricating 0.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cross_section -v`

- [ ] **Step 5: Commit**

```bash
git add ah_recommendation_system/backend/stock_recommend/cross_section.py ah_recommendation_system/backend/tests/test_cross_section.py
git commit -m "feat: add missing-aware cross-sectional rank and zscore"
```

---

### Task 3: Daily shadow panel of tradable names, not official picks

**Files:**
- Modify: `ah_recommendation_system/backend/stock_recommend/local_store.py`
- Modify: `ah_recommendation_system/backend/stock_recommend/run.py`
- Test: `tests/test_stock_recommend_pipeline.py` with an isolated tmp dir

**Interfaces:**
- `persist_ranking_panel(rows: Iterable[dict], root: Path, *, as_of: str) -> dict`
- parquet path `backend/data/stock_recommend/panels/ranking_panel_{YYYYMMDD}.parquet`
- each row includes: `date`, `code`, `name`, `price`, `amount`, `pe`, `market_cap`, `focus_industries`, `factors`, `source_tags_sidecar`, `point_in_time_snapshot=True`, `panel_scope="all_tradable"`, `source="live_execution"` on live runs and `"mock"` on mock runs
- Live `picks` in this task still use six-dimension `composite`.

- [ ] **Step 1: Write the failing test**

Patch `save_report` and panel destination to a temp directory. Run `run_pipeline(mock=True, push=False)` and assert:
- a panel file is written
- panel length equals tradable pre-screen length, not `top_n_candidates`
- official `report["picks"]` still come from composite / `select_by_rules`
- panel rows contain `factors.trend` and `source_tags_sidecar`
- mock panels are tagged `source="mock"` so calibration later refuses them

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL because `persist_ranking_panel` does not exist and `run.py` still replaces `snap.fundamental["rows"]` with the old shortlist.

- [ ] **Step 3: Write minimal implementation**

After tradability `scan_snapshot`, keep the full tradable universe for ranking-panel persistence. `build_candidates` may still truncate the report card to 30 names. The shadow panel must be built from the pre-truncation tradable set. Mock tests may use a 20-name fixture; live path must not re-introduce tag admission. Do not write onto production `latest.json`.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_stock_recommend_pipeline -v`

- [ ] **Step 5: Commit**

```bash
git add ah_recommendation_system/backend/stock_recommend/local_store.py ah_recommendation_system/backend/stock_recommend/run.py ah_recommendation_system/backend/tests/test_stock_recommend_pipeline.py
git commit -m "feat: persist full tradable shadow panel without changing live picks"
```

---

### Task 4: Forward labels are T+1 to T+5 excess vs CSI 300

**Files:**
- Modify: `ah_recommendation_system/backend/stock_recommend/backtest_verify.py`
- Create: `ah_recommendation_system/backend/tests/test_ranking_labels.py`

**Interfaces:**
- `label_ranking_panel(panel, bars_by_code, benchmark_calendar) -> list[dict]`
- `entry_date` = first session strictly after signal date
- `label_end` = fifth session after entry (T+5 close)
- `net_return_pct` from existing `execution_validation`
- `excess_return_pct` = net return minus CSI 300 over the same dates
- `status` in `{filled, unfilled}`
- incomplete horizons stay out of the training set
- membership is by signal date; delayed exits stay in the cohort

- [ ] **Step 1: Write the failing test**

Two names and a CSI 300 series. Signal D0, stock A fills D1 open and exits D5 close +1%, CSI 300 +0.2% over the same window. Assert excess is about 0.8 after costs already inside net return. A second name suspended on D1 is `unfilled` and remains in the panel with no fabricated fill.

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL if labels are still computed only for official picks or use same-day close-to-close.

- [ ] **Step 3: Write minimal implementation**

Reuse `execution_validation` timing. Do not use future bars for features.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_ranking_labels tests.test_forward_verification -v`

- [ ] **Step 5: Commit**

```bash
git add ah_recommendation_system/backend/stock_recommend/backtest_verify.py ah_recommendation_system/backend/tests/test_ranking_labels.py
git commit -m "feat: label tradable panel with T+1 to T+5 CSI300 excess"
```

### Task 5: Ranker with linear fallback, LightGBM optional

**Files:**
- Create: `ah_recommendation_system/backend/stock_recommend/rank_model.py`
- Create: `ah_recommendation_system/backend/tests/test_rank_model.py`

**Interfaces:**
- `fit_ranker(train_rows: list[dict], *, feature_keys: list[str]) -> RankerModel`
- `predict_scores(model: RankerModel, rows: list[dict]) -> list[float | None]`
- Feature keys: `trend`, `price_volume`, `value_quality`, `capital`, `relative_strength`, `event` after Task 2 ranks
- Missing feature: skip that row in training or predict `None`; never impute 0
- `RankerModel.kind` is `"linear"` or `"lightgbm_rank"`
- Try LightGBM lambdarank only if `import lightgbm` works; otherwise ridge/linear on cross-sectional excess

- [ ] **Step 1: Write the failing tests**

```python
def test_linear_ranker_ranks_higher_excess_features_higher(self):
    train = [
        {"code": "1", "factors": {"trend": 0.9, "price_volume": 0.8, "value_quality": 0.5, "capital": 0.4, "relative_strength": 0.7, "event": 0.5}, "excess_return_pct": 2.0},
        {"code": "2", "factors": {"trend": 0.1, "price_volume": 0.2, "value_quality": 0.5, "capital": 0.4, "relative_strength": 0.2, "event": 0.5}, "excess_return_pct": -1.0},
    ]
    model = fit_ranker(train, feature_keys=list(train[0]["factors"]))
    scores = predict_scores(model, train)
    self.assertGreater(scores[0], scores[1])

def test_missing_feature_does_not_become_zero_advantage(self):
    train = [{"code": "1", "factors": {"trend": 0.9, "price_volume": 0.5, "value_quality": 0.5, "capital": 0.5, "relative_strength": 0.5, "event": 0.5}, "excess_return_pct": 1.0}] * 20
    rows = [
        {"factors": {"trend": 0.9, "price_volume": 0.5, "value_quality": 0.5, "capital": 0.5, "relative_strength": 0.5, "event": 0.5}},
        {"factors": {"trend": None, "price_volume": 0.5, "value_quality": 0.5, "capital": 0.5, "relative_strength": 0.5, "event": 0.5}},
    ]
    model = fit_ranker(train, feature_keys=list(rows[0]["factors"]))
    scores = predict_scores(model, rows)
    self.assertIsNotNone(scores[0])
    self.assertTrue(scores[1] is None or scores[1] <= scores[0])
```

- [ ] **Step 2: Run test to verify it fails**

Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

Fit ridge/linear on finite feature rows. Predict None when required features are missing. Keep raw `factor_scores` for explanation.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_rank_model -v`

- [ ] **Step 5: Commit**

```bash
git add ah_recommendation_system/backend/stock_recommend/rank_model.py ah_recommendation_system/backend/tests/test_rank_model.py
git commit -m "feat: add cross-sectional ranker with missing-aware linear fallback"
```

---

### Task 6: Walk-forward promotion gate, live switch is explicit

**Files:**
- Modify: `ah_recommendation_system/backend/stock_recommend/rolling_calibration.py`
- Modify: `ah_recommendation_system/backend/stock_recommend/reweight.py`
- Modify: `ah_recommendation_system/backend/stock_recommend/candidate_pool.py`
- Modify: `ah_recommendation_system/backend/stock_recommend/rule_selector.py`
- Modify: `ah_recommendation_system/backend/tests/test_rolling_calibration.py`

**Interfaces:**
- `rolling_calibrate_ranker(...)` returns the current promotion envelope: `applied`, `reasons`, `methodology="purged_rolling_ranker_v1"`.
- Keep `rolling_calibrate` six-weight fitter as `baseline_metrics`.
- Promotion requires: `source=="live_execution"`, `point_in_time_snapshot`, `panel_scope=="all_tradable"`, purged splits, at least 3 folds, latest test mean net excess > baseline 0.55 six-weight policy, drawdown not worse than the existing comparator.
- Live `run.py` ranks by `composite` unless `factor_weights.json` contains `"ranking_key": "model_score"` and `"factor_version": "ranker-v1"` written only by `applied=true`.
- When ranking key is `model_score`, threshold is a validation quantile stored as `minimum_score` in model-score space, not the old 0.55 composite.
- Default after merge remains `ranking_key="composite"`. Weekly job always writes `proposed_*`.

- [ ] **Step 1: Write the failing tests**

- mock/non-live panel cannot promote
- `panel_scope != all_tradable` cannot promote
- when folds beat baseline, `applied is True` and `ranking_key == "model_score"`
- when folds lose, weights file is unchanged and live pipeline still sorts by composite

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL because ranker calibration API does not exist.

- [ ] **Step 3: Write minimal implementation**

If promoted model file is absent, `model_score` is None and ranking stays composite. Linear coefficients may be stored as JSON; pickle only if needed for LightGBM.

- [ ] **Step 4: Run tests**

`python -m unittest tests.test_rolling_calibration tests.test_stock_recommend_pipeline tests.test_evidence_recommendation -v`

Then: `python -m unittest discover -s tests -p "test_*.py"`

- [ ] **Step 5: Commit**

```bash
git add ah_recommendation_system/backend/stock_recommend/rolling_calibration.py ah_recommendation_system/backend/stock_recommend/reweight.py ah_recommendation_system/backend/stock_recommend/candidate_pool.py ah_recommendation_system/backend/stock_recommend/rule_selector.py ah_recommendation_system/backend/tests/test_rolling_calibration.py
git commit -m "feat: promote ranker only after purged walk-forward beats baseline"
```

---

### Task 7: Keep defensive shell and stop using tags as selection reasons

**Files:**
- Modify: `ah_recommendation_system/backend/stock_recommend/rule_selector.py`
- Modify: `ah_recommendation_system/backend/stock_recommend/report_builder.py` only if it currently prints shortlist tags as the reason
- Add a short audit note under `docs/analyse/`, not a profitability claim

**Interfaces:**
- Official pick `rationale` uses evidence statements, never tag counts.
- Sidecar tags may appear in `candidate_sources` for humans.
- If weekly job `applied=false`, keep composite ranking and add warning `ranking_key_not_promoted`.
- Coverage `candidate_count` is tradable pre-screen size.
- Empty `picks=[]` remains valid. Do not implement Alpha158 / Qlib download in this plan.

- [ ] **Step 1: Write/adjust tests that empty WATCH is allowed when the ranker abstains**

If every `model_score` is below the stored cutoff, `select_by_rules` returns `picks=[]`. Quality gate must still pass when coverage/evidence fields are valid.

- [ ] **Step 2: Run the empty-pick test**

If it already passes under composite, keep that behavior for model_score.

- [ ] **Step 3: Minimal copy/report changes**

Remove wording that the 600-name tagged shortlist is the investable universe.

- [ ] **Step 4: Full suite**

Run: `python -m unittest discover -s tests -p "test_*.py"`

Do not run live `run_daily_job.py` against production latest unless the user asks.

- [ ] **Step 5: Commit**

```bash
git add ah_recommendation_system/backend/stock_recommend/rule_selector.py ah_recommendation_system/backend/stock_recommend/report_builder.py docs/analyse
git commit -m "docs: ranker explanations stay evidence-based; tags are not selection"
```

---

## Out of scope

- Rewriting collection, Feishu/WeChat, ETF 0-3 selection, P0 veto, quality-gate clearing.
- Installing Qlib as a runtime dependency or copying Alpha158 blindly.
- Using LLM hotspots to insert names.
- Filling missing PE/momentum with 0.5 neutral quality.
- Treating yesterday's observation pool as today's universe.

## Self-review

- Spec coverage: tradability vs tags, missing-value discipline, T+1..T+5 CSI 300 labels, purged promotion, keep shell, no live overwrite — each has a task.
- Placeholder scan: no TBD / implement later.
- Type consistency: `scan_snapshot(..., limit=None)`, `persist_ranking_panel`, `fit_ranker` / `predict_scores`, `rolling_calibrate_ranker`, `ranking_key` in `{"composite","model_score"}`.

## Execution notes for agents

Work in the existing dirty checkout. Do not `git reset --hard`. If `factor_weights.json` still stores old `fundamental/capital/event` keys, leave it; `load_factor_weights` already falls back to six-dimension defaults until a ranker-v1 payload is written by Task 6.
