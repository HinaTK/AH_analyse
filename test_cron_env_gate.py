# -*- coding: utf-8 -*-
"""cron 环境（sys.path 无 tools/）门控不得静默失效的回归测试。

2026-10-27 09:20 实况：用户收到 589720 买入 G 格建议，⛔ 一条没有。
根因：fetch_daily_regime 函数内 `import market_phase_check`（顶层模块，
在 tools/ 下）在 cron 环境 ImportError，被外层 except Exception 吞掉，
返回 dict(adx=None) 且不带 bars → RegimeGate 全链 fail-open——
连不依赖 tools/ 的五线判定都被跳过。

修复原则：
- fetch_daily_regime 必须 import 自 tools 子包（market_phase_check 移入
  tools/ 或用 sys.path 无关的定位方式），cron 环境可用；
- ADX 拿不到时仍要返回 bars（五线判定只吃日线，不吃 ADX）；
- 只有日线本身拿不到才返回 dict(adx=None)。
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # 仓库根目录（本测试就在根下）


def run_in_clean_env(code):
    """子进程里只把仓库根目录放 sys.path，模拟 cron 环境。"""
    return subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120)


CRON_ENV_PROBE = '''
import sys
sys.path.insert(0, "{root}")
import confirmed_runtime as rt
import holdings as H

regimes = {{code: rt.fetch_daily_regime(code) for code in H.held_codes()}}
gate = rt.RegimeGate(regimes)
for code in H.held_codes():
    r = regimes[code]
    print(f"{{code}}|adx={{r.get('adx')}}|has_bars={{r.get('bars') is not None}}|blocks={{gate.blocks_buy(code)}}")
'''


class CronEnvGateTests(unittest.TestCase):
    def test_gate_does_not_silently_fail_open_in_cron_env(self):
        """cron 环境（无 tools/ 路径）门控必须给出真实判定，不是全 fail-open。

        用 10-26 收盘数据：589720/159363 五线全破必须 blocks=True。
        """
        proc = run_in_clean_env(CRON_ENV_PROBE.format(root=ROOT))
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        for code in ('sh589720', 'sz159363'):
            line = next(l for l in proc.stdout.strip().splitlines() if l.startswith(code))
            fields = line.split('|')
            # fields: code|adx=..|has_bars=..|blocks=..
            has_bars = fields[2].split('=')[1]
            blocks = fields[3].split('=')[1]
            self.assertEqual(has_bars, 'True', f'{code} 必须带 bars（五线判定数据源）')
            self.assertEqual(blocks, 'True', f'{code} 五线全破在 cron 环境也必须拦')


if __name__ == '__main__':
    unittest.main()
