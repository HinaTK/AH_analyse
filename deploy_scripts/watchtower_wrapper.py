#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""观察哨 cron 入口：直接调用 watchtower_monitor（自身已带 watchdog 静默逻辑）。

解释器钉子（蓝本 rate_ignition_monitor_wrapper.py，2026-10-29 cron 部署事故教训：
cron 会话的 sys.executable 不是纯 python，而是 hermes CLI 二进制——
用它起子进程时脚本路径被当成 CLI 参数，argparse 直接拒绝，只吐 usage 文本）。
因此：本 wrapper 接力到系统 312；子进程一律显式 SYSTEM_PY，绝不信任 sys.executable。

中转铁律（2026-11-03 用户"这都不是表格"事故）：子进程 stdout 是 Windows 文本模式
（\r\n）；wrapper 若用 print() 中转，会被本进程文本模式再翻译成 \r\r\n，Hermes
按通用换行读成双换行 → 表格每行之间被塞空行 → 飞书表格不渲染。中转必须走
relay()：规范化为 \n 后经 sys.stdout.buffer 二进制直写，绕开文本翻译。
"""
import subprocess
import sys

SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'
_IS_312 = sys.version_info[:2] == (3, 12) and 'Programs' in sys.executable

if __name__ == '__main__' and not _IS_312:
    import os
    sys.stdout.flush(); sys.stderr.flush()
    sys.exit(subprocess.call([SYSTEM_PY, os.path.abspath(__file__)] + sys.argv[1:]))

MONITOR = r"D:/Code/AH_analyse/tools/watchtower_monitor.py"


def relay(raw: bytes):
    """子进程 stdout 原样中转：换行统一为 \\n 后二进制写出，禁止文本模式二次翻译。"""
    if not raw:
        return
    text = raw.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sys.stdout.flush()
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def main():
    r = subprocess.run([SYSTEM_PY, MONITOR], capture_output=True, timeout=300)
    relay(r.stdout)
    if r.returncode != 0:
        print(f"watchtower 执行失败:\n{r.stderr.decode('utf-8', errors='replace')[:400]}")
        sys.exit(1)


if __name__ == '__main__':
    main()
