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

阈值唯一真源：deploy_scripts/overseas_grid_rules.json（本文件、账本 plan 字段、
记忆卡、白板里出现的数值均为历史说明，不作规则来源）。配置缺失 → 买入信号全部静默。

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
# 2026-11-05 用户定：持仓账本也读 DSH 自己那份（与 STATE 同目录），不再读 hermes-home。
POSITIONS = STATE.parent / 'overseas-positions.json'

# 阈值唯一真源（R1/R2）：结构化配置，脚本与账本 plan 字段都不再各自持有规则。
RULES_PATH = Path(__file__).with_name('overseas_grid_rules.json')


def _load_rules():
    """读取唯一真源；文件缺失或损坏返回 None（调用方 fail-closed，不用散落兜底值）。"""
    try:
        data = json.loads(RULES_PATH.read_text(encoding='utf-8'))
        required = ('溢价上限百分比', '日经禁买溢价百分比', '纳指启动溢价百分比',
                    '纳指加仓回撤百分比', '止损比例', '预算总额', '档位')
        if all(k in data for k in required):
            return data
    except Exception:
        pass
    return None


RULES = _load_rules()
# 溢价口径留痕（M1）：净值日期/同源性/数据源，供事后审计，不参与判定。
_LAST_PREMIUM_META = {}

# 2026-11-05 23:0x Master 指令：纳指/日经暂停买入，待次日复核并修复后再开。
# 标志文件与 STATE 同目录，两条链共读一份；删除文件或置 paused=false 即恢复，无需改代码。
PAUSE_FLAG = STATE.parent / 'overseas-buy-pause.json'
# 买入类信号：暂停时整体静默。nikkei_stop 属风控卖出，不受买入闸门约束。
BUY_SIGNAL_KEYS = {'nasdaq_premium', 'nasdaq_drawdown', 'nikkei_t2', 'nikkei_t3'}


def _buy_paused():
    """跨境买入总闸：标志存在且 paused=true → 静默全部买入类信号。

    标志缺失 / paused=false / 内容损坏 → 不暂停（可逆开关，坏文件不锁死交易）。
    """
    try:
        return bool(json.loads(PAUSE_FLAG.read_text(encoding='utf-8')).get('paused'))
    except Exception:
        return False


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
    """513300：溢价 < 启动线 + 净值回撤 ≥ 加仓线，阈值一律取自唯一真源配置。

    配置缺失 → 静默全部买入信号（fail-closed），绝不退回散落的硬编码值。
    """
    navs = _nav_series('513300')
    nav_date, nav = navs[-1]
    peak = max(v for _, v in navs)
    dd = (nav / peak - 1) * 100
    price = _spot('sh513300')
    prem = (price / nav - 1) * 100
    meta = dict(净值日期=nav_date,
                溢价口径=('同日净值' if nav_date == date.today().isoformat() else '滞后净值'),
                数据源='东财已发布净值')
    data = dict(nav=nav, peak=peak, dd=dd, prem=prem, date=nav_date, **meta)
    if RULES is None:
        data['规则状态'] = '规则配置缺失，买入信号静默'
        return [], data
    fires = []
    start_line = RULES['纳指启动溢价百分比']
    if prem < start_line:
        fires.append(('nasdaq_premium', f"🟢 513300 溢价 {prem:+.1f}% 已回到 <{start_line:.0f}% 启动线内——纳指方案可启动（溢价口径：{meta['溢价口径']}，净值日期 {nav_date}，非实时 IOPV，下单前须复核）", True))
    # 溢价硬闸门：超标时加仓信号整体静默，只留启动线口径
    if dd <= RULES['纳指加仓回撤百分比'] and prem < RULES['溢价上限百分比']:
        fires.append(('nasdaq_drawdown', f"📉 513300 净值距一年峰值回撤 {dd:+.1f}%，达 {RULES['纳指加仓回撤百分比']:.0f}% 加仓线，当前溢价 {prem:+.1f}% 已过 <{RULES['溢价上限百分比']:.0f}% 闸门（溢价口径：{meta['溢价口径']}，非实时 IOPV，下单前须复核）", True))
    return fires, data


def _nikkei_stop_price():
    """止损价 = 账本加权成本 × 止损比例（正常取唯一真源配置）。

    风控兜底：配置缺失时仍按账本 plan 既定的 0.75 计算，绝不因「规则文件丢了」
    连止损都不判——买入可以静默，风控卖出任何时候都要响。
    """
    ratio = RULES['止损比例'] if RULES is not None else 0.75
    try:
        data = json.loads(POSITIONS.read_text(encoding='utf-8'))
        unit_cost = float(data['sz159866']['unit_cost'])
        return round(unit_cost * ratio, 4)
    except Exception:
        return None


def _nikkei_prem(price):
    """日经 159866 溢价（%）：场内价 ÷ 东财最新已发布净值 - 1。

    与旧版的差别（审核 M1）：
    - 拉不到 → None，由调用方 fail-closed 静默买入信号，不再 fail-open 照常推；
    - 净值日期与口径写进 _LAST_PREMIUM_META，供消息与 state 留痕，避免把
      「滞后净值」误当成同日净值（11-06 假折价事件的直接成因）。
    """
    global _LAST_PREMIUM_META
    try:
        navs = _nav_series('159866')
        nav_date, nav = navs[-1]
        _LAST_PREMIUM_META = dict(净值日期=nav_date,
                                  溢价口径=('同日净值' if nav_date == date.today().isoformat() else '滞后净值'),
                                  数据源='东财已发布净值')
        return (price / nav - 1) * 100
    except Exception:
        _LAST_PREMIUM_META = dict(净值日期=None, 溢价口径='数据不可用', 数据源='东财已发布净值')
        return None


def _premium_note():
    """买入信号统一附带的口径警示：非实时 IOPV、净值日期、下单前须复核。"""
    meta = _LAST_PREMIUM_META or {}
    nd = meta.get('净值日期') or '未知'
    return (f"｜溢价口径：{meta.get('溢价口径') or '未知'}，净值日期 {nd}，"
            f"非实时 IOPV，下单前须按当日实时 IOPV 复核（2026-11-05）")


def check_nikkei():
    """159866 三档+止损监控；阈值/档位取自唯一真源配置，溢价失败 fail-closed。

    止损信号不受买入闸门与配置缺失影响（风控卖出任何时候都要响）。
    """
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
    ratio = RULES['止损比例'] if RULES is not None else 0.75
    rule_status = ('规则配置缺失（止损用兜底比例）' if RULES is None else '已加载')
    # 止损优先：现价已破线 → 持续触发；日低破过线现价回升 → 触价提醒（每日一次）。
    # 止损线在场即不再提示买入档位（都低于止损线，此时提示买入是错误信号）。
    if stop is not None:
        if price <= stop:
            fires.append(('nikkei_stop', f"🔴 159866 现价 {price:.3f} 已跌破止损线 {stop:.4f}（成本×{ratio}）——按既定规则执行止损，卖出全部持仓", True))
            return fires, dict(price=price, low=low, quote_time=qt, stop=stop, 规则状态=rule_status)
        if low <= stop:
            fires.append(('nikkei_stop', f"⚠️ 159866 盘中最低 {low:.3f} 已触及止损线 {stop:.4f}，现价 {price:.3f} 回升——触价≠成交，按既定规则应执行止损", False))
            return fires, dict(price=price, low=low, quote_time=qt, stop=stop, 规则状态=rule_status)
    meta = dict(_LAST_PREMIUM_META or {})
    basis = dict(净值日期=meta.get('净值日期'), 溢价口径=meta.get('溢价口径'),
                 数据源=meta.get('数据源'))
    if RULES is None:
        return fires, dict(price=price, low=low, quote_time=qt,
                           规则状态='规则配置缺失（止损用兜底比例），买入信号静默', **basis)
    prem = _nikkei_prem(price)
    meta = dict(_LAST_PREMIUM_META or {})
    basis = dict(净值日期=meta.get('净值日期'), 溢价口径=meta.get('溢价口径'),
                 数据源=meta.get('数据源'))
    # 溢价硬闸门：数据不可用也静默（fail-closed），不再「不硬拦、照常推」。
    if prem is None:
        return fires, dict(price=price, low=low, quote_time=qt, prem=None,
                           溢价状态='数据不可用', **basis)
    if prem > RULES['日经禁买溢价百分比']:
        return fires, dict(price=price, low=low, quote_time=qt, prem=prem,
                           溢价状态='超闸门静默', **basis)
    # 2026-11-03 第一档已成交 → 盯二档/三档；档位来自配置而非硬编码
    for t in RULES['档位']:
        tag, level, act = t['名称'], t['触发价'], t['说明']
        if price <= level:
            fires.append((tag, f"🟢 159866 现价 {price:.3f} 进入{act}{_premium_note()}", True))
            break
        if low <= level:
            fires.append((tag, f"⚠️ 159866 盘中最低 {low:.3f} 触及{act.split('买入')[0]}触发线，现价 {price:.3f} 回升——触价≠成交{_premium_note()}", False))
            break
    return fires, dict(price=price, low=low, quote_time=qt, prem=prem,
                       溢价状态='已通过', **basis)


def _budget_check():
    """只读预算校验（审核 M4）：三档全建是否超预算，写进 state 留痕，不拦截。

    拦截属交易规则变更，待 Master 拍板后另行实现。
    """
    if RULES is None:
        return None
    try:
        pos = json.loads(POSITIONS.read_text(encoding='utf-8'))['sz159866']
        spent = float(pos['total_cost'])
        budget = float(pos.get('budget', RULES['预算总额']))
        extra = sum(t['份额'] * t['触发价'] for t in RULES['档位'])
        total = round(spent + extra, 2)
        return dict(已投入=spent, 二三档估算=round(extra, 2), 三档全建估算=total,
                    预算总额=budget, 三档全建超额=bool(total > budget),
                    超额金额=round(max(0.0, total - budget), 2), 已拦截=False,
                    口径='只读留痕；份额口径假设，是否改硬拦截待拍板')
    except Exception:
        return None


def main():
    today = date.today().isoformat()
    paused = _buy_paused()
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding='utf-8'))
        except Exception:
            state = {}

    errors = []
    try:
        n_fires, n_data = check_nasdaq()
    except Exception as e:
        n_fires, n_data = [], dict(error=str(e)[:80])
        errors.append(f"纳指 {type(e).__name__}: {str(e)[:80]}")
    try:
        k_fires, k_data = check_nikkei()
    except Exception as e:
        k_fires, k_data = [], dict(error=str(e)[:80])
        errors.append(f"日经 {type(e).__name__}: {str(e)[:80]}")

    messages = []
    # 审核 M5：异常不再静默；当日首次异常推一条告警，避免每 10 分钟刷屏。
    if errors:
        state['检查异常'] = errors
        if state.get('异常告警日期') != today:
            messages.append(f"⚠️ 海外监控数据异常：{'；'.join(errors)}（本轮信号不完整，买入判定已静默）")
            state['异常告警日期'] = today
    else:
        state.pop('检查异常', None)
        state.pop('异常告警日期', None)

    all_fires = n_fires + k_fires
    # 暂停买入（2026-11-05 Master 指令）：只过滤买入类信号，止损信号照常。
    # 同时把 prev_active 里的买入键剔除，避免暂停首轮误推「触发已解除」噪音。
    if paused:
        all_fires = [f for f in all_fires if f[0] not in BUY_SIGNAL_KEYS]
    now_active = set(key for key, _, persistent in all_fires if persistent)
    touch_keys = set(key for key, _, persistent in all_fires if not persistent)
    prev_active = set(state.get('active', []))
    if paused:
        prev_active = {k for k in prev_active if k not in BUY_SIGNAL_KEYS}
    # 持续型新触发 → 推送；已解除 → 推送一次"已解除"（触价型不产生解除噪音）
    for key, msg, persistent in all_fires:
        if persistent and key not in prev_active:
            messages.append(msg)
    for key in prev_active - now_active - touch_keys:
        def _fmt(v):
            return f"{v:+.1f}" if isinstance(v, (int, float)) else str(v)
        messages.append(f"ℹ️ 触发已解除：{key}（当前纳指溢价{_fmt(n_data.get('prem', '?'))}%、回撤{_fmt(n_data.get('dd', '?'))}%；日经 {k_data.get('price', '?')}）")
    # 触价型（已回升）：每日最多推一次，跨日重推
    touch = dict(state.get('touch', {}))
    for key, msg, persistent in all_fires:
        if not persistent and touch.get(key) != today:
            messages.append(msg)
            touch[key] = today

    state['active'] = sorted(now_active)
    state['touch'] = touch
    state['last_run'] = today
    state['buy_paused'] = paused
    state['nasdaq'] = n_data
    state['nikkei'] = k_data
    budget_state = _budget_check()
    if budget_state is not None:
        state['预算校验'] = budget_state
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
