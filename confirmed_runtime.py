"""One confirmed-state runtime. Advice is conditional, never a broker order."""
import json
from pathlib import Path
from decimal import Decimal as D, ROUND_HALF_UP

import holdings as H

CODES = ('sh589720', 'sz159363')          # legacy compatibility only
BUDGETS = {'sh589720': D('8000'), 'sz159363': D('6000')}
GAP = D('0.015')
WARNING = ('条件建议，非可直接执行委托：sz159992 处于迁移退出模式（停买、停接回、只卖不买），'
           '00:01 已同步可卖份额；账户现金、银河冻结及在途委托未对账，不自动下单，触价不等于成交。')
DAILY_BAR_SOURCES = (
    'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param={code},day,,,80,qfq',
    'https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,80,qfq',
)


def load_states(root):
    result = {}
    for code in H.held_codes():
        state = json.loads((Path(root) / f'confirmed-{code[-6:]}.json').read_text(encoding='utf-8'))
        if state['code'] != code:
            raise ValueError('ETF状态文件身份不符')
        from confirmed_state_validation import validate_state
        validate_state(state, allow_uninitialized_sellable=True)
        result[code] = state
    return result


def price(value):
    return str(value.quantize(D('0.001'), rounding=ROUND_HALF_UP))


def plan(root):
    states = load_states(root)
    holdings = H.load_holdings()
    budgets = H.lot_budgets(holdings)
    names = H.names(holdings)
    actions = []
    for code, state in states.items():
        active = H.is_active(code, holdings)
        top = state['open_grid_positions'][-1] if state['open_grid_positions'] else None
        depth = len(state['open_grid_positions'])
        if state['max_grid'] != (chr(64 + depth) if depth else None):
            raise ValueError('最大网格序号不一致')
        available = state.get('sellable_qty')
        if type(available) is not int or not 0 <= available <= state['qty']:
            if active or available is not None:
                raise ValueError('保存的可卖库存无效')
        if active and top and type(available) is int and available >= top['qty'] and state['qty'] - top['qty'] >= (4600 if code == 'sz159363' else 0):
            actions.append(dict(code=code, side='sell', price=price(D(top['price']) * (1 + GAP)), qty=top['qty'], lot=state['max_grid'], buy_id=top['id']))
        if active and depth < 26 and state['trades'] and budgets.get(code) is not None:
            px = price(D(top['price'] if top else state['trades'][-1]['price']) / (1 + GAP))
            qty = int(budgets[code] / (D(px) * 100)) * 100
            if qty:
                actions.append(dict(code=code, side='buy', price=px, qty=qty, lot=chr(65 + depth)))
    return dict(actions=actions, executable=False, cash=None, warning=WARNING, states=states, names=names)


def phase(now):
    from confirmed_calendar import is_session
    hhmm = now.hour * 100 + now.minute
    try:
        session = is_session(now.date())
    except ValueError:
        session = False
    if not session:
        return 'closed'
    if hhmm < 931:
        return 'preview'
    if 931 <= hhmm <= 1130 or 1300 <= hhmm <= 1500:
        return 'execute'
    return 'closed'


def quotes_are_live(quotes, now):
    if not quotes or set(quotes) != set(H.held_codes()):
        return False
    for quote in quotes.values():
        stamp = str(quote.get('time', ''))
        if len(stamp) != 14 or not stamp.isdigit() or not stamp.startswith(now.strftime('%Y%m%d')) or stamp[8:12] < '0930' or stamp > now.strftime('%Y%m%d%H%M%S'):
            return False
        try:
            from datetime import datetime
            stamped = datetime.strptime(stamp, '%Y%m%d%H%M%S').replace(tzinfo=now.tzinfo)
            if (now - stamped).total_seconds() > 180:
                return False
            if any(not D(quote[key]).is_finite() or D(quote[key]) <= 0 for key in ('last',)):
                return False
        except (KeyError, ValueError, ArithmeticError):
            return False
    return True


def fetch_quotes():
    import re
    import urllib.request
    codes = H.held_codes()
    request = urllib.request.Request('https://qt.gtimg.cn/q=' + ','.join(codes), headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=15) as response:
        text = response.read().decode('gbk', errors='replace')
    result = {}
    for code in codes:
        match = re.search(rf'v_{code}="([^"]*)"', text)
        if not match:
            raise ValueError('腾讯缺少ETF行情')
        fields = match.group(1).split('~')
        result[code] = dict(last=fields[3], prev=fields[4], time=fields[30], high=fields[33], low=fields[34])
    return result


def fetch_daily_bars(code):
    """Daily qfq bars from Tencent; mirror first since ifzq fqkline broke 2026-10-23."""
    import urllib.request
    errors = []
    for template in DAILY_BAR_SOURCES:
        url = template.format(code=code)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.load(response)
            if data.get('code') != 0:
                raise ValueError('腾讯日线失败')
            rows = data['data'][code].get('qfqday', data['data'][code].get('day', []))
            if not rows:
                raise ValueError('腾讯日线为空')
            return [dict(date=row[0], close=row[2]) for row in rows]
        except (OSError, ValueError, KeyError, IndexError) as error:
            errors.append(f'{url}: {error}')
    raise ValueError('行情源全部失败：' + '; '.join(errors))


def monitor(ticket, quotes, state, day):
    """有效触碰 = 建议生成后的触碰。

    每条建议首次被看到时记录当时的日内极值为基准（生成前的旧极值不算触碰）。
    之后仅两种情况有效：现价触价（发生在当下），或极值越过基准的新触碰。
    建议消失（成交入账后重算）即清窗；同价建议重生时窗口重开、可再次提醒。
    """
    if state.get('day') != day:
        state.clear()
        state.update(day=day, alerts={}, baselines={})
    state.setdefault('baselines', {})
    alive = {(action['code'], action['side'], str(action['price'])) for action in ticket['actions']}
    # 清掉已消失建议的窗口与已报记录，重生时可重报
    def _advice_of_alert(k):
        parts = k.split(':')  # day:code:side:price
        return (parts[1], parts[2], parts[3])
    for stale in [k for k in list(state['alerts']) if _advice_of_alert(k) not in alive]:
        del state['alerts'][stale]
    for stale_key in [k for k in list(state['baselines']) if tuple(k.split(':', 2)) not in alive]:
        del state['baselines'][stale_key]
    messages = []
    for action in ticket['actions']:
        quote = quotes[action['code']]
        last = D(quote['last'])
        extremes = {}
        for label in ('low','high'):
            try:
                value = D(quote.get(label) or 'NaN')
                if value.is_finite() and value > 0:
                    extremes[label] = value
            except ArithmeticError:
                pass
        low = extremes.get('low', last)
        high = extremes.get('high', last)
        key = f"{day}:{action['code']}:{action['side']}:{action['price']}"
        base_key = f"{action['code']}:{action['side']}:{action['price']}"
        price = D(action['price'])
        # 现价触价：触碰发生在当下，必然晚于建议生成 → 有效
        hit_by_last = (last <= price) if action['side'] == 'buy' else (last >= price)
        if base_key not in state['baselines']:
            # 首见：记录极值基准；生成前极值不触发
            state['baselines'][base_key] = dict(low=str(low), high=str(high))
            hit = hit_by_last
            if hit:
                state['alerts'][key] = True
                direction = '买' if action['side'] == 'buy' else '卖'
                messages.append(f"{action['code']} {action['lot']}格 条件{direction} {action['qty']:,}份 @ {action['price']}；现价={last}，腾讯时间={quote.get('time','未知')}；触价发生在建议生成后（首见现价触价），无法确定触价时刻，触价不等于成交，请核对银河。")
            continue
        if key in state['alerts']:
            continue
        base = state['baselines'][base_key]
        if action['side'] == 'buy':
            # 有效：现价触价，或生成后新低（低于基准）且触及触发价
            new_low = 'low' in extremes and low < D(base['low'])
            hit = hit_by_last or (new_low and low <= price)
        else:
            new_high = 'high' in extremes and high > D(base['high'])
            hit = hit_by_last or (new_high and high >= price)
        if hit:
            state['alerts'][key] = True
            key_extreme = 'low' if action['side'] == 'buy' else 'high'
            evidence = (f"建议生成后日内{'最低' if key_extreme == 'low' else '最高'}={extremes[key_extreme]}（基准{base[key_extreme]}）" if key_extreme in extremes else f'现价={last}')
            direction = '买' if action['side'] == 'buy' else '卖'
            messages.append(f"{action['code']} {action['lot']}格 条件{direction} {action['qty']:,}份 @ {action['price']}；{evidence}，现价={last}，腾讯时间={quote.get('time','未知')}；无法确定触价时刻，可能早于建议，触价不等于成交，请核对银河。")
    return '\n'.join(messages)


def root_from_home():
    import os
    return Path(os.environ.get('HERMES_HOME', 'D:/Hermes Agent CN Desktop/data/hermes-home')) / 'cache/grid-account'


def ops_main(argv=None):
    import argparse
    from datetime import datetime, timezone, timedelta
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('auto','preview','execute','grid'), default='auto')
    parser.add_argument('--result', choices=('成功','失败'))
    args = parser.parse_args(argv)
    if args.result:
        parser.error('禁止整票记账；请用grid_weixin_confirm.py显式提供ETF/方向/实际数量/价格/日期/成交ID')
    now = datetime.now(timezone(timedelta(hours=8)))
    current = phase(now)
    if current == 'closed':
        print('休市或非连续交易时段：不生成执行建议')
        return
    ticket = plan(root_from_home())
    if args.phase == 'grid':
        print('【09:24 盘前网格条件建议：按已确认账本计算，不依赖实时行情】')
        print(render(ticket))
        return
    quotes = fetch_quotes()
    live = quotes_are_live(quotes, now)
    ticket['phase'] = 'execute' if current == 'execute' and live and args.phase != 'preview' else 'preview'
    print('【开盘后条件建议】' if ticket['phase'] == 'execute' else '【预览：非当前可执行报价】')
    print(render(ticket))
    print('腾讯报价现价及时间：' + json.dumps({code:dict(last=q['last'],time=q['time']) for code,q in quotes.items()}, ensure_ascii=False))


def intraday_main():
    from datetime import datetime, timezone, timedelta
    from grid_state import locked, save
    now = datetime.now(timezone(timedelta(hours=8)))
    if phase(now) != 'execute':
        return
    quotes = fetch_quotes()
    if not quotes_are_live(quotes, now):
        return
    root = root_from_home()
    ticket = plan(root)  # Always regenerate from current authoritative fills, never old tickets.
    path = root / 'confirmed-intraday-alerts.json'
    with locked(path):
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        message = monitor(ticket, quotes, state, now.date().isoformat())
        save(path, state)
    if message:
        print(WARNING + '\n' + message)


def confirm_main(argv=None):
    import argparse
    from grid_state import record
    from datetime import datetime, timezone, timedelta
    started_at = datetime.now(timezone(timedelta(hours=8))).isoformat()
    parser = argparse.ArgumentParser()
    parser.add_argument('result', choices=('成功','失败'))
    parser.add_argument('--code', choices=CODES)
    parser.add_argument('--side', choices=('buy','sell'))
    parser.add_argument('--qty', type=int)
    parser.add_argument('--price')
    parser.add_argument('--date', help='可选历史日期覆盖；未来/乱序/早于库存结算日拒绝')
    parser.add_argument('--id', dest='execution_id', help='兼容显式成交ID；稳定ID支持重试')
    parser.add_argument('--received-at', help='适配器提供原消息接收ISO时间，必须含时区；省略为本地入口接收时间')
    parser.add_argument('--message-id', help='适配器稳定来源消息身份；自动成交ID必需，非用户输入')
    parser.add_argument('--fill-item-key', default='0', help='同一消息中的稳定成交项键，单笔默认0')
    args = parser.parse_args(argv)
    if args.result == '失败':
        print('未成交：不修改任何成交/库存状态')
        return
    if any(value is None for value in (args.code,args.side,args.qty,args.price)):
        parser.error('成功必须显式提供--code --side --qty --price；禁止按整票推定成交')
    if args.execution_id is None and not args.message_id:
        parser.error('自动成交ID需要适配器--message-id；人工兼容路径可提供--id，不能按价量去重')
    state = record(root_from_home() / f'confirmed-{args.code[-6:]}.json', args.side, args.qty,
                   args.price, args.date, execution_id=args.execution_id,
                   received_at=args.received_at, message_id=args.message_id,
                   fill_item_key=args.fill_item_key, ingestion_at=started_at)
    print(json.dumps({key:state[key] for key in ('code','qty','sellable_qty','max_grid')}, ensure_ascii=False))
    print('现在的剩余操作建议')
    print(render(plan(root_from_home())))


def eod_report(root, now, quotes, bars):
    import hashlib
    ticket = plan(root)
    decisions = {}
    for code, state in ticket['states'].items():
        stamp = str(quotes[code]['time'])
        if not stamp.startswith(now.strftime('%Y%m%d')) or stamp[8:12] < '1500':
            raise ValueError('未获得当日收盘行情')
        rows = bars[code]
        close = D(str(rows[-1]['close']))
        if rows[-1]['date'] != now.date().isoformat() or not close.is_finite() or close <= 0 or abs(close - D(quotes[code]['last'])) > max(D('0.002'), close * D('0.005')):
            raise ValueError('日线与当日收盘快照不一致')
        decisions[code] = dict(close=str(close), qty=state['qty'], sellable_qty=state['sellable_qty'], max_grid=state['max_grid'], net_invested=state['net_invested'], net_unit_cost=state['net_unit_cost'], t_net=state['t_net'], completed_cycles=len(state['t_records']), reason='上移基准评估未验证，保持不改参数；历史日期不补造，未知日期周期不推导20日效率，禁止自动上移/换仓')
    summary = None
    try:
        from grid_summary import summarize_account
        summary = summarize_account(root)
    except (OSError, ValueError):
        summary = None  # 汇总失败不阻断收盘报告，渲染层会标注
    return dict(asof=now.date().isoformat(), policy_version='confirmed-grid-1.5-v1', executable=False, cash=None, warning=WARNING, decisions=decisions, actions=ticket['actions'], summary=summary, state_hashes={code:hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False).encode()).hexdigest() for code,state in ticket['states'].items()}, names=ticket.get('names'), source='腾讯日线和收盘快照交叉核验；仅已确认ETF状态')


def render_eod(report):
    """Human-readable EOD summary for Feishu delivery; never a broker order.

    表格化输出（2026-10-26 用户要求）：持仓概览表 + 累计做T表 + 当日做T表，
    全部数据来自 report['summary']（grid_summary 模块产出），不手拼数字。
    """
    lines = ['【收盘效率与轮换检查 ' + report.get('asof', '') + '】']
    warning = report.get('warning', '')
    if warning:
        lines.append('⚠️ ' + warning)
    names = report.get('names') or {}
    asof = report.get('asof', '')

    # ① 持仓概览表
    lines.append('')
    lines.append('## 持仓概览')
    lines.append('| ETF | 收盘 | 持有 | 可卖 | 最大格 | 净投入 | T净利 | 完成T轮 |')
    lines.append('|---|---|---|---|---|---|---|---|')
    for code, d in report.get('decisions', {}).items():
        lines.append(
            f"| {code} {names.get(code, '')} | {d['close']} | {d['qty']:,} | {d['sellable_qty']:,} "
            f"| {d['max_grid']} | {d['net_invested']} | {d['t_net']} | {d['completed_cycles']} |"
        )

    summary = report.get('summary')
    if summary is None:
        lines.append('')
        lines.append('⚠️ 汇总数据不可用（账本读取失败），做T表省略')
    else:
        etfs = summary.get('etfs', {})
        daily = summary.get('daily', {})
        totals = summary.get('totals', {})

        # ② 累计做T表
        lines.append('')
        lines.append('## 累计做T')
        lines.append('| ETF | T轮数 | 毛利 | 双边佣金 | T净利 |')
        lines.append('|---|---|---|---|---|')
        for code, e in etfs.items():
            lines.append(
                f"| {code} {e['name']} | {e['t_rounds']} | {e['t_gross']} | {e['t_fees']} | {e['t_net']} |"
            )
        window = totals.get('window') or {}
        lines.append(
            f"| **合计** | **{totals.get('t_rounds', 0)}** | **{totals.get('t_gross', '0.00')}** "
            f"| **{totals.get('t_fees', '0.00')}** | **{totals.get('t_net', '0.00')}** |"
        )
        lines.append(
            f"区间 {window.get('start', '—')} → {window.get('end', '—')}｜交易日 {totals.get('trading_days', 0)} 天"
            f"｜净投入合计 {totals.get('net_invested', '—')}"
        )

        # ③ 当日做T表
        today_stats = daily.get(asof)
        lines.append('')
        lines.append(f'## 当日做T（{asof}）')
        if not today_stats or (today_stats.get('rounds', 0) == 0 and today_stats.get('n_buys', 0) == 0 and today_stats.get('n_sells', 0) == 0):
            lines.append('当日无成交')
        else:
            lines.append('| 轮数 | T净利 | 买入笔数 | 卖出笔数 | 买入金额 | 卖出金额 |')
            lines.append('|---|---|---|---|---|---|')
            lines.append(
                f"| {today_stats['rounds']} | {today_stats['t_net']} | {today_stats['n_buys']} "
                f"| {today_stats['n_sells']} | {today_stats['buy_amount']} | {today_stats['sell_amount']} |"
            )

    # ④ 次日条件建议
    lines.append('')
    lines.append('## 剩余操作建议')
    for action in report.get('actions', []):
        direction = '买' if action['side'] == 'buy' else '卖'
        lines.append(f"- {action['code']} {names.get(action['code'], '')} 条件{direction} {action['lot']}格 **{action['qty']:,}份** @ **{action['price']}**")
    lines.append('')
    lines.append('来源：' + report.get('source', '腾讯日线和收盘快照交叉核验；仅已确认ETF状态'))
    return '\n'.join(lines)


def eod_main(render=False):
    from datetime import datetime, timezone, timedelta
    import urllib.request
    from grid_state import save, locked
    now = datetime.now(timezone(timedelta(hours=8)))
    # Use the same exchange holiday gate; after-close itself is not executable.
    if phase(now.replace(hour=10,minute=0)) == 'closed' or now.hour * 60 + now.minute < 915:
        return '收盘未确认或休市：不生成评估'
    quotes = fetch_quotes()
    bars = {}
    for code in H.held_codes():
        bars[code] = fetch_daily_bars(code)
    root = root_from_home()
    report = eod_report(root,now,quotes,bars)
    path = root / 'eod' / f'{now.date().isoformat()}.json'
    with locked(path):
        save(path,report)
    if render:
        return render_eod(report)
    return json.dumps(report,ensure_ascii=False,indent=2)


def safe_entrypoint(function, *args):
    try:
        result = function(*args)
        if result is not None:
            print(result)
    except (OSError, ValueError, KeyError, IndexError, ArithmeticError) as error:
        print(f'行情或状态未验证：不生成执行建议；{error}')


def render(ticket):
    lines = ['【统一已确认ETF网格 1.5%】', WARNING]
    names = ticket.get('names') or {}
    for code, state in ticket['states'].items():
        tag = '（迁移退出：只读，不生成买卖建议）' if not H.is_active(code) else ''
        lines.append(f"{code} {names.get(code,'')} {tag} 持有={state['qty']} 保存可卖={state['sellable_qty']} 最大格={state['max_grid']} 净投入={state['net_invested']} 已完成T净收益={state['t_net']}")
    for action in ticket['actions']:
        direction = '买' if action['side'] == 'buy' else '卖'
        name = names.get(action['code'], '')
        lines.append(f"- {action['code']} {name} 条件{direction} {action['lot']}格 **{action['qty']:,}份** @ **{action['price']}**")
    return '\n'.join(lines)
