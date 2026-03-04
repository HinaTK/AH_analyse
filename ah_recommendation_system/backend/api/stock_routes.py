# AH股基础信息API
# =============

from fastapi import APIRouter, HTTPException
from typing import List, Dict

from ah_recommendation_system.backend.api.models import ResponseModel, AHStock
from ah_recommendation_system.backend.data.ah_stock_list import (
    get_ah_stock_list,
    get_ah_pairs,
    get_stock_name,
    get_stock_industry,
    get_active_ah_stocks,
    filter_by_market_cap,
)

router = APIRouter(prefix="/api/v1/stocks", tags=["stocks"])


@router.get("/", response_model=dict)
async def get_ah_stocks(min_market_cap: float = 0):
    """获取AH股票列表"""
    try:
        stocks = get_active_ah_stocks()

        if min_market_cap > 0:
            stocks = [s for s in stocks if s.get("market_cap", 0) >= min_market_cap]

        return {"success": True, "count": len(stocks), "stocks": stocks}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pairs", response_model=dict)
async def get_stock_pairs():
    """获取AH股票对应关系"""
    try:
        pairs = get_ah_pairs()

        result = []
        for a_code, h_code in pairs.items():
            result.append(
                {
                    "a_code": a_code,
                    "h_code": h_code,
                    "name": get_stock_name(a_code),
                    "industry": get_stock_industry(a_code),
                }
            )

        return {"success": True, "pairs": result, "count": len(result)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{a_code}", response_model=dict)
async def get_stock_info(a_code: str):
    """获取单个AH股票信息"""
    try:
        pairs = get_ah_pairs()
        h_code = pairs.get(a_code, "")

        if not h_code:
            raise HTTPException(status_code=404, detail="股票未找到")

        return {
            "success": True,
            "stock": {
                "a_code": a_code,
                "h_code": h_code,
                "name": get_stock_name(a_code),
                "industry": get_stock_industry(a_code),
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry/summary")
async def get_industry_summary():
    """获取AH股票行业分布"""
    try:
        pairs = get_ah_pairs()

        industry_count = {}
        for a_code in pairs.keys():
            industry = get_stock_industry(a_code)
            industry_count[industry] = industry_count.get(industry, 0) + 1

        return {
            "success": True,
            "summary": {"total_stocks": len(pairs), "by_industry": industry_count},
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
