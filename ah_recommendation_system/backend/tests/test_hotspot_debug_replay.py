import json
import unittest
from pathlib import Path

from ah_recommendation_system.backend.stock_recommend.hotspot_analyzer import normalize_hotspots, selected_evidence
from ah_recommendation_system.backend.stock_recommend.news_ranker import select_hotspot_evidence

DUMP = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/data/stock_recommend/_hotspot_debug.json")


class TestHotspotDebugReplay(unittest.TestCase):
    def test_replay_keeps_real_themes_and_ranks_important_news(self):
        dump = json.loads(DUMP.read_text(encoding="utf-8"))
        selected = select_hotspot_evidence(dump["news"])
        blob = " ".join(str(item.get("title") or "") for item in selected)
        self.assertIn("\u53d1\u6539\u59d4", blob)
        self.assertTrue("\u7845" in blob or "\u82af\u7247" in blob or "\u534a\u5bfc\u4f53" in blob)
        self.assertTrue("\u6c14\u4ef7" in blob or "\u5929\u7136\u6c14" in blob)
        original_refs = {str(item.get("event_id")) for item in dump.get("prompt_news") or []}
        normalized = normalize_hotspots(dump["llm_raw"], valid_refs=original_refs)
        self.assertGreaterEqual(len(normalized), 3)
        self.assertTrue(all(0 <= item["confidence"] <= 1 for item in normalized))
        self.assertFalse(any("\u65b0\u95fb\u9a71\u52a8\u5f85\u786e\u8ba4" in item["theme"] for item in normalized))
        evidence = selected_evidence({"items": dump["news"]}, [])
        from ah_recommendation_system.backend.stock_recommend.news_ranker import DEFAULT_HOTSPOT_EVIDENCE_LIMIT
        self.assertGreaterEqual(len(selected), 24)
        self.assertLessEqual(len(selected), DEFAULT_HOTSPOT_EVIDENCE_LIMIT)
        self.assertEqual(len(evidence), len(selected))


if __name__ == "__main__":
    unittest.main()
