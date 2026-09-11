
import unittest
from datetime import datetime

from ah_recommendation_system.backend.stock_recommend.news_ranker import select_hotspot_evidence


class TestNewsRanker(unittest.TestCase):
    def test_select_hotspot_evidence_prefers_policy_price_supply_over_ingest_order(self):
        noise = [
            {
                "event_id": f"n{i}",
                "title": f"某公司回购公告{i}",
                "source": "东方财富全球财经",
                "published_at": "2026-09-10 08:00:00",
            }
            for i in range(30)
        ]
        important = [
            {
                "event_id": "p1",
                "title": "发改委开展价格监督检查并查处价格违法行为",
                "source": "证券时报网",
                "published_at": "2026-09-09 20:00:00",
            },
            {
                "event_id": "p2",
                "title": "欧洲天然气价格升至2022年12月以来最高",
                "source": "东方财富全球财经",
                "published_at": "2026-09-10 07:00:00",
            },
            {
                "event_id": "p3",
                "title": "工业硅价格因供应收缩上涨",
                "source": "财联社",
                "published_at": "2026-09-10 06:00:00",
            },
        ]
        selected = select_hotspot_evidence(
            noise + important,
            limit=24,
            now=datetime(2026, 9, 10, 9, 0, 0),
        )
        ids = [item["event_id"] for item in selected]
        self.assertIn("p1", ids)
        self.assertIn("p2", ids)
        self.assertIn("p3", ids)
        self.assertLess(ids.index("p1"), 10)

    def test_candidate_stock_news_can_enter_prompt_pack(self):
        macro = [
            {
                "event_id": f"m{i}",
                "title": f"某公司回购{i}",
                "source": "东方财富全球财经",
                "published_at": "2026-09-10 08:00:00",
            }
            for i in range(80)
        ]
        stock = [{
            "event_id": "s1",
            "title": "宁波银行发布利好公告",
            "source": "证券时报网",
            "published_at": "2026-09-10 08:10:00",
        }]
        selected = select_hotspot_evidence(
            macro + stock,
            candidates=[{"name": "宁波银行", "focus_industries": ["银行"]}],
            limit=24,
            now=datetime(2026, 9, 10, 9, 0, 0),
        )
        self.assertIn("s1", [item["event_id"] for item in selected])


if __name__ == "__main__":
    unittest.main()
