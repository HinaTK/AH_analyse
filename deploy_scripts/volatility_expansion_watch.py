# -*- coding: utf-8 -*-
"""日频「波动扩张」观察预警（2026-11-06 Master 授权，只读，不交易）。

规则：最近 3 个交易日中 ≥2 日「日振幅 ≥4% 且 量比 ≥1.5」→ 提示波动扩张。
用绝对阈值组合，不用相对扩张比（2026-11-06 回测：波动基数抬高后
「5日均振幅 ≥ 前20日×1.5」在 131 日样本里只触发 1 次、本轮完全钝化）。

只读约束：不写 confirmed-*.json / holdings.json、不生成买卖建议、不自动建仓，
不改动任何定时任务状态。无触发时输出空串，run_and_push 自动静默。
生产走腾讯日K（与 market_phase_check 同源，end 留空）；测试用注入夹具。
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AMP_TH = 4.0          # 日振幅阈值 %
VOLUME_RATIO_TH = 1.5  # 当日量 / 前20日量中位数
WINDOW = 3            # 观察窗口（交易日）
MIN_HITS = 2          # 窗口内命中天数
MIN_HISTORY = 21      # 至少 20 日基线 + 1 日当日

SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'


def day_amplitude(row):
    """日振幅 % = (high-low)/open。open 缺失或非法时返回 None。"""
    try:
        o = float(row['open'])
        hi, lo = float(row['high']), float(row['low'])
    except (KeyError, TypeError, ValueError):
        return None
    if o <= 0 or hi < lo:
        return None
    return (hi - lo) / o * 100.0


def volume_ratio(rows, index):
    """当日量 / 前 20 日量中位数；基线不足或为 0 时返回 None（不误报）。"""
    if index < 20:
        return None
    try:
        current = float(rows[index].get('volume') or 0)
        base = [float(r.get('volume') or 0) for r in rows[index - 20:index]]
    except (TypeError, ValueError):
        return None
    median = statistics.median(base)
    if current <= 0 or median <= 0:
        return None
    return current / median


def evaluate(code, name, rows):
    """对单只标的判定；rows 按日期升序，每项含 date/open/high/low/close/volume。"""
    rows = list(rows or [])
    out = dict(code=code, name=name, triggered=False, hit_days=0,
               latest_amp=None, latest_volume_ratio=None, amp20_mean=None,
               hit_dates=[], reason='', asof=None)
    if len(rows) < MIN_HISTORY:
        out['reason'] = f'数据不足（{len(rows)}日 < {MIN_HISTORY}日），不判定'
        return out
    out['asof'] = str(rows[-1].get('date') or '')
    amps = [day_amplitude(r) for r in rows]
    out['latest_amp'] = amps[-1]
    out['latest_volume_ratio'] = volume_ratio(rows, len(rows) - 1)
    out['amp20_mean'] = statistics.mean(a for a in amps[-20:] if a is not None) \
        if any(a is not None for a in amps[-20:]) else None
    hits = []
    for i in range(len(rows) - WINDOW, len(rows)):
        if i < 20:
            continue
        amp, vr = amps[i], volume_ratio(rows, i)
        if amp is not None and vr is not None and amp >= AMP_TH and vr >= VOLUME_RATIO_TH:
            hits.append(str(rows[i].get('date') or ''))
    out['hit_days'] = len(hits)
    out['hit_dates'] = hits
    out['triggered'] = len(hits) >= MIN_HITS
    if not out['triggered']:
        out['reason'] = f'近{WINDOW}日命中{len(hits)}日 < {MIN_HITS}日（振幅≥{AMP_TH:g}% 且 量比≥{VOLUME_RATIO_TH:g}）'
    return out


def render(signals, failures=None):
    """预警正文；无信号且无取数失败时返回空串（wrapper 静默）。禁止任何交易动作词。"""
    fired = [s for s in signals if s.get('triggered')]
    failures = list(failures or [])
    if not fired and not failures:
        return ''
    lines = ['【波动扩张观察·仅观察】',
             f"判据：近{WINDOW}个交易日 ≥{MIN_HITS}日 日振幅≥{AMP_TH:g}% 且 量比≥{VOLUME_RATIO_TH:g}（量比=当日量/前20日量中位数）。"]
    for s in fired:
        amp = '不可用' if s['latest_amp'] is None else f"{s['latest_amp']:.2f}%"
        vr = '不可用' if s['latest_volume_ratio'] is None else f"{s['latest_volume_ratio']:.2f}"
        mean = '不可用' if s['amp20_mean'] is None else f"{s['amp20_mean']:.2f}%"
        lines.append(f"{s['code']} {s['name']}｜最新振幅{amp}｜量比{vr}｜近20日均振幅{mean}"
                     f"｜命中{','.join(s['hit_dates'])}｜asof {s['asof'] or '不可用'}")
    if failures:
        lines.append(f"⚠️ 取数失败 {len(failures)} 只（{', '.join(failures[:5])}"
                     f"{'…' if len(failures) > 5 else ''}）：本次为有限样本观察池，未覆盖失败标的，"
                     '不得据此断言全池无波动扩张。')
    lines.append('失效信号：量比连续 3 日 <1.2；5 日均振幅回落 <3%；近 5 日振幅≥4% 的天数 ≤1。')
    lines.append('本提示只说明波动状态变化，不含行情方向判断，不构成操作依据；'
                 '数据为同窗历史日K，不改动持仓、账本与任务状态。')
    return '\n'.join(lines)


def to_secid(code):
    """观察池代码 → 东财 secid（tencent_symbol 需要 market.digits）。

    池内混用三种格式：holdings.json 的纯 6 位、研究榜单的 sh/sz 前缀、
    以及已规范化的 1./0. 前缀。ETF 代码 5/6 开头属上交所(1.)，
    1 开头属深交所(0.)；股票 6 开头同理归上交所。
    """
    text = str(code).strip().lower()
    if '.' in text and text.split('.', 1)[0] in ('0', '1'):
        return text
    digits = text[2:] if text[:2] in ('sh', 'sz') else text
    if not digits.isdigit() or len(digits) != 6:
        raise ValueError(f'无法识别的标的代码：{code}')
    return ('1.' if digits[0] in ('5', '6') else '0.') + digits


def _fetch_daily(secid, lmt=40):
    """生产取数：腾讯日K（end 留空，2026-11-04 修复口径）。"""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.market_phase_check import fetch_tencent_kline
    rows = fetch_tencent_kline(to_secid(secid), lmt=lmt, klt='101')
    return [dict(date=r['date'], open=r['open'], high=r['high'], low=r['low'],
                 close=r['close'], volume=r.get('volume') or 0) for r in rows]


def _universe(account_root):
    """观察池 = holdings.json 的 active 标的 + 最近研究榜单前列，去重。"""
    codes, names = [], {}
    hp = Path(account_root) / 'holdings.json'
    if hp.exists():
        try:
            data = json.loads(hp.read_text(encoding='utf-8'))
            for code, entry in (data.get('holdings') or {}).items():
                if entry.get('active'):
                    codes.append(code)
                    names[code] = entry.get('name', code)
        except (ValueError, OSError):
            pass
    research_root = Path(account_root).parent / 'grid-research'
    if research_root.exists():
        # 2026-11-06 联动防御：只把「含 entry-ranking.csv」的目录纳入候选。
        # 每日轻量快照 16:15 落盘的 daily-snapshots/ 目录 mtime 更新但无榜单，
        # 若仍按 mtime 取最新一个目录，次日 16:05 的波动观察会静默丢失榜单
        # 前20补充观察池。按榜单存在性筛选比按名字排除更稳健（未来任何无榜单
        # 的新目录都不误伤）。见 tests/test_grid_daily_snapshot.py 的 RED 回归。
        dirs = sorted((d for d in research_root.iterdir()
                       if d.is_dir() and (d / 'entry-ranking.csv').exists()),
                      key=lambda d: d.stat().st_mtime, reverse=True)
        for d in dirs[:1]:
            f = d / 'entry-ranking.csv'
            if f.exists():
                import csv
                try:
                    for i, r in enumerate(csv.DictReader(f.open(encoding='utf-8-sig'))):
                        if i >= 20:
                            break
                        code = r.get('code')
                        if code and code not in codes:
                            codes.append(code)
                            names[code] = r.get('name', code)
                except (OSError, ValueError):
                    pass
    return [(c, names.get(c, c)) for c in codes]


def run(fixture_path=None, account_root=None, fetch=None, limit=None):
    """只读执行：fixture 注入优先（测试）；否则走生产日K。返回待推送文本。"""
    if fixture_path is not None:
        data = json.loads(Path(fixture_path).read_text(encoding='utf-8'))
        pairs = [(code, code, rows) for code, rows in data.items()]
        failures = []
    else:
        root = Path(account_root or os.environ.get(
            'HERMES_HOME', r'D:\Hermes Agent CN Desktop\data\hermes-home')) / 'cache' / 'grid-account'
        fetch = fetch or _fetch_daily
        universe = _universe(root)
        if limit:
            universe = universe[:limit]
        pairs = []
        failures = []
        for code, name in universe:
            try:
                pairs.append((code, name, fetch(code)))
            except Exception:
                failures.append(code)  # 单只失败不影响其余，但必须披露缺口
    signals = [evaluate(code, name, rows) for code, name, rows in pairs]
    return render(signals, failures=failures)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description='日频波动扩张观察（只读）')
    p.add_argument('--fixture-path', help='离线夹具 JSON：{code: [日线行]}')
    p.add_argument('--account-root', help='账本根（只读 holdings.json / 研究榜单）')
    p.add_argument('--limit', type=int, help='限制观察池数量（生产调试用）')
    args = p.parse_args(argv)
    text = run(fixture_path=args.fixture_path, account_root=args.account_root, limit=args.limit)
    if text:
        print(text)
    return text


if __name__ == '__main__':
    main()
