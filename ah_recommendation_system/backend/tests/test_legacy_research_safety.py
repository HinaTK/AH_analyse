"""Offline behavioral tests; execute production classes without module singletons."""
import ast
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def strategy_class(filename, name, **extra):
    source = (ROOT / "backend/strategies" / filename).read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == name)
    scope = dict(
        pd=pd,
        np=np,
        datetime=datetime,
        timedelta=timedelta,
        Dict=dict,
        List=list,
        Optional=__import__("typing").Optional,
        Tuple=__import__("typing").Tuple,
        get_stock_name=lambda c: c,
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
        os=__import__("os"),
        joblib=SimpleNamespace(dump=lambda *a, **k: None, load=lambda *a, **k: None),
        ML_AVAILABLE=True,
        StandardScaler=__import__("sklearn.preprocessing", fromlist=["StandardScaler"]).StandardScaler,
        RandomForestRegressor=__import__("sklearn.ensemble", fromlist=["RandomForestRegressor"]).RandomForestRegressor,
        GradientBoostingRegressor=__import__("sklearn.ensemble", fromlist=["GradientBoostingRegressor"]).GradientBoostingRegressor,
        mean_squared_error=lambda *a, **k: 0.0,
        r2_score=lambda *a, **k: 0.0,
    )
    scope.update(extra)
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), scope)
    return scope[name]


def frontend_fmt_source():
    source = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    start = source.index("fmt(v) {")
    i = start + len("fmt(v) ")
    depth = 0
    for j, ch in enumerate(source[i:], i):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[i : j + 1]
    raise AssertionError("fmt() body not found")


def frontend_fmt(body=None):
    body = body or frontend_fmt_source()
    code = (
        "const fmt = function(v) "
        + body
        + "; console.log(JSON.stringify({null:fmt(null), empty:fmt(''), num:fmt(1.5)}))"
    )
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


class LegacyResearchSafetyTests(unittest.TestCase):
    def test_fixed_valuation_is_demo_at_row_and_payload(self):
        cls = strategy_class("multi_factor.py", "MultiFactorStrategy")
        strategy = cls.__new__(cls)
        strategy.config = {"top_n": 1}
        strategy.weights = dict(valuation=0.25, momentum=0.25, liquidity=0.25, ah_premium=0.25)
        strategy._ah_pairs = {"A": "H"}
        strategy.price_fetcher = SimpleNamespace(
            get_a_share_price=lambda *a: pd.DataFrame({"close": range(1, 31), "volume": [100] * 30}),
            get_ah_premium=lambda *a: pd.DataFrame({"premium_pct": range(30)}),
        )
        result = strategy.generate_recommendations(["A"])
        for payload in [result, result["recommendations"][0]]:
            self.assertEqual(payload.get("data_mode"), "demo")
            self.assertIs(payload.get("investment_usable"), False)
            self.assertIn("PE/PB", payload.get("data_warning", ""))
        self.assertIn("total_score", result["recommendations"][0])

    def test_ml_fallback_is_labelled_non_probability(self):
        cls = strategy_class("ml_predictor.py", "MLPredictorStrategy")
        strategy = cls.__new__(cls)
        strategy.config = {"predict_horizon": 5, "train_window": 60, "model_type": "rf", "features": []}
        strategy.model_type = "rf"
        strategy.price_fetcher = SimpleNamespace(
            get_a_share_price=lambda *a: pd.DataFrame({"close": list(range(1, 40)), "volume": [100] * 39}),
            get_ah_premium=lambda *a: pd.DataFrame({"premium_pct": list(range(39))}),
        )
        strategy.create_features = lambda price_df, premium_df: pd.DataFrame({"premium_pct": premium_df["premium_pct"]})
        with patch.object(cls, "load_model", return_value=None):
            prediction = strategy.predict("A", "H")
        self.assertEqual(prediction["prediction_method"], "premium_trend_fallback")
        self.assertEqual(prediction["confidence_kind"], "fixed_rule_not_probability")
        self.assertIs(prediction["investment_usable"], False)

    def test_frontend_missing_return_is_pending_not_zero(self):
        formatted = frontend_fmt()
        self.assertEqual(formatted["null"], "待验证")
        self.assertEqual(formatted["empty"], "待验证")
        self.assertEqual(formatted["num"], "+1.50%")

    def test_frontend_fmt_extracts_nested_object_body(self):
        nested = "{ if (v === null) { return '待验证' } const n = Number(v); return Number.isFinite(n) ? n.toFixed(2) + '%' : '待验证' }"
        formatted = frontend_fmt(nested)
        self.assertEqual(formatted["null"], "待验证")
        self.assertEqual(formatted["num"], "1.50%")

    def test_frontend_no_longer_claims_static_demo_mode(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        self.assertNotIn("模式: <span class=\"mono\">演示/模拟</span>", html)
        self.assertIn("按模块核对来源/时间", html)
        self.assertIn("行情口径", html)

    def test_premarket_page_is_a_decision_card_not_a_quote_table(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        self.assertIn("盘前决策卡", html)
        self.assertIn("现在能不能用", html)
        self.assertIn("市场环境", html)
        self.assertIn("当前主攻", html)
        self.assertIn("1~3个月方向", html)
        self.assertIn("回避 / 撤退", html)
        self.assertIn("触发条件 / 否定条件", html)
        self.assertNotIn("今日盘前推荐", html)
        self.assertNotIn("p.rationale", html)


if __name__ == "__main__":
    unittest.main()
