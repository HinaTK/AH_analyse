# AH股每日推荐系统

## 概述

AH股每日推荐系统是一个量化投资工具，提供三种策略的AH股票推荐：
1. **AH溢价配对交易** - 基于AH溢价率历史均值回归
2. **多因子Alpha模型** - 综合估值、动量、流动性因子
3. **机器学习预测** - 用ML预测AH溢价走势

## 技术栈

- **后端**: FastAPI + Python 3.10+
- **数据**: AKShare (免费A股/港股数据)
- **前端**: Vue.js 3 + TailwindCSS + ECharts
- **ML**: scikit-learn / XGBoost
- **调度**: APScheduler

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 启动后端服务

```bash
cd backend
python main.py
```

服务运行在 `http://localhost:8000`

### 3. 启动定时任务 (可选)

```bash
python -m scheduler.daily_job
```

### 4. 访问Web界面

打开浏览器访问 `http://localhost:8000`

## API文档

### 策略端点

| 端点 | 说明 |
|-----|------|
| GET /api/v1/pair-trading | AH溢价配对交易推荐 |
| GET /api/v1/multi-factor | 多因子Alpha模型推荐 |
| GET /api/v1/ml-prediction | ML预测推荐 |
| GET /api/v1/comparison | 所有策略对比 |
| GET /api/v1/stocks | AH股票列表 |

### 导出端点

| 端点 | 说明 |
|-----|------|
| POST /api/v1/export | 导出数据 (xlsx/csv/pdf) |
| GET /api/v1/export/download/{file} | 下载导出文件 |

## 策略说明

### 1. AH溢价配对交易

**逻辑**: 当AH溢价率偏离历史均值时，做空高估方，做多低估方

**参数**:
- 回溯期: 20交易日
- 上限阈值: 1.15 (15%溢价)
- 下限阈值: 0.85 (15%折价)

**信号**:
- `buy_ah`: 买入A股，做空H股
- `sell_ah`: 做空A股，买入H股
- `hold`: 持有

### 2. 多因子Alpha模型

**因子**:
- 估值因子 (25%): PE、PB、股息率
- 动量因子 (25%): N日收益率
- 流动性因子 (20%): 量比、换手率
- AH溢价因子 (30%): 溢价率偏离度

### 3. 机器学习预测

**模型**: Gradient Boosting / Random Forest

**特征**:
- 动量指标 (5/10/20日)
- RSI、MACD、布林带
- 量比、波动率
- AH溢价历史数据

## 配置

编辑 `backend/config.py` 可修改:

```python
STRATEGY_CONFIG = {
    "pair_trading": {
        "premium_lookback": 20,
        "upper_threshold": 1.15,
        "lower_threshold": 0.85,
    },
    # ...
}
```

## 目录结构

```
ah_recommendation_system/
├── backend/
│   ├── api/
│   │   ├── models.py       # Pydantic数据模型
│   │   ├── strategy_routes.py
│   │   ├── export_routes.py
│   │   └── stock_routes.py
│   ├── strategies/
│   │   ├── pair_trading.py    # 策略1: 配对交易
│   │   ├── multi_factor.py    # 策略2: 多因子
│   │   └── ml_predictor.py   # 策略3: ML预测
│   ├── data/
│   │   ├── ah_stock_list.py   # AH股票列表
│   │   ├── price_fetcher.py   # 价格数据获取
│   │   └── factor_calculator.py  # 因子计算
│   ├── scheduler/
│   │   └── daily_job.py       # 定时任务
│   ├── config.py              # 配置
│   ├── main.py               # FastAPI入口
│   └── requirements.txt       # 依赖
├── frontend/
│   └── index.html            # Web界面
└── README.md
```

## 免责声明

本系统仅供研究和学习使用，不构成投资建议。投资者应自行承担投资风险。

## License

MIT
