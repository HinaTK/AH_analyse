#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对 divi_universe.json 全部个股做技术面+基本面综合评分（stock-analysis skill 逻辑的本地实现）。

技术面: 均线排列/MACD/RSI/KDJ/量能/趋势 → 0-100
基本面: 净利增速/ROE/股息可持续性 → 0-100
综合 = 0.45×股息分 + 0.35×基本面分 + 0.20×技术面分
"""
import json, math

with open(r"D:/Code/AH_analyse/tools/divi_universe.json", encoding="utf-8") as f:
    data = json.load(f)


def score_tech(t):
    if not t or not t.get("close"):
        return None, "无数据"
    try:
        close = float(t["close"])
        ma20, ma60, ma250 = float(t["ma20"]), float(t["ma60"]), float(t["ma250"])
        macd = float(t["macd"])
        rsi6, kdjj = float(t["rsi6"]), float(t["kdj_j"])
    except (KeyError, ValueError, TypeError):
        return None, "字段缺失"
    s = 50.0
    notes = []
    if close >= ma20: s += 10
    else: s -= 10
    if close >= ma60: s += 10
    else: s -= 5
    if close >= ma250: s += 10
    else: s -= 10
    if macd > 0: s += 10
    else: s -= 8
    if 40 <= rsi6 <= 65: s += 5
    elif rsi6 < 30: s += 8   # 超卖反弹机会
    elif rsi6 > 75: s -= 8   # 超买
    if kdjj < 20: s += 5
    elif kdjj > 85: s -= 5
    trend = "多头" if (close >= ma20 >= ma60) else ("空头" if (close <= ma20 <= ma60) else "震荡")
    return max(0, min(100, s)), trend


def score_fund(fin, y):
    if not fin:
        return None
    s = 50.0
    try:
        yoy = float(fin.get("np_yoy") or 0)
        s += max(-20, min(20, yoy * 2))
    except (ValueError, TypeError):
        pass
    try:
        roe = float(fin.get("roe_ttm") or 0)
        s += max(-10, min(20, (roe - 8) * 2))
    except (ValueError, TypeError):
        pass
    return max(0, min(100, s))


def score_yield(y):
    if y is None:
        return 0
    # 6% 满分，3% 及格线
    return max(0, min(100, (y - 3) / 3 * 100))


rows = []
for r in data["results"]:
    y = r.get("yield_ttm")
    fin = r.get("fin") or {}
    tech_s, trend = score_tech(r.get("tech") or {})
    fund_s = score_fund(fin, y)
    yl_s = score_yield(y)
    tech_s = tech_s if tech_s is not None else 50
    fund_s = fund_s if fund_s is not None else 50
    total = 0.45 * yl_s + 0.35 * fund_s + 0.20 * tech_s
    rows.append({
        "code": r["code"], "name": r["name"], "sector": r["sector"],
        "price": r.get("price"), "yield_ttm": y,
        "div_n": r.get("div_n"), "dps": r.get("dps_ttm"),
        "np_yoy": fin.get("np_yoy"), "roe": fin.get("roe_ttm"), "eps_ttm": fin.get("eps_ttm"),
        "trend": trend, "tech_s": round(tech_s), "fund_s": round(fund_s), "yield_s": round(yl_s),
        "total": round(total, 1),
    })

rows.sort(key=lambda x: -x["total"])
print(f"{'排名':<4}{'代码':<10}{'名称':<6}{'板块':<5}{'现价':>7}{'股息率TTM':>9}{'净利YoY':>9}{'ROE':>7}{'趋势':<5}{'综合分':>7}")
for i, r in enumerate(rows, 1):
    yoy = f"{float(r['np_yoy']):+.1f}%" if r.get("np_yoy") else "—"
    roe = f"{float(r['roe']):.1f}%" if r.get("roe") else "—"
    print(f"{i:<4}{r['code']:<10}{r['name']:<6}{r['sector']:<5}{r['price']:>7.2f}{r['yield_ttm']:>8.2f}%{yoy:>9}{roe:>7}{r['trend']:<5}{r['total']:>7.1f}")

with open(r"D:/Code/AH_analyse/tools/divi_rank.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)
