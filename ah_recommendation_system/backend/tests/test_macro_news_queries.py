
import unittest

import pandas as pd

from ah_recommendation_system.backend.stock_recommend.data_collector import (
    _collect_macro_news_fallback,
    select_macro_news_by_bucket,
)


class TestMacroNewsQueries(unittest.TestCase):
    def test_macro_collection_keeps_late_policy_and_price_items(self):
        generic = [{"title": f"某公司回购{i}", "url": f"https://example.com/g{i}"} for i in range(80)]
        important = [
            {"title": "发改委开展价格监督检查", "url": "https://example.com/p1"},
            {"title": "工业硅价格因供应收缩上涨", "url": "https://example.com/p2"},
        ]
        selected = select_macro_news_by_bucket(generic + important, limit=80)
        titles = [item["title"] for item in selected]
        self.assertIn("发改委开展价格监督检查", titles)
        self.assertIn("工业硅价格因供应收缩上涨", titles)

    def test_macro_news_fallback_classifies_before_cap(self):
        class AkModule:
            @staticmethod
            def stock_info_global_em():
                rows = [{"title": f"generic buyback {i}", "url": f"https://example.com/g{i}"} for i in range(80)]
                rows.append({"title": "NDRC price inspection", "url": "https://example.com/policy"})
                return pd.DataFrame(rows)

            @staticmethod
            def stock_info_global_sina():
                return pd.DataFrame()

            @staticmethod
            def news_economic_baidu():
                return pd.DataFrame([{"title": "发改委开展价格监督检查", "url": "https://example.com/policy-cn"}])

        rows = _collect_macro_news_fallback(limit=80, ak_module=AkModule())
        titles = [row["title"] for row in rows]
        self.assertTrue(any("发改委" in title or "NDRC" in title for title in titles))


if __name__ == "__main__":
    unittest.main()
