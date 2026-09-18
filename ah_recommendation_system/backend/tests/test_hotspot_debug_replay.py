import unittest
from datetime import datetime
from unittest.mock import patch

from ah_recommendation_system.backend.stock_recommend.hotspot_analyzer import normalize_hotspots, selected_evidence
from ah_recommendation_system.backend.stock_recommend.news_ranker import select_hotspot_evidence

REPLAY_TIME = datetime(2026, 9, 10, 18)


def replay_fixture():
    # Keep the historical replay independent of mutable runtime artifacts.
    titles = ["发改委发布产业政策", "半导体芯片供应改善", "天然气气价回落"]
    titles += [f"行业供需跟踪样本{chr(0x4e00 + index)}" for index in range(30)]
    news = [
        {"event_id": f"news-{index}", "title": title, "source": "fixture",
         "published_at": "2026-09-10 17:30:00"}
        for index, title in enumerate(titles)
    ]
    return {
        "news": news,
        "prompt_news": news,
        "llm_raw": {"hotspots": [
            {"theme": "产业政策", "confidence": "high", "evidence_refs": ["news-0", "news-3"]},
            {"theme": "半导体供应", "confidence": 75, "evidence_refs": ["news-1", "news-4"]},
            {"theme": "天然气价格", "confidence": 0.6, "evidence_refs": ["news-2", "news-5"]},
            {"theme": "新闻驱动待确认", "confidence": 0.8, "evidence_refs": ["news-0", "news-1"]},
        ]},
    }


class TestHotspotDebugReplay(unittest.TestCase):
    def test_replay_keeps_real_themes_and_ranks_important_news(self):
        dump = replay_fixture()
        selected = select_hotspot_evidence(dump["news"], now=REPLAY_TIME)
        blob = " ".join(str(item.get("title") or "") for item in selected)
        self.assertIn("\u53d1\u6539\u59d4", blob)
        self.assertTrue("\u7845" in blob or "\u82af\u7247" in blob or "\u534a\u5bfc\u4f53" in blob)
        self.assertTrue("\u6c14\u4ef7" in blob or "\u5929\u7136\u6c14" in blob)
        original_refs = {str(item.get("event_id")) for item in dump.get("prompt_news") or []}
        normalized = normalize_hotspots(dump["llm_raw"], valid_refs=original_refs)
        self.assertGreaterEqual(len(normalized), 3)
        self.assertTrue(all(0 <= item["confidence"] <= 1 for item in normalized))
        self.assertFalse(any("\u65b0\u95fb\u9a71\u52a8\u5f85\u786e\u8ba4" in item["theme"] for item in normalized))
        with patch("ah_recommendation_system.backend.stock_recommend.news_ranker.datetime", wraps=datetime) as clock:
            clock.now.return_value = REPLAY_TIME
            evidence = selected_evidence({"items": dump["news"]}, [])
        from ah_recommendation_system.backend.stock_recommend.news_ranker import DEFAULT_HOTSPOT_EVIDENCE_LIMIT
        self.assertGreaterEqual(len(selected), 24)
        self.assertLessEqual(len(selected), DEFAULT_HOTSPOT_EVIDENCE_LIMIT)
        self.assertEqual(len(evidence), len(selected))

    def test_replay_news_still_expires_outside_its_historical_window(self):
        self.assertEqual(select_hotspot_evidence(
            replay_fixture()["news"], now=datetime(2026, 9, 18, 18)
        ), [])


if __name__ == "__main__":
    unittest.main()
