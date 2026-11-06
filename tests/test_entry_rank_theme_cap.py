"""可建仓排行榜：每个大题材最多 5 只（2026-11-06 Master 要求）。

与周五轮换 TOP2 的区别：
- TOP2 是两个替换候选必须题材互斥（每题材 1 只）；
- 排行榜**不去重**，同题材仍可多只，只限制每个大题材最多 5 只，
  避免创新药一个题材霸占前 10。
- 题材用名称粗分，未识别的按代码独立成组，不互相挤占。
- 榜单数字仍逐格来自 rows，原 rank 保留（全池名次），CSV 全量不变。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.etf_research import entry_rank, weekly  # noqa: E402


def _row(rank, code, name, full=None):
    return dict(rank=rank, code=code, name=name, label='仅试错仓',
                full_cycles=full if full is not None else float(50 - rank),
                full_cycle_net=3000.0 - rank,
                recent20_cycles=8.0,
                full_cycle_net_per_avg_cost_pct=12.0 - rank * 0.1,
                regime20='震荡')


def _report(rows):
    return dict(asof='2026-11-05', rows=rows,
                excluded={'holding': 0, 'incomplete': 0, 'timing': 0,
                          'recent20': 0, 'no_bars': 0, 'error': 0})


def _data_lines(text):
    return [x for x in text.splitlines()
            if x.startswith('|') and '---' not in x and '名次' not in x]


def _mixed_pool():
    rows = [_row(i + 1, 'sz1595%02d' % i, f'港股通创新药ETF{i}') for i in range(8)]
    rows += [_row(i + 9, 'sh5127%02d' % i, f'卫星ETF{i}') for i in range(4)]
    rows += [_row(i + 13, 'sh5152%02d' % i, f'煤炭ETF{i}') for i in range(3)]
    return rows


class ThemeCapTests(unittest.TestCase):
    def test_cap_limits_each_theme_to_five_not_one(self):
        """不去重：创新药 8 只应保留 5 只，而不是压成 1 只。"""
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=10)
        drug_lines = [x for x in _data_lines(out) if '创新药' in x]
        self.assertEqual(len(drug_lines), 5)
        self.assertGreater(len(drug_lines), 1, '必须是限额，不是去重压成一只')

    def test_top_n_is_filled_by_other_themes_after_cap(self):
        """限额后前 10 仍要凑满 10 行，由后面题材补上。"""
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=10)
        self.assertEqual(len(_data_lines(out)), 10)

    def test_unknown_names_never_share_a_cap(self):
        """15 只无题材关键词的候选不得被误当成同一题材挤掉。"""
        rows = [_row(i + 1, f'sz1599{i:02d}', f'票{i}') for i in range(15)]
        out = entry_rank.render_markdown(_report(rows), top_n=10)
        self.assertEqual(len(_data_lines(out)), 10)

    def test_original_rank_preserved_no_renumbering(self):
        """表格铁律：数字逐格来自 rows，名次保留全池原值。"""
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=10)
        ranks = [int(x.split('|')[1].strip()) for x in _data_lines(out)]
        self.assertEqual(ranks[:5], [1, 2, 3, 4, 5])
        self.assertIn(9, ranks, '创新药第 6-8 只被跳过，后面的卫星应从原名次 9 开始')
        self.assertNotIn(6, ranks)

    def test_header_states_cap_and_keeps_median_line(self):
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=10)
        self.assertIn('每题材最多5只', out)
        self.assertIn('名称粗分', out)
        self.assertIn('近20日高/低线=', out)

    def test_cap_can_be_disabled(self):
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=10, per_theme=0)
        self.assertEqual(len([x for x in _data_lines(out) if '创新药' in x]), 8)

    def test_cap_stats_report_dropped(self):
        cap = entry_rank.cap_per_theme(_mixed_pool(), limit=5)
        self.assertEqual(len(cap['rows']), 12)
        self.assertEqual(cap['dropped'], 3)
        self.assertEqual(cap['themes'], 3)

    def test_line_threshold_uses_full_pool_not_capped_rows(self):
        """近20日中位线仍基于完整入选池，不能因限额改变判据。"""
        rows = [_row(i + 1, 'sz1595%02d' % i, f'创新药ETF{i}', ) for i in range(8)]
        for i, r in enumerate(rows):
            r['recent20_cycles'] = float(2 + i)
        full = entry_rank.median_r20_threshold(rows)
        out = entry_rank.render_markdown(_report(rows), top_n=10)
        self.assertIn(f'近20日高/低线={full:g}', out)


class OmittedSummaryTests(unittest.TestCase):
    def test_skipped_rows_are_summarised_in_brackets(self):
        """跳号处必须括号概括被省略的是哪些（2026-11-06 Master）。"""
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=10)
        self.assertIn('（省略', out)
        self.assertIn('港股通创新药ETF5', out)
        self.assertIn('港股通创新药ETF6', out)
        self.assertIn('港股通创新药ETF7', out)

    def test_summary_names_each_skipped_code_and_reason(self):
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=10)
        self.assertIn('sz159505', out)
        self.assertIn('每题材最多5只', out)
        self.assertIn('医药创新药', out)

    def test_summary_lines_respect_120_char_limit(self):
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=20)
        self.assertTrue(all(len(x) <= 120 for x in out.splitlines()))

    def test_no_skips_means_no_summary(self):
        rows = [_row(i + 1, f'sz1599{i:02d}', f'票{i}') for i in range(10)]
        out = entry_rank.render_markdown(_report(rows), top_n=10)
        self.assertNotIn('（省略', out)

    def test_summary_does_not_break_table_row_count(self):
        """括注行不得以 | 开头，否则会被当成表格数据行。"""
        out = entry_rank.render_markdown(_report(_mixed_pool()), top_n=10)
        self.assertEqual(len(_data_lines(out)), 10)

    def test_long_names_never_drop_detail_lines(self):
        """真实标的名称较长、同题材跳过数量多时必须换行保留明细（2026-11-06 回归）。

        复现：11 只同题材长名称合成候选，限额 5 只后跳过 6 只，
        单行必然超 120；旧实现把 chunk 误赋给 `_`，导致不换行、整行被过滤。
        """
        rows = [_row(i + 1, 'sz1595%02d' % i, '港股通创新药医疗ETF富国%s号' % i)
                for i in range(11)]
        rows += [_row(12, 'sh512700', '卫星ETF永赢')]
        out = entry_rank.render_markdown(_report(rows), top_n=10)
        self.assertGreater(out.count('（省略'), 0)
        for i in range(5, 11):
            self.assertIn('sz1595%02d' % i, out, f'第{i}只被省略标的必须列出')
        self.assertIn('、', out, '同一行多只标的必须用顿号分隔')
        self.assertTrue(all(len(x) <= 120 for x in out.splitlines()))


class WeeklyDigestTests(unittest.TestCase):
    def test_digest_uses_capped_rows_same_as_table(self):
        """飞书精简摘要必须与完整表同源（2026-10-24 教训）。"""
        report = _report(_mixed_pool())
        with mock.patch.object(weekly, 'rank_entries', return_value=report):
            report_lines, digest = weekly.entry_rank_block(
                {'summary': {}}, output='unused', top_n=10, digest_n=3)
        table = '\n'.join(report_lines)
        codes_in_table = [x.split('|')[2].strip() for x in _data_lines(table)][:3]
        digest_codes = [x.split(' ')[1] for x in digest if '. ' in x and '｜' in x][:3]
        self.assertEqual(digest_codes, codes_in_table,
                         '摘要前3必须与限额后的表格前3同源')
        self.assertEqual(len([x for x in digest if '｜' in x]), 3)


if __name__ == '__main__':
    unittest.main()
