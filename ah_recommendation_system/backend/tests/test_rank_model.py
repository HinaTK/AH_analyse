import unittest


class TestRankModel(unittest.TestCase):
    def test_linear_ranker_ranks_higher_excess_features_higher(self):
        from ah_recommendation_system.backend.stock_recommend.rank_model import fit_ranker, predict_scores

        train = [
            {"code": "1", "factors": {"trend": 0.9, "price_volume": 0.8, "value_quality": 0.5, "capital": 0.4, "relative_strength": 0.7, "event": 0.5}, "excess_return_pct": 2.0},
            {"code": "2", "factors": {"trend": 0.1, "price_volume": 0.2, "value_quality": 0.5, "capital": 0.4, "relative_strength": 0.2, "event": 0.5}, "excess_return_pct": -1.0},
        ]
        model = fit_ranker(train, feature_keys=list(train[0]["factors"]))
        scores = predict_scores(model, train)
        self.assertGreater(scores[0], scores[1])

    def test_missing_feature_does_not_become_zero_advantage(self):
        from ah_recommendation_system.backend.stock_recommend.rank_model import fit_ranker, predict_scores

        train = [{"code": "1", "factors": {"trend": 0.9, "price_volume": 0.5, "value_quality": 0.5, "capital": 0.5, "relative_strength": 0.5, "event": 0.5}, "excess_return_pct": 1.0}] * 20
        rows = [
            {"factors": {"trend": 0.9, "price_volume": 0.5, "value_quality": 0.5, "capital": 0.5, "relative_strength": 0.5, "event": 0.5}},
            {"factors": {"trend": None, "price_volume": 0.5, "value_quality": 0.5, "capital": 0.5, "relative_strength": 0.5, "event": 0.5}},
        ]
        model = fit_ranker(train, feature_keys=list(rows[0]["factors"]))
        scores = predict_scores(model, rows)
        self.assertIsNotNone(scores[0])
        self.assertTrue(scores[1] is None or scores[1] <= scores[0])


if __name__ == "__main__":
    unittest.main()
