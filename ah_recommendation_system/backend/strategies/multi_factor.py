# 策略2: 多因子Alpha模型选股
# ========================

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import loguru

from ah_recommendation_system.backend.data.ah_stock_list import (
    get_ah_pairs,
    get_stock_name,
)
from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.data.factor_calculator import (
    get_factor_calculator,
)
from ah_recommendation_system.backend.config import STRATEGY_CONFIG

logger = loguru.logger


class MultiFactorStrategy:
    """多因子Alpha模型选股策略"""

    def __init__(self):
        self.config = STRATEGY_CONFIG["multi_factor"]
        self.weights = self.config["factor_weights"]
        self.price_fetcher = get_price_fetcher()
        self.factor_calculator = get_factor_calculator()
        self._ah_pairs = None

    @property
    def ah_pairs(self):
        if self._ah_pairs is None:
            self._ah_pairs = get_ah_pairs()
        return self._ah_pairs

    def calculate_valuation_score(self, stock_info: Dict) -> float:
        """计算估值因子得分"""
        pe = stock_info.get("pe", 15)
        pb = stock_info.get("pb", 2)
        dividend_yield = stock_info.get("dividend_yield", 2)

        pe_score = max(0, min(1, (20 - pe) / 15))
        pb_score = max(0, min(1, (3 - pb) / 2))
        div_score = min(1, dividend_yield / 5)

        return (pe_score + pb_score + div_score) / 3

    def calculate_momentum_score(self, price_df: pd.DataFrame) -> float:
        """计算动量因子得分"""
        if price_df.empty:
            return 0.5

        mom_20d = price_df["close"].pct_change(20).iloc[-1] if len(price_df) > 20 else 0
        mom_score = 0.5 + (mom_20d * 2)

        return max(0, min(1, mom_score))

    def calculate_liquidity_score(self, price_df: pd.DataFrame) -> float:
        """计算流动性因子得分"""
        if price_df.empty or "volume" not in price_df.columns:
            return 0.5

        avg_volume = price_df["volume"].tail(20).mean()
        current_volume = price_df["volume"].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

        return min(1, volume_ratio / 2)

    def calculate_ah_premium_score(self, premium_df: pd.DataFrame) -> float:
        """计算AH溢价因子得分"""
        if premium_df.empty or "premium_pct" not in premium_df.columns:
            return 0.5

        if len(premium_df) < 10:
            return 0.5

        current = premium_df.iloc[-1]["premium_pct"]
        recent = premium_df.tail(20)
        mean = recent["premium_pct"].mean()
        std = recent["premium_pct"].std()

        if std == 0:
            return 0.5

        zscore = abs(current - mean) / std
        return max(0, min(1, 1 - zscore / 3))

    def calculate_composite_score(
        self, stock_info: Dict, price_df: pd.DataFrame, premium_df: pd.DataFrame = None
    ) -> Dict:
        """计算综合得分"""
        valuation = self.calculate_valuation_score(stock_info)
        momentum = self.calculate_momentum_score(price_df)
        liquidity = self.calculate_liquidity_score(price_df)
        ah_premium = (
            self.calculate_ah_premium_score(premium_df)
            if premium_df is not None
            else 0.5
        )

        total_score = (
            valuation * self.weights["valuation"]
            + momentum * self.weights["momentum"]
            + liquidity * self.weights["liquidity"]
            + ah_premium * self.weights["ah_premium"]
        )

        return {
            "total_score": round(total_score, 3),
            "factor_scores": {
                "valuation": round(valuation, 3),
                "momentum": round(momentum, 3),
                "liquidity": round(liquidity, 3),
                "ah_premium": round(ah_premium, 3),
            },
        }

    def analyze_single_stock(self, a_code: str, h_code: str = None) -> Dict:
        """分析单个AH股票"""
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")

            price_df = self.price_fetcher.get_a_share_price(
                a_code, start_date, end_date
            )

            if price_df.empty:
                return {}

            if h_code:
                premium_df = self.price_fetcher.get_ah_premium(
                    a_code, h_code, start_date, end_date
                )
            else:
                premium_df = pd.DataFrame()

            stock_info = {
                "name": get_stock_name(a_code),
                "pe": 12,
                "pb": 1.5,
                "dividend_yield": 3.0,
            }

            scores = self.calculate_composite_score(stock_info, price_df, premium_df)
            latest_price = price_df.iloc[-1]["close"]

            return {
                "a_code": a_code,
                "h_code": h_code or "",
                "name": stock_info["name"],
                "current_price": latest_price,
                "total_score": scores["total_score"],
                "factor_scores": scores["factor_scores"],
                "data_mode": "demo",
                "investment_usable": False,
                "data_warning": "估值使用固定PE/PB/股息率占位，仅供演示排序，不可作为投资依据。",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        except Exception as e:
            logger.error(f"分析 {a_code} 时出错: {e}")
            return {}

    def generate_recommendations(
        self, stock_list: List[str] = None, top_n: int = None
    ) -> Dict:
        """生成多因子推荐列表"""
        if top_n is None:
            top_n = self.config["top_n"]

        if stock_list is None:
            stock_list = list(self.ah_pairs.keys())

        results = []

        for a_code in stock_list:
            h_code = self.ah_pairs.get(a_code, "")
            result = self.analyze_single_stock(a_code, h_code)

            if result:
                results.append(result)

        results.sort(key=lambda x: x["total_score"], reverse=True)

        return {
            "strategy": "多因子Alpha模型",
            "description": "结合估值、动量、流动性和AH溢价的综合因子选股策略",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_mode": "demo",
            "investment_usable": False,
            "data_warning": "估值使用固定PE/PB/股息率占位，仅供演示排序，不可作为投资依据。",
            "parameters": {"factor_weights": self.weights, "top_n": top_n},
            "recommendations": results[:top_n],
            "summary": {
                "total_analyzed": len(results),
                "top_stocks": [s["name"] for s in results[:top_n]],
                "avg_score": round(np.mean([s["total_score"] for s in results]), 3)
                if results
                else 0,
            },
        }


multi_factor_strategy = MultiFactorStrategy()


def get_multi_factor_strategy() -> MultiFactorStrategy:
    return multi_factor_strategy
