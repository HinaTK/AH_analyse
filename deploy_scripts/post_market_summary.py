# -*- coding: utf-8 -*-
"""盘后只读参考四合一汇总 + 跨信号冲突裁决 + 全球市场客观快照。

将原 15:35 / 15:40 / 15:50 / 16:05 四条收盘后只读推送合并为单次汇总输出：
- 顶部直接给出「跨信号裁决」，自动揭示指数试仓与持仓门控/宏观/波动/地量之间的分歧；
- 附带轻量化「全球市场客观快照」（美股昨收 + 恒生/日经 + 汇率/黄金，纯事实不预测）；
- 高门槛事件（哨④ A 级政策或全球主要股指单日 ±2.5% 以上波动）提示按需发起深度「异动分析」；
- 省略静默小节；全部静默时零输出；单节异常不影响其余板块。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
SYSTEM_PY = Path(r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe')
DEPLOY_DIR = Path(__file__).resolve().parent

SECTIONS: tuple[tuple[str, Path], ...] = (
    ('市况右侧信号', DEPLOY_DIR / 'market_phase_monitor.py'),
    ('利率点火', DEPLOY_DIR / 'rate_ignition_monitor_wrapper.py'),
    ('观察哨', DEPLOY_DIR / 'watchtower_wrapper.py'),
    ('波动扩张观察', DEPLOY_DIR / 'volatility_expansion_watch.py'),
)

US_INDICES: tuple[tuple[str, str], ...] = (
    ('纳斯达克', 'usIXIC'),
    ('标普500', 'usINX'),
    ('道琼斯', 'usDJI'),
)
GLOBAL_EQUITY_NAMES = frozenset({'纳斯达克', '标普500', '道琼斯', '恒生指数', '日经225'})
SWING_THRESHOLD_PCT = 2.5


def _normalize_newlines(text: str) -> str:
    return (text or '').replace('\r\n', '\n').replace('\r', '\n').strip()


def _http_get(url: str, headers: dict[str, str] | None = None, encoding: str = 'utf-8', timeout: int = 8) -> str:
    merged = {'User-Agent': 'Mozilla/5.0'}
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, headers=merged)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, 'replace')


def parse_us_kline_row(name: str, sym: str, payload: dict) -> dict | None:
    """Compute US index close & daily % change from Tencent usfqkline payload."""
    try:
        node = payload['data'][sym]
        rows = node.get('day') or node.get('qfqday') or []
        if len(rows) < 2:
            return None
        prev_close = float(rows[-2][2])
        last_close = float(rows[-1][2])
        if prev_close <= 0:
            return None
        pct = (last_close / prev_close - 1.0) * 100.0
        asof = f"{rows[-1][0]} 收盘"
        return {'name': name, 'price': f'{last_close:.2f}', 'pct': pct, 'asof': asof}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _extract_assignments(raw_text: str, prefix: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    pat = re.compile(rf'(?:var\s+)?{re.escape(prefix)}([A-Za-z0-9_]+)\s*=\s*"([^"]*)"')
    for m in pat.finditer(raw_text or ''):
        out[m.group(1)] = m.group(2).split(',')
    return out


def parse_sina_indices(raw_text: str) -> list[dict]:
    """Parse HK Hang Seng and Nikkei 225 from Sina quote response."""
    parsed = _extract_assignments(raw_text, 'hq_str_')
    rows: list[dict] = []
    hk = parsed.get('rt_hkHSI')
    if hk and len(hk) >= 18 and hk[6] and hk[8]:
        try:
            rows.append({
                'name': '恒生指数',
                'price': f'{float(hk[6]):.2f}',
                'pct': float(hk[8]),
                'asof': hk[17].replace('/', '-'),
            })
        except ValueError:
            pass
    nky = parsed.get('b_NKY')
    if nky and len(nky) >= 7 and nky[1] and nky[3]:
        try:
            rows.append({
                'name': '日经225',
                'price': f'{float(nky[1]):.2f}',
                'pct': float(nky[3]),
                'asof': nky[6],
            })
        except ValueError:
            pass
    return rows


def parse_qt_macro(raw_text: str) -> list[dict]:
    """Parse USD/CNY and COMEX Gold from Tencent qt.gtimg.cn response."""
    rows: list[dict] = []
    for line in (raw_text or '').splitlines():
        m = re.match(r'^v_([A-Za-z0-9_]+)="([^"]*)";?$', line.strip())
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key == 'whUSDCNY':
            parts = val.split('~')
            if len(parts) >= 14 and parts[3] and parts[13]:
                try:
                    asof = parts[-1] if '-' in parts[-1] else ''
                    rows.append({
                        'name': '美元/人民币',
                        'price': f'{float(parts[3]):.4f}',
                        'pct': float(parts[13]),
                        'asof': asof,
                    })
                except ValueError:
                    pass
        elif key == 'hf_GC':
            parts = val.split(',')
            if len(parts) >= 13 and parts[0] and parts[1]:
                try:
                    rows.append({
                        'name': 'COMEX黄金',
                        'price': f'{float(parts[0]):.2f}',
                        'pct': float(parts[1]),
                        'asof': parts[12],
                    })
                except ValueError:
                    pass
    return rows


def fetch_global_snapshot(fetcher=None) -> tuple[list[dict], list[str]]:
    """Best-effort read-only fetch of global close & macro snapshot."""
    get_fn = fetcher or _http_get
    rows: list[dict] = []
    missing: list[str] = []

    for name, sym in US_INDICES:
        try:
            raw = get_fn(f'https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param={sym},day,,,5,qfq')
            row = parse_us_kline_row(name, sym, json.loads(raw))
            if row:
                rows.append(row)
            else:
                missing.append(name)
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            missing.append(name)

    try:
        sina_raw = get_fn(
            'https://hq.sinajs.cn/list=rt_hkHSI,b_NKY',
            headers={'Referer': 'https://finance.sina.com.cn/'},
            encoding='gbk',
        )
        sina_rows = parse_sina_indices(sina_raw)
        got_names = {r['name'] for r in sina_rows}
        rows.extend(sina_rows)
        for expected in ('恒生指数', '日经225'):
            if expected not in got_names:
                missing.append(expected)
    except (urllib.error.URLError, OSError, ValueError):
        missing.extend(['恒生指数', '日经225'])

    try:
        qt_raw = get_fn('https://qt.gtimg.cn/q=whUSDCNY,hf_GC', encoding='gbk')
        qt_rows = parse_qt_macro(qt_raw)
        got_names = {r['name'] for r in qt_rows}
        rows.extend(qt_rows)
        for expected in ('美元/人民币', 'COMEX黄金'):
            if expected not in got_names:
                missing.append(expected)
    except (urllib.error.URLError, OSError, ValueError):
        missing.extend(['美元/人民币', 'COMEX黄金'])

    return rows, missing


def render_global_snapshot(rows: list[dict], missing: list[str]) -> str:
    if not rows and not missing:
        return ''
    lines = ['### 🌐 全球市场客观快照（只读参考，不预测）', '']
    if rows:
        lines += ['| 市场/资产 | 最新 | 涨跌幅 | 口径 |', '|---|---:|---:|---|']
        for r in rows:
            lines.append(f"| {r['name']} | {r['price']} | {r['pct']:+.2f}% | {r.get('asof') or '实时'} |")
    if missing:
        lines.append(f"⚠️ 全球快照部分缺失：{', '.join(missing)}")
    return '\n'.join(lines)


def analyze_conflicts(
    section_outputs: dict[str, str],
    global_rows: list[dict] | None = None,
    global_missing: list[str] | None = None,
    has_child_failure: bool = False,
) -> list[str]:
    """Detect real cross-signal contradictions and high-threshold news triggers."""
    market = section_outputs.get('市况右侧信号', '')
    rate = section_outputs.get('利率点火', '')
    watch = section_outputs.get('观察哨', '')
    vol = section_outputs.get('波动扩张观察', '')

    notes: list[str] = []
    has_probe = any(k in market for k in ('试仓买入', '买入·', '持有·'))
    has_gate_block = any(
        k in market for k in ('方向仓观察·0成', '⏸️ 暂停买入', '⛔ 禁止建仓', '迁移退出·0成')
    )
    has_flameout = '🚨熄火' in rate
    has_vol_exp = '【波动扩张观察' in vol
    non_dry = ('哨①量能地量' in watch) and ('未到' in watch)
    has_a_policy = ('A级' in watch) or ('[A]' in watch)
    has_b_policy = (('B级命中' in watch) or ('[B]' in watch)) and not has_a_policy

    if has_probe and has_gate_block:
        notes.append('存在分歧：指数现局部试探读数，但持仓网格仍受门控拦买/退出限制（0成），不构成买单依据。')
    if has_probe and (has_flameout or has_vol_exp):
        notes.append('存在分歧：宏观利率熄火或波动扩张偏逆风，与市况偏多读数相反，按只读参考互有矛盾不执行。')
    if has_probe and non_dry:
        notes.append('量能地量尚缺，仅属局部先行试探，非全市场右侧确认。')
    if has_b_policy:
        notes.append('政策仅 B 级常规机制消息（仅背景记录），不升级为反转依据。')
    if has_a_policy:
        notes.append('🚨 触发 A 级政策事件（924 级量级/新工具），建议按需发起「异动分析 / 大盘分析」核实消息面传导。')

    swings = [
        f"{r['name']}({r['pct']:+.2f}%)"
        for r in (global_rows or [])
        if r.get('name') in GLOBAL_EQUITY_NAMES and abs(float(r.get('pct', 0.0))) >= SWING_THRESHOLD_PCT
    ]
    if swings:
        notes.append(
            f"全球市场单日显著波动（{'、'.join(swings)}），需结合隔夜风险；如需消息面归因可按需发起「异动分析」。"
        )

    any_missing = has_child_failure or any(
        '数据缺失' in text or '⚠️【' in text for text in section_outputs.values()
    )
    if any_missing:
        notes.append('部分数据源异常或缺失，当前汇总按有限样本降级参考。')
    if global_missing:
        notes.append(f"全球快照部分缺失（{', '.join(global_missing)}），未覆盖项不作外推。")

    if not notes:
        notes.append('各只读参考口径无明显矛盾；仍仅作参考，实际动作以 09:20 盘前建议与跨境止损为准。')
    return notes


def _run_child(label: str, script: Path, timeout: int = 240) -> tuple[int, str, str]:
    """Run one post-market child script without spawning a console window."""
    python = SYSTEM_PY if SYSTEM_PY.exists() else Path(sys.executable)
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    try:
        completed = subprocess.run(
            [str(python), str(script)],
            cwd=str(script.parent),
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
        return completed.returncode, completed.stdout or '', completed.stderr or ''
    except subprocess.TimeoutExpired:
        return 124, '', f'{label}超时（>{timeout}s）'
    except OSError as exc:
        return 1, '', f'{type(exc).__name__}: {exc}'


def collect_summary(
    runner=None,
    global_fetcher=None,
    today: str | None = None,
    sections: tuple[tuple[str, Path], ...] = SECTIONS,
) -> tuple[str, int]:
    """Collect, reconcile, and merge post-market read-only monitors + global snapshot."""
    run_fn = runner or _run_child
    day = today or datetime.now(CST).strftime('%Y-%m-%d')
    blocks: list[str] = []
    section_map: dict[str, str] = {}
    ok_count = 0
    fail_count = 0

    for label, script in sections:
        rc, out, err = run_fn(label, script)
        body = _normalize_newlines(out)
        err_text = _normalize_newlines(err)
        if rc == 0:
            ok_count += 1
            section_map[label] = body
            if body:
                blocks.append(body)
        else:
            fail_count += 1
            detail = err_text or body or f'rc={rc}'
            err_block = f'⚠️【{label} 异常】{detail[-600:]}'
            section_map[label] = err_block
            blocks.append(err_block)

    if not blocks:
        return '', 0

    g_fetch = global_fetcher or fetch_global_snapshot
    global_rows, global_missing = g_fetch()
    global_block = render_global_snapshot(global_rows, global_missing)
    if global_block:
        blocks.append(global_block)

    verdicts = analyze_conflicts(
        section_map,
        global_rows=global_rows,
        global_missing=global_missing,
        has_child_failure=fail_count > 0,
    )
    verdict_block = '⚖️ **跨信号裁决**\n' + '\n'.join(f'- {line}' for line in verdicts)
    header = f'📋 **盘后只读参考汇总（{day}）**｜不作为下单指令'
    text = header + '\n\n' + verdict_block + '\n\n---\n\n' + '\n\n---\n\n'.join(blocks)
    exit_code = 1 if (fail_count > 0 and ok_count == 0) else 0
    return text, exit_code


def _write_utf8(text: str) -> None:
    """Write normalized LF UTF-8 bytes so Windows text mode cannot break tables."""
    if not text:
        return
    sys.stdout.flush()
    sys.stdout.buffer.write((_normalize_newlines(text) + '\n').encode('utf-8'))
    sys.stdout.buffer.flush()


def main() -> int:
    text, rc = collect_summary()
    _write_utf8(text)
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
