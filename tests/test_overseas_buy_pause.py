# -*- coding: utf-8 -*-
"""TDD: 跨境买入总闸（2026-11-05 Master 指令：纳指/日经暂停买入，待复核修复后再开）。

契约:
1. 标志文件 STATE.parent/overseas-buy-pause.json 存在且 paused=true
   → 全部买入类信号（nasdaq_premium / nasdaq_drawdown / nikkei_t2 / nikkei_t3）静默；
2. 止损信号 nikkei_stop 不受闸门影响（卖出任何时候都要响）；
3. 标志缺失 / paused=false / 内容损坏 → 不暂停，行为与基线一致；
4. 暂停状态写进 state['buy_paused'] 供事后审计；
5. 恢复只需删除文件或置 paused=false，无需改代码。
"""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy_scripts' / 'overseas_trigger_monitor.py'


def _load():
    spec = importlib.util.spec_from_file_location('otm_pause_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDate:
    current = '2026-11-06'

    @classmethod
    def today(cls):
        return cls

    @classmethod
    def isoformat(cls):
        return cls.current


BUY_ONLY = [
    ('nasdaq_premium', '🟢 513300 溢价回到 <3%——纳指方案可启动', True),
    ('nikkei_t2', '🟢 159866 现价 1.515 进入第二档买入30%', True),
]
STOP_ONLY = [('nikkei_stop', '🔴 159866 现价 1.199 已跌破止损线 1.2002', True)]


class TestOverseasBuyPause(unittest.TestCase):
    def setUp(self):
        self.otm = _load()
        self.otm.date = FakeDate
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.otm.STATE = self.root / 'overseas-triggers.json'
        self.otm.PAUSE_FLAG = self.root / 'overseas-buy-pause.json'
        self.otm.check_nasdaq = lambda: ([BUY_ONLY[0]], dict(prem=1.0, dd=-9.0))
        self.otm.check_nikkei = lambda: ([BUY_ONLY[1]], dict(price=1.515, low=1.505))
        FakeDate.current = '2026-11-06'

    def tearDown(self):
        self._tmp.cleanup()

    def _write_flag(self, payload):
        self.otm.PAUSE_FLAG.write_text(json.dumps(payload), encoding='utf-8')

    def _run(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.otm.main()
        return buf.getvalue()

    def test_flag_path_is_shared_with_state(self):
        """标志与 STATE 同目录 → 两链读同一份，一处放置即同时生效。"""
        self.assertEqual(self.otm.PAUSE_FLAG.name, 'overseas-buy-pause.json')
        self.otm.PAUSE_FLAG = None
        # 模块常量在真实部署里由 STATE.parent 推导，测试重建一份验证推导规则
        fresh = _load()
        self.assertEqual(fresh.PAUSE_FLAG, fresh.STATE.parent / 'overseas-buy-pause.json')

    def test_pause_suppresses_all_buy_signals(self):
        """paused=true → 纳指启动与日经二档都不推送。"""
        self._write_flag({'paused': True, 'scope': ['159866', '513300']})
        out = self._run()
        self.assertNotIn('纳指方案可启动', out)
        self.assertNotIn('第二档', out)
        self.assertEqual(out, '')

    def test_pause_keeps_stop_signal(self):
        """暂停买入不得拦止损（风控卖出必须仍响）。"""
        self._write_flag({'paused': True})
        self.otm.check_nikkei = lambda: (list(STOP_ONLY), dict(price=1.199, low=1.198))
        out = self._run()
        self.assertIn('止损', out)
        self.assertNotIn('纳指方案可启动', out)

    def test_pause_records_state_flag(self):
        """暂停生效须在 state 留痕，供事后审计。"""
        self._write_flag({'paused': True})
        self._run()
        state = json.loads(self.otm.STATE.read_text(encoding='utf-8'))
        self.assertTrue(state.get('buy_paused'))

    def test_no_flag_behaves_as_baseline(self):
        """标志缺失 → 买入信号照常推（不改变基线行为）。"""
        out = self._run()
        self.assertIn('纳指方案可启动', out)
        self.assertIn('第二档', out)

    def test_paused_false_behaves_as_baseline(self):
        """paused=false → 视为已解除，买入信号照常推。"""
        self._write_flag({'paused': False, 'reason': 'resumed'})
        out = self._run()
        self.assertIn('纳指方案可启动', out)
        state = json.loads(self.otm.STATE.read_text(encoding='utf-8'))
        self.assertFalse(state.get('buy_paused'))

    def test_corrupt_flag_falls_back_to_baseline(self):
        """标志损坏 → 不暂停（可逆开关，不因坏文件锁死交易）。"""
        self.otm.PAUSE_FLAG.write_text('{broken', encoding='utf-8')
        out = self._run()
        self.assertIn('纳指方案可启动', out)

    def test_resume_after_pause_pushes_buy_again(self):
        """暂停→删除标志→恢复：买入信号重新作为新触发推送，且不产生'已解除'噪音。"""
        self._write_flag({'paused': True})
        self.assertEqual(self._run(), '')
        self.otm.PAUSE_FLAG.unlink()
        FakeDate.current = '2026-11-07'
        try:
            out = self._run()
            self.assertIn('纳指方案可启动', out)
            self.assertNotIn('触发已解除', out)
        finally:
            FakeDate.current = '2026-11-06'


if __name__ == '__main__':
    unittest.main()
