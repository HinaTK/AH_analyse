"""收盘后门控缓存预计算（15:30 前后由市况监控链路调用，或手动跑）。

2026-10-28 用户定：早间拉行情不可靠（东财限流/腾讯501），门控判断提前做好。
本脚本收盘后跑：拉当日完整日K → 算四级判定 → 落 regime-cache.json（asof=今日）。
次日 09:20 盘前直接用这份缓存（期望 asof=昨日收盘），不再依赖盘前拉取。

2026-10-29 用户定：行情源失败不再一次放弃——循环重试直到全部成功
（只重拉缺失标的，退避 120s→600s 封顶）；安全截止线=次日 09:00
（早于 09:20 消费方），到线仍缺才带 missed 退出（走旧缓存兜底）。
本任务投递 local，不再推送汇报。

2026-11-03 事故修复（11-02/11-03 连续两天 15:30 任务被 cron 3600s
硬杀、零落盘）："重试到次日 09:00" 与 cron 硬超时冲突——行情源在
15:30-16:30 持续故障时脚本整晚重试，16:30 被杀时循环尚未自然结束，
一次都没落盘。两处修复：
A. 自身截止线收紧为 min(次日09:00, now+1800s)：15:30 触发最晚
   16:00 自然退出落盘，永远早于 3600s 硬杀（09:00 线保留给晨间手动补跑）。
B. collect_regimes 增加 on_round 回调，每轮结束即增量落盘
   （成功标的新条目 + 缺失标的保留旧缓存条目）——任意时点被杀
   都不丢已成功标的。
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
SELF_LIMIT_SECONDS = 1800.0   # 2026-11-03：自设 30 分钟上限，防撞 cron 3600s 硬杀


def production_deadline(now=None):
    """安全截止线：min(次日 09:00, now+1800s)——两个上界取小。

    - now+1800s（2026-11-03 修复A）：自设 30 分钟上限。15:30 cron 触发
      → 最晚 16:00 自然退出，永远早于 cron 3600s 硬杀；任何时段手动
      补跑同样只重试 30 分钟，不无限占机。重试 5-6 轮的实测最坏成功
      案例（10-30：5 轮 17 分钟）在此窗内，留一半余量。
    - 次日 09:00（早于 09:20 盘前消费方；窗口<24h 不跨天堆叠）：只在
      now+1800s 越过它时起钳制（如 08:45 跑 → 09:00 而非 09:15），
      保证晨间补跑不挤占盘前消费窗口。
    """
    now = now or datetime.now(_CN)
    dl = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if dl <= now:
        dl += timedelta(days=1)
    self_limit = now + timedelta(seconds=SELF_LIMIT_SECONDS)
    return min(dl, self_limit)


def merge_old_entries(cache, missed, old_cache_path):
    """缺失标的保留旧缓存条目（宁可用旧判定，不可无门控）。

    供 __main__ 与 on_round 回调共用：cache 原地更新并返回。
    """
    if not missed or not old_cache_path.is_file():
        return cache
    import json as _json
    try:
        old_cache = _json.loads(old_cache_path.read_text(encoding='utf-8'))
    except Exception:
        return cache
    for code in missed:
        if code in old_cache and code not in cache:
            cache[code] = old_cache[code]
    return cache


def collect_regimes(fetch_fn, codes, sleep_fn=time.sleep,
                    deadline=None, clock=None, is_fresh=None,
                    on_round=None, old_cache_path=None):
    """逐标的拉门控行情，失败的循环重试直到全部成功或到截止线。

    返回 (regimes, missed, attempts)：
    - regimes: {code: 行情dict}（成功标的）
    - missed: 到截止线仍拉不到的标的（调用方走旧缓存兜底）
    - attempts: 拉取轮数（首轮=1）
    退避：120s → ×1.5 递增 → 600s 封顶；只重拉缺失标的，成功的不重拉。
    is_fresh(r)：非空但陈旧的数据（收盘后 asof≠今日）也判失败重试；
    None=只按"拉空"判失败（盘中跑时用，当日K线本来就不该在）。
    on_round(round_no, regimes, missed)（2026-11-03 修复B）：每轮结束
    调用一次，供调用方增量落盘——任意时点被杀不丢已成功标的。
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
        if on_round is not None:
            try:
                on_round(attempts, regimes, missed)
            except Exception:
                pass  # 落盘失败不阻断重试（下一轮还会再试）
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

    old_cache_path = rt._regime_cache_path(rt.root_from_home())

    def _on_round(round_no, got, still_missing):
        """修复B：每轮增量落盘——任意时点被杀不丢已成功标的。"""
        cache_now = rt._regimes_to_cache(dict(got))
        merge_old_entries(cache_now, still_missing, old_cache_path)
        try:
            rt.save_regime_cache(rt.root_from_home(), cache_now)
        except Exception:
            pass  # 落盘失败不阻断重试；warn 留给最终落盘处
        if still_missing:
            print(f"warn: 第{round_no}轮后仍缺 {len(still_missing)} 只，已增量落盘 {len(cache_now)} 条")

    regimes, missed, attempts = collect_regimes(
        rt.fetch_daily_regime, list(H.held_codes()), is_fresh=_is_fresh_after_close,
        on_round=_on_round, old_cache_path=old_cache_path)
    if attempts > 1:
        tail = '（仍有缺失，走旧缓存兜底）' if missed else ''
        print(f"行情源不稳，重试 {attempts} 轮{tail}")
    cache = rt._regimes_to_cache(regimes)
    # 部分失败不丢已有保险：旧缓存里该标的的条目保留（宁可旧判定，不可无门控）
    merge_old_entries(cache, missed, old_cache_path)
    for code in missed:
        if code in cache:
            print(f"warn: {code} 行情缺失，保留旧缓存条目(asof={cache[code].get('asof')})")
        else:
            print(f"warn: {code} 行情缺失且无旧缓存——明早将现拉或降级")
    path = rt.save_regime_cache(rt.root_from_home(), cache)
    print(f"已落缓存: {path}")
    for code, entry in cache.items():
        print(f"  {code}: level={entry['level']} 拦={entry['blocks_buy']} adx={entry['adx'] and round(entry['adx'],1)} asof={entry['asof']}")
