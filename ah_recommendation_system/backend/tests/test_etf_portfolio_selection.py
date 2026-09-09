import unittest


def _row(code, name, **kwargs):
    row = {
        "code": code,
        "name": name,
        "status": "ok",
        "history_days": 120,
        "turnover": 500_000_000,
        "trend_score": 80.0,
        "ret_20d": 8.0,
        "ret_60d": 12.0,
        "ret_120d": 15.0,
        "above_ma20": True,
        "above_ma60": True,
        "ma20_above_ma60": True,
        "volatility_20d_pct": 2.0,
        "max_drawdown_60d_pct": -8.0,
        "breakout_gap_60d_pct": -4.0,
    }
    row.update(kwargs)
    return row


class TestEtfPortfolioSelection(unittest.TestCase):
    def test_same_underlying_index_keeps_only_highest_score(self):
        from ah_recommendation_system.backend.etf_sector.etf_portfolio import select_etf_portfolio

        rows = [
            _row("159030", "华夏国证粮食产业ETF", underlying_index="国证粮食产业指数", composite_score=82),
            _row("159063", "南方国证粮食产业ETF", underlying_index="国证粮食产业指数", composite_score=79),
            _row("510300", "沪深300ETF", underlying_index="沪深300指数", category="宽基", composite_score=75),
        ]
        result = select_etf_portfolio(rows, limit=3)

        self.assertEqual([row["code"] for row in result["selected"]], ["159030", "510300"])
        self.assertEqual([row["code"] for row in result["deduplicated"]], ["159063"])

    def test_two_food_etfs_are_not_both_selected_without_index_metadata(self):
        from ah_recommendation_system.backend.etf_sector.etf_portfolio import select_etf_portfolio

        rows = [
            _row("159030", "华夏国证粮食产业ETF", composite_score=82),
            _row("159063", "南方国证粮食产业ETF", composite_score=79),
            _row("159981", "能源化工ETF建信", composite_score=78),
        ]
        result = select_etf_portfolio(rows, limit=3)

        selected = {row["code"] for row in result["selected"]}
        self.assertFalse({"159030", "159063"}.issubset(selected))
        self.assertEqual(len(selected), 2)

    def test_hard_gate_rejects_low_liquidity_and_below_ma60(self):
        from ah_recommendation_system.backend.etf_sector.etf_portfolio import build_etf_quality_scores, select_etf_portfolio

        rows = [
            _row("510300", "沪深300ETF", turnover=50_000_000),
            _row("512880", "证券ETF", above_ma60=False),
        ]
        scored = build_etf_quality_scores(rows)
        result = select_etf_portfolio(scored, limit=3)

        self.assertEqual(result["selected"], [])
        rejected = {row["code"]: row["rejection_reasons"] for row in result["rejected"]}
        self.assertTrue(any("liquidity" in reason for reason in rejected["510300"]))
        self.assertTrue(any("ma60" in reason for reason in rejected["512880"]))

    def test_crowding_penalty_reduces_score_for_overextended_etf(self):
        from ah_recommendation_system.backend.etf_sector.etf_portfolio import build_etf_quality_scores

        clean = build_etf_quality_scores([_row("510300", "沪深300ETF")])[0]
        crowded = build_etf_quality_scores([
            _row("159030", "粮食ETF", ret_20d=20.0, breakout_gap_60d_pct=-1.0, volatility_20d_pct=4.0)
        ])[0]

        self.assertLess(crowded["risk_control_score"], clean["risk_control_score"])
        self.assertIn("crowding_penalty", crowded["risk_flags"])

    def test_fewer_than_three_is_allowed_and_has_reason(self):
        from ah_recommendation_system.backend.etf_sector.etf_portfolio import select_etf_portfolio

        result = select_etf_portfolio([_row("510300", "沪深300ETF", composite_score=75)], limit=3)

        self.assertEqual(len(result["selected"]), 1)
        self.assertIn("不足", result["portfolio_summary"]["missing_slots_reason"])

    def test_theme_hotspot_only_changes_theme_dimension(self):
        from ah_recommendation_system.backend.etf_sector.etf_portfolio import build_etf_quality_scores

        rows = [_row("159981", "能源化工ETF", composite_score=0)]
        scored = build_etf_quality_scores(rows, hotspots=[{"theme": "油气", "industries": ["油气开采"], "status": "confirmed"}])[0]

        self.assertGreater(scored["theme_match_score"], 50)
        self.assertEqual(scored["trend_score"], 80.0)

    def test_bond_etf_is_classified_as_defensive(self):
        from ah_recommendation_system.backend.etf_sector.etf_portfolio import classify_etf_exposure, select_etf_portfolio

        exposure = classify_etf_exposure({"name": "5年地方债ETF"})
        self.assertEqual(exposure["theme_group"], "债券防御")
        self.assertEqual(exposure["exposure_group"], "defensive")
        selected = select_etf_portfolio([_row("159972", "5年地方债ETF")], limit=1)["selected"]
        self.assertEqual(selected[0]["position"], "防御")

    def test_feishu_shows_etf_position_and_factor_scores(self):
        import json
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        card = build_card({
            "as_of": "2026-09-09",
            "picks": [],
            "etf_picks": [{
                "code": "159981",
                "name": "能源化工ETF",
                "position": "主线",
                "score": 79.0,
                "factor_scores": {
                    "trend": 84.0,
                    "relative_strength": 77.0,
                    "liquidity": 72.0,
                    "risk_control": 68.0,
                    "theme_match": 91.0,
                },
                "rationale": "20/60日收益 +15.8%/+12.6%，站上 MA20/MA60",
            }],
        })
        rendered = json.dumps(card, ensure_ascii=False)

        self.assertIn("主线", rendered)
        self.assertIn("趋势 84", rendered)
        self.assertIn("相对强度 77", rendered)
        self.assertIn("风险控制 68", rendered)

    def test_report_keeps_explicit_empty_etf_selection_empty(self):
        from ah_recommendation_system.backend.stock_recommend.report_builder import build_report

        report = build_report(
            selection={"picks": [], "etf_picks": [], "as_of": "2026-09-09"},
            candidates=[],
        )

        self.assertEqual(report["etf_picks"], [])


if __name__ == "__main__":
    unittest.main()
