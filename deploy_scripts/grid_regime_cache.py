"""收盘后门控缓存预计算（15:30 前后由市况监控链路调用，或手动跑）。

2026-10-28 用户定：早间拉行情不可靠（东财限流/腾讯501），门控判断提前做好。
本脚本收盘后跑：拉当日完整日K → 算四级判定 → 落 regime-cache.json（asof=今日）。
次日 09:20 盘前直接用这份缓存（期望 asof=昨日收盘），不再依赖盘前拉取。
"""
import os
import sys

SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'
_IS_312 = sys.version_info[:2] == (3, 12) and 'Programs' in sys.executable

if __name__ == '__main__' and not _IS_312:
    # cron 用 hermes 自带 Py3.14（无 pandas）→ 接力到系统 Py312（蓝本同款钉子，已验证）
    import subprocess
    sys.stdout.flush(); sys.stderr.flush()
    sys.exit(subprocess.call([SYSTEM_PY, os.path.abspath(__file__)] + sys.argv[1:]))

sys.path.insert(0, 'D:/Code/AH_analyse')
sys.path.insert(0, 'D:/Code/AH_analyse/tools')

if __name__ == '__main__':
    import confirmed_runtime as rt
    import holdings as H

    regimes = {}
    missed = []
    for code in H.held_codes():
        r = rt.fetch_daily_regime(code)
        if r.get('adx') is None and r.get('bars') is None:
            missed.append(code)
            continue
        regimes[code] = r
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
