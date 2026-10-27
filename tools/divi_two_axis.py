#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""两轴框架重刷：48只三榜个股 ×（分红轴 + 股价轴），盈利收益率(EPS/现价)为核心定价。

输出排序规则（透明、数字门槛，无黑箱）：
  A级 双轴硬: 股息率≥4.5% 且 盈利收益率≥7% 且 趋势非空头
  B级 单轴硬: 股息率≥4.5% 或 盈利收益率≥7%（另一轴弱或趋势空头）
  C级 双轴弱: 其余
红线: 派息率>100%（分本金）或 净利YoY<-20%（分红水源枯竭）
"""
import json, subprocess, time, re, urllib.request
from datetime import datetime

WESTOCK = r"C:/Users/Administrator/.local/bin/westock.exe"


def westock(*args):
    r = subprocess.run([WESTOCK, *args], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace")


def parse_md(text):
    lines = [l for l in text.splitlines() if l.startswith("|")]
    if len(lines) < 3:
        return []
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    out = []
    for l in lines[2:]:
        cells = [c.strip() for c in l.strip("|").split("|")]
        if len(cells) == len(hdr):
            out.append(dict(zip(hdr, cells)))
    return out


def refetch_finance(code):
    """EPS/净利YoY 补抓（对 collect 时缺财务的票）。"""
    for i in range(3):
        out = westock("finance", code, "--limit", "1")
        if "|" in out:
            break
        time.sleep(1 + i)
    rows = parse_md(out.split("**利润表**")[-1])
    if not rows:
        return {}
    r = rows[0]
    return {"eps_ttm": r.get("EPSTTM"), "np_yoy": r.get("NPParentCompanyYOY"),
            "roe_ttm": r.get("ROETTM")}


def kline_stats(code):
    """52周分位 + 均线位置 + 年线价（带退避重试）。"""
    out = ""
    for i in range(3):
        out = westock("kline", code, "--period", "day", "--limit", "250")
        if out.count("|") > 10:
            break
        time.sleep(1 + i)
    rows = parse_md(out)
    if not rows:
        return {}
    try:
        closes = [float(r["last"]) for r in rows]
    except (KeyError, ValueError):
        return {}
    if len(closes) < 60:
        return {}
    ma250 = sum(closes) / len(closes)
    ma20 = sum(closes[:20]) / 20
    ma60 = sum(closes[:60]) / 60
    lo, hi = min(closes), max(closes)
    pct = (closes[0] - lo) / (hi - lo) * 100 if hi > lo else 50
    return {"pct52": round(pct), "ma20": round(ma20, 2), "ma60": round(ma60, 2),
            "year_line": round(ma250, 2), "lo52": lo, "hi52": hi}


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    with open(r"D:/Code/AH_analyse/tools/divi_universe.json", encoding="utf-8") as fp:
        data = json.load(fp)

    rows = []
    for r in data["results"]:
        code, name, sector = r["code"], r["name"], r["sector"]
        price = r.get("price")
        yield_t = r.get("yield_ttm")
        fin = r.get("fin") or {}
        tech = r.get("tech") or {}

        eps = f(fin.get("eps_ttm"))
        np_yoy = f(fin.get("np_yoy"))
        if eps is None or price is None or eps <= 0:
            fin2 = refetch_finance(code)
            eps = f(fin2.get("eps_ttm")) or eps
            np_yoy = f(fin2.get("np_yoy")) if np_yoy is None else np_yoy
            time.sleep(0.2)

        ks = kline_stats(code)
        time.sleep(0.2)

        eyield = round(eps / price * 100, 2) if (eps and price and eps > 0) else None
        payout = round(r.get("dps_ttm", 0) / eps * 100) if (eps and eps > 0 and r.get("dps_ttm")) else None

        # 趋势判定
        try:
            close = float(tech.get("close") or price)
            t20, t60 = f(tech.get("ma20")), f(tech.get("ma60"))
            t250 = f(tech.get("ma250")) or ks.get("year_line")
            if t20 and t60:
                trend = "多头" if (close >= t20 >= t60) else ("空头" if (close <= t20 <= t60) else "震荡")
            else:
                trend = "?"
        except Exception:
            trend = "?"

        # 分级
        y_ok = (yield_t or 0) >= 4.5
        e_ok = (eyield or 0) >= 7
        red_payout = payout is not None and payout > 100
        red_yoy = np_yoy is not None and np_yoy < -20
        # 白酒低基数虚增特判: 五粮液2026中报+89.3%源于2025基数重述-76%，产销腰斩
        LOW_BASE = {"sz000858"}
        if code in LOW_BASE and np_yoy is not None and np_yoy > 50:
            red_yoy = True
            np_yoy_note = f"{np_yoy:+.1f}%🚩低基数"
        else:
            np_yoy_note = f"{np_yoy:+.1f}%" if np_yoy is not None else None
        if y_ok and e_ok and trend != "空头":
            grade = "A"
        elif y_ok or e_ok:
            grade = "B"
        else:
            grade = "C"
        if red_payout:
            grade += "🚩分本金"
        if red_yoy:
            grade += "🚩水源枯"

        # 买点参考: 盈利收益率回到8%的价 = eps/0.08
        buy8 = round(eps / 0.08, 2) if (eps and eps > 0) else None

        rows.append({
            "grade": grade, "code": code, "name": name, "sector": sector,
            "price": price, "yield_t": yield_t, "eyield": eyield,
            "payout": payout, "np_yoy": np_yoy, "np_yoy_note": np_yoy_note,
            "trend": trend,
            "pct52": ks.get("pct52"), "year_line": ks.get("year_line"),
            "buy8": buy8,
        })
        print(f"OK {code} {name} grade={grade} eyield={eyield} pct52={ks.get('pct52')}", flush=True)

    order = {"A": 0, "B": 1, "C": 2}
    rows.sort(key=lambda x: (order.get(x["grade"][0], 9), -(x["yield_t"] or 0)))

    with open(r"D:/Code/AH_analyse/tools/divi_two_axis.json", "w", encoding="utf-8") as fp:
        json.dump(rows, fp, ensure_ascii=False, indent=1)

    print(f"\n## 两轴重刷完成 {len(rows)}只 @ {datetime.now().date()}")
    print("| 级 | 代码 | 名称 | 板块 | 现价 | 股息率TTM | 盈利收益率 | 派息率 | 净利YoY | 趋势 | 52周分位 | 年线 | 8%买点 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for x in rows:
        yoy = x.get("np_yoy_note") or "—"
        pay = f"{x['payout']}%" if x["payout"] is not None else "—"
        ey = f"{x['eyield']:.1f}%" if x["eyield"] else "—"
        yl = f"{x['year_line']:.2f}" if x["year_line"] else "—"
        b8 = f"{x['buy8']:.2f}" if x["buy8"] else "—"
        p52 = f"{x['pct52']}%" if x["pct52"] is not None else "—"
        print(f"| {x['grade']} | {x['code']} | {x['name']} | {x['sector']} | {x['price']:.2f} | {x['yield_t']:.2f}% | {ey} | {pay} | {yoy} | {x['trend']} | {p52} | {yl} | {b8} |")


if __name__ == "__main__":
    main()
