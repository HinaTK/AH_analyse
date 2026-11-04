# -*- coding: utf-8 -*-
"""纳指513300+日经159866 双标的触发监控（watchdog静默模式）。

用户2026-10-29总纲：辅助赚钱。两条线等触发，触发即推飞书：

纳指 513300（趋势持有方案，存档 reports/nasdaq-etf-trend-holding-plan.md）：
  ① 溢价 <3% → 方案启动信号（QDII额度松/情绪退潮，干净入场）
     ——2026-11-04 用户拍板：跨境溢价 >3% 放弃；旧 <5% 启动线废弃（5% 本身就破 3% 线）
  ② 净值距一年峰值回撤 ≥8% → 加仓信号（按方案分份买入）
     ——同日拍板：加仓信号受 >3% 溢价闸门否决（溢价超标时整体静默）

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

STATE = Path('D:/Code/AH_analyse/.cache/grid-home/cache/grid-account/overseas-triggers.json')
# 2026-11-04 用户拍板 STATE 迁移：活体状态从 hermes cache 迁到 AH .cache/grid-home
#（run_and_push.py L44 指定的账本根），复制不剪切、hermes 侧留冻结备份；
# 迁移操作记录见 cache/confirmed-runtime-deploy/20261104-* 目录。


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
    """513300：溢价<3%（启动，2026-11-04 从5%收紧）+ 净值回撤≥8%（加仓，受3%闸门）。均为持续触发。"""
    navs = _nav_series('513300')
    nav = navs[-1][1]
    peak = max(v for _, v in navs)
    dd = (nav / peak - 1) * 100
    price = _spot('sh513300')
    prem = (price / nav - 1) * 100
    fires = []
    if prem < 3.0:
        fires.append(('nasdaq_premium', f"🟢 513300 溢价 {prem:+.1f}% 已回到 <3% 放弃线内——纳指方案可启动（按存档方案执行：底仓40%+回撤8%加仓）", True))
    # 溢价硬闸门（2026-11-04 用户拍板：跨境 >3% 放弃）：超标时加仓信号整体静默，只留启动线口径
    if dd <= -8.0 and prem < 3.0:
        fires.append(('nasdaq_drawdown', f"📉 513300 净值距一年峰值回撤 {dd:+.1f}%，达 -8% 加仓线，当前溢价 {prem:+.1f}% 已过 <3% 闸门（按方案分份买入）", True))
    return fires, dict(nav=nav, peak=peak, dd=dd, prem=prem, date=navs[-1][0])


def _nikkei_stop_price():
    """止损价 = 账本加权成本 × 0.75（overseas-positions.json plan 字段既定规则）。

    2026-11-03 收编缺口补齐：此前账本写了规则、脚本零执行（第二个"有规则无代码"）。
    动态读账本 unit_cost，不写死数字（分红/加减仓后成本变，线跟着变）；
    账本缺失/损坏/无持仓 → None（调用方不判定止损，宁缺勿误报）。
    """
    positions_path = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account/overseas-positions.json')
    try:
        data = json.loads(positions_path.read_text(encoding='utf-8'))
        unit_cost = float(data['sz159866']['unit_cost'])
        return round(unit_cost * 0.75, 4)
    except Exception:
        return None


def _nikkei_prem(price):
    """日经 159866 实时溢价（%）：场内价 ÷ 东财最新净值 - 1。

    拉不到（净值源故障）→ None：闸门语义为"不硬拦"——这是提示型监控，
    触价≠成交，用户执行前还有当天实时 IOPV 一道人工闸；但 data 里记 None 备查。
    """
    try:
        navs = _nav_series('159866')
        nav = navs[-1][1]
        return (price / nav - 1) * 100
    except Exception:
        return None


def check_nikkei():
    """159866 三档+止损监控：一档已成交(11-03)，盯二档≤1.52、三档≤1.42、止损=成本×0.75；触价=min(现价,日低)。
    买入档位受溢价闸门（2026-11-04 用户拍板：日经 >2% 不买/不加仓）；止损不受闸门约束。"""
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
    stop = _nikkei_stop_price()
    # 止损优先：现价已破线 → 持续触发；日低破过线现价回升 → 触价提醒（每日一次）。
    # 止损线在场即不再提示买入档位（都低于止损线，此时提示买入是错误信号）。
    if stop is not None:
        if price <= stop:
            fires.append(('nikkei_stop', f"🔴 159866 现价 {price:.3f} 已跌破止损线 {stop:.4f}（成本×0.75）——按既定规则执行止损，卖出全部持仓", True))
            return fires, dict(price=price, low=low, quote_time=qt, stop=stop)
        if low <= stop:
            fires.append(('nikkei_stop', f"⚠️ 159866 盘中最低 {low:.3f} 已触及止损线 {stop:.4f}，现价 {price:.3f} 回升——触价≠成交，按既定规则应执行止损", False))
            return fires, dict(price=price, low=low, quote_time=qt, stop=stop)
    prem = _nikkei_prem(price)
    # 溢价硬闸门（2026-11-04 用户拍板：日经 >2% 不买/不加仓）：超标时买入档位整体静默
    if prem is not None and prem > 2.0:
        return fires, dict(price=price, low=low, quote_time=qt, prem=prem)
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
    return fires, dict(price=price, low=low, quote_time=qt, prem=prem)


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
