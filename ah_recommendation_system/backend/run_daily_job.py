from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure repo root is on sys.path so `tools.*` imports work when running from this folder.
try:
    BACKEND_DIR = Path(__file__).resolve().parent
    # repo root contains the `tools/` directory
    REPO_ROOT = BACKEND_DIR.parents[2]
    sys.path.insert(0, str(REPO_ROOT))
except Exception:
    pass

from ah_recommendation_system.backend.backtest.pair_trading_backtest import (
    run_backtest_from_price_dfs,
)

from loguru import logger

from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)
from ah_recommendation_system.backend.strategies.ml_predictor import (
    get_ml_predictor_strategy,
)
from ah_recommendation_system.backend.strategies.multi_factor import (
    get_multi_factor_strategy,
)
from ah_recommendation_system.backend.strategies.pair_trading import (
    get_pair_trading_strategy,
)
from ah_recommendation_system.backend.trading.cost_model import DEFAULT_COST_MODEL

from ah_recommendation_system.backend.etf_sector.etf_sector_report import (
    generate_etf_sector_block,
)


def _generate_pair_trading_backtest(pair_rec: Dict[str, Any]) -> Dict[str, Any]:
    """Compute minimal pair-trading backtest results for the latest signals.

    Design goals:
    - Workflow-first: stored report contains backtest metrics for UI consumption.
    - Keep runtime bounded: only backtest pairs that appear in the top signal buckets.
    - Backward compatible: attach under pair_trading.backtest.
    """
    fetcher = get_price_fetcher()

    lookback_any = get_pair_trading_strategy().config.get("premium_lookback", 20)
    lookback = 20
    if isinstance(lookback_any, int):
        lookback = lookback_any
    elif isinstance(lookback_any, float):
        lookback = int(lookback_any)
    elif isinstance(lookback_any, str):
        try:
            lookback = int(lookback_any)
        except ValueError:
            lookback = 20
    entry_z = 1.5
    exit_z = 0.2
    round_trip_cost_pct = float(DEFAULT_COST_MODEL.estimate_round_trip_cost_pct())

    # Backtest window: ensure enough data for rolling statistics.
    end_date = datetime.now().strftime("%Y%m%d")
    # Use a wide window; price_fetcher will handle data availability.
    start_date = (datetime.now() - timedelta(days=540)).strftime("%Y%m%d")

    signals = (pair_rec or {}).get("signals") or {}
    max_pairs = int((pair_rec or {}).get("parameters", {}).get("max_positions") or 10)

    seen: set[str] = set()
    pairs: list[Dict[str, Any]] = []
    for bucket in ("buy_ah", "sell_ah"):
        for item in (signals.get(bucket) or [])[:max_pairs]:
            a_code = (item or {}).get("a_code")
            h_code = (item or {}).get("h_code")
            if not a_code or not h_code:
                continue
            key = f"{a_code}|{h_code}"
            if key in seen:
                continue
            seen.add(key)
            pairs.append(
                {"a_code": a_code, "h_code": h_code, "name": (item or {}).get("name")}
            )

    results: list[Dict[str, Any]] = []
    trades_total = 0
    total_returns: list[float] = []
    win_rates: list[float] = []

    hkd_cny = float(fetcher.get_hkd_cny_exchange_rate())

    for p in pairs:
        a_code = p["a_code"]
        h_code = p["h_code"]
        name = p.get("name")

        a_df = fetcher.get_a_share_price(a_code, start_date, end_date)
        h_df = fetcher.get_h_share_price(h_code, start_date, end_date)
        if a_df is None or h_df is None or a_df.empty or h_df.empty:
            continue

        bt = run_backtest_from_price_dfs(
            a_df=a_df,
            h_df=h_df,
            hkd_cny=hkd_cny,
            lookback=lookback,
            entry_z=entry_z,
            exit_z=exit_z,
            round_trip_cost_pct=round_trip_cost_pct,
        )

        metrics = bt.get("metrics") or {}
        trades = bt.get("trades") or []
        trades_total += int(metrics.get("trades") or 0)
        if "total_return_pct" in metrics:
            total_returns.append(float(metrics.get("total_return_pct") or 0.0))
        if "win_rate" in metrics:
            win_rates.append(float(metrics.get("win_rate") or 0.0))

        results.append(
            {
                "a_code": a_code,
                "h_code": h_code,
                "name": name,
                "metrics": metrics,
                "parameters": bt.get("parameters") or {},
                "equity_curve": bt.get("equity_curve") or [],
                "trades": trades[-20:],
            }
        )

    avg_total_return = (
        (sum(total_returns) / len(total_returns)) if total_returns else 0.0
    )
    avg_win_rate = (sum(win_rates) / len(win_rates)) if win_rates else 0.0

    return {
        "strategy": "pair_trading_mean_reversion",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "parameters": {
            "start_date": start_date,
            "end_date": end_date,
            "lookback": lookback,
            "entry_z": entry_z,
            "exit_z": exit_z,
            "round_trip_cost_pct": round_trip_cost_pct,
            "hkd_cny": hkd_cny,
        },
        "summary": {
            "pairs_tested": len(results),
            "trades_total": trades_total,
            "avg_total_return_pct": round(avg_total_return, 3),
            "avg_win_rate": round(avg_win_rate, 4),
        },
        "results": results,
    }


def generate_report() -> Dict[str, Any]:
    store = get_report_store()
    prev = None
    try:
        prev = store.load_latest()
    except Exception:
        prev = None

    pair_strategy = get_pair_trading_strategy()
    mf_strategy = get_multi_factor_strategy()
    ml_strategy = get_ml_predictor_strategy()

    pair_rec = pair_strategy.generate_recommendations()
    # Attach backtest metrics (workflow-first, UI consumes stored report).
    try:
        pair_rec["backtest"] = _generate_pair_trading_backtest(pair_rec)
    except Exception as e:
        logger.warning(f"Pair trading backtest generation failed: {e}")

    mf_rec = mf_strategy.generate_recommendations()
    ml_rec = ml_strategy.generate_recommendations()

    fetcher = get_price_fetcher()
    data_mode = "mock" if getattr(fetcher, "use_mock_data", False) else "live"

    # ETF / 板块 / 消息面 (best-effort, fallback per section)
    etf_sector: Dict[str, Any] = {}
    if data_mode == "mock":
        etf_sector = {
            "data_status": "unavailable",
            "reason": "disabled_in_mock_mode",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    else:
        try:
            etf_sector = generate_etf_sector_block(prev_report=prev)
        except Exception as e:
            logger.warning(f"ETF/板块模块生成失败: {e}")

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_mode": data_mode,
        "pair_trading": pair_rec,
        "multi_factor": mf_rec,
        "ml_prediction": ml_rec,
        "etf_sector": etf_sector or {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate daily AH recommendations and persist report"
    )
    parser.add_argument(
        "--mock", action="store_true", help="Use mock market data (no external network)"
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Generate but do not write report to disk",
    )
    args = parser.parse_args()

    if args.mock:
        get_price_fetcher().enable_mock_data()
        logger.info("Mock data enabled for job run")

    report = generate_report()
    if args.no_write:
        logger.info("Generated report (no-write)")
        return 0

    store = get_report_store()
    path = store.save(report)
    logger.info(f"Report saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
