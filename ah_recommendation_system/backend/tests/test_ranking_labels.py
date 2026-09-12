import unittest
from datetime import datetime, timedelta

import pandas as pd


def make_bars(code, sessions, base_price, closed_from=None):
    rows = []
    for index, date in enumerate(sessions):
        close = base_price * (1.01 if index >= 1 else 1.0)
        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "open": close, "high": close * 1.02, "low": close * 0.98,
            "close": close, "volume": 1000, "prev_close": close,
        })
    return pd.DataFrame(rows)


class TestRankingLabels(unittest.TestCase):
    def test_t1_to_t5_excess_and_unfilled(self):
        from ah_recommendation_system.backend.stock_recommend.backtest_verify import label_ranking_panel

        dates = [datetime(2026, 9, 1) + timedelta(days=i) for i in range(10)]
        bench = pd.DataFrame([
            {"date": d.strftime("%Y-%m-%d"), "open": 100, "close": 100.2, "prev_close": 100}
            for d in dates
        ])
        stock = make_bars("000001", dates, 10)
        panel = [
            {"code": "000001", "date": "2026-09-01", "factors": {"trend": 0.8}},
            {"code": "000002", "date": "2026-09-01", "factors": {"trend": 0.2}},
        ]
        bars_by_code = {"000001": stock}
        labeled = label_ranking_panel(panel, bars_by_code, bench)
        self.assertEqual(labeled[0]["status"], "filled")
        self.assertEqual(labeled[0]["entry_date"], "2026-09-02")
        self.assertEqual(labeled[0]["label_end"], "2026-09-07")
        self.assertAlmostEqual(labeled[0]["excess_return_pct"], labeled[0]["net_return_pct"] - labeled[0]["benchmark_return_pct"], places=6)
        self.assertEqual(labeled[1]["status"], "unfilled")


if __name__ == "__main__":
    unittest.main()
