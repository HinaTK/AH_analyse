"""Backtest verification for stock recommendations.

Reads historical `recommend_YYYYMMDD.json` files, fetches subsequent prices,
computes T+1/3/5/10 return, max drawdown, hit rate.
Writes to a JSONL ledger `docs/analyse/stock-recommend-ledger.jsonl`.
"""
from __future__ import annotations

import json
import hashlib
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
import pandas as pd

from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.stock_recommend.execution_validation import ExecutionCosts, simulate_forward_trade
from ah_recommendation_system.backend.stock_recommend.execution_data import ExecutionDataProvider


HORIZONS = (1, 3, 5, 10, 20)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _load_report(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _returns_for_pick(
    code: str,
    as_of: str,
    *,
    price_fetcher=None,
    evaluation_date: str | None = None,
) -> Dict[str, Any]:
    """Fetch prices for `code` from `as_of` and compute horizon returns.

    as_of: 'YYYY-MM-DD'. Returns dict with T+N return (%), max drawdown (%), and entry price.
    """
    pf = price_fetcher or get_price_fetcher()
    if getattr(pf, "use_mock_data", False) is True:
        return {"code": code, "error": "mock_preview_excluded"}
    # as_of 紧凑化 YYYYMMDD
    dt = datetime.strptime(as_of, "%Y-%m-%d")
    start = (dt - timedelta(days=2)).strftime("%Y%m%d")
    evaluation = pd.Timestamp(evaluation_date or datetime.now().strftime("%Y-%m-%d"))
    end = evaluation.strftime("%Y%m%d")

    try:
        df = pf.get_a_share_price(code, start_date=start, end_date=end)
    except Exception as e:
        return {"code": code, "error": f"price_fetch:{e}"}

    if df is None or df.empty or "date" not in df.columns:
        return {"code": code, "error": "no_price"}

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"] <= evaluation].sort_values("date").drop_duplicates("date")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    # find first available date >= as_of
    future = df[df["date"] >= as_of].reset_index(drop=True)
    if future.empty:
        return {"code": code, "error": "no_future_price"}
    entry = float(future.iloc[0]["close"])
    if not pd.notna(entry) or entry <= 0:
        return {"code": code, "error": "invalid_entry_price"}
    entry_date = str(future.iloc[0]["date"])
    out: Dict[str, Any] = {
        "code": code,
        "entry_price": entry,
        "entry_date": entry_date,
    }
    closes = future["close"].astype(float).tolist()
    if any(not math.isfinite(value) or value <= 0 for value in closes):
        return {"code": code, "error": "invalid_close_price"}
    for h in HORIZONS:
        if len(closes) > h:
            ret = (closes[h] - entry) / entry * 100
            out[f"return_T{h}_pct"] = round(ret, 2)
        else:
            out[f"return_T{h}_pct"] = None

    # Max drawdown over the window
    if closes:
        peak = closes[0]
        max_dd = 0.0
        for v in closes:
            peak = max(peak, v)
            dd = (v - peak) / peak * 100
            max_dd = min(max_dd, dd)
        out["max_drawdown_pct"] = round(max_dd, 2)
    return out


def verify_recommendation(
    report: Dict[str, Any],
    *,
    ledgers_dir: Path,
    price_fetcher=None,
    execution_provider=None,
    evaluation_date: str | None = None,
    costs: ExecutionCosts | None = None,
) -> Dict[str, Any]:
    """Verify a single recommendation report. Returns a per-pick metrics dict."""
    as_of = report.get("as_of") or datetime.now().strftime("%Y-%m-%d")
    picks = report.get("picks") or []
    coverage = report.get("coverage") or {}
    excluded = (
        "mock" in str(coverage.get("mode", "")).lower()
        or "mock" in str(coverage.get("source", "")).lower()
        or bool(coverage.get("stale"))
        or coverage.get("source") == "last_good_snapshot"
        or report.get("data_status") == "failed"
        or report.get("mock") is True
    )
    evaluation_date = evaluation_date or datetime.now().strftime("%Y-%m-%d")
    if not excluded and execution_provider is None:
        execution_provider = ExecutionDataProvider()
    benchmark = pd.DataFrame()
    provider_error = "execution_provider_unavailable"
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=10)).strftime("%Y%m%d")
    end = pd.Timestamp(evaluation_date).strftime("%Y%m%d")
    if not excluded and execution_provider is not None:
        try:
            benchmark = _clip_frame(execution_provider.get_benchmark_bars(start, end), evaluation_date)
            provider_error = "benchmark_data_missing"
        except Exception as exc:
            provider_error = f"benchmark_fetch:{type(exc).__name__}"
    per_pick: List[Dict[str, Any]] = []
    panel = report.get("candidate_panel") or []
    picked_codes = {str(p.get("code")) for p in picks}
    all_candidates = {str(p.get("code")): p for p in panel}
    all_candidates.update({str(p.get("code")): p for p in picks})
    candidate_outcomes = []
    for p in ([] if excluded else all_candidates.values()):
        code = str(p.get("code") or "").strip()
        if not code:
            continue
        metrics = (_returns_for_pick(code, as_of, price_fetcher=price_fetcher, evaluation_date=evaluation_date)
                   if code in picked_codes else {"code": code})
        metrics["name"] = p.get("name", "")
        metrics["action"] = p.get("action", "")
        metrics["confidence"] = p.get("confidence", 0)
        metrics["factors"] = p.get("factor_scores") or p.get("factors") or {}
        metrics["risk_flags"] = p.get("risk_flags") or []
        metrics["as_of"] = as_of
        outcomes = {str(h): {"status": "unavailable", "reason": provider_error} for h in HORIZONS}
        if execution_provider is not None and not benchmark.empty:
            try:
                frame = _clip_frame(execution_provider.get_stock_bars(code, start, end), evaluation_date)
                # Do not call a future benchmark session a missing stock bar if
                # the individual provider has not published that far yet.
                common_benchmark = benchmark
                if not frame.empty:
                    common_benchmark = benchmark[pd.to_datetime(benchmark["date"]) <= pd.to_datetime(frame["date"]).max()]
                outcomes = {
                    str(h): simulate_forward_trade(bars=frame, benchmark=common_benchmark, code=code,
                                                   signal_date=as_of, horizon=h, costs=costs)
                    for h in HORIZONS
                }
            except Exception as exc:
                outcomes = {str(h): {"status": "unavailable", "reason": f"execution_fetch:{type(exc).__name__}"} for h in HORIZONS}
        metrics["execution"] = outcomes
        for h in HORIZONS:
            metrics[f"net_return_T{h}_pct"] = outcomes[str(h)].get("net_return_pct")
            metrics[f"excess_return_T{h}_pct"] = outcomes[str(h)].get("excess_return_pct")
        if code in picked_codes:
            per_pick.append(metrics)
        outcome = outcomes["5"]
        original = next((row for row in panel if str(row.get("code")) == code), {})
        if original and outcome.get("status") == "unfilled":
            sessions = benchmark[pd.to_datetime(benchmark["date"]) > pd.Timestamp(as_of)].sort_values("date")
            if len(sessions) > 5:
                start_bar, end_bar = sessions.iloc[0], sessions.iloc[5]
                entry_open = float(start_bar["open"])
                prices = [entry_open] + [float(value) for value in sessions.iloc[:6]["close"]]
                if any(not math.isfinite(value) or value <= 0 for value in prices):
                    continue
                base_marks = {str(pd.Timestamp(row["date"]).date()): float(row["close"]) / entry_open
                              for row in sessions.iloc[:6].to_dict("records")}
                outcome = dict(outcome, entry_date=str(pd.Timestamp(start_bar["date"]).date()),
                               exit_date=str(pd.Timestamp(end_bar["date"]).date()), net_return_pct=0,
                               excess_return_pct=-(list(base_marks.values())[-1] - 1) * 100,
                               benchmark_return_pct=(list(base_marks.values())[-1] - 1) * 100,
                               daily_equity=dict.fromkeys(base_marks, 1.0), daily_benchmark=base_marks)
        if original and outcome.get("exit_date"):
            generated = pd.to_datetime(report.get("generated_at"), errors="coerce")
            entry = pd.Timestamp(outcome["entry_date"])
            # Historical provider replays are not a saved point-in-time panel.
            contemporaneous = not pd.isna(generated) and pd.Timestamp(as_of) <= generated < entry
            rejected = original.get("rejection_reasons") or []
            supported = {str(e.get("factor")) for e in original.get("evidence", []) if e.get("supports") is True}
            factor_scores = original.get("factor_scores") or {}
            candidate_outcomes.append({
                **outcome, "date": as_of, "label_end": outcome["exit_date"], "code": code,
                "factors": original.get("factor_scores") or {},
                "risk_penalty": (original.get("factor_scores") or {}).get("risk", 0),
                "focus_industries": original.get("focus_industries") or [],
                "selection_policy_version": report.get("selection_policy_version"),
                "defense_qualified": bool({"trend", "relative_strength"}.issubset(supported)
                                          and {"capital", "event", "quality"} & supported
                                          and float(factor_scores.get("trend") or 0) >= .6
                                          and float(factor_scores.get("relative_strength") or 0) > .5),
                "market_calendar": {str(pd.Timestamp(row["date"]).date()): {"open": float(row["open"]), "close": float(row["close"])}
                                    for row in benchmark.to_dict("records")
                                    if math.isfinite(float(row["open"])) and math.isfinite(float(row["close"]))},
                "regime": (report.get("market") or {}).get("regime", "unknown"),
                "eligible": (not original.get("observation_only") and original.get("quality_grade") in {"A", "B"}
                             and len(original.get("valid_dimensions") or []) >= 3
                             and not any(str(reason).startswith(("p0", "stale", "quality", "evidence", "coverage", "market")) for reason in rejected)),
                "source": "live_execution" if benchmark.attrs.get("source") == "baostock" and frame.attrs.get("source") == "baostock" else "unverified_provider",
                "point_in_time_snapshot": bool(contemporaneous),
                "panel_scope": report.get("candidate_panel_scope"),
            })

    # Aggregate hit rate (T+5 return > 0)
    valid = [m for m in per_pick if m.get("return_T5_pct") is not None]
    hit_t5 = (
        sum(1 for m in valid if (m.get("return_T5_pct") or 0) > 0) / len(valid) * 100
        if valid
        else None
    )
    avg_t5 = (
        round(sum(m.get("return_T5_pct", 0) for m in valid) / len(valid), 2)
        if valid
        else None
    )

    execution_states = [outcome["status"] for pick in per_pick for outcome in pick["execution"].values()]
    complete = bool(execution_states) and all(state in {"filled", "unfilled"} for state in execution_states)
    panel_complete = bool(panel) and len(candidate_outcomes) == len(panel)
    if panel and not panel_complete:
        complete = False
    net_valid = [m for m in per_pick if m.get("excess_return_T5_pct") is not None]
    summary = {
        "as_of": as_of,
        "pick_count": len(picks),
        "verified_count": len(valid),
        "hit_rate_T5_pct": round(hit_t5, 2) if hit_t5 is not None else None,
        "avg_return_T5_pct": avg_t5,
        "per_pick": per_pick,
        "candidate_outcomes": candidate_outcomes,
        "candidate_panel_complete": panel_complete,
        "net_verified_count": len(net_valid),
        "avg_net_return_T5_pct": sum(m["net_return_T5_pct"] for m in net_valid) / len(net_valid) if net_valid else None,
        "avg_net_excess_T5_pct": sum(m["excess_return_T5_pct"] for m in net_valid) / len(net_valid) if net_valid else None,
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "evaluation_date": evaluation_date,
        "verification_version": "execution-v1",
        "report_fingerprint": _report_fingerprint(report),
        "verification_status": "excluded" if excluded else "complete" if complete else "pending",
        "factor_version": report.get("factor_version"),
        "regime": (report.get("market") or {}).get("regime", "unknown"),
        "execution_assumption": "next_session_open_fixed_horizon_not_watch_trigger",
        "calibration_eligible": False,
        "calibration_reason": "excluded_data" if excluded else "requires_rolling_validation",
    }

    # Append to ledger
    ledgers_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledgers_dir / "stock-recommend-ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False, allow_nan=False) + "\n")

    logger.info(
        f"verified as_of={as_of} picks={len(picks)} verified={len(valid)} "
        f"hit_T5={summary['hit_rate_T5_pct']} avg_T5={avg_t5}"
    )
    return summary


def _clip_frame(frame: pd.DataFrame, evaluation_date: str) -> pd.DataFrame:
    if frame is None or frame.empty or "date" not in frame:
        return pd.DataFrame()
    return frame[pd.to_datetime(frame["date"], errors="coerce") <= pd.Timestamp(evaluation_date)].copy()


def _report_fingerprint(report: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def verify_all_pending(
    report_dir: Path,
    ledgers_dir: Path,
    *,
    evaluation_date: str | None = None,
    price_fetcher=None,
    execution_provider=None,
) -> List[Dict[str, Any]]:
    """Retry incomplete/version-changed reports as each horizon matures."""
    out: List[Dict[str, Any]] = []
    if not report_dir.exists():
        return out
    ledger_path = ledgers_dir / "stock-recommend-ledger.jsonl"
    seen = {
        row.get("report_fingerprint") for row in _read_jsonl(ledger_path)
        if row.get("verification_version") == "execution-v1"
        and row.get("verification_status") in {"complete", "excluded"}
    }
    cutoff = pd.Timestamp(evaluation_date or datetime.now().strftime("%Y-%m-%d"))

    for p in sorted(report_dir.glob("recommend_*.json")):
        try:
            report = _load_jsonl_compat(p)
        except Exception:
            continue
        if not report:
            continue
        as_of = report.get("as_of") or ""
        if _report_fingerprint(report) in seen:
            continue
        try:
            dt = datetime.strptime(as_of, "%Y-%m-%d")
        except Exception:
            continue
        if dt >= cutoff:
            continue
        out.append(verify_recommendation(report, ledgers_dir=ledgers_dir, evaluation_date=cutoff.strftime("%Y-%m-%d"),
                                         price_fetcher=price_fetcher, execution_provider=execution_provider))
    return out


def _load_jsonl_compat(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def label_ranking_panel(panel, bars_by_code, benchmark_calendar) -> list[Dict[str, Any]]:
    """Attach T+1 open to T+5 close executable labels onto the tradable panel.

    Membership is decided by the signal date; delayed exits stay in the
    cohort. Incomplete horizons return status=pending and never train.
    """
    from ah_recommendation_system.backend.stock_recommend.execution_validation import (
        ExecutionCosts,
        simulate_forward_trade,
    )

    costs = ExecutionCosts()
    labeled = []
    for row in panel:
        code = str(row.get("code") or "")
        bars = bars_by_code.get(code)
        if bars is None or getattr(bars, "empty", False):
            labeled.append({**row, "status": "unfilled", "reason": "entry_data_missing"})
            continue
        outcome = simulate_forward_trade(
            bars=bars,
            benchmark=benchmark_calendar,
            code=code,
            signal_date=str(row.get("date") or ""),
            horizon=5,
            costs=costs,
        )
        if outcome.get("status") == "filled":
            labeled.append({
                **row,
                "status": "filled",
                "entry_date": outcome["entry_date"],
                "label_end": outcome["exit_date"],
                "net_return_pct": outcome["net_return_pct"],
                "benchmark_return_pct": outcome["benchmark_return_pct"],
                "excess_return_pct": outcome["excess_return_pct"],
            })
        else:
            labeled.append({**row, "status": outcome.get("status"), "reason": outcome.get("reason")})
    return labeled
