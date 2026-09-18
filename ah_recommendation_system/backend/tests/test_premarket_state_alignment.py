import json
import unittest

from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate
from ah_recommendation_system.backend.stock_recommend.decision_engine import build_market_decision
from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card
from ah_recommendation_system.backend.stock_recommend.focused_collector import (
    DEFAULT_FOCUS_UNIVERSE,
    attach_industry_tags,
)
from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots
from ah_recommendation_system.backend.stock_recommend.rule_selector import (
    finalize_picks_against_hotspots,
    select_by_rules,
)


def _leader(code, name):
    return Candidate(
        code=code,
        name=name,
        quality_grade="A",
        composite=0.72,
        valid_dimensions={"trend", "price_volume", "relative_strength", "capital"},
        factor_scores={"trend": 0.85, "relative_strength": 0.8, "price_volume": 0.7},
        evidence=[{"factor": key, "statement": key, "supports": True} for key in ("trend", "price_volume", "relative_strength", "capital")],
        candidate_sources=["liquidity_leader"],
        hotspot_match_level="none",
    )

class PremarketStateAlignmentTests(unittest.TestCase):
    def test_benchmark_defense_cannot_publish_offensive_attack_label(self):
        decision = build_market_decision(
            as_of='2026-09-17',
            market_signals=[{'theme': '通信设备', 'change_pct': 2.1, 'advance_count': 28, 'total_count': 40, 'source': 'industry_board'}],
            hotspots=[{'theme': 'AI算力硬件与光通信', 'status': 'early_signal', 'industries': ['通信设备', '光模块'], 'evidence_refs': ['a', 'b'], 'independent_source_count': 2}],
            coverage={'mode': 'full_market', 'ratio': 0.95},
            market_regime={'regime': 'defense', 'status': 'available', 'as_of': '2026-09-17'},
        )
        self.assertEqual(decision['regime'], 'defense')
        self.assertNotEqual(decision['label'], '结构性进攻')
        current = decision['directions']['current_attack'][0]
        self.assertNotEqual(current['status'], '有效')
        self.assertIn('指数', current['action'])

    def test_optical_and_cloth_hotspots_do_not_use_static_osat_names(self):
        mapped = validate_and_expand_hotspots(
            [
                {'theme': 'AI算力硬件与光通信', 'industries': ['通信设备', '光模块', '算力硬件', '光通信设备'], 'evidence_refs': ['a', 'b'], 'status': 'early_signal'},
                {'theme': '玻纤电子布涨价', 'industries': ['玻纤', '电子布', '电子材料'], 'evidence_refs': ['c', 'd'], 'status': 'early_signal'},
            ],
            focus_universe=DEFAULT_FOCUS_UNIVERSE,
        )
        names = []
        for hotspot in mapped['hotspots']:
            names.extend(hotspot.get('representatives') or [])
            self.assertNotIn('600584', hotspot.get('mapped_codes') or [])
            self.assertNotIn('603501', hotspot.get('mapped_codes') or [])
        self.assertNotIn('长电科技', names)
        self.assertNotIn('韦尔股份', names)

    def test_row_industry_maps_real_member_without_static_alias(self):
        mapped = validate_and_expand_hotspots(
            [{'theme': '玻纤电子布涨价', 'industries': ['玻纤', '电子布'], 'evidence_refs': ['a', 'b'], 'status': 'early_signal'}],
            focus_universe={},
            rows=[{'code': '600176', 'name': '中国巨石', 'industry': '玻纤'}],
        )
        self.assertEqual(mapped['hotspots'][0]['mapped_codes'], ['600176'])
        self.assertEqual(mapped['hotspots'][0]['representatives'], ['中国巨石'])
        self.assertIn('600176', mapped['candidate_mappings'])

    def test_attach_industry_tags_from_universe(self):
        rows = [{'code': '600176', 'name': '中国巨石', 'amount': 200000000, 'price': 10}]
        tagged = attach_industry_tags(rows, {'玻纤': [{'code': '600176', 'name': '中国巨石'}]})
        self.assertIn('玻纤', tagged[0]['focus_industries'])
        self.assertEqual(tagged[0]['industry'], '玻纤')

    def test_unrelated_defense_leaders_are_not_formal_picks_when_hotspots_exist(self):
        selection = select_by_rules(
            [_leader('600601', '方正科技'), _leader('601318', '中国平安')],
            top_n_pick=5,
            market_regime={'regime': 'defense', 'status': 'available'},
        )
        self.assertEqual(len(selection['picks']), 2)
        finalized = finalize_picks_against_hotspots(selection, hotspots=[{'theme': 'AI算力硬件与光通信', 'status': 'early_signal'}])
        self.assertEqual(len(finalized['picks']), 2)
        self.assertIsNone(finalized.get('empty_reason'))

    def test_empty_recommendation_card_states_no_formal_picks(self):
        card = build_card({
            'schema_version': 'decision-report-v2',
            'as_of': '2026-09-17',
            'run': {'status': 'passed', 'session': 'pre_market'},
            'quality_gate': {'passed': True, 'blocking_reasons': []},
            'market': {'label': '防守', 'status': '降级观察', 'regime': 'defense'},
            'directions': {
                'current_attack': [{'direction': 'AI算力硬件与光通信', 'action': '等待指数确认', 'status': '需确认'}],
                'medium_term': [],
                'early_positioning': [],
                'avoid_or_exit': [],
            },
            'recommendations': {'stocks': [], 'etfs': []},
            'picks': [],
            'etf_picks': [],
            'summary': '今日无正式个股推荐',
            'empty_reason': '今日无正式个股推荐：现有热点未映射到过线标的，且与主线无关的流动性龙头不作为推荐。',
        })
        rendered = json.dumps(card, ensure_ascii=False)
        self.assertIn('无正式', rendered)
        self.assertNotIn('方正科技', rendered)
        self.assertNotIn('中国平安', rendered)


if __name__ == '__main__':
    unittest.main()
