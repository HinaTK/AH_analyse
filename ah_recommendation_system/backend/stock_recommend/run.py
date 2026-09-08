"""Entry point for stock recommendation pipeline.

Usage:
  python -m ah_recommendation_system.backend.stock_recommend.run --mock
  python -m ah_recommendation_system.backend.stock_recommend.run --live
  python -m ah_recommendation_system.backend.stock_recommend.run --verify-only
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
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
from ah_recommendation_system.backend.stock_recommend.report_builder import (
    build_report,
    save_report,
    save_review_report,
)
from ah_recommendation_system.backend.stock_recommend.post_market import build_post_market_review
from ah_recommendation_system.backend.stock_recommend.local_store import load_last_snapshot, persist_snapshot
from ah_recommendation_system.backend.stock_recommend.reweight import load_factor_weights, run_weekly_reweight
from ah_recommendation_system.backend.stock_recommend.focused_collector import (
    collect_focused_market,
)
from ah_recommendation_system.backend.stock_recommend.dynamic_scanner import scan_snapshot
from ah_recommendation_system.backend.stock_recommend.technical_features import calculate_features
from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient
from ah_recommendation_system.backend.stock_recommend.wechat_pusher import push_to_wechat


def _backend_root() -> Path:
    return _BACKEND_DIR


def _ledgers_dir() -> Path:
    # store ledgers at repo-root docs/analyse (matches existing abnormal-movement convention)
    return _REPO_ROOT / "docs" / "analyse"


def _enrich_with_daily_features(rows: list[Dict[str, Any]], pf: Any, *, as_of: str, limit: int = 100) -> int:
    """Attach cached/provider daily features to the highest-value rows."""
    enriched = 0
    hithink = HithinkClient()
    for row in rows[: max(0, limit)]:
        code = str(row.get("code") or "")
        if len(code) != 6:
            continue
        try:
            start = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=220)).strftime("%Y%m%d")
            end = datetime.strptime(as_of, "%Y-%m-%d").strftime("%Y%m%d")
            bars: list[Dict[str, Any]] = []
            if hithink.enabled:
                start_ms = int(datetime.strptime(start, "%Y%m%d").timestamp() * 1000)
                end_ms = int(datetime.strptime(end, "%Y%m%d").timestamp() * 1000)
                try:
                    bars = hithink.historical(code, start_ms=start_ms, end_ms=end_ms)
                except Exception as exc:
                    row.setdefault("feature_errors", []).append(f"hithink:{exc}")
            if not bars:
                frame = pf.get_a_share_price(code, start, end)
                if frame is None or getattr(frame, "empty", True):
                    continue
                bars = frame.to_dict("records")
            features = calculate_features(bars)
            row.update(features)
            if features.get("return_60d_pct") is not None:
                row["change_60d_pct"] = features["return_60d_pct"]
            enriched += 1
        except Exception as exc:
            row.setdefault("feature_errors", []).append(str(exc))
    return enriched


def _enrich_hithink_candidates(rows: list[Dict[str, Any]], *, limit: int = 600) -> list[Dict[str, Any]]:
    """Enrich only the dynamic short-list, never the whole market snapshot."""
    if not rows or rows[0].get("source") != "hithink_financial_api":
        return rows
    client = HithinkClient()
    head = client.enrich_snapshot(rows[: max(0, limit)])
    return head + rows[max(0, limit) :]


def run_pipeline(
    *,
    mock: bool = False,
    top_n_pick: int = 3,
    top_n_candidates: int = 30,
    push: bool = False,
) -> Dict[str, Any]:
    """Run the full pipeline: collect -> candidates -> LLM select -> report -> (push)."""
    pf = get_price_fetcher()
    if mock:
        pf.enable_mock_data()
    else:
        pf.use_mock_data = False

    logger.info(f"pipeline start mock={mock} top_pick={top_n_pick} push={push}")

    snap = collect_all(limit=6000)
    coverage_mode = "full_market"
    if not mock and not (snap.fundamental.get("rows") or []):
        previous_errors = list(snap.errors)
        if "full_market_unavailable" not in previous_errors:
            previous_errors.append("full_market_unavailable")
        snap = collect_focused_market()
        snap.errors = previous_errors + list(snap.errors)
        coverage_mode = "focused_fallback"
    if not mock and not (snap.fundamental.get("rows") or []):
        try:
            cached_rows = load_last_snapshot(_backend_root())
            if cached_rows:
                snap.fundamental = {
                    "rows": cached_rows,
                    "count": len(cached_rows),
                    "universe_size": len(cached_rows),
                    "source": "last_good_snapshot",
                }
                snap.errors.append("using_stale_last_good_snapshot")
                coverage_mode = "limited_sample"
        except Exception as exc:
            snap.errors.append(f"last_good_snapshot:{exc}")
    data_available = bool(snap.fundamental.get("rows") or []) and snap.fundamental.get("source") != "last_good_snapshot"
    if not data_available and "focused_market_unavailable" not in snap.errors:
        snap.errors.append("focused_market_unavailable")
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
        if not mock:
            try:
                from ah_recommendation_system.backend.stock_recommend.data_collector import collect_events
                event_codes = [str(row.get("code")) for row in seeds[:20] if row.get("code")]
                refreshed_events = collect_events(limit=200, codes=event_codes)
                if refreshed_events.get("stock_news"):
                    snap.events["stock_news"] = refreshed_events["stock_news"]
            except Exception as exc:
                snap.errors.append(f"candidate_news:{exc}")
    if not mock:
        coverage_history_count = _enrich_with_daily_features(snap.fundamental.get("rows") or [], pf, as_of=snap.date)
    else:
        coverage_history_count = sum(
            1 for row in (snap.fundamental.get("rows") or []) if float(row.get("history_days") or 0) >= 60
        )
    if snap.fundamental.get("source") != "last_good_snapshot":
        try:
            persist_snapshot(
                snap.fundamental.get("rows") or [],
                _backend_root(),
                as_of=snap.date,
            )
        except ImportError as exc:
            snap.errors.append(f"local_store_dependency:{exc}")
        except Exception as exc:
            snap.errors.append(f"local_store:{exc}")
    weights_path = _backend_root() / "data" / "stock_recommend" / "factor_weights.json"
    cands = build_candidates(snap, top_n=top_n_candidates, weights=load_factor_weights(weights_path))
    cand_dicts = to_dict_list(cands)
    macro_ctx = (snap.events.get("macro_news") or {})

    selection = select_by_rules(cands, top_n_pick=top_n_pick)
    if not mock:
        try:
            from ah_recommendation_system.backend.etf_sector.etf_sector_report import generate_etf_sector_block
            etf_block = generate_etf_sector_block(prev_report=None)
            etf_rows = ((etf_block.get("etf_trend") or {}).get("recommendations") or [])
            selection["etf_picks"] = [
                {
                    "code": str(row.get("code") or ""),
                    "name": row.get("name") or row.get("code") or "ETF",
                    "action": "WATCH",
                    "rationale": row.get("reason") or row.get("recommendation") or "趋势与行业数据可用",
                    "trigger": "趋势评分维持优先关注或持有观察",
                    "invalidation": "趋势转弱或数据源覆盖不足",
                }
                for row in etf_rows[:2]
                if row.get("code")
            ]
        except Exception as exc:
            snap.errors.append(f"etf_recommendation:{exc}")

    report = build_report(
        selection=selection,
        candidates=cand_dicts,
        snapshot_errors=snap.errors,
        coverage={
            "universe_size": int(snap.fundamental.get("universe_size") or snap.fundamental.get("count") or 0),
            "scanned_count": market_scanned_count,
            "candidate_count": len(seeds),
            "eligible_count": len(cands),
            "mode": coverage_mode,
            "source": snap.fundamental.get("source"),
            "history_count": coverage_history_count,
            "fresh_data_available": data_available,
            "stale": any(bool(row.get("stale")) for row in (snap.fundamental.get("rows") or [])),
            "sources": [snap.fundamental.get("source")] if snap.fundamental.get("source") else [],
        },
    )

    paths = save_report(report, _backend_root())

    push_result: Optional[Dict[str, Any]] = None
    wechat_result: Optional[Dict[str, Any]] = None
    if push:
        push_result = push_to_feishu(report)
        wechat_result = push_to_wechat(report)

    return {
        "ok": data_available,
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
            }
            for r in results
        ],
    }


def run_post_market(*, mock: bool = False, push: bool = False) -> Dict[str, Any]:
    """Review the latest pre-market report and optionally push it to Feishu."""
    pf = get_price_fetcher()
    pf.enable_mock_data() if mock else setattr(pf, "use_mock_data", False)
    report_dir = _backend_root() / "data" / "stock_recommend"
    latest = report_dir / "latest.json"
    if not latest.exists():
        raise FileNotFoundError("No pre-market report found; run the pre-market job first")
    import json

    report = json.loads(latest.read_text(encoding="utf-8"))
    prices: Dict[str, list[float]] = {}
    as_of = str(report.get("as_of") or datetime.now().strftime("%Y-%m-%d"))
    for pick in report.get("picks") or []:
        code = str(pick.get("code") or "")
        if not code:
            continue
        # Pull a sufficiently long window so the review can populate T+1,
        # T+5 and T+20 outcomes; the helper naturally leaves unavailable
        # horizons as ``pending``.
        end_date = (datetime.strptime(as_of, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y%m%d")
        df = pf.get_a_share_price(code, as_of.replace("-", ""), end_date)
        if df is not None and not df.empty and "close" in df.columns:
            prices[code] = [float(x) for x in df["close"].tolist()]
    review = build_post_market_review(report, prices=prices)
    paths = save_review_report(review, _backend_root())
    push_result = push_to_feishu(review) if push else None
    wechat_result = push_to_wechat(review) if push else None
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
    parser.add_argument("--pick", type=int, default=3, help="Top picks count")
    parser.add_argument(
        "--candidates", type=int, default=30, help="Candidate pool size"
    )
    parser.add_argument(
        "--push", action="store_true", help="Push result to Feishu webhook"
    )
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
        result = run_post_market(mock=bool(args.mock) or not bool(args.live), push=bool(args.push))
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
    )
    print(json_dumps({"ok": result["ok"], "paths": result["paths"], "push": result["push"]}))
    return 0


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
