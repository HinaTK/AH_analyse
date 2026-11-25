# -*- coding: utf-8 -*-
"""TDD：盘后只读参考四合一汇总 + 跨信号冲突裁决 + 全球市场客观快照。"""
import ast
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO / 'deploy_scripts' / 'post_market_summary.py'
RUN_AND_PUSH_PATH = REPO / 'deploy_scripts' / 'run_and_push.py'
DEPLOY_PATH = REPO / 'tools' / 'confirmed_grid' / 'deploy.py'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PostMarketSummaryTests(unittest.TestCase):
    def test_all_silent_produces_empty_output_and_zero_exit(self):
        mod = _load('post_market_summary_under_test', SCRIPT_PATH)
        runner = lambda label, script: (0, '', '')
        text, rc = mod.collect_summary(
            runner=runner,
            global_fetcher=lambda: ([], []),
            today='2026-11-25',
        )
        self.assertEqual(text, '')
        self.assertEqual(rc, 0)

    def test_merges_non_empty_sections_and_omits_silent_ones(self):
        mod = _load('post_market_summary_under_test', SCRIPT_PATH)
        outputs = {
            '市况右侧信号': (0, '📈 市况操作信号\r\n| 标的 | 收盘 |\r\n|---|---:|\r\n| 上证指数 | 3500 |', ''),
            '利率点火': (0, '   \n', ''),
            '观察哨': (0, '### 🗼 观察哨\n| 哨 | 状态 |\n|---|---|\n| 哨① | 未到 |', ''),
            '波动扩张观察': (0, '', ''),
        }
        text, rc = mod.collect_summary(
            runner=lambda label, script: outputs[label],
            global_fetcher=lambda: ([], []),
            today='2026-11-25',
        )
        self.assertEqual(rc, 0)
        self.assertIn('盘后只读参考汇总（2026-11-25）', text)
        self.assertIn('不作为下单指令', text)
        self.assertIn('📈 市况操作信号', text)
        self.assertIn('### 🗼 观察哨', text)
        self.assertNotIn('利率点火', text)
        self.assertNotIn('波动扩张观察', text)
        self.assertNotIn('\r', text)

    def test_partial_failure_does_not_drop_healthy_sections(self):
        mod = _load('post_market_summary_under_test', SCRIPT_PATH)
        outputs = {
            '市况右侧信号': (0, '📈 市况正常输出', ''),
            '利率点火': (1, '', 'westock timeout'),
            '观察哨': (0, '', ''),
            '波动扩张观察': (0, '【波动扩张观察·仅观察】\n命中', ''),
        }
        text, rc = mod.collect_summary(
            runner=lambda label, script: outputs[label],
            global_fetcher=lambda: ([], []),
            today='2026-11-25',
        )
        self.assertEqual(rc, 0)
        self.assertIn('📈 市况正常输出', text)
        self.assertIn('【波动扩张观察·仅观察】', text)
        self.assertIn('利率点火', text)
        self.assertIn('westock timeout', text)
        self.assertIn('降级', text)

    def test_all_failed_returns_nonzero(self):
        mod = _load('post_market_summary_under_test', SCRIPT_PATH)
        runner = lambda label, script: (1, '', f'{label} boom')
        text, rc = mod.collect_summary(
            runner=runner,
            global_fetcher=lambda: ([], []),
            today='2026-11-25',
        )
        self.assertNotEqual(rc, 0)
        self.assertIn('市况右侧信号', text)
        self.assertIn('波动扩张观察', text)


class CrossSignalConflictAndGlobalTests(unittest.TestCase):
    def test_detects_index_probe_vs_gate_blocked_non_dry_and_b_tier_noise(self):
        mod = _load('post_market_summary_conflict_test', SCRIPT_PATH)
        outputs = {
            '市况右侧信号': (
                0,
                '| 上证指数 | 3548.37 | +0.27% | 试仓买入·1成 | ○○● | 周线金叉先行 |\n'
                '| 科创创新药ETF国泰 | 0.70 | -1.40% | 方向仓观察·0成 | ●○○ | 网格 **⛔ 禁止建仓** 中 |',
                '',
            ),
            '利率点火': (0, '', ''),
            '观察哨': (
                0,
                '| 哨①量能地量(<1/3) | 未到 | 量能比0.411 |\n'
                '| 哨④924级政策开关 | 🔔B级命中·仅记录，不操作 | [B]座谈会 |',
                '',
            ),
            '波动扩张观察': (0, '', ''),
        }
        global_rows = [
            {'name': '纳斯达克', 'price': '23733.54', 'pct': -1.48, 'asof': '2026-11-24 收盘'},
            {'name': '日经225', 'price': '57011.40', 'pct': -2.78, 'asof': '2026-11-25'},
        ]
        text, rc = mod.collect_summary(
            runner=lambda label, script: outputs[label],
            global_fetcher=lambda: (global_rows, []),
            today='2026-11-25',
        )
        self.assertEqual(rc, 0)
        self.assertIn('跨信号裁决', text)
        self.assertIn('门控拦买', text)
        self.assertIn('地量尚缺', text)
        self.assertIn('B 级', text)
        self.assertIn('全球市场客观快照', text)
        self.assertIn('纳斯达克', text)
        self.assertIn('日经225', text)
        self.assertIn('异动分析', text)

    def test_detects_rate_flameout_and_volatility_divergence(self):
        mod = _load('post_market_summary_conflict_test', SCRIPT_PATH)
        outputs = {
            '市况右侧信号': (0, '| 上证指数 | 3548.37 | +0.27% | 试仓买入·1成 | ○○● | 周线金叉 |', ''),
            '利率点火': (0, '10年国债≤1.50%警报 | 🚨熄火 | 估算10Y 1.48%', ''),
            '观察哨': (0, '', ''),
            '波动扩张观察': (0, '【波动扩张观察·仅观察】\n命中', ''),
        }
        text, rc = mod.collect_summary(
            runner=lambda label, script: outputs[label],
            global_fetcher=lambda: ([], ['纳斯达克']),
            today='2026-11-25',
        )
        self.assertEqual(rc, 0)
        self.assertIn('逆风', text)
        self.assertIn('互有矛盾不执行', text)
        self.assertIn('全球快照部分缺失', text)

    def test_detects_a_tier_policy_and_suggests_deep_news_attribution(self):
        mod = _load('post_market_summary_conflict_test', SCRIPT_PATH)
        outputs = {
            '市况右侧信号': (0, '| 上证指数 | 3500.00 | +1.20% | 空仓观望·0成 | ●○○ | 观察 |', ''),
            '利率点火': (0, '', ''),
            '观察哨': (0, '| 哨④924级政策开关 | 🔔A级候选·待人工确认 | [A]新创设工具 |', ''),
            '波动扩张观察': (0, '', ''),
        }
        text, rc = mod.collect_summary(
            runner=lambda label, script: outputs[label],
            global_fetcher=lambda: ([], []),
            today='2026-11-25',
        )
        self.assertEqual(rc, 0)
        self.assertIn('A 级政策事件', text)
        self.assertIn('异动分析', text)

    def test_global_parsers_compute_expected_values(self):
        mod = _load('post_market_summary_parser_test', SCRIPT_PATH)
        us_json = {
            'data': {
                'usIXIC': {
                    'day': [
                        ['2026-11-23', '24269.75', '24089.56', '24353.65', '23794.96', '1'],
                        ['2026-11-24', '23745.86', '23733.54', '23884.74', '23455.84', '1'],
                    ]
                }
            }
        }
        row = mod.parse_us_kline_row('纳斯达克', 'usIXIC', us_json)
        self.assertEqual(row['name'], '纳斯达克')
        self.assertEqual(row['price'], '23733.54')
        self.assertAlmostEqual(row['pct'], -1.4779, places=2)
        self.assertEqual(row['asof'], '2026-11-24 收盘')

        sina_text = (
            'var hq_str_rt_hkHSI="HSI,恒生指数,22252.810,22219.650,22507.830,21936.210,21958.631,-261.020,-1.170,0,0,0,0,0,0,0,0,2026/11/25,15:36:32";\n'
            'var hq_str_b_NKY="日经225指数,57011.4000,-1633.23,-2.78,2:12 AM,14:12:00,2026-11-25,14:30:01";\n'
        )
        hk, nky = mod.parse_sina_indices(sina_text)
        self.assertEqual(hk['price'], '21958.63')
        self.assertAlmostEqual(hk['pct'], -1.17, places=2)
        self.assertEqual(nky['price'], '57011.40')
        self.assertAlmostEqual(nky['pct'], -2.78, places=2)

        qt_text = (
            'v_whUSDCNY="310~美元人民币~USDCNY~6.6726~0~20261125153555~6.6635~6.6620~6.6744~6.6583~6.6726~6.6728~0.0091~0.14~0";\n'
            'v_hf_GC="3550.15,-1.14,3551.40,3551.70,3602.90,3540.00,15:36:00,3591.10,3586.90,0,2,1,2026-11-25,纽约黄金";\n'
        )
        fx_rows = mod.parse_qt_macro(qt_text)
        self.assertEqual(len(fx_rows), 2)
        self.assertEqual(fx_rows[0]['name'], '美元/人民币')
        self.assertEqual(fx_rows[1]['name'], 'COMEX黄金')
        self.assertAlmostEqual(fx_rows[1]['pct'], -1.14, places=2)


class PostMarketSummaryRegistrationTests(unittest.TestCase):
    def test_job_registered_and_push_on(self):
        mod = _load('run_and_push_post_market_test', RUN_AND_PUSH_PATH)
        self.assertIn('post_market_summary', mod.JOBS)
        spec = mod.JOBS['post_market_summary']
        self.assertEqual(spec['push'], 'on')
        self.assertGreaterEqual(spec['timeout'], 600)
        resolved = Path(mod.resolve_script('post_market_summary')).resolve()
        self.assertEqual(resolved, SCRIPT_PATH.resolve())
        self.assertTrue(resolved.is_file())

    def test_deploy_manifest_covers_summary_script(self):
        mod = _load('deploy_manifest_post_market_test', DEPLOY_PATH)
        manifest = mod.manifest(REPO)
        self.assertIn('post_market_summary.py', manifest)
        self.assertEqual(manifest['post_market_summary.py'].resolve(), SCRIPT_PATH.resolve())

    def test_all_subprocess_calls_pass_creationflags(self):
        tree = ast.parse(SCRIPT_PATH.read_text(encoding='utf-8'))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'subprocess'
            and node.func.attr in ('run', 'Popen', 'call', 'check_output', 'check_call')
        ]
        self.assertTrue(calls)
        for call in calls:
            keywords = {kw.arg for kw in call.keywords}
            self.assertIn('creationflags', keywords)


if __name__ == '__main__':
    unittest.main()
