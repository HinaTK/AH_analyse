# 策略3: 机器学习预测AH溢价
# ======================

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from loguru import logger
import joblib
import os

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ah_recommendation_system.backend.data.ah_stock_list import (
    get_ah_pairs,
    get_stock_name,
)
from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
from ah_recommendation_system.backend.data.factor_calculator import (
    get_factor_calculator,
)
from ah_recommendation_system.backend.config import STRATEGY_CONFIG

try:
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import mean_squared_error, r2_score

    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("ML库未安装，将使用简化版预测")


class MLPredictorStrategy:
    """机器学习预测AH溢价策略"""

    def __init__(self):
        self.config = STRATEGY_CONFIG["ml_predictor"]
        self.model_type = self.config["model_type"]
        self.features = self.config["features"]
        self.price_fetcher = get_price_fetcher()
        self.factor_calculator = get_factor_calculator()
        self.model_dir = "data/models"
        self._ensure_dir(self.model_dir)
        self._ah_pairs = None

    @property
    def ah_pairs(self):
        if self._ah_pairs is None:
            self._ah_pairs = get_ah_pairs()
        return self._ah_pairs

    def _ensure_dir(self, path: str):
        os.makedirs(path, exist_ok=True)

    def create_features(
        self, price_df: pd.DataFrame, premium_df: pd.DataFrame
    ) -> pd.DataFrame:
        """创建机器学习特征"""
        if price_df.empty:
            return pd.DataFrame()

        features = pd.DataFrame()
        features["close"] = price_df["close"]
        features["volume"] = price_df.get("volume", 0)

        for period in [5, 10, 20]:
            if len(price_df) > period:
                features[f"momentum_{period}d"] = (
                    price_df["close"] / price_df["close"].shift(period) - 1
                )

        delta = price_df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        features["rsi_14"] = 100 - (100 / (1 + rs))

        ema_12 = price_df["close"].ewm(span=12, adjust=False).mean()
        ema_26 = price_df["close"].ewm(span=26, adjust=False).mean()
        features["macd"] = ema_12 - ema_26

        sma_20 = price_df["close"].rolling(window=20).mean()
        std_20 = price_df["close"].rolling(window=20).std()
        upper = sma_20 + (2 * std_20)
        lower = sma_20 - (2 * std_20)
        features["boll_position"] = (price_df["close"] - lower) / (upper - lower)

        avg_volume = price_df["volume"].rolling(window=20).mean()
        features["volume_ratio"] = price_df["volume"] / avg_volume

        returns = price_df["close"].pct_change()
        features["volatility"] = returns.rolling(window=20).std()

        if premium_df is not None and not premium_df.empty:
            features["premium_pct"] = premium_df["premium_pct"]

            for period in [5, 10, 20]:
                if len(premium_df) > period:
                    features[f"premium_ma{period}d"] = (
                        premium_df["premium_pct"].rolling(window=period).mean()
                    )

            features["premium_momentum"] = premium_df["premium_pct"] - premium_df[
                "premium_pct"
            ].shift(5)

        return features.dropna()

    def prepare_data(self, a_code: str, h_code: str) -> Tuple[pd.DataFrame, pd.Series]:
        """准备训练数据"""
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (
            datetime.now() - timedelta(days=self.config["train_window"] * 2)
        ).strftime("%Y%m%d")

        price_df = self.price_fetcher.get_a_share_price(a_code, start_date, end_date)

        if price_df.empty:
            return None, None

        premium_df = self.price_fetcher.get_ah_premium(
            a_code, h_code, start_date, end_date
        )
        features = self.create_features(price_df, premium_df)

        if features.empty or "premium_pct" not in features.columns:
            return None, None

        future_days = self.config["predict_horizon"]

        if len(features) <= future_days:
            return None, None

        target = features["premium_pct"].shift(-future_days) - features["premium_pct"]
        target = target.dropna()

        features = features.iloc[: len(target)]

        return features, target

    def train_model(self, a_code: str, h_code: str) -> Optional[object]:
        """训练单个股票的预测模型"""
        if not ML_AVAILABLE:
            return None

        features, target = self.prepare_data(a_code, h_code)

        if features is None or target is None:
            return None

        try:
            split = int(len(features) * 0.8)
            horizon = int(self.config.get("predict_horizon") or 0)
            train_end = max(1, split - max(0, horizon))
            if train_end >= len(features) or train_end < 2:
                return None
            X_train = features.iloc[:train_end]
            y_train = target.iloc[:train_end]
            X_test = features.iloc[split:]
            y_test = target.iloc[split:]
            if X_test.empty or y_test.empty:
                return None

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)

            if self.model_type == "xgboost":
                model = GradientBoostingRegressor(
                    n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42
                )
            else:
                model = RandomForestRegressor(
                    n_estimators=100, max_depth=10, random_state=42
                )

            model.fit(X_train_scaled, y_train)

            y_pred = model.predict(X_test_scaled)
            mse = mean_squared_error(y_test, y_pred)
            r2 = r2_score(y_test, y_pred)

            logger.info(f"{a_code}: MSE={mse:.4f}, R2={r2:.4f}")

            model_path = f"{self.model_dir}/{a_code.replace('.', '_')}.joblib"
            joblib.dump({"model": model, "scaler": scaler}, model_path)

            return model

        except Exception as e:
            logger.error(f"训练模型失败 {a_code}: {e}")
            return None

    def load_model(self, a_code: str) -> Optional[Dict]:
        """加载已训练的模型"""
        model_path = f"{self.model_dir}/{a_code.replace('.', '_')}.joblib"

        if os.path.exists(model_path):
            try:
                return joblib.load(model_path)
            except Exception as e:
                logger.warning(f"加载模型失败 {a_code}: {e}")

        return None

    def predict(self, a_code: str, h_code: str) -> Dict:
        """预测未来AH溢价走势"""
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")

            price_df = self.price_fetcher.get_a_share_price(
                a_code, start_date, end_date
            )

            if price_df.empty:
                return {}

            premium_df = self.price_fetcher.get_ah_premium(
                a_code, h_code, start_date, end_date
            )
            features = self.create_features(price_df, premium_df)

            if features.empty:
                return {}

            current_premium = (
                premium_df.iloc[-1]["premium_pct"] if not premium_df.empty else 0
            )

            prediction = {
                "a_code": a_code,
                "h_code": h_code,
                "name": get_stock_name(a_code),
                "current_premium": round(current_premium, 2),
            }

            model_data = self.load_model(a_code)

            if model_data:
                try:
                    model = model_data["model"]
                    scaler = model_data["scaler"]
                    latest_features = scaler.transform(features.tail(1))
                    future_change = model.predict(latest_features)[0]

                    if future_change > 1:
                        signal = "premium_increase"
                    elif future_change < -1:
                        signal = "premium_decrease"
                    else:
                        signal = "stable"

                    prediction.update(
                        {
                            "predicted_change": round(future_change, 2),
                            "predicted_direction": signal,
                            "confidence": min(abs(future_change) / 3, 1.0),
                            "prediction_method": "trained_model",
                            "confidence_kind": "scaled_magnitude_not_probability",
                            "investment_usable": False,
                            "data_warning": "置信度由预测幅度缩放得到，不是胜率或校准概率。",
                        }
                    )
                except Exception as e:
                    logger.warning(f"预测失败 {a_code}: {e}")

            if "predicted_direction" not in prediction:
                recent = premium_df.tail(10)
                if len(recent) >= 5:
                    trend = (
                        recent["premium_pct"].iloc[-1] - recent["premium_pct"].iloc[0]
                    )

                    if trend > 2:
                        prediction["predicted_direction"] = "premium_increase"
                    elif trend < -2:
                        prediction["predicted_direction"] = "premium_decrease"
                    else:
                        prediction["predicted_direction"] = "stable"
                    prediction["predicted_change"] = round(trend, 2)
                    prediction["confidence"] = 0.5
                    prediction["prediction_method"] = "premium_trend_fallback"
                    prediction["confidence_kind"] = "fixed_rule_not_probability"
                    prediction["investment_usable"] = False
                    prediction["data_warning"] = "无可用模型，已回退近期溢价趋势规则；固定置信度不是胜率。"
                else:
                    prediction["predicted_direction"] = "unknown"
                    prediction["confidence"] = 0.3
                    prediction["prediction_method"] = "insufficient_history_fallback"
                    prediction["confidence_kind"] = "fixed_rule_not_probability"
                    prediction["investment_usable"] = False
                    prediction["data_warning"] = "样本不足，使用固定规则置信度，不是胜率。"

            prediction["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return prediction

        except Exception as e:
            logger.error(f"预测 {a_code} 时出错: {e}")
            return {}

    def generate_recommendations(self, stock_list: List = None) -> Dict:
        """生成ML预测推荐"""
        if stock_list is None:
            stock_list = list(self.ah_pairs.items())

        predictions = []

        for a_code, h_code in stock_list:
            if not h_code:
                continue

            result = self.predict(a_code, h_code)

            if result:
                predictions.append(result)

        predictions.sort(key=lambda x: x.get("confidence", 0), reverse=True)

        return {
            "strategy": "机器学习预测",
            "description": "基于机器学习或规则回退预测AH溢价率未来走势；输出仅供研究，不代表胜率。",
            "model_type": self.model_type,
            "investment_usable": False,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "predictions": predictions[:20],
            "summary": {
                "total_analyzed": len(predictions),
                "premium_increase": len(
                    [
                        p
                        for p in predictions
                        if p.get("predicted_direction") == "premium_increase"
                    ]
                ),
                "premium_decrease": len(
                    [
                        p
                        for p in predictions
                        if p.get("predicted_direction") == "premium_decrease"
                    ]
                ),
                "stable": len(
                    [p for p in predictions if p.get("predicted_direction") == "stable"]
                ),
            },
        }


ml_predictor_strategy = MLPredictorStrategy()


def get_ml_predictor_strategy() -> MLPredictorStrategy:
    return ml_predictor_strategy
