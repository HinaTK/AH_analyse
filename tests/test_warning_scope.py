# -*- coding: utf-8 -*-
"""TDD：免责说明不得出现与本次输出无关的标的（2026-11-13 Master 指出）。

原 WARNING 是全局常量，硬编码「sz159992 处于迁移退出模式…」，被 4 个出口共用，
导致只讲 sh589720 的盘中触价推送也带上 159992。修复方向：通用免责保持全局，
迁移退出说明改为按「本次输出实际涉及的标的」动态生成。
"""
import re
import unittest


INACTIVE = 'sz159992'
ACTIVE = 'sh589720'
HOLDINGS = {
    ACTIVE: {'name': '科创创新药ETF国泰', 'active': True},
    INACTIVE: {'name': '创新药ETF银华', 'active': False},
}


class WarningScopeTests(unittest.TestCase):
    def test_warning_has_no_ticker_code(self):
        import confirmed_runtime as runtime
        self.assertNotIn('159992', runtime.WARNING)
        self.assertIsNone(re.search(r'\b(?:sh|sz)?\d{6}\b', runtime.WARNING),
                          '通用免责里不得出现任何具体标的代码')

    def test_warning_keeps_generic_disclaimer(self):
        import confirmed_runtime as runtime
        for word in ('条件建议', '非可直接执行委托', '不自动下单', '触价不等于成交'):
            self.assertIn(word, runtime.WARNING)

    def test_warning_for_excludes_unrelated_migration_etf(self):
        import confirmed_runtime as runtime
        out = runtime.warning_for([ACTIVE], holdings=HOLDINGS)
        self.assertIn(runtime.WARNING, out)
        self.assertNotIn('159992', out)
        self.assertNotIn('迁移退出', out)

    def test_warning_for_includes_migration_etf_only_when_listed(self):
        import confirmed_runtime as runtime
        out = runtime.warning_for([ACTIVE, INACTIVE], holdings=HOLDINGS)
        self.assertIn('迁移退出', out)
        self.assertIn('停买、停接回、只卖不买', out)
        self.assertIn(INACTIVE, out)

    def test_warning_for_deduplicates(self):
        import confirmed_runtime as runtime
        out = runtime.warning_for([INACTIVE, INACTIVE, INACTIVE], holdings=HOLDINGS)
        self.assertEqual(out.count('迁移退出'), 1)

    def test_render_keeps_generic_warning_in_output(self):
        import confirmed_runtime as runtime
        ticket = dict(states={}, names={}, actions=[], warning=runtime.WARNING)
        out = runtime.render(ticket)
        self.assertIn(runtime.WARNING, out)

    def test_all_outputs_use_dynamic_warning(self):
        """4 个出口不得再直接引用全局 WARNING 作为本次推送文案。"""
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / 'confirmed_runtime.py'
        text = src.read_text(encoding='utf-8')
        body = text.split('WARNING = ', 1)[1].split('\n', 2)[-1]
        self.assertNotIn('warning=WARNING', body, 'ticket/eod 不得直接用全局常量')
        self.assertNotIn("print(WARNING + '\\n' + message)", body, '盘中推送不得直接用全局常量')
        self.assertNotIn("['【统一已确认ETF网格 1.5%】', WARNING]", body,
                         'render 不得直接用全局常量')

    def test_production_entrypoints_import_clean(self):
        import importlib
        for name in ('confirmed_runtime', 'holdings', 'upside_guard',
                     'tools.confirmed_grid.launchers.grid_weixin_confirm'):
            importlib.import_module(name)


if __name__ == '__main__':
    unittest.main()
