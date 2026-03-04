import unittest


class TestAhPairMapping(unittest.TestCase):
    def test_known_pairs_are_correct(self):
        from ah_recommendation_system.backend.data.ah_stock_list import (
            get_ah_pairs,
        )

        pairs = get_ah_pairs()
        # A/H should be the same company for these canonical pairs.
        self.assertEqual(pairs.get("601988.SH"), "3988.HK")  # 中国银行
        self.assertEqual(pairs.get("601939.SH"), "0939.HK")  # 建设银行
        self.assertEqual(pairs.get("601398.SH"), "1398.HK")  # 工商银行
        self.assertEqual(pairs.get("600030.SH"), "6030.HK")  # 中信证券

    def test_pair_trading_guess_map_matches(self):
        from ah_recommendation_system.backend.strategies.pair_trading import (
            get_pair_trading_strategy,
        )

        st = get_pair_trading_strategy()
        self.assertEqual(st._guess_h_code("601988.SH"), "3988.HK")
        self.assertEqual(st._guess_h_code("601939.SH"), "0939.HK")

    def test_pair_trading_rejects_mismatched_pair(self):
        from ah_recommendation_system.backend.data.price_fetcher import (
            get_price_fetcher,
        )
        from ah_recommendation_system.backend.strategies.pair_trading import (
            get_pair_trading_strategy,
        )

        get_price_fetcher().enable_mock_data()
        st = get_pair_trading_strategy()
        # Intentionally pass a wrong H code; should be rejected.
        res = st.analyze_single_pair("601988.SH", "0939.HK")
        self.assertEqual(res, {})

    def test_pair_trading_does_not_guess_missing_pairs(self):
        from ah_recommendation_system.backend.data.price_fetcher import (
            get_price_fetcher,
        )
        from ah_recommendation_system.backend.strategies.pair_trading import (
            get_pair_trading_strategy,
        )

        get_price_fetcher().enable_mock_data()
        st = get_pair_trading_strategy()
        out = st.generate_recommendations(stock_list=["000001.SZ"], max_positions=10)
        summary = out.get("summary") or {}
        self.assertEqual(summary.get("skipped_pairs"), 1)


if __name__ == "__main__":
    unittest.main()
