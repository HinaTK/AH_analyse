# 因子计算模块
# ============

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from loguru import logger


class FactorCalculator:
    """因子计算器"""
    
    def __init__(self):
        pass
    
    # ==================== 估值因子 ====================
    
    def calculate_pe_ratio(self, price_df: pd.DataFrame, 
                          earnings_df: pd.DataFrame = None) -> pd.Series:
        """计算市盈率因子"""
        if price_df.empty or "close" not in price_df.columns:
            return pd.Series()
        
        pe = price_df["close"] / 10  # 简化处理，实际应使用财报EPS
        return pe
    
    def calculate_pb_ratio(self, price_df: pd.DataFrame,
                          book_value: float = None) -> pd.Series:
        """计算市净率因子"""
        if price_df.empty:
            return pd.Series()
        
        if book_value:
            pb = price_df["close"] / book_value
        else:
            pb = price_df["close"] / 5  # 默认账面价值
        return pb
    
    def calculate_dividend_yield(self, price_df: pd.DataFrame,
                                 dividend: float = None) -> pd.Series:
        """计算股息率因子"""
        if price_df.empty or not dividend:
            return pd.Series()
        
        dividend_yield = dividend / price_df["close"] * 100
        return dividend_yield
    
    # ==================== 动量因子 ====================
    
    def calculate_momentum(self, price_df: pd.DataFrame, 
                           periods: List[int] = [5, 10, 20]) -> Dict[str, pd.Series]:
        """计算动量因子"""
        if price_df.empty or "close" not in price_df.columns:
            return {}
        
        momentum = {}
        for period in periods:
            momentum[f"momentum_{period}d"] = (
                price_df["close"] / price_df["close"].shift(period) - 1
            ) * 100
        
        return momentum
    
    def calculate_rsi(self, price_df: pd.DataFrame, 
                     period: int = 14) -> pd.Series:
        """计算RSI指标"""
        if price_df.empty or "close" not in price_df.columns:
            return pd.Series()
        
        delta = price_df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_macd(self, price_df: pd.DataFrame,
                       fast: int = 12, slow: int = 26, 
                       signal: int = 9) -> Dict[str, pd.Series]:
        """计算MACD指标"""
        if price_df.empty or "close" not in price_df.columns:
            return {}
        
        ema_fast = price_df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = price_df["close"].ewm(span=slow, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        macd_histogram = macd_line - signal_line
        
        return {
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": macd_histogram
        }
    
    def calculate_bollinger_bands(self, price_df: pd.DataFrame,
                                  period: int = 20, 
                                  std_dev: int = 2) -> Dict[str, pd.Series]:
        """计算布林带"""
        if price_df.empty or "close" not in price_df.columns:
            return {}
        
        sma = price_df["close"].rolling(window=period).mean()
        std = price_df["close"].rolling(window=period).std()
        
        upper_band = sma + (std_dev * std)
        lower_band = sma - (std_dev * std)
        
        # 布林带位置 (0-1之间，越接近1表示越接近上轨)
        bbp = (price_df["close"] - lower_band) / (upper_band - lower_band)
        
        return {
            "bb_upper": upper_band,
            "bb_middle": sma,
            "bb_lower": lower_band,
            "bbp": bbp
        }
    
    # ==================== 流动性因子 ====================
    
    def calculate_volume_ratio(self, price_df: pd.DataFrame,
                               period: int = 20) -> pd.Series:
        """计算量比"""
        if price_df.empty or "volume" not in price_df.columns:
            return pd.Series()
        
        avg_volume = price_df["volume"].rolling(window=period).mean()
        volume_ratio = price_df["volume"] / avg_volume
        
        return volume_ratio
    
    def calculate_turnover_rate(self, price_df: pd.DataFrame,
                                market_cap: float = None) -> pd.Series:
        """计算换手率"""
        if price_df.empty or "volume" not in price_df.columns:
            return pd.Series()
        
        # 简化计算
        turnover = price_df["volume"] / 1000000 * 100  # 假设流通股数
        return turnover
    
    # ==================== AH溢价因子 ====================
    
    def calculate_ah_premium_ma(self, premium_df: pd.DataFrame,
                               periods: List[int] = [5, 10, 20]) -> Dict[str, pd.Series]:
        """计算AH溢价率移动平均"""
        if premium_df.empty or "premium_pct" not in premium_df.columns:
            return {}
        
        premium_ma = {}
        for period in periods:
            premium_ma[f"premium_ma{period}d"] = (
                premium_df["premium_pct"].rolling(window=period).mean()
            )
        
        return premium_ma
    
    def calculate_premium_zscore(self, premium_df: pd.DataFrame,
                                period: int = 20) -> pd.Series:
        """计算AH溢价率Z分数"""
        if premium_df.empty or "premium_pct" not in premium_df.columns:
            return pd.Series()
        
        rolling_mean = premium_df["premium_pct"].rolling(window=period).mean()
        rolling_std = premium_df["premium_pct"].rolling(window=period).std()
        
        zscore = (premium_df["premium_pct"] - rolling_mean) / rolling_std
        
        return zscore
    
    def calculate_premium_momentum(self, premium_df: pd.DataFrame,
                                  periods: List[int] = [5, 10]) -> Dict[str, pd.Series]:
        """计算AH溢价率动量"""
        if premium_df.empty or "premium_pct" not in premium_df.columns:
            return {}
        
        momentum = {}
        for period in periods:
            momentum[f"premium_mom{period}d"] = (
                premium_df["premium_pct"] - premium_df["premium_pct"].shift(period)
            )
        
        return momentum
    
    # ==================== 波动率因子 ====================
    
    def calculate_volatility(self, price_df: pd.DataFrame,
                            period: int = 20) -> pd.Series:
        """计算历史波动率"""
        if price_df.empty or "close" not in price_df.columns:
            return pd.Series()
        
        returns = price_df["close"].pct_change()
        volatility = returns.rolling(window=period).std() * np.sqrt(252) * 100
        
        return volatility
    
    # ==================== 综合因子计算 ====================
    
    def calculate_all_factors(self, 
                             price_df: pd.DataFrame,
                             premium_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        计算所有因子
        返回包含所有因子的DataFrame
        """
        if price_df.empty:
            return pd.DataFrame()
        
        factors = pd.DataFrame(index=price_df.index)
        factors["close"] = price_df["close"]
        factors["volume"] = price_df.get("volume", 0)
        factors["date"] = price_df["date"]
        
        # 动量因子
        momentum = self.calculate_momentum(price_df)
        for key, value in momentum.items():
            factors[key] = value
        
        # RSI
        factors["rsi_14"] = self.calculate_rsi(price_df, 14)
        
        # MACD
        macd = self.calculate_macd(price_df)
        for key, value in macd.items():
            factors[key] = value
        
        # 布林带
        bb = self.calculate_bollinger_bands(price_df)
        for key, value in bb.items():
            factors[key] = value
        
        # 量比
        factors["volume_ratio"] = self.calculate_volume_ratio(price_df)
        
        # 波动率
        factors["volatility"] = self.calculate_volatility(price_df)
        
        # AH溢价因子
        if premium_df is not None and not premium_df.empty:
            premium_merged = pd.merge(
                price_df[["date"]], 
                premium_df[["date", "premium_pct"]], 
                on="date", 
                how="left"
            ).set_index(price_df.index)
            
            factors["premium_pct"] = premium_merged["premium_pct"]
            
            # 溢价MA
            premium_ma = self.calculate_ah_premium_ma(premium_df)
            for key, value in premium_ma.items():
                factors[key] = value
            
            # 溢价Z分数
            factors["premium_zscore"] = self.calculate_premium_zscore(premium_df)
            
            # 溢价动量
            premium_mom = self.calculate_premium_momentum(premium_df)
            for key, value in premium_mom.items():
                factors[key] = value
        
        return factors
    
    def get_latest_factors(self, 
                          price_df: pd.DataFrame,
                          premium_df: pd.DataFrame = None) -> Dict:
        """获取最新一期的因子值"""
        factors = self.calculate_all_factors(price_df, premium_df)
        
        if factors.empty:
            return {}
        
        latest = factors.iloc[-1]
        return latest.to_dict()


# 全局实例
factor_calculator = FactorCalculator()


def get_factor_calculator() -> FactorCalculator:
    return factor_calculator
