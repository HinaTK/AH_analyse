"""Send scheduled stdout as a Feishu rich-text post (Hermes-compatible path).

Hermes renders Markdown tables with ``msg_type=post`` and a ``md`` node in
``zh_cn.content``. DSH-IM's proactive delivery currently sends an interactive
card instead. This module uses the same bot credentials as the DSH-IM plugin
to send a real ``post`` message, so DSH scheduled pushes match Hermes.

Secrets are read from the local credential store and never logged or printed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

DSH_HOME = Path(os.environ.get('DSH_HOME') or (Path.home() / '.dsh'))
DEFAULT_CONFIG = DSH_HOME / 'integrations' / 'dsh-feishu' / 'config.json'
DEFAULT_CREDENTIALS = DSH_HOME / '.credentials.yaml'
DEFAULT_WORKSPACES = DSH_HOME / 'integrations' / 'dsh-feishu' / 'workspaces.json'
TOKEN_URL = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
MESSAGES_URL = 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id'


def build_post_content(text: str) -> dict:
    """Build a Feishu post payload, isolating fenced code blocks like Hermes."""
    text = text or ''
    if '```' not in text:
        return {'zh_cn': {'content': [[{'tag': 'md', 'text': text}]]}}
    rows = []
    current = []
    in_code = False
    for raw_line in text.splitlines():
        is_fence = raw_line.strip().startswith('```')
        if is_fence and not in_code:
            if current:
                rows.append([{'tag': 'md', 'text': '\n'.join(current)}])
                current = []
        current.append(raw_line)
        if is_fence:
            in_code = not in_code
            if not in_code:
                rows.append([{'tag': 'md', 'text': '\n'.join(current)}])
                current = []
    if current:
        rows.append([{'tag': 'md', 'text': '\n'.join(current)}])
    return {'zh_cn': {'content': rows or [[{'tag': 'md', 'text': text}]]}}


def _read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _bot_credentials(bot_id: str, config_path: Path) -> tuple[str, str]:
    config = _read_json(config_path)
    for bot in config.get('bots', []):
        if bot.get('id') == bot_id:
            app_id, ref = bot.get('appId'), bot.get('secretRef')
            if app_id and ref:
                return str(app_id), str(ref)
    raise ValueError('未找到机器人凭据配置')


def _app_secret(ref: str, credentials_path: Path) -> str:
    for line in Path(credentials_path).read_text(encoding='utf-8').splitlines():
        match = re.match(r'^\s*' + re.escape(ref) + r'\s*:\s*(\S+)', line)
        if match:
            return match.group(1)
    raise ValueError('未找到机器人密钥')


def _open_id(bot_id: str, target_id: str, workspaces_path: Path) -> str:
    targets = _read_json(workspaces_path)['deliveryTargets'][bot_id]
    return str(targets[target_id]['route']['openId'])


def send_post(text: str, *, bot_id: str, target_id: str, opener=None,
              config_path: Path | None = None,
              credentials_path: Path | None = None,
              workspaces_path: Path | None = None) -> bool:
    """Send one post message; return True only when Feishu confirms a message id."""
    config_path = Path(config_path or DEFAULT_CONFIG)
    credentials_path = Path(credentials_path or DEFAULT_CREDENTIALS)
    workspaces_path = Path(workspaces_path or DEFAULT_WORKSPACES)
    urlopen = opener or urllib.request.urlopen
    app_id, ref = _bot_credentials(bot_id, config_path)
    secret = _app_secret(ref, credentials_path)
    receive_id = _open_id(bot_id, target_id, workspaces_path)

    token_body = json.dumps({'app_id': app_id, 'app_secret': secret}).encode('utf-8')
    token_request = urllib.request.Request(
        TOKEN_URL, data=token_body,
        headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    try:
        with urlopen(token_request, timeout=15) as response:
            token_reply = json.loads(response.read().decode('utf-8', 'replace'))
    except (OSError, urllib.error.URLError, ValueError):
        return False
    token = token_reply.get('tenant_access_token') if token_reply.get('code') == 0 else None
    if not token:
        return False

    message_body = json.dumps({
        'receive_id': receive_id,
        'msg_type': 'post',
        'content': json.dumps(build_post_content(text), ensure_ascii=False),
    }, ensure_ascii=False).encode('utf-8')
    message_request = urllib.request.Request(
        MESSAGES_URL, data=message_body,
        headers={'Content-Type': 'application/json; charset=utf-8',
                 'Authorization': 'Bearer ' + token}, method='POST')
    try:
        with urlopen(message_request, timeout=15) as response:
            reply = json.loads(response.read().decode('utf-8', 'replace'))
    except (OSError, urllib.error.URLError, ValueError):
        return False
    return reply.get('code') == 0 and bool((reply.get('data') or {}).get('message_id'))
