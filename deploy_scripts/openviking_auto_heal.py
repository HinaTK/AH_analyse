#!/usr/bin/env python3
"""OpenViking auto-heal — check health and restart the server if down.

Runs via Hermes cron every 5 minutes.

通知策略（2026-10-31 用户明确要求"成功不用告诉我，只有失败才汇报"）：
- 健康            → 完全静默
- 挂了但自愈成功   → 完全静默（用户不需要知道）
- 自愈失败/没回来  → 输出一条干净的中文告警（cron 原样推送）
- 一小时内反复重启 ≥3 次 → 抖动告警（自愈"成功"但服务不稳，仍属失败）

exit code 一律 0：cron 对 exit!=0 的脚本会套上
"Cron 'xxx' failed: Script exited with code 1 stdout: ..." 的机器外壳并截断正文，
用户读不了。告警正文本身就是信号，不靠 exit code。

Restarts the server directly as a detached process (does NOT depend on the
Windows scheduled task or supervisor, which can silently lose registration).

历史事故（勿重犯）：
- 13:50 自愈成功却 return 1 → cron 标 failed 误报（用户当天两次抱怨）。
- 15:05 start_server 用 OV_HOME / "logs" 拼路径（OV_HOME 是 str）→ TypeError，
  重启在落盘阶段就崩，守卫自己成了故障点。一律 os.path.join。
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

OV_HOME = r"C:\Users\Administrator\.openviking"
SERVER_EXE = os.path.join(OV_HOME, "venv", "Scripts", "openviking-server.exe")
CONFIG_FILE = os.path.join(OV_HOME, "ov.conf")
CLI_CONFIG_FILE = os.path.join(OV_HOME, "ovcli.conf")
STATE_FILE = os.path.join(OV_HOME, "state", "autoheal-state.json")
HEALTH_URL = "http://127.0.0.1:1933/health"
HOST = "127.0.0.1"
PORT = 1933
START_TIMEOUT_S = 45  # server can take ~10s to bind; allow margin

# 抖动判定：一小时内重启 ≥3 次 = 服务不稳定，虽然每次都"自愈成功"也要报
FLAP_WINDOW_S = 3600
FLAP_THRESHOLD = 3
FLAP_ALERT_DEDUPE_S = 3600  # 抖动告警一小时内只报一次，不刷屏

CST = timezone(timedelta(hours=8))

# Detach so the server survives this short-lived cron process.
DETACHED_FLAGS = (
    subprocess.DETACHED_PROCESS
    | subprocess.CREATE_NEW_PROCESS_GROUP
    | subprocess.CREATE_NO_WINDOW
)


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def is_healthy():
    """Return (healthy, detail)."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") == "ok" and payload.get("healthy") is True:
            return True, f"version={payload.get('version', '?')}"
        return False, f"unhealthy payload: {payload}"
    except Exception as exc:  # noqa: BLE001 - any transport failure = down
        return False, f"{type(exc).__name__}: {exc}"


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("restarts", [])
            return data
    except (OSError, ValueError):
        pass
    return {"restarts": []}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except OSError:
        pass  # 状态落盘失败不该让守卫本身崩（事故2教训）


def record_restart(state):
    """记录本次重启，只保留窗口内的记录。返回窗口内重启次数。"""
    now = time.time()
    restarts = [t for t in state.get("restarts", []) if now - t <= FLAP_WINDOW_S]
    restarts.append(now)
    state["restarts"] = restarts
    save_state(state)
    return len(restarts)


def start_server():
    """Launch openviking-server detached. Returns (ok, detail)."""
    if not os.path.exists(SERVER_EXE):
        return False, f"server exe missing: {SERVER_EXE}"
    env = os.environ.copy()
    env["OPENVIKING_CONFIG_FILE"] = CONFIG_FILE
    env["OPENVIKING_CLI_CONFIG_FILE"] = CLI_CONFIG_FILE
    log_fh = None
    try:
        # 2026-10-31: 服务器输出不再吞进 DEVNULL——崩溃原因下次有据可查
        # 2026-10-31 事故2: 此处曾写 OV_HOME / "logs" / ... 而 OV_HOME 是 str，
        # 抛 TypeError 使重启在落盘阶段就崩 → 守卫自己变成故障点。一律 os.path.join。
        log_dir = os.path.join(OV_HOME, "logs")
        os.makedirs(log_dir, exist_ok=True)
        server_log = os.path.join(log_dir, "server-autoheal.log")
        log_fh = open(server_log, "ab")
        subprocess.Popen(
            [SERVER_EXE, "--host", HOST, "--port", str(PORT)],
            cwd=OV_HOME,
            env=env,
            creationflags=DETACHED_FLAGS,
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"launch failed: {type(exc).__name__}: {exc}"
    finally:
        # 子进程已继承句柄；父进程必须关掉，否则每次重启漏一个句柄（测试里表现为临时目录删不掉）
        if log_fh is not None:
            log_fh.close()
    return True, "launched"


def alert(lines):
    """输出告警正文（cron 原样推送给用户）。"""
    print("\n".join(lines))


def flap_alert_if_needed(state, count):
    """反复重启→告警（一小时内只报一次）。返回是否已告警。"""
    if count < FLAP_THRESHOLD:
        return False
    now = time.time()
    last = state.get("last_flap_alert") or 0
    if now - last < FLAP_ALERT_DEDUPE_S:
        return False
    state["last_flap_alert"] = now
    save_state(state)
    alert([
        f"⚠️ OpenViking 一小时内已重启 {count} 次，虽然每次都救回来了，但服务不稳定。",
        f"   最近一次：{now_str()}",
        "   建议查一下 C:\\Users\\Administrator\\.openviking\\logs\\observe.log 里的报错"
        "（常见：模型接口超时、磁盘空间不足）。",
    ])
    return True


def main():
    healthy, detail = is_healthy()
    if healthy:
        state = load_state()
        if state.get("restarts"):
            state["restarts"] = []
            save_state(state)
        return 0  # 健康：静默

    ok, launch_detail = start_server()
    if not ok:
        alert([
            f"❌ OpenViking 挂了，自动重启也失败了（{now_str()}）",
            f"   故障原因：{detail}",
            f"   重启失败：{launch_detail}",
            "   需要你手动跑一下 C:\\Users\\Administrator\\.openviking\\start-openviking.cmd",
        ])
        return 0

    deadline = time.time() + START_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(3)
        healthy2, _detail2 = is_healthy()
        if healthy2:
            state = load_state()
            count = record_restart(state)
            flap_alert_if_needed(state, count)
            return 0  # 自愈成功：静默（抖动除外）

    healthy3, detail3 = is_healthy()
    if healthy3:
        state = load_state()
        count = record_restart(state)
        flap_alert_if_needed(state, count)
        return 0  # 晚到恢复也是成功：静默

    alert([
        f"❌ OpenViking 重启失败，{START_TIMEOUT_S} 秒后仍然连不上（{now_str()}）",
        f"   故障原因：{detail}",
        f"   现状：{detail3}",
        "   已尝试自动拉起但无效，需要人工介入："
        "先跑 C:\\Users\\Administrator\\.openviking\\start-openviking.cmd，"
        "再看 logs\\server-autoheal.log 和 observe.log 的报错。",
    ])
    return 0


if __name__ == "__main__":
    sys.exit(main())
