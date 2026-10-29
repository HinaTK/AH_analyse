"""One confirmed-state runtime. Advice is conditional, never a broker order."""
import json
import os
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal as D, ROUND_HALF_UP

import holdings as H

CODES = ('sh589720', 'sz159363')          # legacy compatibility only
BUDGETS = {'sh589720': D('8000'), 'sz159363': D('6000')}
GAP = D('0.015')


class RegimeGate:
    """统一四级门控（2026-10-26 合并 entry_timing 位置判定与 ADX 动能判定）。

    级别：暂停买入(五线全破) > 暂停买入(强动能跌势, ADX>=25且收盘<60日线) > 试错仓（破
    1-4 条线）> 正常。从严者胜，任一级拦截即不生成买入建议；卖出保留。
    均线判定复用 tools.etf_research.gate_check（与榜单同源，不重复实现）。
    regime 无 bars 时退回纯 ADX 判定（向后兼容）；行情缺失 fail-open。
    """

    def __init__(self, regimes):
        self._regimes = regimes or {}

    @staticmethod
    def _adonly_blocks(regime):
        return regime['adx'] >= 25 and regime.get('mdi', 0) > regime.get('pdi', 0)

    def _unified(self, code):
        """走 gate_check 的统一判定；返回 (blocks_buy, reason) 或 None。"""
        r = self._regimes.get(code) or {}
        bars = r.get('bars')
        if bars is None:
            return None
        try:
            from tools.etf_research.gate_check import gate
            verdict = gate(bars, regime=r)
        except Exception:
            return None  # 判定失败：退回纯 ADX，不放大拦截范围
        blocks = verdict['blocks_buy']
        level_names = {'no_entry': '暂停买入(五线全破)', 'pause_buy': '暂停买入(强动能跌势)'}
        reason = f"{code} {level_names.get(verdict['level'], verdict['level'])}：{verdict['reason']}"
        return blocks, reason

    def blocks_buy(self, code):
        unified = self._unified(code)
        if unified is not None:
            return unified[0]
        r = self._regimes.get(code)
        if not r or r.get('adx') is None:
            return False  # fail-open：无数据不暂停
        return self._adonly_blocks(r)

    def reason(self, code):
        unified = self._unified(code)
        if unified is not None:
            if unified[0]:
                return unified[1]
            return f"{code} 门控未触发暂停（{unified[1]}）"
        r = self._regimes.get(code)
        if not r or r.get('adx') is None:
            return f'{code} 市况未知（行情缺失，不暂停买入）'
        if self._adonly_blocks(r):
            return f"{code} 单边下跌（ADX={r['adx']:.1f}，-DI {r['mdi']:.0f} > +DI {r['pdi']:.0f}），暂停新格买入，卖出保留"
        return f"{code} 市况未触发暂停"


def _load_market_phase_check():
    """加载 market_phase_check（模块在 tools/ 下）。

    2026-10-27 cron 事故：函数内 `import market_phase_check`（顶层名）在
    cron 环境（sys.path 只有仓库根目录）抛 ImportError，被外层 except
    吞掉 → dict(adx=None) 不带 bars → 门控静默失效（09:20 推了买入）。
    正确定位顺序：tools 子包 → tools 目录加 path → 顶层名兜底。
    """
    try:
        from tools import market_phase_check as mp  # 仓库根目录在 path 时
        return mp
    except ImportError:
        pass
    import importlib
    for candidate in (Path(__file__).resolve().parent / 'tools',):
        if (candidate / 'market_phase_check.py').is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return importlib.import_module('market_phase_check')
    import market_phase_check as mp  # 开发环境兜底
    return mp


def _fetch_regime_klines(code):
    """拉取门控用的日K（截至昨日收盘：drop 今日未收K，ADX/均线均无未来函数）。"""
    mp = _load_market_phase_check()
    rows = mp.fetch_kline(('1.' if code.startswith('sh') else '0.') + code[-6:], lmt=300, klt='101')
    # 盘中丢掉今日未收K（drop_unclosed_bar 在 entry_timing，不在 market_phase_check）
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8)))
    if now.hour < 15:
        today = now.strftime('%Y-%m-%d')
        rows = [r for r in rows if r['date'] != today]
    return rows


def fetch_daily_regime(code):
    """算某ETF的市况（ADX/±DI + 同一批日K bars，供统一门控均线判定）。

    2026-10-26 合并后：一次拉数，ADX 和均线共用同一事实源。
    2026-10-27 修复：ADX 算不出时仍返回 bars（五线判定只吃日线），
    只有日线本身拿不到才 dict(adx=None)——不让 ADX 的失败拖死均线判定。
    """
    import pandas as pd
    try:
        rows = _fetch_regime_klines(code)
    except Exception:
        return dict(adx=None)
    frame = pd.DataFrame(rows)
    adx = pdi = mdi = None
    try:
        mp = _load_market_phase_check()
        result = mp.wilder_adx(rows)
        if result:
            adx, pdi, mdi = result
    except Exception:
        pass  # ADX 失败：bars 照带，五线判定不受影响
    return dict(adx=adx, pdi=pdi, mdi=mdi, bars=frame)
WARNING = ('条件建议，非可直接执行委托：sz159992 处于迁移退出模式（停买、停接回、只卖不买），'
           '00:01 已同步可卖份额；账户现金、银河冻结及在途委托未对账，不自动下单，触价不等于成交。')
DAILY_BAR_SOURCES = (
    'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param={code},day,,,80,qfq',
    'https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,80,qfq',
)


REGIME_CACHE_NAME = 'regime-cache.json'
REGIME_CACHE_FRESH_DAYS = 1  # 盘前期望昨日收盘；允许今日收盘（15:35后重算）


def _regime_cache_path(root):
    return Path(root) / REGIME_CACHE_NAME


def save_regime_cache(root, regimes_verdicts):
    """把门控判定落盘（15:35 收盘后调用；盘前 09:20 兜底读它）。

    参数 regimes_verdicts: {code: {level, blocks_buy, reason, asof, adx}}
    2026-10-28 用户定：早间拉行情不可靠，判断要提前做好。
    """
    path = _regime_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(regimes_verdicts, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)
    return path


def load_regime_cache(root, expect_asof, allow_stale=False):
    """读缓存；日期戳必须是 expect_asof（昨日收盘）或今日（15:35 后重算的当日）。

    allow_stale=True 用于现拉失败的兜底：过期缓存好过没缓存（门控在，
    至少拦的是稍旧的状态——宁可多拦一天，不可 fail-open 放行接飞刀）。
    """
    path = _regime_cache_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None
    today = date.today().isoformat()
    for v in data.values():
        asof = v.get('asof')
        if asof not in (expect_asof, today):
            return None if not allow_stale else data
        break
    return data


def build_gate(root, expect_asof=None, fetch=True):
    """构建门控（三级降级）：现拉 → 缓存（期望日期）→ 过期缓存 → None。

    2026-10-28 之前的行为是"现拉失败即 None（fail-open）"——两次事故
    （10-27 sys.path、10-28 解释器）都是这个缝隙。现在缓存兜底后，
    只有连缓存都没有（首次运行/被删）才会 None。
    """
    cache = load_regime_cache(root, expect_asof or date.today().isoformat()) if root else None
    if cache is not None:
        return _cache_to_regimes(cache)  # _CachedGate：鸭子类型（blocks_buy/reason），不套 RegimeGate
    if fetch:
        try:
            regimes = {code: fetch_daily_regime(code) for code in H.held_codes()}
            gate = RegimeGate(regimes)
            # 现拉成功也顺手落缓存（下一道保险）
            save_regime_cache(root, _regimes_to_cache(regimes))
            return gate
        except Exception:
            pass
    stale = load_regime_cache(root, expect_asof or date.today().isoformat(), allow_stale=True) if root else None
    if stale is not None:
        return _cache_to_regimes(stale)
    return None


def _regimes_to_cache(regimes):
    """RegimeGate 兼容 dict（含 adx/bars）→ 缓存格式（level/blocks_buy/reason）。

    asof 语义：bars 最后一根的日期（盘中手动落缓存时 fetch 已 drop 今日
    未收K → asof=昨日；15:30 收盘后落 → asof=今日收盘。戳与数据一致）。
    """
    out = {}
    root = root_from_home()
    for code, r in regimes.items():
        bars = r.get('bars')
        verdict = None
        if bars is not None:
            try:
                from tools.etf_research.gate_check import gate as gate_fn
                import pandas as pd
                frame = bars if isinstance(bars, pd.DataFrame) else pd.DataFrame(bars)
                verdict = gate_fn(frame, regime=r)
            except Exception:
                verdict = None
        bars = r.get('bars')
        try:
            last_date = str(bars.iloc[-1]['date']) if bars is not None and len(bars) else None
        except Exception:
            last_date = None
        try:
            last_close = str(bars.iloc[-1]['close']) if bars is not None and len(bars) else None
        except Exception:
            last_close = None
        entry = dict(level=(verdict or {}).get('level') or ('pause_buy' if r.get('adx') and r['adx'] >= 20 else 'probe_only'),
                     blocks_buy=bool((verdict or {}).get('blocks_buy')),
                     reason=(verdict or {}).get('reason') or '缓存降级判定',
                     adx=r.get('adx'), close=last_close,
                     asof=last_date or date.today().isoformat())
        out[code] = entry
    return out


def _cache_to_regimes(cache):
    """缓存格式 → RegimeGate 兼容 dict（直接 blocks_buy 判定走缓存值）。"""
    class _CachedGate:
        def __init__(self, entries):
            self._entries = entries

        def blocks_buy(self, code):
            e = self._entries.get(code)
            return bool(e and e.get('blocks_buy'))

        def reason(self, code):
            e = self._entries.get(code) or {}
            level_names = {'no_entry': '暂停买入(五线全破)', 'pause_buy': '暂停买入(强动能跌势)'}
            head = f"{code} {level_names.get(e.get('level'), e.get('level') or '门控')}："
            return head + (e.get('reason') or '缓存判定')

        def close(self, code):
            e = self._entries.get(code) or {}
            return e.get('close')

        def was_blocked(self, code):
            """恢复日检测：本 gate 自身不拦但缓存历史拦过（由调用方比对昨日缓存）。"""
            return False

        @property
        def _regimes(self):
            return self._entries
    return _CachedGate(cache)


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


REANCHOR_DEVIATION = D('0.015')  # 偏离超过一个格距才重锚（2026-10-29 用户定）


def reanchor_price(old_next, spot):
    """门控恢复日重锚判定：旧格买价偏离现市 > 一个格距时，锚到现价下方一档。

    规则（2026-10-29 用户确认"落地一下"）：
    - 偏离 = old_next / spot - 1，绝对值 > 1.5% 才动
    - 重锚价 = spot × (1 - GAP)：保证低于现价（挂得出去、不追高）
    - 偏离在带内 → None（维持原网格价，不抖散结构）
    """
    if old_next is None or spot is None:
        return None
    old_next = D(str(old_next))
    spot = D(str(spot))
    if spot <= 0:
        return None
    deviation = abs(old_next / spot - 1)
    if deviation <= REANCHOR_DEVIATION:
        return None
    return price(spot * (1 - GAP))


def plan(root, regime_gate=None, spot=None, gate_lifted=None):
    states = load_states(root)
    holdings = H.load_holdings()
    budgets = H.lot_budgets(holdings)
    names = H.names(holdings)
    actions = []
    regime_blocks = []
    reanchors = []
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
            if regime_gate is not None and regime_gate.blocks_buy(code):
                regime_blocks.append(regime_gate.reason(code))
            else:
                px = price(D(top['price'] if top else state['trades'][-1]['price']) / (1 + GAP))
                # 门控恢复日重锚（2026-10-29）：旧格价脱离现市>1格距 → 锚到现价下方一档
                if gate_lifted and gate_lifted.get(code) and spot and spot.get(code) is not None:
                    new_px = reanchor_price(px, spot[code])
                    if new_px is not None and new_px != px:
                        reanchors.append(dict(code=code, old_price=str(px), new_price=str(new_px),
                                              spot=str(spot[code]), lot=chr(65 + depth)))
                        px = new_px
                qty = int(budgets[code] / (D(px) * 100)) * 100
                if qty:
                    actions.append(dict(code=code, side='buy', price=px, qty=qty, lot=chr(65 + depth)))
    ticket = dict(actions=actions, executable=False, cash=None, warning=WARNING, states=states, names=names)
    if regime_gate is not None:
        ticket['regime_blocks'] = regime_blocks
    if reanchors:
        ticket['reanchor'] = reanchors
    return ticket


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
    parser.add_argument('--no-regime-gate', action='store_true',
                        help='关闭单边下跌买入暂停（紧急用；默认开启联动）')
    args = parser.parse_args(argv)
    if args.result:
        parser.error('禁止整票记账；请用grid_weixin_confirm.py显式提供ETF/方向/实际数量/价格/日期/成交ID')
    now = datetime.now(timezone(timedelta(hours=8)))
    current = phase(now)
    if current == 'closed':
        print('休市或非连续交易时段：不生成执行建议')
        return
    gate = None
    if not args.no_regime_gate:
        # 2026-10-28 用户定：早间拉行情不可靠，判断提前做好。
        # 三级降级：盘前期望"昨日收盘"缓存 → 现拉（成功顺手落缓存）→ 过期缓存 → None
        try:
            from datetime import timedelta as _td
            yesterday = (datetime.now(timezone(_td(hours=8))) - _td(days=1)).date().isoformat()
            gate = build_gate(root_from_home(), expect_asof=yesterday)
        except Exception:
            gate = None  # 三级全部失败（无缓存+现拉失败）才 fail-open
    # 恢复日重锚（2026-10-29 用户定）：昨日拦+今日放 → gate_lifted；
    # spot 用 gate 的收盘价（与恢复判定同源，无未来函数）
    gate_lifted = {}
    spot = {}
    if gate is not None:
        try:
            yesterday_cache = load_regime_cache(root_from_home(), expect_asof=yesterday, allow_stale=True)
        except Exception:
            yesterday_cache = None
        for code in H.held_codes():
            try:
                if yesterday_cache and yesterday_cache.get(code, {}).get('blocks_buy') and not gate.blocks_buy(code):
                    gate_lifted[code] = True
                close_attr = getattr(gate, 'close', None)
                if close_attr:
                    c = close_attr(code)
                    if c is not None:
                        spot[code] = D(str(c))
            except Exception:
                pass
    ticket = plan(root_from_home(), regime_gate=gate, spot=spot or None,
                  gate_lifted=gate_lifted or None)
    if args.phase == 'grid':
        print('【09:20 盘前网格条件建议：按已确认账本计算，不依赖实时行情】')
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

        # ③ 当日做T表（按ETF分桶，含合计行）
        today_stats = daily.get(asof)
        lines.append('')
        lines.append(f'## 当日做T（{asof}）')
        if not today_stats or (today_stats.get('rounds', 0) == 0 and today_stats.get('n_buys', 0) == 0 and today_stats.get('n_sells', 0) == 0):
            lines.append('当日无成交')
        else:
            lines.append('| ETF | 轮数 | T净利 | 买入笔数 | 卖出笔数 | 买入金额 | 卖出金额 |')
            lines.append('|---|---|---|---|---|---|---|')
            for code, eb in (today_stats.get('by_etf') or {}).items():
                etf_name = etfs.get(code, {}).get('name', '')
                lines.append(
                    f"| {code} {etf_name} | {eb['rounds']} | {eb['t_net']} | {eb['n_buys']} "
                    f"| {eb['n_sells']} | {eb['buy_amount']} | {eb['sell_amount']} |"
                )
            lines.append(
                f"| **合计** | **{today_stats['rounds']}** | **{today_stats['t_net']}** "
                f"| **{today_stats['n_buys']}** | **{today_stats['n_sells']}** "
                f"| **{today_stats['buy_amount']}** | **{today_stats['sell_amount']}** |"
            )

    # 收盘推送不再带"剩余操作建议"（2026-10-26 用户要求：收盘后建议无意义，归09:20盘前任务）
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
    for block in ticket.get('regime_blocks') or []:
        lines.append(f"⛔ {block}")
    for r in ticket.get('reanchor') or []:
        lines.append(f"📍 {r['code']} 门控恢复日重锚：{r['lot']}格买价 {r['old_price']} → {r['new_price']}"
                     f"（恢复时收盘 {r['spot']}，旧格价偏离箱体超一档；旧格卖单保持原价等解套）")
    for action in ticket['actions']:
        direction = '买' if action['side'] == 'buy' else '卖'
        name = names.get(action['code'], '')
        lines.append(f"- {action['code']} {name} 条件{direction} {action['lot']}格 **{action['qty']:,}份** @ **{action['price']}**")
    return '\n'.join(lines)
