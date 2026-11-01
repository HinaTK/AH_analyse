"""Windows 计划任务用的通用包装器：跑一个脚本，把它的 stdout 推到飞书。

背景
----
Hermes 的 cron 只做两件事：按点触发 + 把脚本 stdout 投递到飞书。搬到 Windows
计划任务后，触发由 schtasks 负责，投递由本包装器补上，脚本本身不用改一行。

为什么不让计划任务直接跑脚本
----------------------------
计划任务选「不管用户是否登录」时进程跑在 session 0，没有控制台，`sys.stdout`
可能是 None，脚本里的 `print` 会抛 AttributeError。本包装器始终用管道捕获子进程
输出，子进程永远有合法的 stdout，两种情况都成立。

用法
----
    pythonw run_and_push.py --job intraday          # 计划任务用这个
    pythonw run_and_push.py --job intraday --dry    # 跑一遍不推送，用于比对
    pythonw run_and_push.py --name 临时 --script x.py --push on   # 临时任务

退出码恒为 0：计划任务把非 0 当失败并弹提示，而真正的失败信息已经写进日志、
并且单独推送了一条告警。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))

SYSTEM_PY = Path(r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe')
SCRIPTS = Path(r'D:\Hermes Agent CN Desktop\data\hermes-home\scripts')
REPO = Path(r'D:\Code\AH_analyse')

# 迁移后的账本根目录：root_from_home() 取 HERMES_HOME/cache/grid-account。
# 原 Hermes 目录只读保留（复制而非剪切），便于随时回滚。
DEFAULT_HERMES_HOME = REPO / '.cache' / 'grid-home'
LOG_DIR = REPO / 'logs' / 'scheduler'

# 飞书单条文本上限约 30KB，留足余量。
MAX_PUSH_CHARS = 8000

# DSH-IM 主动投递（复用设置页里已接入的飞书机器人，不依赖 Hermes webhook）。
# 目标要在「设置 → IM机器人 → 齿轮 → 新建目标」里建，名字与此处一致。
IM_BOT_ID = 'bot_33dda378bac343d695e4e63180c53d11'
IM_TARGET_ID = 'grid-alerts'

# 任务注册表：id -> 显示名 / 脚本 / 工作目录 / 是否推送
# 与 Hermes cron/jobs.json 的 13 个脚本任务一一对应（gateway_keeper 守护的是
# Hermes 自己，随 Hermes 退役，不迁移）。
JOBS: dict[str, dict[str, object]] = {
    'preview_0910':   {'name': '网格0910预告',      'script': 'grid_weixin_preview.py',           'cwd': None,  'push': 'off'},
    'morning_0920':   {'name': '网格0920盘前建议',  'script': 'grid_weixin_execute.py',           'cwd': None,  'push': 'on'},
    'intraday':       {'name': '网格盘中触价',      'script': 'grid_weixin_intraday.py',          'cwd': None,  'push': 'on'},
    'eod_1520':       {'name': '网格1520收盘',      'script': 'grid_eod_decision.py',             'cwd': None,  'push': 'on'},
    'weekly_fri':     {'name': '网格周五1525周报',  'script': 'grid_weekly_rotation.py',          'cwd': None,  'push': 'on', 'timeout': 2700},
    'regime_1530':    {'name': '网格1530门控缓存',  'script': 'grid_regime_cache.py',             'cwd': None,  'push': 'off'},
    'market_1535':    {'name': '市况1535右侧信号',  'script': 'market_phase_monitor.py',          'cwd': None,  'push': 'on'},
    'rate_1540':      {'name': '利率1540点火',      'script': 'rate_ignition_monitor_wrapper.py', 'cwd': None,  'push': 'on'},
    'watchtower_1550':{'name': '观察哨1550',        'script': 'watchtower_wrapper.py',            'cwd': None,  'push': 'on'},
    'overseas':       {'name': '海外盘中触发',      'script': 'overseas_trigger_monitor.py',      'cwd': None,  'push': 'on'},
    'midnight_0001':  {'name': '网格0001可卖同步',  'script': 'grid_midnight_rollover.py',        'cwd': None,  'push': 'off'},
    'git_2300':       {'name': '运维2300git推送',   'script': 'git_daily_push.py',                'cwd': str(REPO), 'push': 'off'},
    'openviking':     {'name': '运维OpenViking守卫','script': 'openviking_auto_heal.py',          'cwd': None,  'push': 'on'},
}


def _log(name: str, message: str) -> None:
    """按天写日志。pythonw 下没有控制台，绝不能依赖 print。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(CST).strftime('%Y%m%d')
        line = f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        with (LOG_DIR / f'{name}-{stamp}.log').open('a', encoding='utf-8') as fh:
            fh.write(line)
    except OSError:
        pass


def _save_latest(name: str, body: str) -> None:
    """把本次输出单独落一份 latest 文件，供 DSH 任务板的判断卡片直接读。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')
        (LOG_DIR / f'{name}-latest.txt').write_text(
            f'# {name} 生成于 {stamp}\n{body}\n' if body else f'# {name} 生成于 {stamp}\n（无输出）\n',
            encoding='utf-8',
        )
    except OSError:
        pass


def _webhook() -> str:
    """AH_FEISHU_WEBHOOK 是用户级环境变量，计划任务继承得到。"""
    raw = (os.environ.get('AH_FEISHU_WEBHOOK') or '').strip()
    if raw.startswith('{'):
        # 兼容 {web_hook, https://...} 这种 erlang 元组写法
        start = raw.find('http')
        raw = raw[start:].rstrip('}').strip() if start >= 0 else ''
    return raw


def _push_webhook(text: str) -> bool:
    hook = _webhook()
    if not hook:
        _log('_push', '没有 AH_FEISHU_WEBHOOK，跳过 webhook')
        return False
    body = text if len(text) <= MAX_PUSH_CHARS else text[:MAX_PUSH_CHARS] + '\n…（内容过长已截断，完整内容见日志）'
    payload = json.dumps({'msg_type': 'text', 'content': {'text': body}}, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        hook,
        data=payload,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode('utf-8', 'replace')
        data = json.loads(raw) if raw.strip().startswith('{') else {}
        code = data.get('code', data.get('StatusCode', 0))
        ok = code in (0, None)
        _log('_push', f'webhook 返回 code={code} ok={ok} body={raw[:200]}')
        return ok
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _log('_push', f'webhook 失败 {type(exc).__name__}: {exc}')
        return False


def _harness_ports() -> list[int]:
    """找出 DeepSeek Harness 正在监听的 loopback 端口（Web 端口每次启动可能变）。"""
    try:
        listing = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq DeepSeek Harness.exe', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except OSError:
        return []
    pids = set()
    for line in listing.splitlines():
        parts = [chunk.strip('"') for chunk in line.strip().split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            pids.add(parts[1])
    if not pids:
        return []
    try:
        table = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True, timeout=20).stdout
    except OSError:
        return []
    ports = []
    for line in table.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[3] != 'LISTENING' or fields[4] not in pids:
            continue
        address, _, port = fields[1].rpartition(':')
        if address in ('127.0.0.1', '[::1]') and port.isdigit():
            ports.append(int(port))
    return ports


def _im_urls() -> list[str]:
    cache = REPO / '.cache' / 'dsh-im-endpoint.txt'
    urls: list[str] = []
    if cache.exists():
        try:
            remembered = cache.read_text(encoding='utf-8').strip()
        except OSError:
            remembered = ''
        if remembered:
            urls.append(remembered)
    for port in _harness_ports():
        url = f'http://127.0.0.1:{port}/api/dsh-im/delivery/messages'
        if url not in urls:
            urls.append(url)
    return urls


def _push_im(text: str) -> bool:
    """走 DSH-IM 主动投递：不依赖已停用的 Hermes webhook，也复用同一个飞书机器人。"""
    body = text if len(text) <= MAX_PUSH_CHARS else text[:MAX_PUSH_CHARS] + '\n…（内容过长已截断，完整内容见日志）'
    payload = json.dumps(
        {'botId': IM_BOT_ID, 'targetId': IM_TARGET_ID, 'text': body},
        ensure_ascii=False,
    ).encode('utf-8')
    for url in _im_urls():
        request = urllib.request.Request(
            url,
            data=payload,
            headers={'Content-Type': 'application/json; charset=utf-8'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode('utf-8', 'replace') if exc.fp else ''
            code = ''
            if raw.strip().startswith('{'):
                try:
                    code = str(((json.loads(raw).get('error') or {}).get('code')) or '')
                except ValueError:
                    code = ''
            if code == 'unknown-target':
                # 服务器认出来了，只是目标还没建：记下端口，等目标建好后自动生效
                _log('_push', f'IM 接口可用，但目标 {IM_TARGET_ID} 未创建 @ {url}')
                _remember_endpoint(url)
                return False
            if code in ('unknown-bot', 'bad-request'):
                _log('_push', f'IM 拒绝 {code} @ {url}')
                continue
            _log('_push', f'IM HTTP {exc.code} @ {url}: {raw[:200]}')
            continue
        except (urllib.error.URLError, OSError, ValueError) as exc:
            _log('_push', f'IM 连接失败 @ {url}: {type(exc).__name__}: {exc}')
            continue
        if raw.strip().startswith('{'):
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            if data.get('sent') is True:
                _remember_endpoint(url)
                _log('_push', f'IM 已发送 @ {url}')
                return True
        _log('_push', f'IM 未返回 sent @ {url}: {raw[:200]}')
    return False


def _remember_endpoint(url: str) -> None:
    try:
        cache = REPO / '.cache' / 'dsh-im-endpoint.txt'
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists() or cache.read_text(encoding='utf-8').strip() != url:
            cache.write_text(url, encoding='utf-8')
    except OSError:
        pass


def _push(text: str) -> bool:
    """优先走 DSH-IM（同一个飞书机器人），失败再退回 webhook。"""
    if _push_im(text):
        return True
    return _push_webhook(text)



def _run(script: Path, args: list[str], cwd: Path, hermes_home: Path, timeout: int) -> tuple[int, str, str]:
    python = SYSTEM_PY if SYSTEM_PY.exists() else Path(sys.executable)
    env = dict(os.environ)
    env['HERMES_HOME'] = str(hermes_home)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    completed = subprocess.run(
        [str(python), str(script), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
    )
    return completed.returncode, completed.stdout or '', completed.stderr or ''


def main() -> int:
    parser = argparse.ArgumentParser(description='跑脚本并把输出推到飞书')
    parser.add_argument('--job', choices=sorted(JOBS), help='任务注册表里的 id')
    parser.add_argument('--name', help='临时任务的显示名')
    parser.add_argument('--script', help='临时任务的脚本绝对路径')
    parser.add_argument('--cwd', default=None, help='子进程工作目录，默认用脚本所在目录')
    parser.add_argument('--hermes-home', default=str(DEFAULT_HERMES_HOME), help='HERMES_HOME 指向的账本根目录')
    parser.add_argument('--push', choices=('on', 'off'), default=None)
    parser.add_argument('--timeout', type=int, default=None)
    parser.add_argument('--dry', action='store_true', help='跑但不推送')
    parser.add_argument('rest', nargs='*', help='透传给脚本的参数')
    options = parser.parse_args()

    if options.job:
        spec = JOBS[options.job]
        name = str(spec['name'])
        script = SCRIPTS / str(spec['script'])
        cwd = Path(str(spec['cwd'])) if spec['cwd'] else script.parent
        push = str(options.push or spec['push'])
        timeout = options.timeout or int(spec.get('timeout', 240))
    elif options.script:
        name = options.name or Path(options.script).stem
        script = Path(options.script)
        cwd = Path(options.cwd) if options.cwd else script.parent
        push = options.push or 'on'
        timeout = options.timeout or 240
    else:
        parser.error('需要 --job 或 --script')

    hermes_home = Path(options.hermes_home)
    started = time.monotonic()

    if not script.exists():
        _log(name, f'脚本不存在：{script}')
        if not options.dry:
            _push(f'【{name} 失败】脚本不存在：{script}')
        return 0

    try:
        rc, out, err = _run(script, options.rest, cwd, hermes_home, timeout)
    except subprocess.TimeoutExpired:
        _log(name, f'超时 {timeout}s')
        if not options.dry:
            _push(f'【{name} 超时】超过 {timeout}s 未结束，已放弃本次')
        return 0

    elapsed = time.monotonic() - started
    body = out.strip()
    _log(name, f'rc={rc} elapsed={elapsed:.1f}s stdout={len(out)}B stderr={len(err)}B push={push}')
    if err.strip():
        _log(name, 'stderr: ' + err.strip()[:2000])

    if rc == 0:
        _save_latest(name, body)

    if rc != 0:
        tail = (err.strip() or out.strip())[-1200:]
        if not options.dry:
            _push(f'【{name} 失败】rc={rc}，耗时 {elapsed:.0f}s\n{tail}')
        return 0

    if not body:
        _log(name, '无输出，静默结束')
        return 0

    if options.dry:
        _log(name, 'dry 模式，输出如下：\n' + body[:4000])
        return 0

    if push == 'off':
        _log(name, 'push=off，只记录不推送：\n' + body[:4000])
        return 0

    _log(name, '推送：\n' + body[:4000])
    _push(body)
    return 0


if __name__ == '__main__':
    sys.exit(main())
