"""Versioned, read-only five-minute research. No account/order imports."""
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

def latest_session(now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    day = now.date()
    if now.hour * 60 + now.minute < 15 * 60 + 15:
        day -= timedelta(days=1)
    # Chinese exchange holidays; fail closed outside the verified calendar.
    from .calendar import is_session
    while not is_session(day):
        day -= timedelta(days=1)
    return day.isoformat()

def select_window(data, asof, sessions):
    common = None
    for code in BASE:
        frame = data[code]
        dates = sorted(set(frame.loc[frame.time.str.endswith('15:00:00') & (frame.time.str[:10] <= asof), 'time'].str[:10]))
        if not dates or dates[-1] != asof:
            raise ValueError(f'stale baseline {code}: last={dates[-1] if dates else None}, expected={asof}')
        common = set(dates) if common is None else common.intersection(dates)
    dates = sorted(common)
    if len(dates) < sessions:
        raise ValueError(f'insufficient common sessions: {len(dates)} < {sessions}')
    from .calendar import is_session
    from datetime import date
    expected=[];day=date.fromisoformat(asof)
    while len(expected)<sessions:
        if is_session(day):expected.append(day.isoformat())
        day-=timedelta(days=1)
    expected=sorted(expected)
    missing=set(expected)-common
    if missing:raise ValueError(f'missing baseline sessions: {sorted(missing)}')
    return expected
import pandas as pd

def get_model():
    from . import grid_model
    return grid_model

VERSION = 'rolling-m5-min1-v1'
BASE = ['sh589720', 'sz159363']
HOLDINGS = BASE + ['sz159992']

def load_universe(path):
    table = pd.read_csv(path)
    pool = table[table.eligible.astype(str).str.lower().eq('true')].copy()
    for code in HOLDINGS:
        if code not in set(pool.code):
            match = table[table.code.eq(code)]
            extra = match.iloc[0].to_dict() if len(match) else {'code': code, 'name': code}
            pool = pd.concat([pool, pd.DataFrame([extra])], ignore_index=True)
    return pool.drop_duplicates('code').reset_index(drop=True)

def run_research(**kwargs):
    from .engine import run_research as run
    return run(**kwargs)

def main(argv=None):
    import argparse,json
    from .engine import DEFAULT_INPUT,dump
    parser=argparse.ArgumentParser(description='滚动全资格池5分钟研究（历史资格快照）')
    parser.add_argument('--input-path',default=str(DEFAULT_INPUT))
    parser.add_argument('--bars-dir')
    parser.add_argument('--output-path')
    parser.add_argument('--asof')
    parser.add_argument('--sessions',type=int,default=63)
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--workers',type=int,default=8)
    result=run_research(**vars(parser.parse_args(argv)))
    print(dump(result['summary']))
    return result

if __name__=='__main__':main()
