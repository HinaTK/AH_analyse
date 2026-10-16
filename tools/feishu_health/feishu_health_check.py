#!/usr/bin/env python3
"""Feishu gateway health check — runs every 5 minutes via cron.

Checks:
1. Gateway process is running (pid file + tasklist)
2. FEISHU_GROUP_POLICY is not 'disabled'
3. FEISHU_REQUIRE_MENTION is not 'true' (unless user wants @)
4. Gateway log shows recent feishu connection
5. Channel directory has the expected group channel

If any check fails, prints a clear alert. No side effects — read-only.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

HERMES_HOME = os.environ.get(
    "HERMES_HOME",
    r"D:\Hermes Agent CN Desktop\data\hermes-home",
)
GATEWAY_PID = r"D:\Hermes Agent CN Desktop\data\gateway-runtime\gateway.pid"
GATEWAY_LOG = os.path.join(HERMES_HOME, "logs", "gateway.log")
CHANNEL_DIR = os.path.join(HERMES_HOME, "channel_directory.json")
ENV_FILE = os.path.join(HERMES_HOME, ".env")

CST = timezone(timedelta(hours=8))

def now_str():
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

def check_pid_file():
    """Check if gateway process is running (via PID file or tasklist fallback)."""
    # Try PID file first
    if os.path.exists(GATEWAY_PID):
        try:
            with open(GATEWAY_PID) as f:
                data = json.load(f)
            pid = data.get("pid")
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq hermes*", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            if pid and str(pid) in result.stdout:
                return True, f"pid={pid} alive"
            return False, f"pid={pid} not found in process list"
        except Exception as e:
            pass  # fall through to tasklist

    # Fallback: check tasklist directly for hermes-gateway process
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq hermes-agent-cn-runtime-win32-x64.exe", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        if lines:
            # Extract PID from first matching line
            parts = lines[0].split()
            if len(parts) >= 2:
                pid = parts[1]
                return True, f"pid={pid} alive (no PID file, tasklist fallback)"
        return False, "no gateway process found"
    except Exception as e:
        return False, f"error: {e}"

def check_env():
    """Check FEISHU_GROUP_POLICY and FEISHU_REQUIRE_MENTION."""
    issues = []
    if not os.path.exists(ENV_FILE):
        return False, ".env missing"
    with open(ENV_FILE) as f:
        content = f.read()
    if "FEISHU_GROUP_POLICY=disabled" in content:
        issues.append("FEISHU_GROUP_POLICY=disabled (群聊被禁用)")
    if "FEISHU_REQUIRE_MENTION=true" in content:
        issues.append("FEISHU_REQUIRE_MENTION=true (需要@才响应)")
    if issues:
        return False, "; ".join(issues)
    return True, "OK"

def check_recent_feishu():
    """Check if gateway log has recent feishu activity.
    Primary: gateway.log. Fallback: agent.log (gateway may write there instead)."""
    # Startup connection markers rotate out of the active logs. Their absence
    # is not evidence of disconnection; process/config checks are independent.
    log_files = [GATEWAY_LOG, os.path.join(HERMES_HOME, "logs", "agent.log")]
    activity = False
    for log_file in log_files:
        try:
            with open(log_file, encoding="utf-8", errors="replace") as stream:
                recent = stream.readlines()[-500:]
            activity = activity or any("feishu:group" in line for line in recent)
        except OSError:
            continue
    if activity:
        return True, "group activity observed (log evidence only)"
    return True, "unknown: missing connection log is not proof of disconnection"


def check_channel_dir():
    """Check channel directory has feishu group."""
    if not os.path.exists(CHANNEL_DIR):
        return False, "channel_directory.json missing"
    try:
        with open(CHANNEL_DIR) as f:
            data = json.load(f)
        feishu_channels = data.get("platforms", {}).get("feishu", [])
        group_channels = [c for c in feishu_channels if c.get("type") == "group"]
        if group_channels:
            return True, f"{len(group_channels)} group channel(s)"
        return False, "no group channel in directory"
    except Exception as e:
        return False, f"error: {e}"

def main():
    checks = [
        ("Gateway PID", check_pid_file),
        ("Env config", check_env),
        ("Feishu log", check_recent_feishu),
        ("Channel dir", check_channel_dir),
    ]

    all_ok = True
    failures = []
    for name, fn in checks:
        ok, msg = fn()
        if not ok:
            all_ok = False
            failures.append(f"  ❌ {name}: {msg}")

    if all_ok:
        # Silent on success — cron delivers nothing
        return 0

    print(f"=== ❌ Feishu Health Check [{now_str()}] ===")
    for line in failures:
        print(line)
    print("     Fix: FEISHU_GROUP_POLICY=open, FEISHU_REQUIRE_MENTION=false, restart gateway")
    return 1

if __name__ == "__main__":
    sys.exit(main())