# API模型定义
# ==========

from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime


# 通用响应模型
class ResponseModel(BaseModel):
    """通用API响应"""

    success: bool
    message: str
    data: Optional[Dict] = None
    timestamp: str


# 策略1: 配对交易
class PairTradingSignal(BaseModel):
    """配对交易信号"""

    a_code: str
    h_code: str
    name: str
    current_premium: float
    premium_ma: float
    premium_std: float
    signal: str  # "buy_ah", "sell_ah", "hold"
    confidence: float
    position_size: float
    zscore: float
    last_updated: str


class PairTradingRecommendation(BaseModel):
    """配对交易推荐结果"""

    strategy: str
    description: str
    generated_at: str
    parameters: Dict
    signals: Dict[str, List[PairTradingSignal]]
    summary: Dict


# 策略2: 多因子
class MultiFactorStock(BaseModel):
    """多因子选股结果"""

    a_code: str
    h_code: str
    name: str
    current_price: float
    total_score: float
    factor_scores: Dict
    last_updated: str


class MultiFactorRecommendation(BaseModel):
    """多因子推荐结果"""

    strategy: str
    description: str
    generated_at: str
    parameters: Dict
    recommendations: List[MultiFactorStock]
    summary: Dict


# 策略3: ML预测
class MLPrediction(BaseModel):
    """ML预测结果"""

    a_code: str
    h_code: str
    name: str
    current_premium: float
    predicted_change: Optional[float]
    predicted_direction: str  # "premium_increase", "premium_decrease", "stable"
    confidence: float
    last_updated: str


class MLRecommendation(BaseModel):
    """ML策略推荐结果"""

    strategy: str
    description: str
    model_type: str
    generated_at: str
    predictions: List[MLPrediction]
    summary: Dict


# 导出
class ExportRequest(BaseModel):
    """导出请求"""

    format: str  # "xlsx", "csv", "pdf"
    data_type: (
        str  # "pair_trading", "multi_factor", "ml_prediction", "etf_trend", "all"
    )
    date: Optional[str] = None


class ExportResponse(BaseModel):
    """导出响应"""

    success: bool
    file_path: Optional[str]
    message: str
    download_url: Optional[str]


# AH股票
class AHStock(BaseModel):
    """AH股票信息"""

    a_code: str
    h_code: str
    name: str
    industry: str
    market_cap: Optional[float]


# 图表数据
class ChartDataPoint(BaseModel):
    """图表数据点"""

    date: str
    value: float


class ChartData(BaseModel):
    """图表数据"""

    title: str
    x_label: str
    y_label: str
    data: List[ChartDataPoint]
