"""Daily-line gate for opening or rotating into a position. Not an order.

Distances are measured in 14-day ATR so the same rule fits low- and
high-volatility ETFs. A close above the 20-day average is an entry only when a
low in the last 3 sessions came back to the 20-day line and the close is no more
than 2 ATR above it; otherwise it is not an entry, and a close above the
5/10/20/30/60-day averages that is at or above 3% under the prior 20-session high
is rejected outright. A close under the 60-day average is always a probe, whether or not that average
is still falling. The probe exits on a close through the lowest low of the last
20 sessions. A full position requires at least 3 consecutive closes above a 60-day
average that is not falling, plus the 20-day pullback with the close holding the
20-day line.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

import pandas as pd

ATR_DAYS = 14
TOUCH_ATR = 0.5
EXTEND_ATR = 2.0
TOUCH_DAYS = 3
NEAR_HIGH = 0.03
SLOPE_DAYS = 5
HIGH_LOOKBACK = 20
EXIT_LOOKBACK = 20
HOLD_DAYS = 3
MIN_ROWS = 60 + SLOPE_DAYS
MARKET_TZ = timezone(timedelta(hours=8))
MARKET_CLOSE_HOUR = 15
DAILY_URL = (
    'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
    'CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen=400'
)
LABELS = {
    'reject': '否决建仓',
    'no_entry': '暂停买入(五线全破)',
    'probe_only': '仅试错仓',
    'full': '可以整仓',
    'wait': '等待触发',
    'insufficient': '数据不足',
}


def prefix_code(code):
    text = str(code).strip().lower()
    if text.startswith(('sh', 'sz', 'bj')):
        return text
    if text.startswith(('5', '6', '9')):
        return 'sh' + text
    if text.startswith(('4', '8')):
        return 'bj' + text
    return 'sz' + text


def drop_unclosed_bar(frame, now=None):
    """Drop today's bar while the session is still open; it is not a close."""
    now = now or datetime.now(MARKET_TZ)
    if frame.empty or now.hour >= MARKET_CLOSE_HOUR:
        return frame
    today = now.strftime('%Y-%m-%d')
    return frame[frame['date'] != today].reset_index(drop=True)


def fetch_daily(code):
    request = urllib.request.Request(
        DAILY_URL.format(code=prefix_code(code)),
        headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn'},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        rows = json.load(response)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'empty daily response for {code}')
    frame = pd.DataFrame(rows).rename(columns={'day': 'date'})
    return drop_unclosed_bar(prepare(frame))


def prepare(frame):
    out = frame.copy()
    if 'date' not in out.columns:
        out = out.rename(columns={'time': 'date'})
    out['date'] = pd.to_datetime(out['date']).dt.strftime('%Y-%m-%d')
    for column in ('open', 'high', 'low', 'close'):
        out[column] = pd.to_numeric(out[column], errors='raise')
    out = out.sort_values('date').drop_duplicates('date', keep='last').reset_index(drop=True)
    if out.empty or out['date'].duplicated().any():
        raise ValueError('empty or duplicate daily bars')
    if (out[['open', 'high', 'low', 'close']] <= 0).any().any():
        raise ValueError('non-positive daily prices')
    return out


def _levels(frame):
    out = frame.copy()
    for period in (5, 10, 20, 30, 60):
        out[f'ma{period}'] = out['close'].rolling(period).mean()
    prev_close = out['close'].shift(1)
    true_range = pd.concat([
        out['high'] - out['low'],
        (out['high'] - prev_close).abs(),
        (out['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = true_range.rolling(ATR_DAYS).mean()
    out['touch'] = out['low'] <= out['ma20'] + TOUCH_ATR * out['atr']
    out['prior_high'] = out['high'].shift(1).rolling(HIGH_LOOKBACK).max()
    out['ma60_prev'] = out['ma60'].shift(SLOPE_DAYS)
    out['exit_low'] = out['low'].rolling(EXIT_LOOKBACK).min()
    return out


def _days_above_ma60(levelled, today):
    """Consecutive closes above the 60-day line, counting back from today."""
    days = 0
    for index in range(today, -1, -1):
        ma60 = levelled['ma60'].iloc[index]
        if pd.isna(ma60) or levelled['close'].iloc[index] <= ma60:
            break
        days += 1
    return days


def judge_entry(frame, asof=None):
    daily = prepare(frame)
    if asof is not None:
        asof = pd.to_datetime(asof).strftime('%Y-%m-%d')
        daily = daily[daily['date'] <= asof].reset_index(drop=True)
        if daily.empty or daily['date'].iloc[-1] != asof:
            raise ValueError(f'no daily bar on {asof}')
    levelled = _levels(daily)
    today = len(levelled) - 1
    row = levelled.iloc[today]
    result = {
        'verdict': 'insufficient',
        'label': LABELS['insufficient'],
        'asof': row['date'],
        'close': float(row['close']),
        'low': float(row['low']),
        'reasons': [],
        'exit_price': None,
        'ma': {},
    }
    needed = ('ma5', 'ma10', 'ma20', 'ma30', 'ma60', 'ma60_prev', 'atr', 'prior_high', 'exit_low')
    if today + 1 < MIN_ROWS or any(pd.isna(row[column]) for column in needed):
        result['reasons'].append(f'日线仅{today + 1}根，计算60日线及5日斜率至少需要{MIN_ROWS}根')
        return result
    ma = {period: float(row[f'ma{period}']) for period in (5, 10, 20, 30, 60)}
    result['ma'] = ma
    close = float(row['close'])
    low = float(row['low'])
    atr = float(row['atr'])
    prior_high = float(row['prior_high'])
    prior_low = float(row['exit_low'])
    ma60_prev = float(row['ma60_prev'])
    above_all = all(close > ma[period] for period in (5, 10, 20, 30, 60))
    near_high = close >= prior_high * (1 - NEAR_HIGH)
    recent_touch = bool(levelled['touch'].iloc[today - TOUCH_DAYS + 1:today + 1].any())
    extension = (close - ma[20]) / atr
    in_entry_zone = recent_touch and extension <= EXTEND_ATR
    ma60_falling = ma[60] < ma60_prev
    days_above = _days_above_ma60(levelled, today)

    if close > ma[20] and not in_entry_zone:
        if not recent_touch:
            gap = f'近{TOUCH_DAYS}日最低价没有回到20日线{ma[20]:.3f}上方{TOUCH_ATR}ATR以内'
        else:
            gap = f'收盘高出20日线{extension:.1f}ATR，超过{EXTEND_ATR}ATR'
        if above_all and near_high:
            result.update(verdict='reject', label=LABELS['reject'])
            result['reasons'] = [
                f"收盘{close:.3f}站在5/10/20/30/60日线之上（{'/'.join(f'{ma[period]:.3f}' for period in (5, 10, 20, 30, 60))}）",
                f'前20日高点{prior_high:.3f}，收盘距该高点{close / prior_high - 1:+.1%}，处于高点{NEAR_HIGH:.0%}以内或已越过，属于追高',
                gap,
            ]
        else:
            result.update(verdict='no_entry', label=LABELS['no_entry'])
            result['reasons'] = [f'收盘{close:.3f}在20日线{ma[20]:.3f}之上{close / ma[20] - 1:+.1%}，{gap}']
        return result
    if close < ma[60]:
        below_count = sum(1 for period in (5, 10, 20, 30, 60) if close < ma[period])
        result['below_count'] = below_count
        if below_count >= 5:
            result.update(verdict='no_entry', label=LABELS['no_entry'], exit_price=None)
            result['reasons'] = [
                f"收盘{close:.3f}低于全部五条均线（5/10/20/30/60日线：{'/'.join(f'{ma[period]:.3f}' for period in (5, 10, 20, 30, 60))}），破线计数{below_count}≥5",
                f'暂停买入：五线全破。等收盘先站回5日线{ma[5]:.3f}上方，自动恢复可建仓',
            ]
            return result
        slope = f"60日线{ma[60]:.3f}，{SLOPE_DAYS}个交易日前为{ma60_prev:.3f}，{'仍在下行' if ma60_falling else '未下行'}"
        result.update(verdict='probe_only', label=LABELS['probe_only'], exit_price=prior_low)
        result['reasons'] = [
            slope,
            f'收盘{close:.3f}在60日线下方（破线计数{below_count}/5，未全破）',
            f'只能试错仓；收盘跌破近20日最低{prior_low:.3f}退出',
        ]
        return result
    if days_above >= HOLD_DAYS and not ma60_falling and recent_touch and close >= ma[20]:
        result.update(verdict='full', label=LABELS['full'])
        result['reasons'] = [
            f'收盘{close:.3f}在60日线{ma[60]:.3f}之上，已连续{days_above}日收在60日线上方，60日线未下行',
            f'近{TOUCH_DAYS}日最低价回到20日线{ma[20]:.3f}附近，收盘守住20日线',
        ]
        return result
    missing = []
    if days_above < HOLD_DAYS:
        missing.append(f'仅连续{days_above}日收在60日线上方（需至少{HOLD_DAYS}日）')
    if ma60_falling:
        missing.append(f'60日线{ma[60]:.3f}仍在下行（{SLOPE_DAYS}日前{ma60_prev:.3f}）')
    if not recent_touch:
        missing.append(f'近{TOUCH_DAYS}日没有回踩20日线')
    if close < ma[20]:
        missing.append(f'收盘跌破20日线{ma[20]:.3f}')
    result.update(verdict='wait', label=LABELS['wait'])
    result['reasons'] = [f"收盘{close:.3f}，20日线{ma[20]:.3f}，60日线{ma[60]:.3f}；" + '；'.join(missing)]
    return result


def render(result, code=None):
    name = f'{code} ' if code else ''
    lines = [
        f"{name}{result['asof']} 收盘 {result['close']:.3f}",
        f"判定：{result['label']}",
        '原因：',
        *(f"- {reason}" for reason in result['reasons']),
        '这是日线位置判断，不是下单；新浪日线为不复权价格，遇ETF拆分/分红需自行核对均线。',
    ]
    return '\n'.join(lines)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='按日线位置判断能否建仓或换入')
    parser.add_argument('code', nargs='?', help='ETF代码，如 159363 或 sz159363')
    parser.add_argument('--asof', help='判断用的已有日线日期 YYYY-MM-DD')
    parser.add_argument('--csv', help='本地日线CSV，列含 date/time, open, high, low, close')
    args = parser.parse_args(argv)
    if not args.code and not args.csv:
        parser.error('需要代码或 --csv')
    if args.csv:
        frame = prepare(pd.read_csv(args.csv))
        code = args.code
    else:
        code = prefix_code(args.code)
        frame = fetch_daily(code)
    result = judge_entry(frame, asof=args.asof)
    print(render(result, code=code))
    return result


if __name__ == '__main__':
    main()
