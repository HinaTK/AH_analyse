"""Read-only market gate estimates; persist only this observer's diagnostics.

Public API: evaluate(root, now=..., history_fn=..., quote_fn=...) is read-only.
run(...) saves observer state and returns only changed/error alert text; main(...)
prints that text. Injected history_fn(code) and quote_fn(code) never need network.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import urllib.request
import uuid

from confirmed_calendar import is_session
from confirmed_state_validation import validate_state
from grid_state import locked, save

CN = timezone(timedelta(hours=8))
DEFAULT_HOME = Path('D:/Code/AH_analyse/.cache/grid-home')
PROVISIONAL_METHOD = 'legacy_daily_gate'
HEADER = '【盘中门控观察：仅预估，不切换正式门控】'
FOOTER = '未收盘确认，正式门控未切换；不构成可执行买单。'
LEVELS = {'normal': False, 'probe_only': False, 'pause_buy': True, 'no_entry': True}
# 展示口径（Master 2026-11-09）：推送正文一律「中文加粗 + emoji」，不出现裸英文级别名。
# 只作用于渲染层；LEVELS、判据、快照与去重签名仍用内部英文键，避免影响变更检测。
LEVEL_LABELS = {
    'normal': '**✅ 正常可买**',
    'probe_only': '**🟡 试错仓**',
    'pause_buy': '**⏸️ 暂停买入**',
    'no_entry': '**⛔ 禁止建仓**',
}


class WatchError(ValueError):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def default_root():
    """Standalone DSH default; no Hermes Desktop fallback or discovery."""
    return Path(os.environ.get('HERMES_HOME') or DEFAULT_HOME) / 'cache/grid-account'


def _now(value=None):
    value = value or datetime.now(CN)
    # Injected naive times are explicitly interpreted as China market wall time.
    return value.replace(tzinfo=CN) if value.tzinfo is None else value.astimezone(CN)


def _session_part(stamp):
    minute = stamp.hour * 60 + stamp.minute
    if 9 * 60 + 31 <= minute <= 11 * 60 + 30:
        return 'morning'
    if 13 * 60 <= minute <= 14 * 60 + 59:
        return 'afternoon'
    return None


def _same_session(start, current):
    return current.date() == start.date() and _session_part(current) == _session_part(start)


def previous_session(day):
    previous = day - timedelta(days=1)
    while not is_session(previous):
        previous -= timedelta(days=1)
    return previous


def _market_module():
    # Pin the helper's import-time holdings read to DSH; its enumeration is unused.
    previous_home = os.environ.get('HERMES_HOME')
    if not previous_home:
        os.environ['HERMES_HOME'] = str(DEFAULT_HOME)
    try:
        from tools import market_phase_check
        return market_phase_check
    finally:
        if previous_home is None:
            os.environ.pop('HERMES_HOME', None)
        else:
            os.environ['HERMES_HOME'] = previous_home


def fetch_history(code):
    secid = ('1.' if code.startswith('sh') else '0.') + code[-6:]
    return _market_module().fetch_tencent_kline(secid, lmt=300, klt='101')


def fetch_quote(code):
    """Direct Tencent snapshot (GBK): open/high/low/last/prev/quote timestamp."""
    request = urllib.request.Request(
        'https://qt.gtimg.cn/q=' + code,
        headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'})
    with urllib.request.urlopen(request, timeout=15) as response:
        text = response.read().decode('gbk')
    match = re.search(r'v_' + re.escape(code) + r'="([^"]+)"', text)
    if not match:
        raise ValueError('腾讯快照缺失对应代码')
    fields = match.group(1).split('~')
    if len(fields) <= 34 or fields[2] != code[-6:]:
        raise ValueError('腾讯快照代码或字段不匹配')
    stamp = datetime.strptime(fields[30], '%Y%m%d%H%M%S').replace(tzinfo=CN)
    return dict(name=fields[1], open=float(fields[5]), high=float(fields[33]),
                low=float(fields[34]), last=float(fields[3]), prev=float(fields[4]),
                timestamp=stamp.isoformat())


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _ohlc(row, close_key, kind):
    try:
        values = {key: float(row[key]) for key in ('open', 'high', 'low', close_key)}
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError('价格须为有限正数')
        if not (values['low'] <= min(values['open'], values[close_key])
                <= max(values['open'], values[close_key]) <= values['high']):
            raise ValueError('OHLC范围不一致')
        return values
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise WatchError(kind, f'OHLC未验证：{exc}') from exc


def _validated_quote(quote, now):
    values = _ohlc(quote, 'last', 'quote_invalid')
    try:
        prev = float(quote['prev'])
        if not math.isfinite(prev) or prev <= 0:
            raise ValueError('前收须为有限正数')
        raw_stamp = quote['timestamp']
        stamp = raw_stamp if isinstance(raw_stamp, datetime) else datetime.fromisoformat(raw_stamp)
        stamp = _now(stamp)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise WatchError('quote_invalid', f'行情前收/时间未验证：{exc}') from exc
    if stamp.date() != now.date():
        raise WatchError('quote_wrong_day', '行情日期不是当前交易日')
    age = (now - stamp).total_seconds()
    if age < 0:
        raise WatchError('quote_future', '行情时间位于未来')
    if age > 180:
        raise WatchError('quote_stale', f'行情已过期（{age:.0f}秒）')
    if _session_part(stamp) != _session_part(now):
        raise WatchError('quote_session', '行情不是当前连续交易时段快照')
    return dict(values, prev=prev, timestamp=stamp.isoformat())


def _completed_rows(history, today, previous):
    rows, dates = [], set()
    try:
        for row in history:
            day = date.fromisoformat(row['date'])
            if day >= today:
                continue  # Discard every existing today row before one synthetic upsert.
            # The verified live calendar is limited to 2026; a 300-bar feed also
            # contains older completed years. Its last date is checked strictly.
            if day in dates or day.weekday() >= 5:
                raise ValueError('历史日期重复或不是工作日')
            dates.add(day)
            values = _ohlc(row, 'close', 'history_invalid')
            rows.append(dict(date=day.isoformat(), **values))
    except WatchError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise WatchError('history_invalid', f'历史日K未验证：{exc}') from exc
    rows.sort(key=lambda row: row['date'])
    if len(rows) < 65:
        raise WatchError('history_insufficient', f'完整历史仅{len(rows)}根，至少需要65根')
    if rows[-1]['date'] != previous.isoformat():
        raise WatchError('history_stale', f'最后完整日不是上一交易日{previous.isoformat()}')
    return rows


def _official(cache, code, previous):
    if not isinstance(cache, dict) or code not in cache:
        raise WatchError('official_missing', '正式门控缓存未覆盖该标的')
    entry = cache[code]
    if not isinstance(entry, dict):
        raise WatchError('official_invalid', '正式门控缓存条目无效')
    metadata = ' '.join(str(entry.get(key, '')) for key in ('reason', 'tag', 'reason_tag'))
    # 正式门控必须与盘中预估的 legacy 口径一致；任何其它方法标记都拒绝比较。
    if (str(entry.get('mode', '')).lower() not in ('', 'legacy', 'legacy_daily_gate')
            or str(entry.get('method', '')).lower() not in ('', 'legacy', 'legacy_daily_gate')
            or re.search(r'\b(?:atr_expand|five_break)\b', metadata)):
        raise WatchError('official_method_mismatch', '正式门控不是 legacy 口径，与盘中均线/DMI规则不一致，不能比较解除')
    if (not isinstance(entry.get('level'), str) or entry['level'] not in LEVELS
            or type(entry.get('blocks_buy')) is not bool
            or LEVELS[entry['level']] != entry['blocks_buy']):
        raise WatchError('official_invalid', '正式门控级别/买入拦截状态未验证')
    if entry.get('asof') != previous.isoformat():
        raise WatchError('official_stale', f'正式门控不是上一完整交易日{previous.isoformat()}，今日未收盘缓存无效')
    return dict(entry)


def _error(code, name, kind, message, buy_paused=False):
    return dict(status='error', code=code, name=name, kind=kind,
                message=str(message), buy_paused=buy_paused)


def evaluate(root=None, *, now=None, history_fn=None, quote_fn=None):
    """Evaluate active held ETFs without writes; closed sessions do no I/O/network.

    Returns {status, trade_day, observed_at, provisional_method, results}. Per-code
    errors never carry a provisional verdict. Quote timestamps are China time;
    injection accepts ISO strings (or datetime objects), including aware offsets.
    """
    live_clock = now is None
    now = _now(now)
    report = dict(status='closed', trade_day=now.date().isoformat(),
                  observed_at=now.isoformat(), provisional_method=PROVISIONAL_METHOD, results={})
    try:
        if not is_session(now.date()) or not _session_part(now):
            return report
        previous = previous_session(now.date())
    except ValueError as exc:
        report.update(status='calendar_error', results={
            '_account': _error('_account', '交易日历', 'calendar_invalid', exc)})
        return report
    report['status'] = 'ok'
    root = Path(root) if root is not None else default_root()
    try:
        raw = _read_json(root / 'holdings.json')
        holdings = raw.get('holdings', raw)
        if not isinstance(holdings, dict):
            raise ValueError('holdings必须是对象')
    except (OSError, ValueError, AttributeError) as exc:
        report['results']['_account'] = _error('_account', '持仓清单', 'holdings_invalid', exc)
        return report
    try:
        cache = _read_json(root / 'regime-cache.json')
        cache_error = None
    except (OSError, ValueError) as exc:
        cache, cache_error = None, str(exc)
    history_fn, quote_fn = history_fn or fetch_history, quote_fn or fetch_quote
    for code, info in sorted(holdings.items()):
        if not isinstance(info, dict):
            report['results'][code] = _error(code, code, 'holdings_invalid', '标的持仓设置无效')
            continue
        if info.get('active') is not True:
            continue
        name, paused = info.get('name') or code, info.get('buy_paused') is True
        try:
            if not re.fullmatch(r'(sh|sz)\d{6}', code):
                raise ValueError('标的代码无效')
            state = _read_json(root / f'confirmed-{code[-6:]}.json')
            validate_state(state)
            if state['code'] != code:
                raise ValueError('确认账本代码不匹配')
            if state['qty'] == 0:
                continue
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report['results'][code] = _error(code, name, 'state_invalid', exc, paused)
            continue
        try:
            if cache_error:
                raise WatchError('official_invalid', '正式缓存不可读：' + cache_error)
            official = _official(cache, code, previous)
            try:
                quote = quote_fn(code)
            except Exception as exc:
                raise WatchError('quote_fetch', f'快照取数失败：{exc}') from exc
            checked_at = _now() if live_clock else now
            if not _same_session(now, checked_at):
                report.update(status='closed', results={})
                return report
            quote = _validated_quote(quote, checked_at)
            try:
                history = history_fn(code)
            except Exception as exc:
                raise WatchError('history_fetch', f'历史取数失败：{exc}') from exc
            checked_at = _now() if live_clock else now
            if not _same_session(now, checked_at):
                report.update(status='closed', results={})
                return report
            quote = _validated_quote(quote, checked_at)
            rows = _completed_rows(history, now.date(), previous)
            if abs(Decimal(str(rows[-1]['close'])) - Decimal(str(quote['prev']))) > Decimal('0.002'):
                raise WatchError('prev_close_mismatch', '历史前收与腾讯快照prev相差超过0.002')
            completed = len(rows)
            rows.append(dict(date=now.date().isoformat(), open=quote['open'],
                             high=quote['high'], low=quote['low'], close=quote['last']))
            try:
                import pandas as pd
                from tools.etf_research.gate_check import gate
                dmi = _market_module().wilder_adx(rows)
                if dmi is None or len(dmi) != 3 or not all(math.isfinite(v) and v >= 0 for v in dmi):
                    raise ValueError('Wilder ADX/DI不可用')
                adx, pdi, mdi = dmi
                provisional = gate(pd.DataFrame(rows), regime=dict(adx=adx, pdi=pdi, mdi=mdi))
                if (provisional.get('level') not in LEVELS
                        or type(provisional.get('blocks_buy')) is not bool
                        or LEVELS[provisional['level']] != provisional['blocks_buy']):
                    raise ValueError('门控判定状态无效')
            except Exception as exc:
                raise WatchError('calculation_invalid', f'指标/门控未验证：{exc}') from exc
            report['results'][code] = dict(
                status='ok', code=code, name=name, quote=quote, official=official,
                provisional=provisional, provisional_method=PROVISIONAL_METHOD,
                adx=adx, pdi=pdi, mdi=mdi, completed_bars=completed,
                checked_at=checked_at.isoformat(), buy_paused=paused)
        except WatchError as exc:
            report['results'][code] = _error(code, name, exc.kind, exc, paused)
    return report


def _signature(verdict):
    return [verdict['level'], verdict['blocks_buy']]


def _alert_reason(prior, provisional, official_state, official):
    """去重判据（Master 2026-11-09 授权降噪）：只在拦买结论翻转或正式门控变化时推。

    prior / official_state 为上一拍签名 [级别, 是否拦买]，首拍为 None。
    两档都拦买（暂停买入 ↔ 禁止建仓）或都放行之间的级别跳档不推——
    价格贴均线反复穿越会制造无信息量推送，实际能不能买并未改变。
    """
    if prior is None:
        if provisional[1] != official[1]:
            return dict(kind='first', **{'from': None}, to=provisional[0],
                        official_changed=False, official_from=None, official_to=None)
        return None
    block_flip = prior[1] != provisional[1]
    official_changed = official_state != official
    if not (block_flip or official_changed):
        return None
    return dict(kind='change', **{'from': prior[0]}, to=provisional[0],
                official_changed=official_changed,
                official_from=(official_state or [None])[0],
                official_to=official[0])


def _render(alerts):
    if not alerts:
        return ''
    lines = [HEADER]
    for result in alerts:
        identity = f"{result['code']} {result['name']}"
        if result['status'] == 'error':
            lines.append(f"⚠️取数/状态未验证 {identity}：{result['message']}（{result['kind']}）")
        else:
            official, provisional, quote = result['official'], result['provisional'], result['quote']
            lines.extend([
                f"{identity} 现价 {quote['last']:.3f}｜行情时间 {quote['timestamp']}",
                f"正式 {LEVEL_LABELS[official['level']]}（{official['asof']}）"
                f" ｜ 盘中预估（均线/DMI口径） {LEVEL_LABELS[provisional['level']]}",
                f"ADX={result['adx']:.2f} / +DI={result['pdi']:.2f} / -DI={result['mdi']:.2f}",
                '正式原因：' + str(official.get('reason') or '缓存未提供原因'),
                '盘中预估原因：' + provisional['reason'],
            ])
            change = result.get('change')
            if change:
                if change['kind'] == 'first':
                    lines.append('本次变化：本交易日首拍，正式门控与盘中预估的拦买结论不一致')
                else:
                    tail = ('；正式门控由 %s → %s' % (
                        LEVEL_LABELS.get(change['official_from'], '**🟡 门控待确认**'),
                        LEVEL_LABELS[change['official_to']])
                        if change['official_changed'] else '（正式门控未变）')
                    lines.append('本次变化：盘中预估 由 %s → %s%s' % (
                        LEVEL_LABELS.get(change['from'], '**🟡 门控待确认**'),
                        LEVEL_LABELS[change['to']], tail))
        if result.get('buy_paused'):
            lines.append('⚠️用户暂停买入 buy_paused=true 独立生效；本观察仅描述市场预估，不改变用户开关。')
    return '\n'.join(lines + [FOOTER])


def run(root=None, *, now=None, history_fn=None, quote_fn=None):
    """Save one diagnostic snapshot per in-session run; return deduplicated text.

    Only intraday-gate-watch/latest.json and snapshots/YYYY-MM-DD/*.json are
    persisted. grid_state's OS lock belongs exclusively to observer latest.json.
    """
    root = Path(root) if root is not None else default_root()
    report = evaluate(root, now=now, history_fn=history_fn, quote_fn=quote_fn)
    if report['status'] == 'closed':
        return ''
    if report['status'] == 'calendar_error':
        return _render(list(report['results'].values()))  # Unverified calendar: no writes.
    if now is None and not _same_session(datetime.fromisoformat(report['observed_at']), _now()):
        return ''
    directory = root / 'intraday-gate-watch'
    latest_path = directory / 'latest.json'
    with locked(latest_path):
        if latest_path.exists():
            try:
                latest = _read_json(latest_path)
                if (not isinstance(latest.get('codes'), dict)
                        or any(not isinstance(state, dict) for state in latest['codes'].values())):
                    raise ValueError('观察器codes或标的状态不是对象')
            except (OSError, ValueError, AttributeError) as exc:
                report['results']['_observer'] = _error('_observer', '观察器状态', 'observer_invalid', exc)
                _save_snapshot(directory, report)
                return _render([report['results']['_observer']])
        else:
            latest = dict(version=1, codes={})
        if latest.get('trade_day') != report['trade_day']:
            for state in latest['codes'].values():
                state.update(provisional_state=None, official_state=None, error_kind=None)
        alerts = []
        for code, result in report['results'].items():
            state = latest['codes'].setdefault(code, dict(last_success=None))
            state['last_result'] = result
            if result['status'] == 'error':
                if state.get('error_kind') != result['kind']:
                    alerts.append(result)
                state['error_kind'] = result['kind']
                continue
            provisional, official = _signature(result['provisional']), _signature(result['official'])
            prior = state.get('provisional_state')
            change = _alert_reason(prior, provisional, state.get('official_state'), official)
            if change is not None:
                result['change'] = change
                alerts.append(result)
            state.update(last_success=result, provisional_state=provisional,
                         official_state=official, error_kind=None)
        latest.update(trade_day=report['trade_day'], updated_at=report['observed_at'])
        report['alert_codes'] = [item['code'] for item in alerts]
        _save_snapshot(directory, report)
        save(latest_path, latest)
    return _render(alerts)


def _save_snapshot(directory, report):
    stamp = datetime.fromisoformat(report['observed_at']).strftime('%H%M%S-%f')
    # UUID keeps diagnostics distinct even for concurrent/repeated fixed-time runs.
    target = directory / 'snapshots' / report['trade_day'] / f'{stamp}-{uuid.uuid4().hex[:12]}.json'
    save(target, report)


def main(*, root=None, now=None, history_fn=None, quote_fn=None):
    text = run(root, now=now, history_fn=history_fn, quote_fn=quote_fn)
    if text:
        print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
