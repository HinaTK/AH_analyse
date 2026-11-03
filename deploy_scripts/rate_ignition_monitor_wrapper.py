#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""利率点火监控 wrapper（cron 入口，watchdog 模式）。

规则：
  - 有 🔥点火 / 🚨熄火 / ✅先行 / ✅起步 任一状态 → 完整推送
  - 状态从"触发"回落到"未触发"（解除）→ 推送一次解除通知
  - 全部信号"未触发/正常"且昨日也全部未触发 → 静默（不推送）
  - 首次运行（无状态文件）→ 推送基线
"""
import json
import subprocess
import sys
from pathlib import Path

# 解释器钉子（蓝本 deploy_scripts/grid_weixin_execute.py，2026-10-29 第4变体事故：
# cron 会话的 sys.executable 不是纯 python，而是 hermes CLI 二进制——
# 用它起子进程时脚本路径被当成 CLI 参数，argparse 直接拒绝。
# 因此：本 wrapper 接力到系统 312；子进程一律显式 SYSTEM_PY，绝不信任 sys.executable。）
SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'
_IS_312 = sys.version_info[:2] == (3, 12) and 'Programs' in sys.executable

if __name__ == '__main__' and not _IS_312:
    import os
    sys.stdout.flush(); sys.stderr.flush()
    sys.exit(subprocess.call([SYSTEM_PY, os.path.abspath(__file__)] + sys.argv[1:]))

MONITOR = r"D:/Code/AH_analyse/tools/rate_ignition_monitor.py"
QUIET_STATE = Path("D:/Code/AH_analyse/tools/rate_ignition_quiet_state.json")
TRIGGER_STATES = ("🔥", "🚨", "✅")


def run_monitor():
    r = subprocess.run([SYSTEM_PY, MONITOR, "--json"],
                       capture_output=True, timeout=180)
    if r.returncode != 0:
        print(f"rate_ignition_monitor 执行失败:\n{r.stderr.decode('utf-8', errors='replace')[:500]}")
        sys.exit(1)
    return json.loads(r.stdout.decode("utf-8", errors="replace"))


def relay(raw: bytes):
    """子进程 stdout 原样中转：换行统一为 \\n 后二进制写出，禁止文本模式二次翻译。

    （2026-11-03 观察哨表格事故同款根因：print 中转把 \\r\\n 变 \\r\\r\\n，
    通用换行读取下每行之间多一个空行，飞书表格表头与分隔行被隔开即不渲染。）
    """
    if not raw:
        return
    text = raw.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sys.stdout.flush()
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def main():
    data = run_monitor()
    sigs = data.get("signals", [])
    triggered = [s for s in sigs if any(t in s["state"] for t in TRIGGER_STATES)]
    # 任一信号数据缺失也推送（不静默掩盖故障）
    broken = [s for s in sigs if s["state"] in ("数据缺失",)]

    prev = {}
    if QUIET_STATE.exists():
        try:
            prev = json.loads(QUIET_STATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}
    had_triggered = prev.get("any_triggered", None)
    prev_names = prev.get("triggered_names", [])

    now_names = sorted(s["key"] for s in triggered)
    cleared = [k for k in prev_names if k not in now_names]

    should_push = (
        triggered or broken or had_triggered is None or cleared
    )

    if should_push:
        r = subprocess.run([SYSTEM_PY, MONITOR], capture_output=True, timeout=180)
        relay(r.stdout)
        if cleared:
            print(f"\nℹ️ 已解除: {', '.join(cleared)}（状态回落，仅告知一次）")
    else:
        # 静默：更新状态
        pass

    QUIET_STATE.write_text(json.dumps({
        "any_triggered": bool(triggered),
        "triggered_names": now_names,
    }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
