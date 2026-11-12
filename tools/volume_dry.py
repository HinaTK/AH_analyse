# -*- coding: utf-8 -*-
"""地量判据单一真源（2026-11-12 Master 选 A 方案）。

背景：市况操作信号(15:35, market_phase_check) 与观察哨哨①(15:50, watchtower_monitor)
原本对同一个上证指数、同一个「近5日均额/120日峰值 < 1/3」判据各算一遍：
数据源不同（东财/腾讯 vs westock）、阈值不同（1/3 vs 0.33）、实现不同，
同日可能给出相反结论且无裁决层。

本模块统一三件事：阈值、纯计算公式、取数入口。两条定时任务仍各自独立运行、
各自保留状态机与推送节奏，不引入跨任务状态依赖。

注意：东财/腾讯日K的 amount 是同源量纲（手→股近似），**只有比值有意义**，
avg5_yi / peak_yi 不可当作真实成交额解读，仅供内部读数参考。
"""
from pathlib import Path
import sys

# 单一阈值：1/3（原市况口径）；观察哨旧值 0.33 已废止
DRY_THRESHOLD = 1.0 / 3.0
DRY_LABEL = '1/3'
SHANGHAI_SECID = '1.000001'


def calculate(amounts):
    """纯函数：amounts 按时间正序（旧→新），返回地量比。

    公式与市况原有内联实现逐位一致：
        win = min(120, len(amounts)); (sum(amounts[-5:])/5) / max(amounts[-win:])
    """
    if not amounts or len(amounts) < 5:
        return None
    win = min(120, len(amounts))
    peak = max(amounts[-win:])
    if peak <= 0:
        return None
    avg5 = sum(amounts[-5:]) / 5
    ratio_raw = avg5 / peak
    return dict(ratio_raw=ratio_raw, ratio=round(ratio_raw, 3),
                avg5_yi=round(avg5 / 1e8, 0), peak_yi=round(peak / 1e8, 0))


def shanghai_volume_ratio(fetch_kline=None):
    """取上证日K并算地量比；返回与观察哨 volume_ratio() 一致的 dict 或 None。

    fetch_kline 可注入以便测试；默认延迟导入市况模块的取数函数，
    保证两边用的是同一条东财主源 + 腾讯兜底链路，不再有第二套数字。
    """
    if fetch_kline is None:
        tools_dir = str(Path(__file__).resolve().parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from market_phase_check import fetch_kline as fetch_kline
    try:
        rows = fetch_kline(SHANGHAI_SECID, lmt=300, klt='101')
    except Exception:
        return None
    if not rows or len(rows) < 120:
        return None
    out = calculate([r['amount'] for r in rows])
    if out is None:
        return None
    return dict(ratio=out['ratio'], avg5_yi=out['avg5_yi'],
                peak_yi=out['peak_yi'], date=rows[-1]['date'])


def is_dry(vol_ratio):
    """统一的地量判定；三信号与哨①共用。"""
    return vol_ratio is not None and vol_ratio < DRY_THRESHOLD
