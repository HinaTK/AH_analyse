"""收盘后门控缓存预计算（15:30 前后由市况监控链路调用，或手动跑）。

2026-10-28 用户定：早间拉行情不可靠（东财限流/腾讯501），门控判断提前做好。
本脚本收盘后跑：拉当日完整日K → 算四级判定 → 落 regime-cache.json（asof=今日）。
次日 09:20 盘前直接用这份缓存（期望 asof=昨日收盘），不再依赖盘前拉取。
"""
import sys

IS_PACKED = sys.version_info[:2] == (3, 14)
if not IS_PACKED and 'Programs' not in sys.executable:
    # 慢路径交给 system python（见 launcher 蓝本）；正常 312 直接跑
    import subprocess
    sys.exit(subprocess.call([r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe', __file__] + sys.argv[1:]))

sys.path.insert(0, 'D:/Code/AH_analyse')
sys.path.insert(0, 'D:/Code/AH_analyse/tools')

if __name__ == '__main__':
    import confirmed_runtime as rt
    import holdings as H

    regimes = {}
    for code in H.held_codes():
        r = rt.fetch_daily_regime(code)
        if r.get('adx') is None and r.get('bars') is None:
            print(f"warn: {code} 行情缺失，跳过缓存")
            continue
        regimes[code] = r
    cache = rt._regimes_to_cache(regimes)
    path = rt.save_regime_cache(rt.root_from_home(), cache)
    print(f"已落缓存: {path}")
    for code, entry in cache.items():
        print(f"  {code}: level={entry['level']} 拦={entry['blocks_buy']} adx={entry['adx'] and round(entry['adx'],1)} asof={entry['asof']}")
