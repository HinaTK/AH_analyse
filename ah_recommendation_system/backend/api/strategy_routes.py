# 策略API端点
# ==========

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException

from ah_recommendation_system.backend.api.models import (
    PairTradingRecommendation,
    MultiFactorRecommendation,
    MLRecommendation,
)
from ah_recommendation_system.backend.data.ah_stock_list import get_ah_pairs
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

router = APIRouter(prefix="/api/v1", tags=["strategies"])


def _get_stored_strategy(name: str) -> Optional[dict]:
    store = get_report_store()
    report = store.load_latest()
    if not report:
        return None
    return report.get(name)


@router.get("/pair-trading", response_model=PairTradingRecommendation)
async def get_pair_trading_recommendations(
    stock_list: Optional[str] = None,
    max_positions: Optional[int] = 10,
    source: str = "stored",
):
    """获取AH溢价配对交易推荐

    source:
    - stored: read from latest stored report (default)
    - live: compute on-demand
    """
    try:
        if source == "stored":
            stored = _get_stored_strategy("pair_trading")
            if stored:
                return stored

        strategy = get_pair_trading_strategy()
        stocks = stock_list.split(",") if stock_list else None
        recommendations = strategy.generate_recommendations(
            stock_list=stocks, max_positions=max_positions
        )
        return recommendations
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pair-trading/{a_code}", response_model=dict)
async def get_single_pair_analysis(a_code: str, source: str = "live"):
    """获取单个AH股票对的分析"""
    try:
        strategy = get_pair_trading_strategy()
        ah_pairs = get_ah_pairs()
        h_code = ah_pairs.get(a_code, "")
        result = strategy.analyze_single_pair(a_code, h_code)
        if not result:
            raise HTTPException(status_code=404, detail="股票未找到或数据不可用")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/multi-factor", response_model=MultiFactorRecommendation)
async def get_multi_factor_recommendations(
    stock_list: Optional[str] = None,
    top_n: Optional[int] = 10,
    source: str = "stored",
):
    """获取多因子Alpha模型推荐"""
    try:
        if source == "stored":
            stored = _get_stored_strategy("multi_factor")
            if stored:
                return stored

        strategy = get_multi_factor_strategy()
        stocks = stock_list.split(",") if stock_list else None
        recommendations = strategy.generate_recommendations(
            stock_list=stocks, top_n=top_n
        )
        return recommendations
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/multi-factor/{a_code}", response_model=dict)
async def get_single_stock_factor(a_code: str, source: str = "live"):
    """获取单个股票的因子得分"""
    try:
        strategy = get_multi_factor_strategy()
        ah_pairs = get_ah_pairs()
        h_code = ah_pairs.get(a_code, "")
        result = strategy.analyze_single_stock(a_code, h_code)
        if not result:
            raise HTTPException(status_code=404, detail="股票未找到或数据不可用")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ml-prediction", response_model=MLRecommendation)
async def get_ml_predictions(
    stock_list: Optional[str] = None,
    source: str = "stored",
):
    """获取机器学习AH溢价预测"""
    try:
        if source == "stored":
            stored = _get_stored_strategy("ml_prediction")
            if stored:
                return stored

        strategy = get_ml_predictor_strategy()
        if stock_list:
            pairs = []
            for item in stock_list.split(","):
                if "-" in item:
                    a, h = item.split("-", 1)
                    pairs.append((a.strip(), h.strip()))
                else:
                    pairs.append((item.strip(), ""))
            stocks = pairs
        else:
            ah_pairs = get_ah_pairs()
            stocks = list(ah_pairs.items())

        recommendations = strategy.generate_recommendations(stock_list=stocks)
        return recommendations
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ml-prediction/{a_code}", response_model=dict)
async def get_single_prediction(a_code: str, source: str = "live"):
    """获取单个股票的ML预测"""
    try:
        strategy = get_ml_predictor_strategy()
        ah_pairs = get_ah_pairs()
        h_code = ah_pairs.get(a_code, "")
        result = strategy.predict(a_code, h_code)
        if not result:
            raise HTTPException(status_code=404, detail="预测不可用")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comparison")
async def get_all_strategies_comparison(source: str = "stored"):
    """获取所有策略的综合对比"""
    try:
        if source == "stored":
            store = get_report_store()
            report = store.load_latest()
            if report:
                return {
                    "success": True,
                    "generated_at": report.get("generated_at"),
                    "recommendations": report,
                }

        pair_strategy = get_pair_trading_strategy()
        mf_strategy = get_multi_factor_strategy()
        ml_strategy = get_ml_predictor_strategy()

        pair_rec = pair_strategy.generate_recommendations()
        mf_rec = mf_strategy.generate_recommendations()
        ml_rec = ml_strategy.generate_recommendations()

        all_recommendations = {
            "pair_trading": pair_rec,
            "multi_factor": mf_rec,
            "ml_prediction": ml_rec,
        }

        return {
            "success": True,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recommendations": all_recommendations,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
