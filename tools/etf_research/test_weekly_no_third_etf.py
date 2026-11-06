# -*- coding: utf-8 -*-
"""2026-11-06 Master 指令：周报去掉「综合研究排名·第三ETF互补视图」。

该区块展示 ranking 前 10 的 score/资格，与周报其他区块重复且用户不需要；
移除后周报仍须保留双轨周检、三持仓、可建仓候选、轮换前10、TOP2、错误记录与免责。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, r'D:\Code\AH_analyse')

import tools.etf_research.test_pair_review as helper
from tools.etf_research import weekly


class NoThirdEtfViewTests(unittest.TestCase):
    def test_weekly_report_has_no_complement_view(self):
        result = helper.fixture()
        result.update(leader=dict(code='sh510001', full_cycles=20, full_cycle_net=1500.0), errors=[])
        for c in ('sz159363', 'sh589720', 'sz159992'):
            result['holdings'][c].update(name=c, full_cycle_net=1000.0)
        top = []
        for i in range(10):
            x = helper.row('sh5100%02d' % (i + 10), 30 - i, 9)
            x['name'] = '候选%02d' % i
            x.update(full_cycle_net=3000.0 - i * 100)
            top.append(x)
        from tools.etf_research import research
        result['ranking'] = [dict(helper.row('sh510001', 20, 4), name='sh510001',
                                  full_cycle_net=1500.0), *top]
        result['summary'].update(version=research.VERSION, window_start='2026-07-07',
                                 window_end='2026-10-09', successful_runs=1284,
                                 failed_runs=0, attempted_assets=321)

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            result['summary']['output_path'] = str(tmp_path)
            bars_dir = tmp_path / 'bars'
            bars_dir.mkdir()
            for cand in result['ranking']:
                bars_dir.joinpath(cand['code'] + '-m5.csv').write_text(
                    'time,open,high,low,close', encoding='utf-8')
            (tmp_path / 'result.json').write_text(json.dumps(
                dict(summary=dict(asof='2026-10-09'), ranking=result['ranking'])),
                encoding='utf-8')

            def runner(**kwargs):
                return result

            out = weekly.run_weekly(state_path=tmp_path / 'legacy.json',
                                    pair_state_path=tmp_path / 'pair.json',
                                    research_runner=runner, taxonomy=helper.taxonomy())
        text = out['report']
        self.assertNotIn('【综合研究排名·第三ETF互补视图】', text)
        self.assertNotIn('| 代码 | 名称 | score | 资格 |', text)
        # 2026-11-06 Master 整改：双轨周检表格区块与 legacy reference 不再进正文。
        self.assertNotIn('【逐持仓双轨周检】', text)
        self.assertNotIn('legacy reference', text)
        lines = text.splitlines()
        review_lines = [x for x in lines if x.startswith('轮换复核：')]
        self.assertEqual(len(review_lines), 1, f'须恰好一行轮换复核状态：{review_lines}')
        self.assertTrue(all(len(x) <= 120 for x in lines), '任何报告行不得超过 120 字符')
        provenance = [x for x in lines[:8] if not x.startswith('轮换复核：')
                      and any(k in x for k in
                      ('共同窗口', '共同5分钟窗口', '资格池', '资格快照池', '成功模拟',
                       '模型资格排除', '数据覆盖', 'legacy reference', '口径', '数据截止'))]
        self.assertLessEqual(len(provenance), 2, f'开头口径行须 ≤2 行，实际 {provenance}')
        # 其余区块不受影响
        for marker in ('【当前三持仓·全部展示，不参与领先者】',
                       weekly.ENTRY_BLOCK_TITLE, '【轮换往返前10·同一套5分钟模拟】',
                       'TOP2', '数据/模拟错误记录', '禁止自动买入、撤单、改账本'):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        # 任务4：TOP2 区块只作观察候选，不得出现替换暗示。
        self.assertNotIn('替换候选', text)
        self.assertNotIn('持仓→候选', text)
        self.assertIn('本区块不生成替换建议', text)

    def test_summarize_has_no_complement_view(self):
        """飞书精简摘要同样不得出现该区块。"""
        result = helper.fixture()
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / 'result.json').write_text(json.dumps(
                dict(summary=dict(asof='2026-10-09'), ranking=result['ranking'])),
                encoding='utf-8')
            text = weekly.summarize(result, {})
        self.assertNotIn('第三ETF互补', text)


if __name__ == '__main__':
    unittest.main()
