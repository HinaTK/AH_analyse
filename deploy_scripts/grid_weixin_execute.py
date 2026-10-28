"""09:31 conditional advice, never automatic broker orders.

2026-10-28 修复：cron 调度器使用 hermes 自带 Python 3.14（无 pandas），
confirmed_runtime → judge_entry 链路 ImportError 被 ops_main 的
except 吞掉 → 门控静默失效（09:20 推了 589720/159363 买入建议）。
修复方式：本 launcher 钉死使用系统 Python312（有 pandas/全套依赖），
检测到当前解释器不对时用正确解释器重新启动自身。
"""
import os
import sys

REQUIRED_MARK = 'Python 3.12'  # 系统Python312 路径特征
SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'


def _is_correct_interpreter():
    return sys.version_info[:2] == (3, 12) and 'Programs' in sys.executable


def _relaunch_with_system_python():
    """用 Python312 重新执行本脚本，透传参数与退出码。"""
    argv = [SYSTEM_PY, os.path.abspath(__file__)] + sys.argv[1:]
    import subprocess
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.call(argv)


if __name__ == '__main__':
    if not _is_correct_interpreter():
        rc = _relaunch_with_system_python()
        sys.exit(rc)
    sys.path.insert(0, 'D:/Code/AH_analyse')
    from confirmed_runtime import ops_main, safe_entrypoint

    safe_entrypoint(ops_main, ['--phase', 'grid', *sys.argv[1:]])
