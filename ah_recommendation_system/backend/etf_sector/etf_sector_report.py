from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from loguru import logger

from ah_recommendation_system.backend.etf_sector.rss_fetcher import (
    fetch_news_digest,
)
from ah_recommendation_system.backend.etf_sector.ths_sources import (
    fetch_concept_summary_ths,
    fetch_etf_spot_sina,
    fetch_etf_spot_ths,
    fetch_industry_summary_ths,
    normalize_etf_spot_sina,
    normalize_etf_spot_ths,
    normalize_industry_summary_ths,
)


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


def generate_etf_sector_block(
    *, prev_report: Optional[Dict[str, Any]] = None
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
    try:
        df = fetch_industry_summary_ths()
        strength = normalize_industry_summary_ths(df, limit=20)
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
    try:
        df = fetch_concept_summary_ths()
        items = []
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                items.append(
                    {
                        "date": str(row.iloc[0]),
                        "concept": str(row.iloc[1]),
                        "headline": str(row.iloc[2]),
                        "leader": str(row.iloc[3]) if len(row) > 3 else "",
                        "constituents": int(row.iloc[4])
                        if len(row) > 4 and str(row.iloc[4]).isdigit()
                        else None,
                    }
                )
        concept_payload = {
            "generated_at": _now_str(),
            "source": "ths",
            "items": items[:50],
        }
    except Exception as e:
        concept_err = f"concept_fetch_failed: {e}"
        logger.warning(concept_err)

    # News digest (RSS)
    news_payload: Dict[str, Any] = {}
    news_err: Optional[str] = None
    try:
        news_payload = fetch_news_digest(max_items=120)
    except Exception as e:
        news_err = f"news_fetch_failed: {e}"
        logger.warning(news_err)

    return {
        "generated_at": _now_str(),
        "etf_market": _merge_prev(prev_block, "etf_market", etf_payload, etf_err),
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
        "news_digest": _merge_prev(prev_block, "news_digest", news_payload, news_err),
    }
