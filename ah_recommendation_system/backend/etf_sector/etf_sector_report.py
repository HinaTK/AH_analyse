from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from loguru import logger

from ah_recommendation_system.backend.etf_sector.rss_fetcher import (
    fetch_news_digest,
)
from ah_recommendation_system.backend.etf_sector.etf_trend_analysis import (
    generate_etf_trend_recommendation_block,
)
from ah_recommendation_system.backend.etf_sector.etf_universe_selector import (
    build_theme_breakout_block,
    select_hot_etf_candidates,
)
from ah_recommendation_system.backend.etf_sector.etf_portfolio import (
    build_etf_quality_scores,
    select_etf_portfolio,
)
from ah_recommendation_system.backend.etf_sector.ths_sources import (
    fetch_board_trend_items_ths,
    fetch_concept_summary_ths,
    fetch_etf_spot_sina,
    fetch_etf_spot_ths,
    fetch_industry_summary_ths,
    normalize_concept_summary_ths,
    normalize_etf_spot_sina,
    normalize_etf_spot_ths,
    normalize_industry_summary_ths,
)


def _parse_date_only(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern)
        except Exception:
            continue
    return None


def _filter_stale_concept_items(items: Any, *, max_age_days: int = 7) -> Dict[str, Any]:
    rows = [it for it in (items or []) if isinstance(it, dict)]
    cutoff = datetime.now() - timedelta(days=max(1, int(max_age_days or 7)))
    fresh_items = []
    stale_count = 0
    latest_date = None
    for item in rows:
        parsed = _parse_date_only(item.get("date"))
        if parsed and (latest_date is None or parsed > latest_date):
            latest_date = parsed
        if parsed and parsed >= cutoff:
            fresh_items.append(item)
        else:
            stale_count += 1
    return {
        "items": fresh_items,
        "freshness": {
            "max_age_days": max(1, int(max_age_days or 7)),
            "stale_count": stale_count,
            "is_stale": len(fresh_items) == 0 and len(rows) > 0,
            "latest_date": latest_date.strftime("%Y-%m-%d") if latest_date else None,
            "status": "stale_filtered"
            if len(fresh_items) == 0 and len(rows) > 0
            else "ok",
        },
    }


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _merge_prev(
    prev: Optional[dict], key: str, payload: dict, error: Optional[str]
) -> dict:
    """Merge section with previous payload on failure."""
    if error:
        old = (prev or {}).get(key)
        if isinstance(old, dict) and old:
            return {**old, "error": error, "last_ok_at": old.get("generated_at")}
        return {"error": error, "generated_at": _now_str()}
    return payload


def _merge_prev_list(
    prev: Optional[dict], key: str, payload: list, error: Optional[str]
) -> list:
    if error:
        old = (prev or {}).get(key)
        if isinstance(old, list):
            return old
        return []
    return payload


def generate_etf_sector_block(
    *,
    prev_report: Optional[Dict[str, Any]] = None,
    trend_codes: Optional[str] = None,
    trend_lookback_short: Any = None,
    trend_lookback_mid: Any = None,
    trend_lookback_long: Any = None,
    trend_breakout_window: Any = None,
) -> Dict[str, Any]:
    """Generate ETF + sector + news block.

    Uses multi-source fetching; best-effort. On failures, keeps previous data per section.
    """
    prev_block = (
        (prev_report or {}).get("etf_sector") if isinstance(prev_report, dict) else None
    )

    # ETF market
    etf_payload: Dict[str, Any] = {}
    etf_err: Optional[str] = None
    try:
        # Prefer Sina for turnover; fallback to THS
        sina_df = fetch_etf_spot_sina()
        sina_rows = normalize_etf_spot_sina(sina_df, limit=120)
        ths_df = fetch_etf_spot_ths()
        ths_rows = normalize_etf_spot_ths(ths_df, limit=120)
        etf_payload = {
            "generated_at": _now_str(),
            "source_order": ["sina", "ths"],
            "top_by_turnover": sina_rows[:40],
            "top_gainers": sorted(
                [r for r in sina_rows if r.get("chg_pct") is not None],
                key=lambda r: r.get("chg_pct"),
                reverse=True,
            )[:30],
            "top_losers": sorted(
                [r for r in sina_rows if r.get("chg_pct") is not None],
                key=lambda r: r.get("chg_pct"),
            )[:30],
            "top_gainers_nav": ths_rows[:30],
        }
    except Exception as e:
        etf_err = f"etf_market_fetch_failed: {e}"
        logger.warning(etf_err)

    # Industry boards
    industry_payload: Dict[str, Any] = {}
    industry_err: Optional[str] = None
    industry_names_for_trend = []
    try:
        df = fetch_industry_summary_ths()
        strength = normalize_industry_summary_ths(df, limit=20)
        industry_names_for_trend = [
            str(r.get("name") or "")
            for r in (strength.get("top_gainers") or [])[:6]
            + (strength.get("top_losers") or [])[:6]
        ]
        industry_names_for_trend = [n for n in industry_names_for_trend if n.strip()]
        industry_payload = {
            "generated_at": _now_str(),
            "source": "ths",
            "top_gainers": strength.get("top_gainers") or [],
            "top_losers": strength.get("top_losers") or [],
        }
    except Exception as e:
        industry_err = f"industry_fetch_failed: {e}"
        logger.warning(industry_err)

    # Concept hot list (news-style)
    concept_payload: Dict[str, Any] = {}
    concept_err: Optional[str] = None
    concept_names_for_trend = []
    try:
        df = fetch_concept_summary_ths()
        items = normalize_concept_summary_ths(df, limit=50)
        concept_filter = _filter_stale_concept_items(items[:50], max_age_days=7)
        concept_names_for_trend = [
            str(it.get("concept") or "")
            for it in (concept_filter.get("items") or [])[:8]
        ]
        concept_names_for_trend = [n for n in concept_names_for_trend if n.strip()]
        concept_payload = {
            "generated_at": _now_str(),
            "source": "ths",
            "items": concept_filter.get("items") or [],
            "freshness": concept_filter.get("freshness") or {},
        }
    except Exception as e:
        concept_err = f"concept_fetch_failed: {e}"
        logger.warning(concept_err)

    # Board trends (index momentum)
    trend_payload: Dict[str, Any] = {}
    trend_err: Optional[str] = None
    try:
        lookbacks = [5, 10, 20]
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=200)).strftime("%Y%m%d")

        ind_names = sorted(set(industry_names_for_trend))
        con_names = sorted(set(concept_names_for_trend))

        industry_trend = fetch_board_trend_items_ths(
            kind="industry",
            names=ind_names,
            lookbacks=lookbacks,
            start_date=start_date,
            end_date=end_date,
            per_item_delay_s=0.0,
        )
        concept_trend = fetch_board_trend_items_ths(
            kind="concept",
            names=con_names,
            lookbacks=lookbacks,
            start_date=start_date,
            end_date=end_date,
            per_item_delay_s=0.0,
        )

        trend_payload = {
            "generated_at": _now_str(),
            "source": "ths",
            "lookbacks": lookbacks,
            "start_date": start_date,
            "end_date": end_date,
            "industry": {"items": industry_trend},
            "concept": {"items": concept_trend},
        }
    except Exception as e:
        trend_err = f"trend_fetch_failed: {e}"
        logger.warning(trend_err)

    # News digest (RSS)
    news_payload: Dict[str, Any] = {}
    news_err: Optional[str] = None
    try:
        news_payload = fetch_news_digest(max_items=120)
    except Exception as e:
        news_err = f"news_fetch_failed: {e}"
        logger.warning(news_err)

    # ETF trend recommendation block
    etf_trend_payload: Dict[str, Any] = {}
    etf_trend_err: Optional[str] = None
    auto_selection: Optional[Dict[str, Any]] = None
    try:
        effective_trend_codes = trend_codes
        if (
            not isinstance(effective_trend_codes, str)
            or not effective_trend_codes.strip()
        ):
            auto_selection = select_hot_etf_candidates(
                sina_rows=sina_rows if "sina_rows" in locals() else None,
                ths_rows=ths_rows if "ths_rows" in locals() else None,
                industry_payload=industry_payload,
                concept_payload=concept_payload,
                trend_payload=trend_payload,
                limit=10,
            )
            selected_codes = auto_selection.get("codes") or []
            if selected_codes:
                effective_trend_codes = ",".join(selected_codes)

        etf_trend_payload = generate_etf_trend_recommendation_block(
            codes=effective_trend_codes,
            universe_items=(auto_selection.get("items") if auto_selection else None),
            lookback_short=trend_lookback_short,
            lookback_mid=trend_lookback_mid,
            lookback_long=trend_lookback_long,
            breakout_window=trend_breakout_window,
        )
        if auto_selection and isinstance(etf_trend_payload, dict):
            etf_trend_payload["selection"] = auto_selection
            coverage = etf_trend_payload.get("coverage")
            if isinstance(coverage, dict):
                coverage["custom_universe"] = False
                coverage["selection_mode"] = auto_selection.get("mode")
    except Exception as e:
        etf_trend_err = f"etf_trend_fetch_failed: {e}"
        logger.warning(etf_trend_err)

    if isinstance(etf_trend_payload, dict) and etf_trend_payload.get("recommendations"):
        turnover_map = {}
        for bucket in ("top_by_turnover", "top_gainers", "top_losers", "top_gainers_nav"):
            for spot in (etf_payload.get(bucket) or []):
                digits = "".join(ch for ch in str(spot.get("code") or "") if ch.isdigit())
                code = digits[-6:]
                if len(code) == 6 and spot.get("turnover") is not None:
                    turnover_map[code] = spot.get("turnover")
        rows = []
        for item in etf_trend_payload.get("recommendations") or []:
            row = dict(item)
            code = "".join(ch for ch in str(row.get("code") or "") if ch.isdigit())[-6:]
            if code in turnover_map:
                row["turnover"] = turnover_map[code]
            rows.append(row)
        scored_rows = build_etf_quality_scores(rows)
        etf_trend_payload["portfolio"] = select_etf_portfolio(scored_rows, limit=3, min_score=60.0)

    breakout_payload: Dict[str, Any] = {}
    breakout_err: Optional[str] = None
    try:
        breakout_payload = build_theme_breakout_block(
            industry_payload=industry_payload,
            concept_payload=concept_payload,
            trend_payload=trend_payload,
            news_payload=news_payload,
            etf_payload=etf_payload,
            etf_trend_payload=etf_trend_payload,
            selection_payload=auto_selection,
        )
    except Exception as e:
        breakout_err = f"theme_breakout_build_failed: {e}"
        logger.warning(breakout_err)

    return {
        "generated_at": _now_str(),
        "etf_market": _merge_prev(prev_block, "etf_market", etf_payload, etf_err),
        "etf_trend": _merge_prev(
            prev_block, "etf_trend", etf_trend_payload, etf_trend_err
        ),
        "boards": {
            "industry": _merge_prev(
                prev_block.get("boards") if isinstance(prev_block, dict) else None,
                "industry",
                industry_payload,
                industry_err,
            ),
            "concept_hot": _merge_prev(
                prev_block.get("boards") if isinstance(prev_block, dict) else None,
                "concept_hot",
                concept_payload,
                concept_err,
            ),
        },
        "trend": _merge_prev(prev_block, "trend", trend_payload, trend_err),
        "news_digest": _merge_prev(prev_block, "news_digest", news_payload, news_err),
        "potential_breakouts": _merge_prev_list(
            prev_block,
            "potential_breakouts",
            list((breakout_payload or {}).get("potential_breakouts") or []),
            breakout_err,
        ),
        "confirmed_leaders": _merge_prev_list(
            prev_block,
            "confirmed_leaders",
            list((breakout_payload or {}).get("confirmed_leaders") or []),
            breakout_err,
        ),
        "crowded_risks": _merge_prev_list(
            prev_block,
            "crowded_risks",
            list((breakout_payload or {}).get("crowded_risks") or []),
            breakout_err,
        ),
    }
