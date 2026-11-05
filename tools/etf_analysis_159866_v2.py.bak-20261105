# -*- coding: utf-8 -*-
"""etf-analysis skill 全面分析 159866：溢价历史分位、规模、费率、时机信号。
数据源：东方财富基金F10（净值历史、基本概况）。"""
import json, urllib.request, re

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "http://fundf10.eastmoney.com/"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")

# ---- 1. 基本概况（规模、费率、成立日、跟踪标的） ----
print("=" * 68)
print("1. 基本概况 (fundf10 jbgk)")
print("=" * 68)
try:
    html = get("http://fundf10.eastmoney.com/jbgk_159866.html")
    # parse table rows
    rows = re.findall(r"<td[^>]*>(.*?)</td>", html, re.S)
    clean = [re.sub(r"<[^>]+>|\s+", "", r) for r in rows]
    keys = ["基金全称", "基金简称", "跟踪标的", "管理费率", "托管费率", "销售服务费率",
            "成立日期", "最新规模", "份额规模", "资产规模", "基金管理人", "基金类型"]
    for i, c in enumerate(clean):
        for k in keys:
            if c.startswith(k) or k in c:
                print(f"  {c[:60]}")
                break
except Exception as e:
    print(f"  概况获取失败: {e}")

# ---- 2. 净值历史 + 收盘价 → 溢价历史分位 ----
print()
print("=" * 68)
print("2. 溢价率历史分布 (近一年净值 vs 收盘价)")
print("=" * 68)
try:
    navs = []
    for page in range(1, 6):  # 5 pages x 50 = 250 records
        raw = get(f"https://api.fund.eastmoney.com/f10/lsjz?fundCode=159866&pageIndex={page}&pageSize=50&_=1")
        d = json.loads(raw)
        lst = (d.get("Data") or {}).get("LSJZList") or []
        if not lst:
            break
        navs.extend((r["FSRQ"], float(r["DWJZ"])) for r in lst)
    print(f"  净值记录数: {len(navs)}, 最新: {navs[0] if navs else None}")
except Exception as e:
    print(f"  净值历史获取失败: {e}")
    navs = []

# Sina kline for closes
import sys
sys.path.insert(0, 'D:/Hermes Agent CN Desktop/data/hermes-home/skills/@user_5d56ad01/etf-grid-screener/scripts')
from grid_tool import fetch_kline
r = fetch_kline('159866', 260)
dates, opens, closes, highs, lows, vols = r
close_map = {d: c for d, c in zip(dates, closes)}

# 溢价历史（净值日与收盘日对齐；跨境ETF净值滞后时用前一日）
nav_map = dict(navs)
prem_hist = []
for d, c in zip(dates, closes):
    nav = nav_map.get(d) or nav_map.get((d))
    if nav is None:
        # 尝试最近的前一个净值日
        import datetime
        dt = datetime.datetime.strptime(d, "%Y-%m-%d")
        for back in range(1, 5):
            k = (dt - datetime.timedelta(days=back)).strftime("%Y-%m-%d")
            if k in nav_map:
                nav = nav_map[k]; break
    if nav:
        prem_hist.append((d, (c/nav - 1)*100))

prem_hist.sort()
vals = [p for _, p in prem_hist]
import statistics as st
cur_prem = vals[-1]
rank = sum(1 for v in vals if v <= cur_prem) / len(vals) * 100
print(f"  可对齐样本: {len(vals)} 天 (区间 {prem_hist[0][0]} → {prem_hist[-1][0]})")
print(f"  当前溢价: {cur_prem:+.2f}%")
print(f"  历史分位: {rank:.0f}%")
print(f"  均值 {st.mean(vals):+.2f}% | 中位数 {st.median(vals):+.2f}% | 最小 {min(vals):+.2f}% | 最大 {max(vals):+.2f}%")
print(f"  近20日溢价: {[f'{p:+.1f}' for _, p in prem_hist[-20:]]}")
over2 = sum(1 for v in vals if v > 2) / len(vals) * 100
over5 = sum(1 for v in vals if v > 5) / len(vals) * 100
neg = sum(1 for v in vals if v < 0) / len(vals) * 100
print(f"  溢价>2%的天数占比: {over2:.0f}% | >5%: {over5:.0f}% | <0%(折价): {neg:.0f}%")

# ---- 3. 趋势与位置 ----
print()
print("=" * 68)
print("3. 趋势与位置")
print("=" * 68)
cur = closes[-1]
ma20 = sum(closes[-20:])/20; ma60 = sum(closes[-60:])/60
hi250 = max(highs); lo250 = min(lows)
print(f"  现价 {cur:.3f} | MA20 {ma20:.3f} ({(cur/ma20-1)*100:+.1f}%) | MA60 {ma60:.3f} ({(cur/ma60-1)*100:+.1f}%)")
print(f"  250日区间 {lo250:.3f} ~ {hi250:.3f}, 现价位于 {(cur-lo250)/(hi250-lo250)*100:.0f}% 分位")
print(f"  自250日高点回撤 {(cur/hi250-1)*100:.1f}%")
below = sum(1 for x in closes[-20:] if x < ma20)
print(f"  近20日 {below} 天收于MA20下方")
# 连续下跌天数
streak = 0
for i in range(len(closes)-1, 0, -1):
    if closes[i] < closes[i-1]: streak += 1
    else: break
print(f"  连续收跌: {streak} 天")
