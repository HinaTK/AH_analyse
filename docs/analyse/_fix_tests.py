from pathlib import Path
p = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/tests/test_recommendation_display_repairs.py")
t = p.read_text(encoding="utf-8")
old = '''    def test_incomplete_last_tick_is_not_used_as_liquidity(self):
        from ah_recommendation_system.backend.stock_recommend.run import _apply_daily_feature_row

        row = {"code": "002142", "amount": 5_489_565.0}
        bars = [
            {"date": "2026-09-08", "open": 34, "high": 35, "low": 33, "close": 34.66, "volume": 17_425_068, "amount": 604_176_357},
            {"date": "2026-09-09", "open": 34, "high": 36, "low": 34, "close": 35.87, "volume": 44_975_091, "amount": 1_602_459_052},
            {"date": "2026-09-10", "open": 35.95, "high": 36.0, "low": 35.38, "close": 35.59, "volume": 152_700, "amount": 5_489_565},
        ]
        self.assertTrue(_apply_daily_feature_row(row, bars))
        self.assertEqual(row["amount"], 1_602_459_052)
        self.assertEqual(row["amount_reference"], "latest_completed_daily_bar")

    def test_zero_or_premarket_amount_is_treated_as_missing_for_supplement(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import merge_quote_fields

        primary = {"price": 35.95, "change_pct": 0.22, "amount": 5_489_565.0, "volume": 152700, "pe": 7.6}
        secondary = {"amount": 1_602_459_052.49, "volume": 44_975_091, "pe": 7.2}
        filled = merge_quote_fields(primary, secondary)
        self.assertIn("amount", filled)
        self.assertEqual(primary["amount"], 1_602_459_052.49)
        self.assertEqual(primary["pe"], 7.6)
'''
new = '''    def test_incomplete_last_tick_is_not_used_as_liquidity(self):
        from unittest.mock import patch
        from ah_recommendation_system.backend.stock_recommend.run import _apply_daily_feature_row

        row = {"code": "002142", "amount": 5_489_565.0}
        bars = [
            {"date": "2026-09-08", "open": 34, "high": 35, "low": 33, "close": 34.66, "volume": 17_425_068, "amount": 604_176_357},
            {"date": "2026-09-09", "open": 34, "high": 36, "low": 34, "close": 35.87, "volume": 44_975_091, "amount": 1_602_459_052},
            {"date": "2026-09-10", "open": 35.95, "high": 36.0, "low": 35.38, "close": 35.59, "volume": 152_700, "amount": 5_489_565},
        ]
        with patch(
            "ah_recommendation_system.backend.stock_recommend.run.calculate_features",
            return_value={"history_days": 120, "return_60d_pct": 20.3},
        ):
            self.assertTrue(_apply_daily_feature_row(row, bars))
        self.assertEqual(row["amount"], 1_602_459_052)
        self.assertEqual(row["amount_reference"], "latest_completed_daily_bar")

    def test_zero_or_premarket_amount_is_treated_as_missing_for_supplement(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import merge_quote_fields

        primary = {"price": 35.95, "change_pct": 0.22, "amount": 0, "volume": 0, "pe": 7.6}
        secondary = {"amount": 1_602_459_052.49, "volume": 44_975_091, "pe": 7.2}
        filled = merge_quote_fields(primary, secondary)
        self.assertIn("amount", filled)
        self.assertEqual(primary["amount"], 1_602_459_052.49)
        self.assertEqual(primary["pe"], 7.6)
'''
if old not in t:
    raise SystemExit("test block not found")
p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("fixed tests")
