# AH股每日推荐系统配置文件
# ============================

# 数据配置
DATA_CONFIG = {
    # A股市场 (上海: sh, 深圳: sz)
    "a_share_market": ["sh", "sz"],
    # AH股票列表URL (AKShare)
    "ah_stock_list_url": "stock_ah_spot_em",
    # 默认市值门槛 (亿元)
    "market_cap_threshold": 500,
}

# 策略配置
STRATEGY_CONFIG = {
    # 策略1: AH溢价配对交易
    "pair_trading": {
        # 溢价率历史均值窗口 (交易日)
        "premium_lookback": 20,
        # 触发阈值 (%)
        "upper_threshold": 1.15,   # 溢价率高于此值 → 卖A买H
        "lower_threshold": 0.85,   # 溢价率低于此值 → 买A卖H
        # 最大持仓股票数
        "max_positions": 10,
    },
    
    # 策略2: 多因子Alpha模型
    "multi_factor": {
        # 因子权重
        "factor_weights": {
            "valuation": 0.25,      # 估值因子
            "momentum": 0.25,       # 动量因子
            "liquidity": 0.20,      # 流动性因子
            "ah_premium": 0.30,     # AH溢价因子
        },
        # 评分窗口
        "score_window": 20,
        # 选股数量
        "top_n": 10,
    },
    
    # 策略3: ML预测
    "ml_predictor": {
        # 模型类型
        "model_type": "xgboost",
        # 训练数据窗口 (天)
        "train_window": 365,
        # 预测窗口
        "predict_horizon": 5,
        # 特征列表
        "features": [
            "premium_ma5", "premium_ma10", "premium_ma20",
            "volume_ratio", "price_volatility",
            "rsi_14", "macd", "boll_position",
        ],
    },
}

# 数据库配置
DATABASE_CONFIG = {
    "database": "sqlite:///data/ah_recommendation.db",
    "echo": False,
}

# Redis配置 (可选)
REDIS_CONFIG = {
    "host": "localhost",
    "port": 6379,
    "db": 0,
}

# 定时任务配置
SCHEDULER_CONFIG = {
    # 每日运行时间 (HH:MM)
    "daily_run_time": "18:30",
    # 时区
    "timezone": "Asia/Shanghai",
}

# 导出配置
EXPORT_CONFIG = {
    # 导出目录
    "export_dir": "data/exports",
    # 导出格式
    "formats": ["xlsx", "csv", "pdf"],
}

# 日志配置
LOGGING_CONFIG = {
    "level": "INFO",
    "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    "file": "logs/ah_recommendation.log",
}
