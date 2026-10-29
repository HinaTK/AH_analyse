"""收盘后门控缓存预计算（15:30 前后由市况监控链路调用，或手动跑）。

2026-10-28 用户定：早间拉行情不可靠（东财限流/腾讯501），门控判断提前做好。
本脚本收盘后跑：拉当日完整日K → 算四级判定 → 落 regime-cache.json（asof=今日）。
次日 09:20 盘前直接用这份缓存（期望 asof=昨日收盘），不再依赖盘前拉取。

2026-10-29 用户定：行情源失败不再一次放弃——循环重试直到全部成功
（只重拉缺失标的，退避 120s→600s 封顶）；安全截止线=次日 09:00
（早于 09:20 消费方），到线仍缺才带 missed 退出（走旧缓存兜底）。
本任务投递 local，不再推送汇报。
"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta

SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'
_IS_312 = sys.version_info[:2] == (3, 12) and 'Programs' in sys.executable

if __name__ == '__main__' and not _IS_312:
    # cron 用 hermes 自带 Py3.14（无 pandas）→ 接力到系统 Py312（蓝本同款钉子，已验证）
    import subprocess
    sys.stdout.flush(); sys.stderr.flush()
    sys.exit(subprocess.call([SYSTEM_PY, os.path.abspath(__file__)] + sys.argv[1:]))

sys.path.insert(0, 'D:/Code/AH_analyse')
sys.path.insert(0, 'D:/Code/AH_analyse/tools')

_CN = timezone(timedelta(hours=8))
RETRY_BACKOFF_START = 120.0   # 首轮失败后等 2 分钟再重拉
RETRY_BACKOFF_MAX = 600.0     # 退避封顶 10 分钟


def production_deadline(now=None):
    """安全截止线：次日 09:00（早于 09:20 盘前消费方；窗口<24h 不跨天堆叠）。"""
    now = now or datetime.now(_CN)
    dl = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if dl <= now:
        dl += timedelta(days=1)
    return dl


def collect_regimes(fetch_fn, codes, sleep_fn=time.sleep,
                    deadline=None, clock=None, is_fresh=None):
    """逐标的拉门控行情，失败的循环重试直到全部成功或到截止线。

    返回 (regimes, missed, attempts)：
    - regimes: {code: 行情dict}（成功标的）
    - missed: 到截止线仍拉不到的标的（调用方走旧缓存兜底）
    - attempts: 拉取轮数（首轮=1）
    退避：120s → ×1.5 递增 → 600s 封顶；只重拉缺失标的，成功的不重拉。
    is_fresh(r)：非空但陈旧的数据（收盘后 asof≠今日）也判失败重试；
    None=只按"拉空"判失败（盘中跑时用，当日K线本来就不该在）。
    """
    clock = clock or (lambda: datetime.now(_CN))
    if deadline is None:
        deadline = production_deadline()
    regimes = {}
    missed = list(codes)
    attempts = 0
    backoff = RETRY_BACKOFF_START
    while missed:
        attempts += 1
        still = []
        for code in missed:
            try:
                r = fetch_fn(code)
            except Exception:
                r = {'adx': None, 'bars': None}
            empty = r.get('adx') is None and r.get('bars') is None
            if empty or (is_fresh is not None and not is_fresh(r)):
                still.append(code)
            else:
                regimes[code] = r
        missed = still
        if not missed:
            break
        if clock() >= deadline:
            break
        sleep_fn(backoff)
        backoff = min(backoff * 1.5, RETRY_BACKOFF_MAX)
    return regimes, missed, attempts


if __name__ == '__main__':
    import confirmed_runtime as rt
    import holdings as H

    def _is_fresh_after_close(r):
        """收盘后（>=15:00 北京时间）成功标准：bars 最后一根=今日。"""
        now = datetime.now(_CN)
        if now.hour < 15:
            return True  # 盘中跑：当日K线本来就不该在，非空即成功
        bars = r.get('bars')
        try:
            last = str(bars.iloc[-1]['date']) if bars is not None and len(bars) else None
        except Exception:
            return False
        return last == now.strftime('%Y-%m-%d')

    regimes, missed, attempts = collect_regimes(
        rt.fetch_daily_regime, list(H.held_codes()), is_fresh=_is_fresh_after_close)
    if attempts > 1:
        tail = '（仍有缺失，走旧缓存兜底）' if missed else ''
        print(f"行情源不稳，重试 {attempts} 轮{tail}")
    cache = rt._regimes_to_cache(regimes)
    # 部分失败不丢已有保险：旧缓存里该标的的条目保留（宁可旧判定，不可无门控）
    old_cache_path = rt._regime_cache_path(rt.root_from_home())
    if missed and old_cache_path.is_file():
        import json as _json
        try:
            old_cache = _json.loads(old_cache_path.read_text(encoding='utf-8'))
            for code in missed:
                if code in old_cache:
                    cache[code] = old_cache[code]
                    print(f"warn: {code} 行情缺失，保留旧缓存条目(asof={old_cache[code].get('asof')})")
        except Exception:
            pass
    for code in missed:
        if code not in cache:
            print(f"warn: {code} 行情缺失且无旧缓存——明早将现拉或降级")
    path = rt.save_regime_cache(rt.root_from_home(), cache)
    print(f"已落缓存: {path}")
    for code, entry in cache.items():
        print(f"  {code}: level={entry['level']} 拦={entry['blocks_buy']} adx={entry['adx'] and round(entry['adx'],1)} asof={entry['asof']}")
