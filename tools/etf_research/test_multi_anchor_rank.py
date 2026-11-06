# -*- coding: utf-8 -*-
"""TDD：多锚点稳健排名（2026-11-06 Master 指出「方案落实了却不用」）。

离线诊断口径，不替换生产排行榜；但必须真正用于「重排前 20」这一交付。
"""
import sys
import unittest

sys.path.insert(0, r'D:\Code\AH_analyse')

from tools.etf_research import multi_anchor_rank as m


def _rows():
    return [
        dict(code='A', name='甲', source_rank=1, single_cycles=28,
             median_cycles=22.0, mean_cycles=22.0, median_net=2500.0,
             spread=10, pstdev=3.5, runs_ok=5, runs_total=5, errors=[]),
        dict(code='B', name='乙', source_rank=3, single_cycles=24,
             median_cycles=24.0, mean_cycles=23.4, median_net=3000.0,
             spread=2, pstdev=0.8, runs_ok=5, runs_total=5, errors=[]),
        dict(code='C', name='丙', source_rank=2, single_cycles=None,
             median_cycles=None, mean_cycles=None, median_net=None,
             spread=None, pstdev=None, runs_ok=0, runs_total=5,
             errors=['取数失败']),
    ]


class StableRankTests(unittest.TestCase):
    def test_rank_uses_median_desc_not_single_anchor(self):
        out = m.rank_stable(_rows(), key='median_cycles')
        self.assertEqual([r['code'] for r in out], ['B', 'A', 'C'])
        self.assertEqual(out[0]['stable_rank'], 1)
        self.assertEqual(out[1]['stable_rank'], 2)

    def test_failed_asset_is_disclosed_not_silently_dropped(self):
        out = m.rank_stable(_rows(), key='median_cycles')
        self.assertEqual(out[-1]['code'], 'C')
        self.assertIsNone(out[-1]['stable_rank'])
        self.assertTrue(out[-1]['errors'])

    def test_mean_key_supported(self):
        out = m.rank_stable(_rows(), key='mean_cycles')
        self.assertEqual(out[0]['code'], 'B')

    def test_render_has_chinese_headers_and_disclaimer(self):
        out = m.rank_stable(_rows(), key='median_cycles')
        text = m.render(out, '2026-11-06', key='median_cycles')
        for word in ('多锚点', '稳健名次', '多起点中位往返次数', '单锚点往返次数',
                     '极差', '不叠加市况门控', '不替换生产口径', '非真实成交'):
            with self.subTest(word=word):
                self.assertIn(word, text)
        for banned in ('full_cycles', 'median_cycles', 'score'):
            self.assertNotIn(banned, text)

    def test_render_shows_old_and_new_rank_delta(self):
        out = m.rank_stable(_rows(), key='median_cycles')
        text = m.render(out, '2026-11-06', key='median_cycles')
        self.assertIn('原名次', text)
        self.assertIn('名次变化', text)

    def test_theme_cap_limits_display_but_not_ranking(self):
        rows = [dict(code=f'X{i}', name=f'创新药ETF{i}', source_rank=i + 1,
                     single_cycles=20 - i, median_cycles=20 - i,
                     mean_cycles=20 - i, median_net=2000.0 - i,
                     spread=2, pstdev=0.7, runs_ok=5, runs_total=5, errors=[])
                for i in range(8)]
        out = m.rank_stable(rows, key='median_cycles')
        capped = m.cap_display(out, limit=5)
        self.assertLessEqual(len(capped['rows']), 8)
        self.assertGreaterEqual(capped['dropped'], 0)
        self.assertEqual(out[0]['stable_rank'], 1, '限额只影响展示，不改排名')


class RecentWindowTests(unittest.TestCase):
    """2026-11-06 Master 追问「多锚点都是60+天吗？没有近期数据判断？」"""

    def test_recent_state_detects_density_change(self):
        # 长期日均 0.35 次，近期日均 0.75 次 → 升温
        self.assertEqual(m.recent_state(22, 15), '近期升温')
        # 长期日均 0.35 次，近期日均 0.15 次 → 降温
        self.assertEqual(m.recent_state(22, 3), '近期降温')
        self.assertEqual(m.recent_state(20, 6), '近期平稳')
        self.assertEqual(m.recent_state(None, 6), '近期数据不足')

    def test_recent_key_can_rank(self):
        rows = [dict(r) for r in _rows()]
        rows[0]['recent_median'] = 2.0
        rows[1]['recent_median'] = 9.0
        rows[2]['recent_median'] = None
        out = m.rank_stable(rows, key='recent_median')
        self.assertEqual(out[0]['code'], 'B')

    def test_render_includes_recent_columns(self):
        rows = [dict(r) for r in _rows()]
        # 三行都给有效长期值，近期值分别构造 升温 / 降温 / 平稳，确保三种状态都渲染
        for r in rows:
            r['median_cycles'] = 22.0
        for r, recent in zip(rows, (15.0, 3.0, 8.0)):
            r['recent_median'] = recent
            r['recent_spread'] = 3
            r['recent_state'] = m.recent_state(r['median_cycles'], recent)
        rows = m.rank_stable(rows)
        text = m.render(rows, '2026-11-06')
        for word in ('近20日', '近期状态', '近期升温', '近期降温', '近期平稳'):
            with self.subTest(word=word):
                self.assertIn(word, text)
        self.assertNotIn('recent_median', text)


if __name__ == '__main__':
    unittest.main()
