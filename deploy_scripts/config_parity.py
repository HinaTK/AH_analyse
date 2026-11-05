"""双链账本配置的只读一致性校验（2026-11-05 防漂移）。

背景：迁移对比期两条链各自读写、各自推送；00:01 的 rollover 只同步
confirmed-*.json，不同步 holdings.json，2026-11-05 09:20 曾因副本残留
buy_paused=true 导致两条链给出不同建议。

本模块只做只读比对，不复制、不镜像、不改写任何一侧文件；差异只以
「字段名 + 标的个数」形式呈现，不打印标的代码或字段值，避免泄密。

用法（DSH 包装器侧）：
    result = check_holdings_parity(dsh_home, hermes_home)
    alert = format_alert(result)          # 一致时返回 ''
    signature = alert_signature(result)   # 用于同一天去重
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = 'holdings.json'
SUBPATH = Path('cache') / 'grid-account'


@dataclass(frozen=True)
class ParityResult:
    ok: bool
    reason: str                       # 'match' | 'drift' | 'missing' | 'invalid'
    differences: tuple[str, ...]
    dsh_sha256: str | None
    hermes_sha256: str | None


def holdings_path(home: Path) -> Path:
    return Path(home) / SUBPATH / CONFIG_FILE


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _field_diff(dsh: object, hermes: object) -> tuple[str, ...]:
    """只返回字段名与标的个数，绝不返回标的代码或字段值。"""
    if not isinstance(dsh, dict) or not isinstance(hermes, dict):
        return ('holdings 结构不是对象',)
    a, b = dsh.get('holdings'), hermes.get('holdings')
    if not isinstance(a, dict) or not isinstance(b, dict):
        return ('holdings 结构不是对象',)
    codes = set(a) | set(b)
    keys = set()
    for code in codes:
        left = a.get(code) or {}
        right = b.get(code) or {}
        if not isinstance(left, dict):
            left = {}
        if not isinstance(right, dict):
            right = {}
        keys |= set(left) | set(right)
    diff = []
    for key in sorted(keys):
        count = 0
        for code in codes:
            left = a.get(code) or {}
            right = b.get(code) or {}
            if not isinstance(left, dict):
                left = {}
            if not isinstance(right, dict):
                right = {}
            if left.get(key) != right.get(key):
                count += 1
        if count:
            diff.append(f'{key}（{count} 个标的不一致）')
    return tuple(diff)


def check_holdings_parity(dsh_home: Path, hermes_home: Path) -> ParityResult:
    """只读比对两份 holdings.json。缺失、损坏均返回 ok=False，不抛异常。"""
    dsh_file = holdings_path(dsh_home)
    hermes_file = holdings_path(hermes_home)
    if not dsh_file.is_file() or not hermes_file.is_file():
        missing = []
        if not dsh_file.is_file():
            missing.append('DSH 副本')
        if not hermes_file.is_file():
            missing.append('Hermes 生产')
        return ParityResult(False, 'missing',
                            (f'{"、".join(missing)} holdings.json 缺失',),
                            _sha256(dsh_file) if dsh_file.is_file() else None,
                            _sha256(hermes_file) if hermes_file.is_file() else None)
    dsh_sha = _sha256(dsh_file)
    hermes_sha = _sha256(hermes_file)
    if dsh_sha == hermes_sha:
        return ParityResult(True, 'match', (), dsh_sha, hermes_sha)
    try:
        dsh_obj = json.loads(dsh_file.read_text(encoding='utf-8'))
        hermes_obj = json.loads(hermes_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ParityResult(False, 'invalid', ('holdings.json 无法解析',),
                            dsh_sha, hermes_sha)
    diff = _field_diff(dsh_obj, hermes_obj)
    return ParityResult(False, 'drift', diff or ('字节内容不一致',),
                        dsh_sha, hermes_sha)


def format_alert(result: ParityResult) -> str:
    """一致返回空串；否则返回可推送的告警文本（不含标的代码与字段值）。"""
    if result.ok:
        return ''
    head = '⚠️【双链配置漂移告警】DSH 副本与 Hermes 生产的 holdings.json 不一致。'
    if result.reason == 'missing':
        body = '；'.join(result.differences)
    elif result.reason == 'invalid':
        body = '；'.join(result.differences)
    else:
        body = '差异字段：' + ('；'.join(result.differences) or '字节内容不一致')
    tail = ('本次仅只读校验，未复制、未镜像、未改写任何账本或配置；'
            '请人工核对后按需从只读源复制，并确认是否为有意差异。')
    return f'{head}\n{body}\n{tail}'


def alert_signature(result: ParityResult) -> str:
    """告警内容指纹；一致时返回空串，供同一天去重。"""
    if result.ok:
        return ''
    raw = f'{result.reason}|{result.dsh_sha256}|{result.hermes_sha256}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
