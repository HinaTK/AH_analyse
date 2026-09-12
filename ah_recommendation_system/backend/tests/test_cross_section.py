import unittest


class TestCrossSection(unittest.TestCase):
    def test_missing_values_do_not_fill_zero(self):
        from ah_recommendation_system.backend.stock_recommend.cross_section import (
            cross_sectional_ranks, cross_sectional_zscores,
        )
        rows = [{"x": 1.0}, {"x": None}, {"x": 3.0}]
        ranks = cross_sectional_ranks(rows, "x")
        z = cross_sectional_zscores(rows, "x")
        self.assertEqual(ranks[1], None)
        self.assertEqual(z[1], None)
        self.assertGreater(ranks[2], ranks[0])
        self.assertAlmostEqual(sum(v for v in z if v is not None), 0.0, places=6)

    def test_constant_values_return_none_zscore(self):
        from ah_recommendation_system.backend.stock_recommend.cross_section import cross_sectional_zscores
        rows = [{"x": 5.0}, {"x": 5.0}, {"x": 5.0}]
        z = cross_sectional_zscores(rows, "x")
        self.assertTrue(all(v is None for v in z))

    def test_lower_is_better_flips_rank(self):
        from ah_recommendation_system.backend.stock_recommend.cross_section import cross_sectional_ranks
        rows = [{"x": 1.0}, {"x": 3.0}]
        ranks = cross_sectional_ranks(rows, "x", higher_is_better=False)
        self.assertGreater(ranks[0], ranks[1])


if __name__ == "__main__":
    unittest.main()
