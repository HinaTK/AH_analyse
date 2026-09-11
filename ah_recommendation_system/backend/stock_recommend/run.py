"""Entry point for stock recommendation pipeline.

Usage:
  python -m ah_recommendation_system.backend.stock_recommend.run --mock
  python -m ah_recommendation_system.backend.stock_recommend.run --live
  python -m ah_recommendation_system.backend.stock_recommend.run --verify-only
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Dict, Optional

from loguru import logger

# Ensure repo + backend on sys.path so absolute imports resolve.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = Path(__file__).resolve().parents[1]
for p in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.stock_recommend.backtest_verify import (
    verify_all_pending,
    verify_recommendation,
)
from ah_recommendation_system.backend.stock_recommend.candidate_pool import (
    build_candidates,
    to_dict_list,
)
from ah_recommendation_system.backend.stock_recommend.data_collector import (
    collect_all,
)
from ah_recommendation_system.backend.stock_recommend.feishu_pusher import (
    push_to_feishu,
)
from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules
from ah_recommendation_system.backend.stock_recommend.evidence_collection import enrich_evidence
from ah_recommendation_system.backend.stock_recommend.report_builder import (
    build_report,
    save_report,
    save_review_report,
)
from ah_recommendation_system.backend.stock_recommend.post_market import build_post_market_review, closing_observation
from ah_recommendation_system.backend.stock_recommend.local_store import load_last_snapshot, persist_snapshot
from ah_recommendation_system.backend.stock_recommend.market_data import MarketDataManager, SnapshotResult
from ah_recommendation_system.backend.stock_recommend.reweight import (
    load_event_llm_share,
    load_factor_weights,
    run_weekly_reweight,
)
from ah_recommendation_system.backend.stock_recommend.focused_collector import (
    DEFAULT_FOCUS_UNIVERSE,
    collect_focused_market,
)
from ah_recommendation_system.backend.stock_recommend.dynamic_scanner import scan_snapshot
from ah_recommendation_system.backend.stock_recommend.technical_features import calculate_features
from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient
from ah_recommendation_system.backend.stock_recommend.wechat_pusher import push_to_wechat
from ah_recommendation_system.backend.stock_recommend.hotspot_analyzer import analyze_hotspots
from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots
from ah_recommendation_system.backend.stock_recommend.llm_review import apply_llm_event_scores, review_candidate_events
from ah_recommendation_system.backend.stock_recommend.decision_engine import build_market_decision
from ah_recommendation_system.backend.stock_recommend.risk_review import review_candidate_risks
from ah_recommendation_system.backend.stock_recommend.delivery_guard import (
    get_delivery,
    record_delivery,
    should_deliver,
)
from ah_recommendation_system.backend.etf_sector.etf_portfolio import build_etf_quality_scores, select_etf_portfolio

LLM_EVENT_REVIEW_CANDIDATE_LIMIT = 10


def prefetch_market_snapshot(*, limit: int = 6000) -> SnapshotResult:
    """Warm the shared live snapshot cache before collection starts."""
    return MarketDataManager().prefetch_snapshot(limit=limit)


def market_data_attempted_chain(snap: Any) -> list[str]:
    """Return the source chain actually attempted by this snapshot."""
    provider = (snap.fundamental or {}).get("provider_health") or {}
    attempted = list(provider.get("attempted_sources") or [])
    if attempted:
        return attempted
    source = (snap.fundamental or {}).get("source")
    return [str(source)] if source else []


def _backend_root() -> Path:
    return _BACKEND_DIR


def _ledgers_dir() -> Path:
    # store ledgers at repo-root docs/analyse (matches existing abnormal-movement convention)
    return _REPO_ROOT / "docs" / "analyse"


def _delivery_ledger_path() -> Path:
    return _backend_root() / "data" / "stock_recommend" / "delivery_ledger.json"


def _deliver_report(
    report: Dict[str, Any],
    *,
    ledger_path: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Push once per trade-date/session and attach delivery audit fields."""
    run = dict(report.get("run") or {})
    trade_date = str(run.get("trade_date") or report.get("as_of") or "")
    session = str(run.get("session") or "pre_market")
    target = ledger_path or _delivery_ledger_path()
    if not should_deliver(target, trade_date=trade_date, session=session, force=force):
        existing = get_delivery(target, trade_date=trade_date, session=session)
        ambiguous = bool(existing.get("ambiguous"))
        reason = "previous_delivery_ambiguous" if ambiguous else "duplicate_successful_delivery"
        report.setdefault("delivery", {})
        report["delivery"].update({
            "channel": "feishu",
            "payload_hash": str(existing.get("payload_hash") or ""),
            "accepted": bool(existing.get("accepted")),
            "ambiguous": ambiguous,
            "skipped": True,
            "reason": reason,
        })
        return {"ok": not ambiguous, "skipped": True, "reason": reason, "delivery_ambiguous": ambiguous}
    result = push_to_feishu(report)
    payload_hash = str(result.get("payload_hash") or "")
    accepted = bool(result.get("ok"))
    ambiguous = bool(result.get("delivery_ambiguous"))
    report.setdefault("delivery", {})
    report["delivery"].update({
        "channel": "feishu",
        "payload_hash": payload_hash,
        "accepted": accepted,
        "ambiguous": ambiguous,
        "status": result.get("status"),
    })
    # A prior guarded attempt may have left ``skipped/reason`` fields on the
    # same report. Remove them after an actual (including forced) delivery so
    # the audit record cannot claim both accepted and skipped.
    report["delivery"].pop("skipped", None)
    report["delivery"].pop("reason", None)
    record_delivery(
        target,
        trade_date=trade_date,
        session=session,
        run_id=str(run.get("run_id") or ""),
        payload_hash=payload_hash,
        accepted=accepted,
        ambiguous=ambiguous,
    )
    return result


def _extract_market_signals(etf_block: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Convert industry-board breadth rows into hotspot evidence."""
    boards = etf_block.get("boards") or {}
    industry = boards.get("industry") if isinstance(boards, dict) else {}
    signals: list[Dict[str, Any]] = []
    for row in (industry.get("top_gainers") or [])[:8] if isinstance(industry, dict) else []:
        if not isinstance(row, dict):
            continue
        signals.append({
            "theme": row.get("name"),
            "change_pct": row.get("chg_pct"),
            "advance_count": row.get("advance_count"),
            "total_count": row.get("total_count"),
            "turnover_yi": row.get("turnover_yi"),
            "leader": row.get("leader"),
            "source": row.get("source") or "ths_industry",
        })
    return signals


def _extract_a_share_signal(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize breadth and turnover from the current full A-share snapshot."""
    changes: list[float] = []
    turnover = 0.0
    for row in rows:
        try:
            change = float(row.get("change_pct"))
        except (TypeError, ValueError):
            continue
        changes.append(change)
        try:
            amount = float(row.get("amount") or 0.0)
            if amount > 0:
                turnover += amount
        except (TypeError, ValueError):
            pass
    return {
        "theme": "A股全市场宽度",
        "change_pct": round(float(median(changes)), 3) if changes else None,
        "advance_count": sum(value > 0 for value in changes),
        "total_count": len(changes),
        "turnover_yi": round(turnover / 100_000_000, 3),
        "source": "a_share_full_snapshot",
    }


def _merge_candidate_events(
    existing: Dict[str, Any], refreshed: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge candidate-specific news without erasing market-wide context."""
    merged = dict(existing)
    for key in ("stock_news", "count", "status", "generated_at"):
        if key in refreshed:
            merged[key] = refreshed[key]
    provider_health = dict(existing.get("provider_health") or {})
    provider_health.update(refreshed.get("provider_health") or {})
    merged["provider_health"] = provider_health
    return merged


def _apply_daily_feature_row(row: Dict[str, Any], bars: list[Dict[str, Any]]) -> bool:
    """Mutate one candidate with multi-horizon daily features."""
    features = calculate_features(bars)
    row.update(features)
    # During the pre-market session real-time turnover is commonly
    # zero. Use the most recent completed daily bar as a labelled
    # liquidity reference so quality gates do not discard valid data.
    try:
        realtime_amount = float(row.get("amount") or 0)
    except (TypeError, ValueError):
        realtime_amount = 0.0
    if realtime_amount < 100_000_000:
        completed = []
        for bar in bars:
            try:
                value = float(bar.get("amount") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value >= 100_000_000:
                completed.append(value)
        if completed:
            row["amount"] = completed[-1]
            row["amount_reference"] = "latest_completed_daily_bar"
    if features.get("return_60d_pct") is not None:
        row["change_60d_pct"] = features["return_60d_pct"]
    return bool(features.get("history_days"))


def _enrich_with_daily_features(rows: list[Dict[str, Any]], pf: Any, *, as_of: str, limit: int = 100) -> int:
    """Prefetch candidate daily bars in parallel, then attach 20/60/120d features."""
    targets = [row for row in rows[: max(0, limit)] if len(str(row.get("code") or "")) == 6]
    if not targets:
        return 0
    start = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=220)).strftime("%Y%m%d")
    end = datetime.strptime(as_of, "%Y-%m-%d").strftime("%Y%m%d")

    def fetch_bars(row: Dict[str, Any]):
        code = str(row.get("code") or "")
        frame = pf.get_a_share_price(code, start, end)
        return row, frame

    enriched = 0
    workers = min(8, len(targets))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_bars, row): row for row in targets}
        for future in as_completed(futures):
            row = futures[future]
            try:
                _, frame = future.result()
                if frame is None or getattr(frame, "empty", True):
                    continue
                if "date" not in frame:
                    continue
                import pandas as pd
                frame = frame[pd.to_datetime(frame["date"], errors="coerce") < pd.Timestamp(as_of)].sort_values("date")
                bars = frame.to_dict("records")
                if _apply_daily_feature_row(row, bars):
                    enriched += 1
            except Exception as exc:
                row.setdefault("feature_errors", []).append(str(exc))
    logger.info("daily feature enrichment rows={} amount_refs={}", enriched, sum(1 for row in rows[: max(0, limit)] if row.get("amount_reference")))
    return enriched


def _enrich_hithink_candidates(rows: list[Dict[str, Any]], *, limit: int = 600) -> list[Dict[str, Any]]:
    """Enrich only the dynamic short-list, never the whole market snapshot."""
    if not rows:
        return rows
    source = str(rows[0].get("source") or "")
    # Full-market Financial-API rows and real focused-provider rows both have
    # stable symbol provenance. Synthetic snapshots without quote provenance
    # are left untouched to avoid surprising network calls in tests/callers.
    focused_ready = (source.startswith("focused_") or not source) and any(row.get("quote_source") for row in rows)
    if source != "hithink_financial_api" and not focused_ready:
        return rows
    client = HithinkClient()
    if not client.enabled:
        return rows
    head = client.enrich_snapshot(rows[: max(0, limit)])
    logger.info(
        "Financial-API candidate enrichment rows={} valuations={} market_caps={} turnover={}",
        len(head),
        sum(1 for row in head if row.get("pe") is not None),
        sum(1 for row in head if row.get("market_cap") is not None),
        sum(1 for row in head if row.get("turnover_pct") is not None),
    )
    return head + rows[max(0, limit) :]


def run_pipeline(
    *,
    mock: bool = False,
    top_n_pick: int = 5,
    top_n_candidates: int = 30,
    push: bool = False,
    force_push: bool = False,
) -> Dict[str, Any]:
    """Run the full pipeline: collect -> candidates -> LLM select -> report -> (push)."""
    top_n_pick = min(5, max(0, int(top_n_pick)))
    stages: list[Dict[str, Any]] = []
    stage_started = time.monotonic()

    def checkpoint(name: str, *, status: str = "ok", **details: Any) -> None:
        nonlocal stage_started
        now = time.monotonic()
        stages.append({
            "name": name,
            "status": status,
            "duration_ms": max(0, int((now - stage_started) * 1000)),
            **details,
        })
        stage_started = now

    pf = get_price_fetcher()
    if mock:
        pf.enable_mock_data()
    else:
        pf.use_mock_data = False

    logger.info(f"pipeline start mock={mock} top_pick={top_n_pick} push={push}")

    # Probe optional upstreams once at the start of a live run so a report
    # can distinguish "configured but unavailable" from a later empty result.
    hithink_probe: Dict[str, Any] = {"available": False, "capabilities": {}, "errors": {}}
    if not mock:
        try:
            hithink_probe = HithinkClient().probe()
            logger.info(
                "Financial-API probe available={} capabilities={}",
                hithink_probe.get("available"),
                hithink_probe.get("capabilities") or {},
            )
        except Exception as exc:
            hithink_probe = {"available": False, "capabilities": {}, "errors": {"probe": type(exc).__name__}}
            logger.warning("Financial-API probe failed: {}", type(exc).__name__)

    if not mock:
        try:
            prefetch_market_snapshot(limit=6000)
        except Exception as exc:
            logger.warning("market snapshot prefetch failed: {}", type(exc).__name__)

    snap = collect_all(limit=6000)
    coverage_mode = "mock_sample" if mock else "full_market"
    if not mock and not (snap.fundamental.get("rows") or []):
        previous_errors = list(snap.errors)
        if "full_market_unavailable" not in previous_errors:
            previous_errors.append("full_market_unavailable")
        snap = collect_focused_market()
        snap.errors = previous_errors + list(snap.errors)
        coverage_mode = "focused_fallback"
    if not mock and not (snap.fundamental.get("rows") or []):
        try:
            cached_rows = load_last_snapshot(_backend_root(), max_age_seconds=300)
            if cached_rows:
                cache_source = str(cached_rows[0].get("source") or "last_good_snapshot")
                snap.fundamental = {
                    "rows": cached_rows,
                    "count": len(cached_rows),
                    "universe_size": len(cached_rows),
                    "source": cache_source,
                }
                if cache_source == "disk_cache":
                    snap.errors.append("using_fresh_disk_cache")
                else:
                    snap.errors.append("using_stale_last_good_snapshot")
                    coverage_mode = "limited_sample"
        except Exception as exc:
            snap.errors.append(f"last_good_snapshot:{exc}")
    data_available = bool(snap.fundamental.get("rows") or []) and snap.fundamental.get("source") != "last_good_snapshot"
    if not data_available and "focused_market_unavailable" not in snap.errors:
        snap.errors.append("focused_market_unavailable")
    checkpoint(
        "collect",
        status="ok" if data_available else "failed",
        source=snap.fundamental.get("source"),
        row_count=len(snap.fundamental.get("rows") or []),
        error_count=len(snap.errors),
    )
    # Rebuild the candidate pool on every run from current signals.  Focus
    # industries remain provenance tags, never a score or an investment reason.
    raw_rows = snap.fundamental.get("rows") or []
    market_scanned_count = len(raw_rows)
    focus_universe = None
    if raw_rows and raw_rows[0].get("source") == "hithink_financial_api":
        try:
            focus_universe = HithinkClient().focus_universe(["科技", "半导体", "新能源", "券商", "医疗"])
        except Exception as exc:
            snap.errors.append(f"hithink_industries:{exc}")
    # Keep the hotspot/industry stage useful when the optional Financial-API
    # catalogue is unavailable.  This small, auditable map is only a
    # provenance fallback; it does not bypass the normal factor gates.
    if not focus_universe:
        focus_universe = DEFAULT_FOCUS_UNIVERSE
    else:
        merged = {key: list(value) for key, value in DEFAULT_FOCUS_UNIVERSE.items()}
        for key, value in focus_universe.items():
            merged.setdefault(key, [])
            seen = {str(item.get("code") or "") for item in merged[key]}
            for item in value:
                code = str(item.get("code") or "")
                if code and code not in seen:
                    merged[key].append(dict(item))
                    seen.add(code)
        focus_universe = merged
    seeds = scan_snapshot(
        raw_rows,
        focus_industries=focus_universe,
        activity_rows=snap.capital.get("rows") or [],
    )
    if seeds:
        try:
            seeds = _enrich_hithink_candidates(seeds)
        except Exception as exc:
            snap.errors.append(f"hithink_enrichment:{exc}")
        snap.fundamental["rows"] = seeds
        snap.fundamental["candidate_count"] = len(seeds)
        if not mock and data_available:
            try:
                from ah_recommendation_system.backend.stock_recommend.data_collector import collect_events
                event_codes = [str(row.get("code")) for row in seeds[:20] if row.get("code")]
                refreshed_events = collect_events(limit=200, codes=event_codes)
                snap.events = _merge_candidate_events(snap.events, refreshed_events)
            except Exception as exc:
                snap.errors.append(f"candidate_news:{exc}")
    if not mock and data_available:
        coverage_history_count = _enrich_with_daily_features(snap.fundamental.get("rows") or [], pf, as_of=snap.date)
    else:
        coverage_history_count = sum(
            1 for row in (snap.fundamental.get("rows") or []) if float(row.get("history_days") or 0) >= 60
        )
    collected_rows = list(raw_rows)
    if not mock and snap.fundamental.get("source") not in {"mock", "disk_cache", "last_good_snapshot"}:
        try:
            persist_snapshot(
                collected_rows or (snap.fundamental.get("rows") or []),
                _backend_root(),
                as_of=snap.date,
            )
        except ImportError as exc:
            snap.errors.append(f"local_store_dependency:{exc}")
        except Exception as exc:
            snap.errors.append(f"local_store:{exc}")
    weights_path = _backend_root() / "data" / "stock_recommend" / "factor_weights.json"
    evidence_audit = {"market_regime": {"regime": "unknown", "status": "unavailable"},
                      "coverage": "unavailable", "attempted_count": 0}
    if not mock and data_available:
        evidence_audit = {"market_regime": {"regime": "unknown", "status": "unavailable"},
                          "coverage": "deferred_until_ranked_candidates", "attempted_count": 0}
    weights = load_factor_weights(weights_path)
    from ah_recommendation_system.backend.stock_recommend.reweight import load_selection_threshold
    minimum_score = load_selection_threshold(weights_path)
    event_llm_share = load_event_llm_share(weights_path)
    # Pass 1: deterministic ranking. LLM is deliberately not involved in
    # full-market scoring.
    initial_cands = build_candidates(snap, top_n=top_n_candidates, weights=weights)
    if not mock and data_available and initial_cands:
        selected_codes = {candidate.code for candidate in initial_cands}
        evidence_rows = [row for row in (snap.fundamental.get("rows") or [])
                         if str(row.get("code") or "") in selected_codes]
        _enrich_with_daily_features(evidence_rows, pf, as_of=snap.date, limit=len(evidence_rows))
        evidence_audit = enrich_evidence(evidence_rows, as_of=snap.date, limit=len(evidence_rows))
        evidence_audit["attempted_count"] = len(evidence_rows)
        snap.errors.extend(evidence_audit.get("errors") or [])
        # Fix the evaluation pool before evidence enrichment; later candidates
        # cannot jump in without passing through the same collection step.
        snap.fundamental["rows"] = evidence_rows
        initial_cands = build_candidates(snap, top_n=top_n_candidates, weights=weights)
    checkpoint(
        "rule_scan",
        status="ok" if initial_cands else "degraded",
        market_scanned_count=market_scanned_count,
        candidate_count=len(initial_cands),
    )
    macro_ctx = dict(snap.events.get("macro_news") or {})
    # Hotspot analysis consumes both macro RSS and stock-level news while
    # retaining the existing macro_news argument for compatibility.
    if snap.events.get("stock_news"):
        macro_ctx["stock_news"] = list(snap.events.get("stock_news") or [])
    breadth_signal = _extract_a_share_signal(raw_rows)
    llm_context: Dict[str, Any] = {
        "hotspots": [],
        "market_signals": [breadth_signal] if breadth_signal.get("total_count") else [],
        "llm": {
            "backend": "codex_cli",
            "hotspot_status": "disabled",
            "event_status": "disabled",
            "event_input_candidate_count": 0,
            "event_submitted_count": 0,
            "event_reviewed_count": 0,
        },
    }
    if not mock and data_available:
        try:
            hotspot_result = analyze_hotspots(
                macro_news=macro_ctx,
                candidates=to_dict_list(initial_cands),
                as_of=snap.date,
            )
            mapped = validate_and_expand_hotspots(
                hotspot_result.get("hotspots") or [],
                focus_universe=focus_universe or {},
                rows=collected_rows or snap.fundamental.get("rows") or [],
                max_total=60,
            )
            llm_context["hotspots"] = mapped.get("hotspots") or []
            llm_context["llm"]["hotspot_status"] = hotspot_result.get("status")
            llm_context["llm"]["hotspot_duration_ms"] = hotspot_result.get("duration_ms", 0)
            llm_context["llm"]["hotspot_error"] = hotspot_result.get("error")
            if hotspot_result.get("stderr"):
                logger.warning("hotspot diagnostic: {}", hotspot_result["stderr"])
            if hotspot_result.get("status") == "failed":
                snap.errors.append(f"llm_hotspots:{hotspot_result.get('error') or 'failed'}")
        except Exception as exc:
            snap.errors.append(f"llm_hotspots:{type(exc).__name__}")
            llm_context["llm"]["hotspot_status"] = "failed"

    # Hotspot LLM output is report context only. It must never add securities
    # to, or otherwise rewrite, the deterministic rule candidate pool.
    cands = initial_cands
    llm_context["llm"]["candidate_count_before"] = len(initial_cands)
    llm_context["llm"]["candidate_count_after"] = len(cands)
    if not mock and data_available:
        try:
            event_result = review_candidate_events(
                cands[:LLM_EVENT_REVIEW_CANDIDATE_LIMIT],
                as_of=snap.date,
            )
            normalized_reviews = event_result.get("reviews") or {}
            cands = apply_llm_event_scores(
                cands,
                normalized_reviews,
                weights=weights,
                llm_share=event_llm_share,
            )
            llm_context["llm"]["event_status"] = event_result.get("status")
            llm_context["llm"]["event_duration_ms"] = event_result.get("duration_ms", 0)
            llm_context["llm"]["event_error"] = event_result.get("error")
            llm_context["llm"]["event_llm_share"] = event_llm_share
            llm_context["llm"]["event_input_candidate_count"] = int(
                event_result.get(
                    "input_candidate_count",
                    min(LLM_EVENT_REVIEW_CANDIDATE_LIMIT, len(cands)),
                )
            )
            llm_context["llm"]["event_submitted_count"] = int(
                event_result.get("submitted_count", len(normalized_reviews))
            )
            llm_context["llm"]["event_reviewed_count"] = int(
                event_result.get("reviewed_count", len(normalized_reviews))
            )
            if event_result.get("status") == "failed":
                snap.errors.append(f"llm_event_review:{event_result.get('error') or 'failed'}")
        except Exception as exc:
            snap.errors.append(f"llm_event_review:{type(exc).__name__}")
            llm_context["llm"]["event_status"] = "failed"
    checkpoint(
        "llm_review",
        status=str(llm_context.get("llm", {}).get("event_status") or "disabled"),
        submitted_count=int(llm_context.get("llm", {}).get("event_submitted_count") or 0),
        reviewed_count=int(llm_context.get("llm", {}).get("event_reviewed_count") or 0),
    )
    cand_dicts = to_dict_list(cands)
    risk_result = review_candidate_risks(cands)
    llm_context["llm"]["risk_review_status"] = risk_result.get("status")
    llm_context["llm"]["risk_reviewed_count"] = risk_result.get("reviewed_count", 0)
    llm_context["llm"]["risk_p0_count"] = risk_result.get("p0_count", 0)
    selection = select_by_rules(cands, top_n_pick=top_n_pick, coverage_mode=coverage_mode,
                                minimum_score=minimum_score,
                                market_regime=evidence_audit["market_regime"] if not mock else None)
    selection["factor_version"] = "evidence-v2"
    selection["as_of"] = snap.date
    if not mock and data_available:
        try:
            from ah_recommendation_system.backend.etf_sector.etf_sector_report import generate_etf_sector_block
            etf_block = generate_etf_sector_block(prev_report=None)
            llm_context["market_signals"].extend(_extract_market_signals(etf_block))
            etf_rows = [dict(row) for row in ((etf_block.get("etf_trend") or {}).get("recommendations") or [])]
            turnover_map = {}
            etf_market = etf_block.get("etf_market") or {}
            for bucket in ("top_by_turnover", "top_gainers", "top_losers", "top_gainers_nav"):
                for spot in (etf_market.get(bucket) or []):
                    code = "".join(ch for ch in str(spot.get("code") or "") if ch.isdigit())[-6:]
                    if len(code) == 6 and spot.get("turnover") is not None:
                        turnover_map[code] = spot.get("turnover")
            for row in etf_rows:
                code = "".join(ch for ch in str(row.get("code") or "") if ch.isdigit())[-6:]
                if code in turnover_map:
                    row["turnover"] = turnover_map[code]
            etf_rows = build_etf_quality_scores(
                etf_rows,
                hotspots=llm_context.get("hotspots") or [],
            )
            etf_result = select_etf_portfolio(etf_rows, limit=3, min_score=65.0)
            # ETF turnover feeds are sometimes reported in a smaller unit
            # (or omit large institutional lots).  If the strict 1e8 gate
            # leaves no usable portfolio, retry once at 1e7 with all other
            # trend/history/risk gates unchanged and disclose the relaxation.
            if not etf_result.get("selected"):
                relaxed = select_etf_portfolio(
                    etf_rows,
                    limit=3,
                    min_score=65.0,
                    min_turnover=10_000_000.0,
                )
                if relaxed.get("selected"):
                    relaxed["portfolio_summary"]["liquidity_gate_relaxed"] = True
                    relaxed["portfolio_summary"]["liquidity_gate_reason"] = (
                        "严格流动性门槛无合格标的，按成交额单位差异降至1000万元；趋势、历史、均线和风险门槛未放宽"
                    )
                    etf_result = relaxed
                else:
                    # Last-resort trend-only watchlist when turnover is
                    # unavailable from both Sina/THS.  This is never an
                    # aggressive buy signal; the report records the missing
                    # liquidity confirmation and keeps action=WATCH.
                    trend_only = select_etf_portfolio(
                        etf_rows,
                        limit=3,
                        min_score=65.0,
                        min_turnover=0.0,
                    )
                    if trend_only.get("selected"):
                        trend_only["portfolio_summary"]["liquidity_gate_relaxed"] = True
                        trend_only["portfolio_summary"]["liquidity_gate_reason"] = (
                            "ETF成交额接口不可用，仅依据趋势/历史/均线/风险生成观察名单；流动性待确认"
                        )
                        etf_result = trend_only

            def _etf_rationale(row: Dict[str, Any]) -> str:
                reasons = [str(item).strip() for item in (row.get("reasons") or []) if str(item).strip()]
                reasons.extend(str(item).strip() for item in (row.get("theme_match_reasons") or []) if str(item).strip())
                if reasons:
                    return "；".join(reasons[:3])
                score = row.get("trend_score")
                status = row.get("status") or "unknown"
                if score is not None:
                    try:
                        return f"趋势评分 {float(score):.1f}，数据状态：{status}"
                    except (TypeError, ValueError):
                        pass
                return f"数据状态：{status}，暂缺足够趋势证据"

            selection["etf_picks"] = [
                {
                    "code": str(row.get("code") or ""),
                    "name": row.get("name") or row.get("code") or "ETF",
                    "action": "WATCH",
                    "position": row.get("position") or "主线",
                    "theme_group": row.get("theme_group") or "未分类",
                    "exposure_group": row.get("exposure_group") or "unknown",
                    "score": row.get("composite_score"),
                    "factor_scores": row.get("factor_scores") or {},
                    "risk_flags": row.get("risk_flags") or [],
                    "selection_reasons": row.get("selection_reasons") or [],
                    "rationale": _etf_rationale(row),
                    "trigger": "趋势评分维持优先关注或持有观察",
                    "invalidation": "趋势转弱或数据源覆盖不足时退出观察",
                }
                for row in etf_result["selected"][:3]
                if row.get("code")
            ]
            selection["etf_rejections"] = etf_result["rejected"]
            selection["etf_deduplicated"] = etf_result["deduplicated"]
            selection["etf_portfolio_summary"] = etf_result["portfolio_summary"]
        except Exception as exc:
            snap.errors.append(f"etf_recommendation:{exc}")
    checkpoint(
        "etf_selection",
        status="ok" if selection.get("etf_picks") else "no_eligible_etf",
        selected_count=len(selection.get("etf_picks") or []),
    )

    coverage_payload = {
            "universe_size": int(snap.fundamental.get("universe_size") or snap.fundamental.get("count") or 0),
            "scanned_count": market_scanned_count,
            "candidate_count": len(seeds),
            "history_target_count": len(cands),
            "eligible_count": len(cands),
            "mode": coverage_mode,
            "source": snap.fundamental.get("source"),
            "history_count": sum(1 for row in (snap.fundamental.get("rows") or [])
                                  if str(row.get("code") or "") in {c.code for c in cands}
                                  and float(row.get("history_days") or 0) >= 60),
            "fresh_data_available": data_available,
            "stale": any(bool(row.get("stale")) for row in (snap.fundamental.get("rows") or [])),
            "sources": [snap.fundamental.get("source")] if snap.fundamental.get("source") else [],
        "provider_health": {
                "hithink_financial_api": "healthy" if HithinkClient().enabled and snap.fundamental.get("source") == "hithink_financial_api" else ("disabled" if not HithinkClient().enabled else "degraded"),
                "hithink_probe": {
                    "available": bool(hithink_probe.get("available")),
                    "capabilities": dict(hithink_probe.get("capabilities") or {}),
                    "error_types": {k: type(v).__name__ for k, v in (hithink_probe.get("errors") or {}).items()},
                },
                "akshare": "degraded" if any("AKShare" in str(error) or "akshare" in str(error) for error in snap.errors) else "unknown",
                "tencent_sina_fallback": "active" if str(snap.fundamental.get("source") or "").startswith("focused_") else "standby",
                "market_data_attempted": list((snap.fundamental.get("provider_health") or {}).get("attempted_sources") or []),
                "market_data_skipped": list((snap.fundamental.get("provider_health") or {}).get("skipped_sources") or []),
                "history": dict(pf.provider_health() if hasattr(pf, "provider_health") else {}),
                "news": dict((snap.events or {}).get("provider_health") or {}),
                "cross_market": str((snap.cross_market or {}).get("status") or "disabled"),
                "llm_codex": llm_context.get("llm", {}),
        },
            "fallback_chain": market_data_attempted_chain(snap),
            "circuit_breakers": list((pf.provider_health() if hasattr(pf, "provider_health") else {}).get("history_errors") or []),
        }
    coverage_universe = int(coverage_payload.get("universe_size") or 0)
    coverage_payload["ratio"] = round(market_scanned_count / coverage_universe, 4) if coverage_universe else None
    decision = build_market_decision(
        as_of=snap.date,
        market_signals=llm_context.get("market_signals") or [],
        hotspots=llm_context.get("hotspots") or [],
        coverage=coverage_payload,
        cross_market=snap.cross_market,
    )
    report = build_report(
        selection=selection,
        candidates=cand_dicts,
        snapshot_errors=snap.errors,
        coverage=coverage_payload,
        llm_context=llm_context,
        decision=decision,
        cross_market=snap.cross_market,
    )
    checkpoint(
        "quality_gate",
        status="passed" if report.get("quality_gate", {}).get("passed") else "failed",
        blocking_count=len(report.get("quality_gate", {}).get("blocking_reasons") or []),
    )
    report.setdefault("run", {})["stages"] = stages
    report["evidence_audit"] = evidence_audit
    report["candidate_panel"] = to_dict_list(cands)
    report["selection_policy_version"] = "defensive_relative_leaders_v1"
    report["candidate_panel_scope"] = "all_saved_candidates"
    report["candidate_panel_limit"] = top_n_candidates
    report.setdefault("market", {}).update(regime=evidence_audit["market_regime"]["regime"],
                                           regime_evidence=evidence_audit["market_regime"])

    paths = save_report(report, _backend_root())

    push_result: Optional[Dict[str, Any]] = None
    wechat_result: Optional[Dict[str, Any]] = None
    if push:
        push_result = _deliver_report(report, force=force_push)
        wechat_result = push_to_wechat(report)
        paths = save_report(report, _backend_root())

    return {
        "ok": data_available and bool(report.get("quality_gate", {}).get("passed")),
        "report": report,
        "paths": paths,
        "push": push_result,
        "wechat_push": wechat_result,
        "as_of": report.get("as_of"),
        "generated_at": report.get("generated_at"),
    }


def run_verify_only() -> Dict[str, Any]:
    report_dir = _backend_root() / "data" / "stock_recommend"
    ledgers = _ledgers_dir()
    results = verify_all_pending(report_dir, ledgers)
    return {
        "ok": True,
        "verified_count": len(results),
        "results": [
            {
                "as_of": r.get("as_of"),
                "pick_count": r.get("pick_count"),
                "verified_count": r.get("verified_count"),
                "hit_rate_T5_pct": r.get("hit_rate_T5_pct"),
                "avg_return_T5_pct": r.get("avg_return_T5_pct"),
                "verification_status": r.get("verification_status"),
                "net_verified_count": r.get("net_verified_count"),
                "avg_net_return_T5_pct": r.get("avg_net_return_T5_pct"),
                "avg_net_excess_T5_pct": r.get("avg_net_excess_T5_pct"),
            }
            for r in results
        ],
    }


def _collect_closing_industry_rows() -> list[Dict[str, Any]]:
    """Collect close-confirmed industry performance for the post-market review."""
    from ah_recommendation_system.backend.etf_sector.etf_sector_report import (
        generate_etf_sector_block,
    )

    block = generate_etf_sector_block(prev_report=None)
    industry = ((block.get("boards") or {}).get("industry") or {})
    rows: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in ("top_gainers", "top_losers"):
        for item in industry.get(bucket) or []:
            name = str(item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            rows.append(dict(item))
    return rows


def _build_direction_outcomes(
    report: Dict[str, Any], industry_rows: list[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Match planned directions to close-confirmed industry-board returns."""
    outcomes: Dict[str, Dict[str, Any]] = {}
    for planned in (report.get("directions") or {}).values():
        for item in planned or []:
            direction = str(item.get("direction") or "").strip()
            if not direction:
                continue
            matched = next(
                (
                    row
                    for row in industry_rows
                    if direction in str(row.get("name") or "")
                    or str(row.get("name") or "") in direction
                ),
                None,
            )
            if not matched:
                continue
            try:
                change = float(matched.get("chg_pct"))
            except (TypeError, ValueError):
                continue
            if change >= 0.5:
                status, correction = "confirmed", "keep"
            elif change <= -0.5:
                status, correction = "failed", "downgrade"
            else:
                status, correction = "neutral", "confirm"
            outcomes[direction] = {
                "status": status,
                "correction": correction,
                "evidence": (
                    f"{matched.get('name', direction)}收盘涨跌幅 {change:+.2f}%"
                    f"（来源：{matched.get('source') or 'industry_board'}）"
                ),
            }
    return outcomes


def run_post_market(
    *,
    mock: bool = False,
    push: bool = False,
    force_push: bool = False,
    report_path: Optional[Path] = None,
    expected_as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Review the latest pre-market report and optionally push it to Feishu."""
    pf = get_price_fetcher()
    pf.enable_mock_data() if mock else setattr(pf, "use_mock_data", False)
    report_dir = _backend_root() / "data" / "stock_recommend"
    latest = Path(report_path) if report_path is not None else report_dir / "latest.json"
    if not latest.exists():
        raise FileNotFoundError("No pre-market report found; run the pre-market job first")
    import json

    report = json.loads(latest.read_text(encoding="utf-8"))
    observations: Dict[str, Dict[str, Any]] = {}
    expected_date = expected_as_of or datetime.now().strftime("%Y-%m-%d")
    as_of = str(report.get("as_of") or "")
    if report.get("type") != "stock_recommend_pre_market" or as_of != expected_date:
        reason = f"latest.json 不是当日盘前报告：期望 {expected_date}，实际 {as_of or '缺失'}"
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        review = {
            "schema_version": "decision-report-v2",
            "type": "stock_recommend_post_market_error",
            "as_of": expected_date,
            "generated_at": generated_at,
            "run": {
                "run_id": f"{expected_date.replace('-', '')}-post_market-error",
                "session": "post_market",
                "trade_date": expected_date,
                "generated_at": generated_at,
                "status": "failed",
            },
            "quality_gate": {"passed": False, "blocking_reasons": [reason], "warnings": []},
            "data_status": "failed",
            "picks": [],
            "etf_picks": [],
            "summary": "盘后复盘未执行，避免使用旧报告。",
            "delivery": {"channel": "feishu", "payload_hash": "", "accepted": False},
        }
        paths = save_review_report(review, _backend_root())
        push_result = _deliver_report(review, force=force_push) if push else None
        wechat_result = push_to_wechat(review) if push else None
        if push:
            paths = save_review_report(review, _backend_root())
        return {"ok": False, "review": review, "paths": paths, "push": push_result, "wechat_push": wechat_result}
    for pick in report.get("picks") or []:
        code = str(pick.get("code") or "")
        if not code:
            continue
        start_date = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y%m%d")
        try:
            df = pf.get_a_share_price(code, start_date, as_of.replace("-", ""))
            observations[code] = closing_observation(pick, df, as_of)
        except Exception as exc:
            observations[code] = closing_observation(pick, None, as_of)
            observations[code]["data_reason"] = f"Historical data unavailable: {type(exc).__name__}"
    industry_rows: list[Dict[str, Any]] = []
    if not mock:
        try:
            industry_rows = _collect_closing_industry_rows()
        except Exception as exc:
            logger.warning("post-market industry close collection failed: {}", exc)
    direction_outcomes = _build_direction_outcomes(report, industry_rows)
    review = build_post_market_review(
        report,
        observations=observations,
        direction_outcomes=direction_outcomes,
    )
    import hashlib

    review["source_report"] = {
        "run_id": (report.get("run") or {}).get("run_id"),
        "generated_at": report.get("generated_at"),
        "sha256": hashlib.sha256(latest.read_bytes()).hexdigest(),
    }
    review["closing_market"] = {
        "source": "ths_industry_close" if industry_rows else "unavailable",
        "industry_count": len(industry_rows),
        "top_gainers": sorted(
            industry_rows,
            key=lambda row: float(row.get("chg_pct") or 0.0),
            reverse=True,
        )[:5],
        "top_losers": sorted(
            industry_rows,
            key=lambda row: float(row.get("chg_pct") or 0.0),
        )[:5],
    }
    paths = save_review_report(review, _backend_root())
    push_result = _deliver_report(review, force=force_push) if push else None
    wechat_result = push_to_wechat(review) if push else None
    if push:
        paths = save_review_report(review, _backend_root())
    return {"ok": True, "review": review, "paths": paths, "push": push_result, "wechat_push": wechat_result}


def run_weekly_reweight_job() -> Dict[str, Any]:
    """Apply the bounded weekly factor-weight update from the verification ledger."""
    result = run_weekly_reweight(ledgers_dir=_ledgers_dir())
    logger.info("weekly reweight completed weights_path={}", result.get("weights_path"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Stock recommendation pipeline")
    parser.add_argument("--mock", action="store_true", help="Use mock data (no network)")
    parser.add_argument("--live", action="store_true", help="Use live AKShare data")
    parser.add_argument("--pick", type=int, default=5, help="Top picks count")
    parser.add_argument(
        "--candidates", type=int, default=30, help="Candidate pool size"
    )
    parser.add_argument(
        "--push", action="store_true", help="Push result to Feishu webhook"
    )
    parser.add_argument("--force-push", action="store_true", help="Bypass same-session delivery idempotency")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify historical recommendations (T+N returns)",
    )
    parser.add_argument("--post-market", action="store_true", help="Review latest pre-market report")
    parser.add_argument("--weekly-reweight", action="store_true", help="Update bounded factor weights")
    args = parser.parse_args()

    if args.verify_only:
        result = run_verify_only()
        print(json_dumps(result))
        return 0

    if args.post_market:
        result = run_post_market(
            mock=bool(args.mock) or not bool(args.live),
            push=bool(args.push),
            force_push=bool(args.force_push),
        )
        print(json_dumps({"ok": result["ok"], "paths": result["paths"], "push": result["push"]}))
        return 0

    if args.weekly_reweight:
        result = run_weekly_reweight_job()
        print(json_dumps(result))
        return 0

    result = run_pipeline(
        mock=bool(args.mock) or not bool(args.live),
        top_n_pick=args.pick,
        top_n_candidates=args.candidates,
        push=bool(args.push),
        force_push=bool(args.force_push),
    )
    print(json_dumps({"ok": result["ok"], "paths": result["paths"], "push": result["push"]}))
    return 0


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
