# 策略1: AH溢价配对交易策略
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
from ah_recommendation_system.backend.data.quality import assess_price_frame
from ah_recommendation_system.backend.trading.cost_model import DEFAULT_COST_MODEL
from ah_recommendation_system.backend.config import STRATEGY_CONFIG

logger = loguru.logger


class PairTradingStrategy:
    """AH溢价配对交易策略"""

    def __init__(self):
        self.config = STRATEGY_CONFIG["pair_trading"]
        self.price_fetcher = get_price_fetcher()
        self.factor_calculator = get_factor_calculator()
        self._ah_pairs = None

    @property
    def ah_pairs(self):
        if self._ah_pairs is None:
            self._ah_pairs = get_ah_pairs()
        return self._ah_pairs

    def get_signal(
        self, premium_pct: float, premium_ma: float, premium_std: Optional[float] = None
    ) -> str:
        """生成交易信号"""
        upper = self.config["upper_threshold"]
        lower = self.config["lower_threshold"]

        if premium_pct > upper:
            return "sell_ah"
        elif premium_pct < lower:
            return "buy_ah"

        if premium_std and premium_std > 0:
            zscore = (premium_pct - premium_ma) / premium_std

            if zscore > 1.5:
                return "sell_ah"
            elif zscore < -1.5:
                return "buy_ah"

        return "hold"

    def calculate_position_size(
        self, premium_pct: float, premium_ma: float, confidence: float = 0.5
    ) -> float:
        """计算仓位大小"""
        deviation = abs(premium_pct - premium_ma)
        position = min(confidence * (1 + deviation / 50), 1.0)
        return position

    def analyze_single_pair(
        self, a_code: str, h_code: str, lookback: Optional[int] = None
    ) -> Dict:
        """分析单个AH股票对"""
        # Hard guard: never compute premium for a mismatched A/H pair.
        # If mapping exists and caller passes a different H code, skip this pair.
        expected_h = self.ah_pairs.get(a_code)
        if expected_h and h_code and expected_h != h_code:
            logger.warning(
                f"AH pair mismatch for {a_code}: expected {expected_h}, got {h_code}"
            )
            return {}

        lookback_any = (
            lookback
            if lookback is not None
            else self.config.get("premium_lookback", 20)
        )
        if lookback_any is None:
            lookback_any = 20

        try:
            lookback_int = int(lookback_any)
        except Exception:
            lookback_int = 20

        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=lookback_int * 2)).strftime(
                "%Y%m%d"
            )

            premium_df = self.price_fetcher.get_ah_premium(
                a_code, h_code, start_date, end_date
            )

            if premium_df.empty:
                logger.warning(f"无法获取 {a_code}/{h_code} 的数据")
                return {}

            # Data quality checks
            qa_a = assess_price_frame(
                self.price_fetcher.get_a_share_price(a_code, start_date, end_date)
            )
            qa_h = assess_price_frame(
                self.price_fetcher.get_h_share_price(h_code, start_date, end_date)
            )
            data_ok = qa_a.ok and qa_h.ok

            recent_data = premium_df.tail(lookback_int)

            current_premium = float(premium_df.iloc[-1]["premium_pct"])
            premium_mean = float(recent_data["premium_pct"].mean())
            premium_std = float(recent_data["premium_pct"].std())
            premium_max = float(recent_data["premium_pct"].max())
            premium_min = float(recent_data["premium_pct"].min())

            signal = self.get_signal(current_premium, premium_mean, premium_std)

            if premium_std > 0:
                zscore = (current_premium - premium_mean) / premium_std
                confidence = min(abs(zscore) / 3, 1.0)
            else:
                zscore = 0
                confidence = 0.5

            # Transaction cost buffer gating
            est_cost_pct = DEFAULT_COST_MODEL.estimate_round_trip_cost_pct()
            edge_pct = abs(current_premium - premium_mean)

            tradeable = data_ok and (edge_pct >= est_cost_pct)
            block_reason = (
                "ok"
                if tradeable
                else ("data_quality" if not data_ok else "edge_lt_cost")
            )

            if not tradeable:
                signal = "hold"
                confidence = 0.0

            position_size = self.calculate_position_size(
                current_premium, premium_mean, confidence
            )

            fx_col = "hkd_cny" if "hkd_cny" in premium_df.columns else "exchange_rate"
            fx_rate = (
                float(premium_df.iloc[-1][fx_col])
                if fx_col in premium_df.columns
                else None
            )

            return {
                "a_code": a_code,
                "h_code": h_code,
                "name": get_stock_name(a_code),
                "current_premium": round(current_premium, 2),
                "premium_ma": round(premium_mean, 2),
                "premium_std": round(premium_std, 2),
                "premium_max": round(premium_max, 2),
                "premium_min": round(premium_min, 2),
                "signal": signal,
                "confidence": round(confidence, 2),
                "position_size": round(position_size, 2),
                "zscore": round(zscore, 2) if premium_std > 0 else 0,
                "fx_rate": fx_rate,
                "estimated_round_trip_cost_pct": round(est_cost_pct, 3),
                "edge_vs_mean_pct": round(edge_pct, 3),
                "tradeable": tradeable,
                "block_reason": block_reason,
                "data_quality": {"a": qa_a.to_dict(), "h": qa_h.to_dict()},
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        except Exception as e:
            logger.error(f"分析 {a_code}/{h_code} 时出错: {e}")
            return {}

    def generate_recommendations(
        self,
        stock_list: Optional[List[str]] = None,
        max_positions: Optional[int] = None,
    ) -> Dict:
        """生成推荐列表"""
        if max_positions is None:
            max_positions = self.config["max_positions"]

        if stock_list is None:
            stock_list = list(self.ah_pairs.keys())

        recommendations = {
            "strategy": "AH溢价配对交易",
            "description": "基于AH溢价率历史均值回归的配对交易策略",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "parameters": {
                "lookback_period": self.config["premium_lookback"],
                "upper_threshold": self.config["upper_threshold"],
                "lower_threshold": self.config["lower_threshold"],
            },
            "signals": {"buy_ah": [], "sell_ah": [], "hold": []},
            "summary": {},
        }

        buy_signals = []
        sell_signals = []
        hold_signals = []

        skipped_pairs = 0

        for a_code in stock_list:
            h_code = self.ah_pairs.get(a_code, "")

            if not h_code:
                # Do not guess pairs: guessing can pair different companies and create absurd premiums.
                skipped_pairs += 1
                continue

            result = self.analyze_single_pair(a_code, h_code)

            if result:
                signal = result["signal"]

                if signal == "buy_ah":
                    buy_signals.append(result)
                elif signal == "sell_ah":
                    sell_signals.append(result)
                else:
                    hold_signals.append(result)

        buy_signals.sort(key=lambda x: x["confidence"], reverse=True)
        sell_signals.sort(key=lambda x: x["confidence"], reverse=True)

        recommendations["signals"]["buy_ah"] = buy_signals[:max_positions]
        recommendations["signals"]["sell_ah"] = sell_signals[:max_positions]
        recommendations["signals"]["hold"] = hold_signals[:max_positions]

        recommendations["summary"] = {
            "total_analyzed": len(buy_signals) + len(sell_signals) + len(hold_signals),
            "buy_signals": len(buy_signals),
            "sell_signals": len(sell_signals),
            "hold_signals": len(hold_signals),
            "skipped_pairs": skipped_pairs,
            "top_buy": [s["name"] for s in buy_signals[:3]] if buy_signals else [],
            "top_sell": [s["name"] for s in sell_signals[:3]] if sell_signals else [],
        }

        return recommendations

    def _guess_h_code(self, a_code: str) -> str:
        """猜测H股代码"""
        h_map = {
            "601398.SH": "1398.HK",
            "601988.SH": "3988.HK",
            "601939.SH": "0939.HK",
            "601288.SH": "1288.HK",
            "600028.SH": "0386.HK",
            "002594.SZ": "1211.HK",
            "600030.SH": "6030.HK",
            "601318.SH": "2318.HK",
            "601628.SH": "2628.HK",
            "601088.SH": "1088.HK",
        }
        return h_map.get(a_code, "")


pair_trading_strategy = PairTradingStrategy()


def get_pair_trading_strategy() -> PairTradingStrategy:
    return pair_trading_strategy
