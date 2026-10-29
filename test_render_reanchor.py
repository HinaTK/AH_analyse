# -*- coding: utf-8 -*-
"""TDD：render 输出 📍重锚 提示行（2026-10-29 用户"现在补"）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import confirmed_runtime as rt


def _ticket(reanchors):
    return dict(
        actions=[dict(code='sh589720', side='buy', price='0.745', qty=10700, lot='G')],
        states={},
        names={'sh589720': '科创创新药ETF国泰'},
        reanchor=reanchors,
    )


class RenderReanchorTests(unittest.TestCase):
    def test_render_shows_reanchor_line(self):
        t = _ticket([dict(code='sh589720', old_price='0.785', new_price='0.745',
                          spot='0.756', lot='G')])
        out = rt.render(t)
        self.assertIn('📍', out)
        self.assertIn('重锚', out)
        self.assertIn('0.785', out)   # 旧价可见
        self.assertIn('0.745', out)   # 新价可见
        self.assertIn('0.756', out)   # 现价可见
        self.assertIn('G', out)       # 格号可见

    def test_render_no_reanchor_line_when_absent(self):
        out = rt.render(_ticket([]))
        self.assertNotIn('📍', out)

    def test_reanchor_line_before_actions(self):
        t = _ticket([dict(code='sh589720', old_price='0.785', new_price='0.745',
                          spot='0.756', lot='G')])
        out = rt.render(t)
        idx_anchor = out.find('📍')
        idx_action = out.find('条件买')
        self.assertLess(idx_anchor, idx_action, '重锚行应在买卖建议之前')


if __name__ == '__main__':
    unittest.main()
