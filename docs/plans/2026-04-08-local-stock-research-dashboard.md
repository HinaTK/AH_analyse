# Local Stock Research Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a local-first stock research dashboard on top of the existing A/H recommendation system, adding a watchlist, unified single-stock research, lightweight on-demand backtests, and clean seams for future live-trading modules.

**Architecture:** Extend the current FastAPI + single-file Vue app in place instead of introducing OpenBB/vn.py/Qlib as runtime dependencies. Keep the existing stored-report dashboard intact, add a small JSON-backed watchlist store, add a research aggregation service that composes existing strategy/data modules, and expose new routes for watchlist/research/backtest. Keep future live-trading optional by placing new logic in separate service/store modules rather than stuffing it into `run_daily_job.py` or the existing strategy routers.

**Tech Stack:** FastAPI, Pydantic, unittest, existing Vue 3 + Axios + ECharts single-page frontend, AKShare-backed price/data fetcher, JSON file persistence.

---

## Recommended product scope

### What V1 will include
- Keep the current 4 strategy tabs untouched as the default dashboard.
- Add a **Watchlist** tab for user-selected A/H names.
- Add a **Research** tab for one symbol at a time.
- Show in the Research tab:
  - stock metadata and paired H-share code
  - latest A/H premium and a recent premium time series chart
  - existing pair-trading, multi-factor, and ML single-stock analysis outputs
  - a lightweight on-demand pair backtest for the selected A/H pair
- Persist watchlist locally in repo data files.

### What V1 will explicitly not include
- No broker integration
- No live order execution
- No account/position management
- No DB migration layer yet
- No Qlib/vn.py/OpenBB runtime dependency

### Future-ready seam
If live trading is added later, it should sit beside these V1 modules:
- `backend/data/` for market data
- `backend/research/` for read-only analysis orchestration
- `backend/watchlist/` for user state
- future `backend/execution/` or `backend/portfolio/` for orders/positions/accounts

---

### Task 1: Add local watchlist persistence

**Files:**
- Create: `ah_recommendation_system/backend/watchlist/watchlist_store.py`
- Create: `ah_recommendation_system/backend/tests/test_watchlist_store.py`
- Create: `ah_recommendation_system/backend/data/watchlists/` (runtime output directory)

**Step 1: Write the failing test**

```python
import tempfile
import unittest
from pathlib import Path

from ah_recommendation_system.backend.watchlist.watchlist_store import WatchlistStore


class TestWatchlistStore(unittest.TestCase):
    def test_add_list_remove_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchlistStore(root_dir=Path(tmp))

            store.add_symbol("601398.SH")
            store.add_symbol("601398.SH")  # dedupe
            store.add_symbol("002594.SZ")

            items = store.list_symbols()
            self.assertEqual([item["a_code"] for item in items], ["601398.SH", "002594.SZ"])

            store.remove_symbol("601398.SH")
            items = store.list_symbols()
            self.assertEqual([item["a_code"] for item in items], ["002594.SZ"])
```

**Step 2: Run test to verify it fails**

Run from `ah_recommendation_system/backend`:

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_watchlist_store
```

Expected: FAIL with `ModuleNotFoundError` for `watchlist_store`.

**Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from ah_recommendation_system.backend.data.ah_stock_list import get_ah_pairs, get_stock_name


@dataclass(frozen=True)
class WatchlistStore:
    root_dir: Path

    @property
    def file_path(self) -> Path:
        path = self.root_dir / "data" / "watchlists" / "default.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("[]", encoding="utf-8")
        return path

    def _load_raw(self) -> List[str]:
        data = json.loads(self.file_path.read_text(encoding="utf-8"))
        return [str(item).strip().upper() for item in data if str(item).strip()]

    def _save_raw(self, items: List[str]) -> None:
        self.file_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_symbols(self) -> List[Dict[str, Any]]:
        pairs = get_ah_pairs()
        out = []
        for a_code in self._load_raw():
            out.append({
                "a_code": a_code,
                "h_code": pairs.get(a_code, ""),
                "name": get_stock_name(a_code),
            })
        return out

    def add_symbol(self, a_code: str) -> None:
        items = self._load_raw()
        code = (a_code or "").strip().upper()
        if code and code not in items:
            items.append(code)
            self._save_raw(items)

    def remove_symbol(self, a_code: str) -> None:
        code = (a_code or "").strip().upper()
        items = [item for item in self._load_raw() if item != code]
        self._save_raw(items)
```

**Step 4: Run test to verify it passes**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_watchlist_store
```

Expected: PASS.

**Step 5: Commit**

```bash
git add ah_recommendation_system/backend/watchlist/watchlist_store.py ah_recommendation_system/backend/tests/test_watchlist_store.py
git commit -m "feat: add local watchlist persistence"
```

---

### Task 2: Add a unified research aggregation service

**Files:**
- Create: `ah_recommendation_system/backend/research/research_service.py`
- Create: `ah_recommendation_system/backend/tests/test_research_service.py`
- Modify: `ah_recommendation_system/backend/backtest/pair_trading_backtest.py` (only if a small reusable helper is needed)

**Step 1: Write the failing test**

```python
import unittest
from unittest.mock import patch
import pandas as pd

from ah_recommendation_system.backend.research.research_service import build_stock_research


class TestResearchService(unittest.TestCase):
    @patch("ah_recommendation_system.backend.research.research_service.get_stock_name", return_value="工商银行")
    @patch("ah_recommendation_system.backend.research.research_service.get_ah_pairs", return_value={"601398.SH": "1398.HK"})
    def test_build_stock_research_returns_combined_payload(self, *_mocks):
        premium = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "a_close": [7.0, 7.1],
            "h_close": [5.5, 5.6],
            "hkd_cny": [0.92, 0.92],
            "premium_pct": [38.3, 37.7],
        })

        with patch("ah_recommendation_system.backend.research.research_service.get_price_fetcher") as fetcher_mock:
            fetcher_mock.return_value.get_ah_premium.return_value = premium
            payload = build_stock_research("601398.SH")

        self.assertEqual(payload["stock"]["a_code"], "601398.SH")
        self.assertEqual(payload["stock"]["h_code"], "1398.HK")
        self.assertIn("premium_series", payload)
        self.assertIn("pair_trading", payload)
        self.assertIn("multi_factor", payload)
        self.assertIn("ml_prediction", payload)
```

**Step 2: Run test to verify it fails**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_research_service
```

Expected: FAIL because `research_service.py` does not exist.

**Step 3: Write minimal implementation**

```python
from __future__ import annotations

from typing import Any, Dict

from ah_recommendation_system.backend.data.ah_stock_list import get_ah_pairs, get_stock_name
from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.strategies.pair_trading import get_pair_trading_strategy
from ah_recommendation_system.backend.strategies.multi_factor import get_multi_factor_strategy
from ah_recommendation_system.backend.strategies.ml_predictor import get_ml_predictor_strategy


def _df_to_records(df) -> list[dict]:
    if df is None or getattr(df, "empty", True):
        return []
    rows = []
    for row in df.tail(90).to_dict(orient="records"):
        row = dict(row)
        if "date" in row and hasattr(row["date"], "strftime"):
            row["date"] = row["date"].strftime("%Y-%m-%d")
        rows.append(row)
    return rows


def build_stock_research(a_code: str) -> Dict[str, Any]:
    pairs = get_ah_pairs()
    norm_code = (a_code or "").strip().upper()
    h_code = pairs.get(norm_code, "")

    pair = get_pair_trading_strategy().analyze_single_pair(norm_code, h_code) if h_code else {}
    mf = get_multi_factor_strategy().analyze_single_stock(norm_code, h_code)
    ml = get_ml_predictor_strategy().predict(norm_code, h_code)
    premium_df = get_price_fetcher().get_ah_premium(norm_code, h_code) if h_code else None

    latest_premium = None
    if premium_df is not None and not premium_df.empty:
        latest_premium = float(premium_df.iloc[-1]["premium_pct"])

    return {
        "stock": {
            "a_code": norm_code,
            "h_code": h_code,
            "name": get_stock_name(norm_code),
            "latest_premium_pct": latest_premium,
        },
        "premium_series": _df_to_records(premium_df),
        "pair_trading": pair or {},
        "multi_factor": mf or {},
        "ml_prediction": ml or {},
    }
```

**Step 4: Run test to verify it passes**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_research_service
```

Expected: PASS.

**Step 5: Commit**

```bash
git add ah_recommendation_system/backend/research/research_service.py ah_recommendation_system/backend/tests/test_research_service.py
git commit -m "feat: add unified stock research service"
```

---

### Task 3: Expose watchlist and research API routes

**Files:**
- Create: `ah_recommendation_system/backend/api/watchlist_routes.py`
- Create: `ah_recommendation_system/backend/api/research_routes.py`
- Create: `ah_recommendation_system/backend/tests/test_research_routes.py`
- Modify: `ah_recommendation_system/backend/api/models.py:9-120`
- Modify: `ah_recommendation_system/backend/main.py:165-171`

**Step 1: Write the failing API tests**

```python
import unittest
from fastapi.testclient import TestClient

from ah_recommendation_system.backend.main import app


class TestResearchRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_get_stock_research(self):
        response = self.client.get("/api/v1/research/601398.SH")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("stock", body)
        self.assertIn("premium_series", body)

    def test_watchlist_roundtrip(self):
        add_resp = self.client.post("/api/v1/watchlist/601398.SH")
        self.assertEqual(add_resp.status_code, 200)

        list_resp = self.client.get("/api/v1/watchlist")
        self.assertEqual(list_resp.status_code, 200)
        self.assertTrue(any(item["a_code"] == "601398.SH" for item in list_resp.json()["items"]))
```

**Step 2: Run test to verify it fails**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_research_routes
```

Expected: FAIL with 404 routes.

**Step 3: Write minimal implementation**

```python
# watchlist_routes.py
from fastapi import APIRouter
from pathlib import Path
from ah_recommendation_system.backend.watchlist.watchlist_store import WatchlistStore

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])
store = WatchlistStore(root_dir=Path(__file__).resolve().parents[1])

@router.get("")
async def list_watchlist():
    return {"success": True, "items": store.list_symbols()}

@router.post("/{a_code}")
async def add_watchlist_symbol(a_code: str):
    store.add_symbol(a_code)
    return {"success": True}

@router.delete("/{a_code}")
async def remove_watchlist_symbol(a_code: str):
    store.remove_symbol(a_code)
    return {"success": True}
```

```python
# research_routes.py
from fastapi import APIRouter
from ah_recommendation_system.backend.research.research_service import build_stock_research

router = APIRouter(prefix="/api/v1/research", tags=["research"])

@router.get("/{a_code}")
async def get_stock_research(a_code: str):
    return build_stock_research(a_code)
```

```python
# main.py additions
from ah_recommendation_system.backend.api.watchlist_routes import router as watchlist_router
from ah_recommendation_system.backend.api.research_routes import router as research_router

app.include_router(watchlist_router)
app.include_router(research_router)
```

**Step 4: Run test to verify it passes**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_research_routes
```

Expected: PASS.

**Step 5: Commit**

```bash
git add ah_recommendation_system/backend/api/watchlist_routes.py ah_recommendation_system/backend/api/research_routes.py ah_recommendation_system/backend/api/models.py ah_recommendation_system/backend/main.py ah_recommendation_system/backend/tests/test_research_routes.py
git commit -m "feat: add watchlist and research APIs"
```

---

### Task 4: Add lightweight on-demand pair backtest for the Research tab

**Files:**
- Modify: `ah_recommendation_system/backend/api/research_routes.py`
- Modify: `ah_recommendation_system/backend/research/research_service.py`
- Create: `ah_recommendation_system/backend/tests/test_research_backtest_route.py`
- Reuse: `ah_recommendation_system/backend/backtest/pair_trading_backtest.py:177-260`

**Step 1: Write the failing test**

```python
import unittest
from fastapi.testclient import TestClient
from ah_recommendation_system.backend.main import app


class TestResearchBacktestRoute(unittest.TestCase):
    def test_backtest_endpoint_returns_metrics(self):
        client = TestClient(app)
        response = client.get("/api/v1/research/601398.SH/backtest")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("metrics", body)
        self.assertIn("equity_curve", body)
        self.assertIn("trades", body)
```

**Step 2: Run test to verify it fails**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_research_backtest_route
```

Expected: FAIL with missing route.

**Step 3: Write minimal implementation**

```python
from datetime import datetime, timedelta

from ah_recommendation_system.backend.backtest.pair_trading_backtest import run_backtest_from_price_dfs
from ah_recommendation_system.backend.data.ah_stock_list import get_ah_pairs
from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher


def build_pair_backtest(a_code: str) -> dict:
    pairs = get_ah_pairs()
    a_code = (a_code or "").strip().upper()
    h_code = pairs.get(a_code, "")
    if not h_code:
        return {"metrics": {}, "equity_curve": [], "trades": []}

    fetcher = get_price_fetcher()
    start_date = (datetime.now() - timedelta(days=540)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")
    a_df = fetcher.get_a_share_price(a_code, start_date, end_date)
    h_df = fetcher.get_h_share_price(h_code, start_date, end_date)
    return run_backtest_from_price_dfs(
        a_df=a_df,
        h_df=h_df,
        hkd_cny=float(fetcher.get_hkd_cny_exchange_rate()),
        lookback=20,
        entry_z=1.5,
        exit_z=0.2,
        round_trip_cost_pct=0.5,
    )
```

```python
@router.get("/{a_code}/backtest")
async def get_stock_research_backtest(a_code: str):
    return build_pair_backtest(a_code)
```

**Step 4: Run test to verify it passes**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_research_backtest_route
```

Expected: PASS.

**Step 5: Commit**

```bash
git add ah_recommendation_system/backend/api/research_routes.py ah_recommendation_system/backend/research/research_service.py ah_recommendation_system/backend/tests/test_research_backtest_route.py
git commit -m "feat: add research backtest endpoint"
```

---

### Task 5: Add Watchlist and Research tabs to the single-file frontend

**Files:**
- Modify: `ah_recommendation_system/frontend/index.html:244-1318`

**Step 1: Add failing frontend smoke target**

Document the manual smoke checklist first; there is no frontend test runner in this repo.

```text
1. Open /
2. See existing four tabs still render
3. See new Watchlist and Research tabs
4. Add a watchlist symbol
5. Click symbol to open Research tab
6. See premium chart + three strategy blocks + backtest metrics
```

**Step 2: Run backend and confirm the new tabs are still missing**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Expected: app starts, but there are no Watchlist/Research tabs yet.

**Step 3: Write minimal frontend implementation**

Add two new Vue components inside `index.html`:

```javascript
const Watchlist = {
  props: ["toast"],
  data() {
    return { items: [], inputCode: "", loading: false }
  },
  methods: {
    async load() {
      this.loading = true
      const { data } = await axios.get("/api/v1/watchlist")
      this.items = data.items || []
      this.loading = false
    },
    async add() {
      if (!this.inputCode) return
      await axios.post(`/api/v1/watchlist/${encodeURIComponent(this.inputCode)}`)
      this.inputCode = ""
      await this.load()
    },
    async remove(code) {
      await axios.delete(`/api/v1/watchlist/${encodeURIComponent(code)}`)
      await this.load()
    },
  },
  mounted() { this.load() },
}
```

```javascript
const Research = {
  props: ["selectedCode", "toast"],
  data() {
    return { detail: null, backtest: null, loading: false }
  },
  watch: {
    selectedCode: {
      immediate: true,
      async handler(code) {
        if (!code) return
        this.loading = true
        const [detailResp, backtestResp] = await Promise.all([
          axios.get(`/api/v1/research/${encodeURIComponent(code)}`),
          axios.get(`/api/v1/research/${encodeURIComponent(code)}/backtest`),
        ])
        this.detail = detailResp.data
        this.backtest = backtestResp.data
        this.loading = false
      }
    }
  }
}
```

Then update root app state near `tabs` to add:

```javascript
{ key: "watchlist", label: "自选股" },
{ key: "research", label: "个股研究" },
```

Also add a shared `selectedResearchCode` state on the root Vue app so clicking a watchlist row can open the Research tab.

**Step 4: Run the server and perform the manual smoke test**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Expected:
- existing tabs still work
- Watchlist tab can add/remove symbols
- Research tab loads unified analysis
- premium chart renders
- backtest metrics and recent trades render

**Step 5: Commit**

```bash
git add ah_recommendation_system/frontend/index.html
git commit -m "feat: add watchlist and stock research tabs"
```

---

### Task 6: Final verification and release-ready baseline

**Files:**
- Modify only if defects appear during verification

**Step 1: Run focused backend tests**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest tests.test_watchlist_store tests.test_research_service tests.test_research_routes tests.test_research_backtest_route
```

Expected: PASS.

**Step 2: Run the full existing suite**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m unittest discover -s tests -p "test_*.py"
```

Expected: PASS with old and new tests green.

**Step 3: Generate a mock stored report for full UI smoke**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python run_daily_job.py --mock
```

Expected: writes `backend/data/daily_reports/report_YYYYMMDD.json` and `latest.json`.

**Step 4: Start the app and perform the end-to-end smoke run**

```powershell
$env:PYTHONPATH='D:\Code\AH_analyse'; python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Expected:
- old dashboard tabs still load from stored report
- new watchlist works locally
- research page works for at least one static mapped A/H pair such as `601398.SH`
- on-demand backtest endpoint returns metrics and trades

**Step 5: Commit**

```bash
git add ah_recommendation_system/backend ah_recommendation_system/frontend
git commit -m "feat: add local stock research dashboard workflow"
```

---

## External repo references to borrow from
- **OpenBB**: product shape and multi-surface data platform ideas; do not import runtime dependencies now.
- **AKShare**: continue using as the China-market data layer.
- **Qlib**: future factor/ML workflow ideas; do not integrate in V1.
- **vn.py**: future execution/gateway architecture reference; do not integrate in V1.
- **vectorbt / backtrader**: future expansion options if the on-demand backtest grows beyond A/H pair backtests.

## Decision log
- Use the current repo as the product base.
- Do not replatform onto OpenBB.
- Do not add live trading in V1.
- Keep state local and file-backed for now.
- Add future live-trading seams by module boundaries, not by introducing heavyweight dependencies early.
