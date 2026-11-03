# -*- coding: utf-8 -*-
"""纳指513300+日经159866 双标的触发监控（watchdog静默模式）。

用户2026-10-29总纲：辅助赚钱。两条线等触发，触发即推飞书：

纳指 513300（趋势持有方案，存档 reports/nasdaq-etf-trend-holding-plan.md）：
  ① 溢价 <5%  → 方案启动信号（QDII额度松/情绪退潮，干净入场）
  ② 净值距一年峰值回撤 ≥8% → 加仓信号（按方案分份买入）

日经 159866（2026-10-20三档方案）：
  ③ 场内价 ≤ 1.600 → 第一档触发（建仓30%）

触价语义（2026-10-30 修复，当日实例：开盘1.598/最低1.595均≤1.600，
现价反弹1.616，旧版只看取价瞬间现价 → 永久漏报）：
  - 持续触发（persistent=True）：现价仍在触发区，走状态翻转逻辑（首次推、
    解除推一次"已解除"）。
  - 触价触发（persistent=False）：盘中最低曾触及但现价已回升——每日最多推
    一次，不进 active、不产生解除噪音。触价≠成交。
  - 行情时间门控：快照非当日或早于09:30（盘前日高低可能是昨日值）不判定。

规则：静默运行（未触发零输出），cron 盘中每10分钟（9:00-15:59 工作日）。
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

IS_312 = sys.version_info[:2] == (3, 12) and 'Programs' in sys.executable
if __name__ == '__main__' and not IS_312:
    import subprocess
    sys.stdout.flush(); sys.stderr.flush()
    sys.exit(subprocess.call([r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe',
                              os.path.abspath(__file__)] + sys.argv[1:]))

STATE = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account/overseas-triggers.json')


def _nav_series(code, n=250):
    url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0',
                                               'Referer': f'https://fund.eastmoney.com/{code}.html'})
    with urllib.request.urlopen(req, timeout=15) as r:
        text = r.read().decode('utf-8', errors='replace')
    m = re.search(r'Data_netWorthTrend\s*=\s*(\[.*?]);', text)
    arr = json.loads(m.group(1))
    return [(time.strftime('%Y-%m-%d', time.localtime(p['x'] / 1000)), p['y']) for p in arr[-n:]]


def _quote(sym):
    """腾讯实时快照：现价/日高/日低/时间戳（YYYYMMDDhhmmss）。"""
    with urllib.request.urlopen(f"https://qt.gtimg.cn/q={sym}", timeout=10) as r:
        text = r.read().decode('gbk', errors='replace')
    f = text.split('"')[1].split('~')
    return dict(price=float(f[3]), high=float(f[33]), low=float(f[34]), quote_time=f[30])


def _spot(sym):
    return _quote(sym)['price']


def check_nasdaq():
    """513300：溢价<5%（启动）+ 净值回撤≥8%（加仓）。均为持续触发。"""
    navs = _nav_series('513300')
    nav = navs[-1][1]
    peak = max(v for _, v in navs)
    dd = (nav / peak - 1) * 100
    price = _spot('sh513300')
    prem = (price / nav - 1) * 100
    fires = []
    if prem < 5.0:
        fires.append(('nasdaq_premium', f"🟢 513300 溢价 {prem:+.1f}% 已回到 <5% 安全区——纳指方案可启动（按存档方案执行：底仓40%+回撤8%加仓）", True))
    if dd <= -8.0:
        fires.append(('nasdaq_drawdown', f"📉 513300 净值距一年峰值回撤 {dd:+.1f}%，达 -8% 加仓线（注意当前溢价 {prem:+.1f}%，>5% 时按纪律暂缓买入）", True))
    return fires, dict(nav=nav, peak=peak, dd=dd, prem=prem, date=navs[-1][0])


def check_nikkei():
    """159866 三档监控：一档已成交(11-03)，盯二档≤1.52、三档≤1.42；触价=min(现价,日低)。"""
    q = _quote('sz159866')
    price = q['price']
    # 脏数据退化：盘前/异常 low=0 时用现价
    low = q['low'] if q['low'] and q['low'] > 0 else price
    fires = []
    # 行情时间门控：非当日快照或 09:30 前（日高低可能是昨日值）不判定
    qt = q.get('quote_time', '')
    live = (len(qt) == 14 and qt[:8] == date.today().isoformat().replace('-', '')
            and qt[8:12] >= '0930')
    if not live:
        return fires, dict(price=price, low=low, quote_time=qt)
    # 2026-11-03 第一档已成交（9,000份@1.600，账本 overseas-positions.json）→ 盯二档/三档
    TRANCHES = (
        ('t2', 1.52, "第二档 1.50-1.52 买入30%（约9,000份）"),
        ('t3', 1.42, "第三档 1.40-1.42 买入最后40%（约12,000份）"),
    )
    for tag, level, act in TRANCHES:
        if price <= level:
            fires.append((f'nikkei_{tag}', f"🟢 159866 现价 {price:.3f} 进入{act}", True))
            break
        if low <= level:
            fires.append((f'nikkei_{tag}', f"⚠️ 159866 盘中最低 {low:.3f} 触及{act.split('买入')[0]}触发线，现价 {price:.3f} 回升——触价≠成交，未执行则等回落再触发", False))
            break
    return fires, dict(price=price, low=low, quote_time=qt)


def main():
    today = date.today().isoformat()
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding='utf-8'))
        except Exception:
            state = {}

    try:
        n_fires, n_data = check_nasdaq()
    except Exception as e:
        n_fires, n_data = [], dict(error=str(e)[:80])
    try:
        k_fires, k_data = check_nikkei()
    except Exception as e:
        k_fires, k_data = [], dict(error=str(e)[:80])

    messages = []
    all_fires = n_fires + k_fires
    now_active = set(key for key, _, persistent in all_fires if persistent)
    touch_keys = set(key for key, _, persistent in all_fires if not persistent)
    prev_active = set(state.get('active', []))
    # 持续型新触发 → 推送；已解除 → 推送一次"已解除"（触价型不产生解除噪音）
    for key, msg, persistent in all_fires:
        if persistent and key not in prev_active:
            messages.append(msg)
    for key in prev_active - now_active - touch_keys:
        messages.append(f"ℹ️ 触发已解除：{key}（当前纳指溢价{n_data.get('prem', '?'):+.1f}%、回撤{n_data.get('dd', '?'):+.1f}%；日经 {k_data.get('price', '?')}）")
    # 触价型（已回升）：每日最多推一次，跨日重推
    touch = dict(state.get('touch', {}))
    for key, msg, persistent in all_fires:
        if not persistent and touch.get(key) != today:
            messages.append(msg)
            touch[key] = today

    state['active'] = sorted(now_active)
    state['touch'] = touch
    state['last_run'] = today
    state['nasdaq'] = n_data
    state['nikkei'] = k_data
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, STATE)

    if messages:
        print(f"【海外敞口触发 {today}】")
        for m in messages:
            print(m)
    # 静默：未触发无输出（watchdog 模式）


if __name__ == '__main__':
    main()
