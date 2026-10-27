#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""补漏：只对 divi_two_axis.json 里缺 pct52 的票重抓K线并重渲染表格。"""
import json, time, sys
sys.path.insert(0, r"D:/Code/AH_analyse/tools")
from divi_two_axis import kline_stats

P = r"D:/Code/AH_analyse/tools/divi_two_axis.json"
with open(P, encoding="utf-8") as f:
    rows = json.load(f)

missing = [r for r in rows if r["pct52"] is None]
print(f"缺分位: {len(missing)}只，逐只重抓（5秒间隔防限流）")
for r in missing:
    ks = None
    for attempt in range(5):
        ks = kline_stats(r["code"])
        if ks:
            break
        time.sleep(5)
    if ks:
        r["pct52"] = ks["pct52"]
        r["year_line"] = ks["year_line"]
        print(f"OK {r['code']} {r['name']} pct52={ks['pct52']}% 年线={ks['year_line']}", flush=True)
    else:
        print(f"仍失败 {r['code']} {r['name']}", flush=True)
    time.sleep(3)

still = [r for r in rows if r["pct52"] is None]
print(f"补完后仍缺: {len(still)}只")

with open(P, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)

order = {"A": 0, "B": 1, "C": 2}
rows.sort(key=lambda x: (order.get(x["grade"][0], 9), -(x["yield_t"] or 0)))
print(f"\n## 两轴框架·三榜48只终版 @ 2026-10-27")
print("| 级 | 代码 | 名称 | 板块 | 现价 | 股息率TTM | 盈利收益率 | 派息率 | 净利YoY | 趋势 | 52周分位 | 年线 |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
for x in rows:
    yoy = x.get("np_yoy_note") or "—"
    pay = f"{x['payout']}%" if x["payout"] is not None else "—"
    ey = f"{x['eyield']:.1f}%" if x["eyield"] else "—"
    yl = f"{x['year_line']:.2f}" if x["year_line"] else "—"
    p52 = f"{x['pct52']}%" if x["pct52"] is not None else "—"
    print(f"| {x['grade']} | {x['code']} | {x['name']} | {x['sector']} | {x['price']:.2f} | {x['yield_t']:.2f}% | {ey} | {pay} | {yoy} | {x['trend']} | {p52} | {yl} |")
