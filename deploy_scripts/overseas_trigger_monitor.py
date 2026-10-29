# -*- coding: utf-8 -*-
"""纳指513300+日经159866 双标的触发监控（watchdog静默模式）。

用户2026-10-29总纲：辅助赚钱。两条线等触发，触发即推飞书：

纳指 513300（趋势持有方案，存档 reports/nasdaq-etf-trend-holding-plan.md）：
  ① 溢价 <5%  → 方案启动信号（QDII额度松/情绪退潮，干净入场）
  ② 净值距一年峰值回撤 ≥8% → 加仓信号（按方案分份买入）

日经 159866（2026-10-20三档方案）：
  ③ 场内价 ≤ 1.600 → 第一档触发（建仓30%）

规则：静默运行（未触发零输出），触发状态翻转才推送一次，
解除也推送（防记着旧警报）。同日重跑不重复推。
cron: 15:40 工作日（市况推送后，不撞车）。
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
    m = re.search(r'Data_netWorthTrend\s*=\s*(\[.*?\]);', text)
    arr = json.loads(m.group(1))
    return [(time.strftime('%Y-%m-%d', time.localtime(p['x'] / 1000)), p['y']) for p in arr[-n:]]


def _spot(sym):
    with urllib.request.urlopen(f"https://qt.gtimg.cn/q={sym}", timeout=10) as r:
        text = r.read().decode('gbk', errors='replace')
    f = text.split('"')[1].split('~')
    return float(f[3])


def check_nasdaq():
    """513300：溢价<5%（启动）+ 净值回撤≥8%（加仓）。"""
    navs = _nav_series('513300')
    nav = navs[-1][1]
    peak = max(v for _, v in navs)
    dd = (nav / peak - 1) * 100
    price = _spot('sh513300')
    prem = (price / nav - 1) * 100
    fires = []
    if prem < 5.0:
        fires.append(('nasdaq_premium', f"🟢 513300 溢价 {prem:+.1f}% 已回到 <5% 安全区——纳指方案可启动（按存档方案执行：底仓40%+回撤8%加仓）"))
    if dd <= -8.0:
        fires.append(('nasdaq_drawdown', f"📉 513300 净值距一年峰值回撤 {dd:+.1f}%，达 -8% 加仓线（注意当前溢价 {prem:+.1f}%，>5% 时按纪律暂缓买入）"))
    return fires, dict(nav=nav, peak=peak, dd=dd, prem=prem, date=navs[-1][0])


def check_nikkei():
    """159866：场内价 ≤1.600 第一档触发。"""
    price = _spot('sz159866')
    fires = []
    if price <= 1.600:
        fires.append(('nikkei_t1', f"🟢 159866 现价 {price:.3f} 已进入第一档 1.59-1.60 建仓区——按三档方案执行：本档买入30%（约9,000份），止损=成本×0.75"))
    return fires, dict(price=price)


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
    now_active = set(key for key, _ in n_fires + k_fires)
    prev_active = set(state.get('active', []))
    # 新触发 → 推送；已解除 → 推送一次"已解除"
    for key, msg in n_fires + k_fires:
        if key not in prev_active:
            messages.append(msg)
    for key in prev_active - now_active:
        messages.append(f"ℹ️ 触发已解除：{key}（当前纳指溢价{n_data.get('prem', '?'):+.1f}%、回撤{n_data.get('dd', '?'):+.1f}%；日经 {k_data.get('price', '?')}）")

    state['active'] = sorted(now_active)
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
