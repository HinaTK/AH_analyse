"""TOP2 不同大题材约束（2026-11-06 Master 授权，周五 weekly_fri 轮换任务）。

规则来源：2026-10-11 更正的「TOP2 指排名前两个不同大题材而非前两只 ETF」；
2026-11-06 Master 明确适用对象是周五 15:25 找替换标的的 weekly_fri 任务，
理由是实盘此前只有两只 ETF 做网格，两个候选不得同题材。
不适用于 research/entry_rank 研究榜单本身。
"""
import importlib.util
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _api():
    spec = importlib.util.spec_from_file_location(
        'rotation_top2_under_test', REPO / 'tools' / 'etf_research' / 'rotation_top2.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(code, name, cycles, net=1000.0, recent=5, **extra):
    row = dict(code=code, name=name, has_all_four_windows=True,
               full_cycles=float(cycles), full_cycle_net=float(net),
               recent20_cycles=float(recent),
               full_cycle_net_per_avg_cost_pct=5.0,
               recent20_cycle_net_per_avg_cost_pct=1.0,
               max_corr_to_base=0.4, max_down_corr_to_base=0.3,
               qualification=True, score=0.8)
    row.update(extra)
    return row


def _result(ranking):
    holdings = {c: _row(c, c, 10, 800.0, 3) for c in
                ('sh589720', 'sz159363', 'sz159992')}
    holdings['sh589720']['name'] = '科创创新药ETF国泰'
    holdings['sz159363']['name'] = '创业板人工智能ETF华宝'
    holdings['sz159992']['name'] = '创新药ETF银华'
    return dict(ranking=ranking, holdings=holdings, errors=[],
                rotation_ranking=ranking, rotation_top10=ranking[:10], leader=None,
                summary=dict(asof='2026-11-06', version='test-v1',
                             window_start='2026-08-03', window_end='2026-11-06',
                             production_scope=False, full_pool=True, offline=True,
                             successful_runs=100, failed_runs=0, attempted_assets=len(ranking),
                             data_failed_runs=0, fetch_errors=0))


class MajorThemeTests(unittest.TestCase):
    def test_satellite_aerospace_defence_share_one_major_theme(self):
        """Master 关心的正是这类扎堆：卫星/航空航天/军工/国防算同一大题材。"""
        api = _api()
        keys = {api.major_theme(n) for n in
                ('卫星ETF永赢', '航空航天ETF华夏', '军工龙头ETF富国', '国防ETF鹏华', '航天ETF华安')}
        self.assertEqual(len(keys), 1, f'军工航天系应归同一大题材，实际 {keys}')

    def test_innovative_drug_variants_share_one_major_theme(self):
        api = _api()
        keys = {api.major_theme(n) for n in
                ('港股通创新药ETF汇添富', '科创创新药ETF汇添富', '创新药ETF银华', '恒生创新药ETF')}
        self.assertEqual(len(keys), 1, f'创新药各细分应归同一大题材，实际 {keys}')

    def test_media_theme_is_recognised(self):
        """真实数据回归：传媒ETF广发曾落到 unknown 单独成组，等于绕过题材去重。"""
        api = _api()
        self.assertEqual(api.major_theme('传媒ETF广发'), '文化传媒')
        self.assertEqual(api.major_theme('游戏ETF华夏'), '文化传媒')

    def test_official_taxonomy_theme_maps_to_major_theme(self):
        api = _api()
        entry = dict(verified=True, theme_id='科创板创新药',
                     sources=['https://official.example/index'])
        self.assertEqual(api.theme_of('sh999999', '随便什么名字',
                                      {'assets': {'sh999999': entry}})[1], 'official')

    def test_name_based_theme_is_labelled_unverified(self):
        api = _api()
        _, source = api.theme_of('sh999999', '卫星ETF测试', None)
        self.assertEqual(source, 'name', '名称粗分必须标注为非官方来源')


class SelectTop2Tests(unittest.TestCase):
    def test_never_returns_two_same_major_theme(self):
        api = _api()
        ranking = [_row(f'sh51000{i}', name, 30 - i) for i, name in enumerate(
            ['卫星ETF甲', '航空航天ETF乙', '军工ETF丙', '国防ETF丁', '航天ETF戊'])]
        out = api.select_top2(_result(ranking))
        themes = [c['theme'] for c in out['candidates']]
        self.assertEqual(len(themes), len(set(themes)), f'TOP2 不得同题材：{themes}')
        self.assertLessEqual(len(out['candidates']), 2)

    def test_excludes_existing_holding_major_themes(self):
        """两个 BASE 持仓题材（创新药/人工智能）都要保守剔除。"""
        api = _api()
        ranking = [_row('sh510001', '港股通创新药ETF甲', 40),
                   _row('sh510002', '创业板人工智能ETF乙', 39),
                   _row('sh510003', '卫星ETF丙', 30),
                   _row('sh510004', '煤炭ETF丁', 20)]
        out = api.select_top2(_result(ranking))
        self.assertEqual([c['code'] for c in out['candidates']], ['sh510003', 'sh510004'])
        blocked = ' '.join(x['reason'] for x in out['blocked'])
        self.assertIn('持仓题材', blocked)

    def test_one_representative_per_theme_picks_top_cycles(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 30),
                   _row('sh510002', '卫星ETF乙', 28),
                   _row('sh510003', '煤炭ETF丙', 25),
                   _row('sh510004', '石油ETF丁', 24)]
        out = api.select_top2(_result(ranking))
        self.assertEqual([c['code'] for c in out['candidates']], ['sh510001', 'sh510003'])

    def test_shortfall_is_explicit_not_silently_padded(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 30), _row('sh510002', '航空航天ETF乙', 28)]
        out = api.select_top2(_result(ranking))
        self.assertEqual(len(out['candidates']), 1)
        self.assertTrue(out['shortfall'])

    def test_unknown_theme_never_fills_a_formal_top2_slot(self):
        """题材未识别的标的不得占 TOP2 名额（与 pair_review 的待核不累计 priority 一致）。"""
        api = _api()
        ranking = [_row('sh510001', '混沌主题甲', 40),
                   _row('sh510002', '不明标的乙', 39),
                   _row('sh510003', '卫星ETF丙', 30),
                   _row('sh510004', '煤炭ETF丁', 20)]
        out = api.select_top2(_result(ranking))
        self.assertEqual(len(out['candidates']), 2)
        self.assertTrue(all(c['theme_source'] != 'unknown' for c in out['candidates']))
        self.assertTrue(any('题材未识别' in b['reason'] for b in out['blocked']))

    def test_output_is_observation_only(self):
        api = _api()
        out = api.select_top2(_result([_row('sh510001', '卫星ETF甲', 30)]))
        self.assertFalse(out['executable'])
        self.assertNotIn('建议买入', json.dumps(out, ensure_ascii=False))

    def test_baseline_delta_numbers_come_from_result(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 30, 3000.0, 12),
                   _row('sh510002', '煤炭ETF乙', 20, 2000.0, 4)]
        out = api.select_top2(_result(ranking))
        first = out['candidates'][0]
        self.assertEqual(first['full_cycles'], 30.0)
        self.assertEqual(first['recent20_cycles'], 12.0)
        self.assertIn('baseline_full_cycles', first)
        self.assertIn('full_cycle_delta', first)


class Top2LeadingGateTests(unittest.TestCase):
    """任务3（2026-11-06 Master）：候选须领先对照基准持仓，且与可建仓榜同口径。

    缺陷：select_top2 原按 63 日往返降序凑满 2 只，未要求领先对照持仓，
    曾推出 18 次往返候选去「替换」21 次的持仓 589720（更差）。
    """

    def test_63d_cycles_must_strictly_beat_baseline(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 8), _row('sh510002', '煤炭ETF乙', 7)]
        out = api.select_top2(_result(ranking))
        self.assertEqual(out['candidates'], [])
        self.assertTrue(out['shortfall'])
        self.assertFalse(out['executable'])
        reasons = ' '.join(x['reason'] for x in out['blocked'])
        self.assertIn('63日往返未领先对照持仓', reasons)

    def test_equal_63d_cycles_is_not_leading(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 10), _row('sh510002', '煤炭ETF乙', 10)]
        out = api.select_top2(_result(ranking))
        self.assertEqual(out['candidates'], [])
        self.assertIn('63日往返未领先对照持仓', ' '.join(x['reason'] for x in out['blocked']))

    def test_recent20_cycles_must_not_lag_baseline(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 20, recent=2),
                   _row('sh510002', '煤炭ETF乙', 25, recent=1)]
        out = api.select_top2(_result(ranking))
        self.assertEqual(out['candidates'], [])
        reasons = ' '.join(x['reason'] for x in out['blocked'])
        self.assertIn('近20日往返落后对照持仓', reasons)

    def test_admitted_set_limits_candidates_to_listed_codes(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 30), _row('sh510002', '煤炭ETF乙', 20)]
        out = api.select_top2(_result(ranking), admitted={'sh510002'})
        self.assertEqual([c['code'] for c in out['candidates']], ['sh510002'])
        self.assertIn('sh510001', [x['code'] for x in out['blocked']])
        self.assertIn('可建仓榜', ' '.join(x['reason'] for x in out['blocked']))

    def test_admitted_none_keeps_legacy_selection(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 30), _row('sh510002', '煤炭ETF乙', 20)]
        out = api.select_top2(_result(ranking), admitted=None)
        self.assertEqual([c['code'] for c in out['candidates']], ['sh510001', 'sh510002'])

    def test_no_qualified_candidate_reports_explicit_reason(self):
        api = _api()
        ranking = [_row('sh510001', '卫星ETF甲', 8), _row('sh510002', '煤炭ETF乙', 7)]
        out = api.select_top2(_result(ranking))
        report = '\n'.join(api.report_lines(out))
        self.assertIn('无同时满足领先条件与建仓规则的候选', report)

    def test_weekly_passes_admitted_set_to_select_top2(self):
        """weekly.py 调用处须传入本期可建仓榜入选集合，取不到不得报错。"""
        import tempfile
        from unittest import mock
        from tools.etf_research import weekly
        ranking = [_row('sh510001', '卫星ETF甲', 30), _row('sh510002', '煤炭ETF乙', 20)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            r = _result(ranking)
            r['summary']['output_path'] = str(root)
            bars = root / 'bars'
            bars.mkdir()
            for row in ranking:
                (bars / (row['code'] + '-m5.csv')).write_text('time,open,high,low,close', encoding='utf-8')
            (root / 'result.json').write_text(json.dumps(
                dict(summary=dict(asof='2026-11-06'), ranking=ranking)), encoding='utf-8')
            real = weekly.rotation_top2.select_top2
            captured = {}

            def spy(result, **kwargs):
                captured.update(kwargs)
                return real(result, **kwargs)

            with mock.patch.object(weekly.rotation_top2, 'select_top2', side_effect=spy):
                weekly.run_weekly(state_path=root / 'legacy.json', pair_state_path=root / 'pair.json',
                                  research_runner=lambda **kw: r, taxonomy={'assets': {}})
        self.assertIn('admitted', captured)


class Top2ObservationWordingTests(unittest.TestCase):
    """任务4（2026-11-06 Master）：TOP2 区块只作观察候选，不得暗示替换持仓。

    旧写法：标题「替换候选」、表头「持仓→候选」、行首「持仓 → 候选」，
    看起来像建议换掉持仓；全部改为观察候选 / 仅与基准比较的中文表述。
    """

    def _top2(self, api):
        ranking = [_row('sh510001', '卫星ETF甲', 30),
                   _row('sh510002', '煤炭ETF乙', 20)]
        return api.select_top2(_result(ranking))

    def test_title_is_observation_not_replacement(self):
        api = _api()
        self.assertNotIn('替换候选', api.TOP2_TITLE)
        self.assertIn('观察候选', api.TOP2_TITLE)
        self.assertIn('只报告，不自动换仓', api.TOP2_TITLE)

    def test_report_header_has_no_replacement_arrow(self):
        api = _api()
        text = '\n'.join(api.report_lines(self._top2(api)))
        self.assertNotIn('持仓→候选', text)
        self.assertIn('观察标的', text)
        self.assertNotIn('→', text)

    def test_report_rows_start_with_candidate_code_only(self):
        api = _api()
        rows = [x for x in api.report_lines(self._top2(api)) if x.startswith('| sh510')]
        self.assertEqual(len(rows), 2)
        base_code = api.research.BASE[0]
        for row in rows:
            first = row.split('|')[1].strip()
            self.assertNotIn('→', first)
            self.assertNotIn(base_code, first)
            self.assertTrue(first.startswith('sh510'), f'行首须只写候选代码+名称：{first}')

    def test_baseline_is_marked_comparison_only(self):
        api = _api()
        text = '\n'.join(api.report_lines(self._top2(api)))
        self.assertIn('对照基准', text)
        self.assertIn('仅用于比较往返次数', text)
        self.assertIn('不是待替换标的', text)

    def test_report_and_digest_declare_no_replacement_advice(self):
        api = _api()
        top2 = self._top2(api)
        for text in ('\n'.join(api.report_lines(top2)), '\n'.join(api.digest_lines(top2))):
            self.assertIn('本区块不生成替换建议', text)

    def test_numeric_and_delta_headers_unchanged(self):
        api = _api()
        text = '\n'.join(api.report_lines(self._top2(api)))
        for header in ('大题材', '题材来源', '63日往返', '持仓往返', '领先差额',
                       '近20往返', '持仓近20', '近期差额', '备注'):
            with self.subTest(header=header):
                self.assertIn(header, text)

    def test_digest_has_no_replacement_wording(self):
        api = _api()
        text = '\n'.join(api.digest_lines(self._top2(api)))
        self.assertNotIn('替换候选', text)
        self.assertNotIn('→', text)
        self.assertIn('观察候选', text)

    def test_weekly_report_has_no_replacement_wording(self):
        import tempfile
        from tools.etf_research import weekly
        ranking = [_row('sh510001', '卫星ETF甲', 30), _row('sh510002', '煤炭ETF乙', 20)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            r = _result(ranking)
            r['summary']['output_path'] = str(root)
            bars = root / 'bars'
            bars.mkdir()
            for row in ranking:
                (bars / (row['code'] + '-m5.csv')).write_text('time,open,high,low,close', encoding='utf-8')
            (root / 'result.json').write_text(json.dumps(
                dict(summary=dict(asof='2026-11-06'), ranking=ranking)), encoding='utf-8')
            out = weekly.run_weekly(state_path=root / 'legacy.json', pair_state_path=root / 'pair.json',
                                    research_runner=lambda **kw: r, taxonomy={'assets': {}})
        for forbidden in ('替换候选', '持仓→候选', '替换依据'):
            self.assertNotIn(forbidden, out['report'])
        self.assertIn('本区块不生成替换建议', out['report'])


class WeeklyIntegrationTests(unittest.TestCase):
    def _run(self, ranking):
        import tempfile
        from tools.etf_research import weekly
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        r = _result(ranking)
        r['summary']['output_path'] = str(root)
        bars = root / 'bars'
        bars.mkdir()
        for row in ranking:
            (bars / (row['code'] + '-m5.csv')).write_text('time,open,high,low,close', encoding='utf-8')
        (root / 'result.json').write_text(json.dumps(
            dict(summary=dict(asof='2026-11-06'), ranking=ranking)), encoding='utf-8')
        out = weekly.run_weekly(state_path=root / 'legacy.json',
                                pair_state_path=root / 'pair.json',
                                research_runner=lambda **kw: r,
                                taxonomy={'assets': {}})
        return out, td

    def test_report_contains_top2_block(self):
        ranking = [_row('sh510001', '卫星ETF甲', 30), _row('sh510002', '煤炭ETF乙', 20)]
        out, td = self._run(ranking)
        self.assertIn('TOP2', out['report'])
        self.assertIn('sh510001', out['report'])
        td.cleanup()

    def test_digest_contains_top2_block(self):
        """定时推送的是 summarize，不带即整改未落地（2026-10-24 教训）。"""
        ranking = [_row('sh510001', '卫星ETF甲', 30), _row('sh510002', '煤炭ETF乙', 20)]
        out, td = self._run(ranking)
        self.assertIn('TOP2', out['summary'])
        td.cleanup()

    def test_report_marks_top10_as_not_deduplicated(self):
        ranking = [_row('sh510001', '卫星ETF甲', 30), _row('sh510002', '卫星ETF乙', 20)]
        out, td = self._run(ranking)
        self.assertIn('本表未按题材去重', out['report'])
        td.cleanup()


if __name__ == '__main__':
    unittest.main()
