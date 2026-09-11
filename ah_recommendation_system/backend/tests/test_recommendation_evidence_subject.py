import unittest

from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates
from ah_recommendation_system.backend.stock_recommend.data_collector import CollectedSnapshot


class TestEvidenceSubject(unittest.TestCase):
    def candidate(self, news, **changes):
        row = dict(code="002142", name="宁波银行", price=35.87, pe=7.6,
                   market_cap=1e11, amount=1e9, change_60d_pct=17, history_days=120)
        row.update(changes)
        snap = CollectedSnapshot(date="2026-09-11", fundamental={"rows": [row]},
                                 capital={"rows": []}, events={"stock_news": news})
        return build_candidates(snap)[0]

    def test_incidental_bank_mention_in_other_company_news_is_not_catalyst(self):
        c = self.candidate([{"title": "剑桥科技603083.SH：完成基金备案", "content": "托管银行为宁波银行002142"}])
        self.assertFalse(any(e.get("factor") == "event" for e in c.evidence))

    def test_actual_company_headline_is_eligible(self):
        c = self.candidate([{"title": "宁波银行：年度业绩增长", "content": "利润增加"}])
        self.assertTrue(any(e.get("factor") == "event" for e in c.evidence))

    def test_financial_name_identifies_bank_when_industry_missing(self):
        c = self.candidate([], financial_records=[{
            "source": "statement", "period_end": "2025-12-31", "published_at": "2026-04-25",
            "roe_pct": 12.21, "profit_growth_pct": 8.47, "debt_to_assets_pct": 93,
            "cash_conversion_ratio": 7.97, "cash_ratio_unit": "ratio", "cash_ratio_source": "statement", "net_profit": 100}])
        self.assertEqual(c.quality_evidence["metric_count"], 2)
        self.assertNotIn("cash_conversion", c.quality_evidence["components"])
