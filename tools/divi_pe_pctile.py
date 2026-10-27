#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""48只个股 PE 分位计算：东财 RPT_VALUEANALYSIS_DET 全历史 PE_TTM → 近5年分位。

输出: divi_pe_pctile.json + markdown 表（按 PE 分位升序 = 越靠前越便宜）。
分位口径: 当前PE_TTM 在近5年(约1215个交易日)每日PE_TTM序列中的百分位。
"""
import json, time, urllib.request, urllib.parse

URL = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
       "reportName=RPT_VALUEANALYSIS_DET&columns=TRADE_DATE,PE_TTM,PB_MRQ"
       "&filter=(SECURITY_CODE%3D%22{code}%22)"
       "&pageSize=500&pageNo={page}"
       "&sortColumns=TRADE_DATE&sortTypes=-1")


def fetch_pe_history(code6):
    """拉全部历史(倒序)，返回 [(date, pe), ...] 正序。"""
    rows = []
    page = 1
    while page <= 20:
        u = URL.format(code=code6, page=page)
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            raw = json.loads(urllib.request.urlopen(req, timeout=20).read())
        except Exception as e:
            print(f"  page {page} fail: {e}", flush=True)
            time.sleep(3)
            continue
        data = ((raw.get("result") or {}).get("data")) or []
        if not data:
            break
        for d in data:
            pe = d.get("PE_TTM")
            if pe is not None and pe > 0:
                rows.append((d["TRADE_DATE"][:10], pe))
        pages = ((raw.get("result") or {}).get("pages")) or 1
        if page >= pages:
            break
        page += 1
        time.sleep(0.4)
    rows.sort()
    return rows


def percentile(current, series):
    return sum(1 for x in series if x <= current) / len(series) * 100


def main():
    with open(r"D:/Code/AH_analyse/tools/divi_universe.json", encoding="utf-8") as f:
        uni = json.load(f)
    out = []
    for r in uni["results"]:
        code = r["code"]
        code6 = code[2:] if code[:2] in ("sh", "sz") else code
        name = r["name"]
        hist = fetch_pe_history(code6)
        time.sleep(0.8)
        if len(hist) < 250:
            print(f"SKIP {code} {name}: 历史PE仅{len(hist)}条", flush=True)
            out.append({"code": code, "name": name, "pe_now": None, "pe_pct5y": None,
                        "n_days": len(hist)})
            continue
        last5y = [pe for d, pe in hist if d >= "2021-10-27"]
        if len(last5y) < 200:
            last5y = hist[-1200:]
        cur = last5y[-1]
        pct = percentile(cur, last5y)
        out.append({"code": code, "name": name, "sector": r["sector"],
                    "pe_now": round(cur, 2), "pe_pct5y": round(pct, 1),
                    "n_days": len(last5y)})
        print(f"OK {code} {name}: PE={cur:.2f} 近5年分位={pct:.1f}% ({len(last5y)}日)", flush=True)

    with open(r"D:/Code/AH_analyse/tools/divi_pe_pctile.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    done = [x for x in out if x["pe_pct5y"] is not None]
    done.sort(key=lambda x: x["pe_pct5y"])
    print(f"\n## PE分位·48只 @ 2026-10-27（东财全历史PE_TTM，近5年窗口）")
    print("| PE分位 | 代码 | 名称 | 当前PE | 近5年分位 | 样本天数 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for x in done:
        print(f"| {'🟢便宜' if x['pe_pct5y']<30 else ('🟡中位' if x['pe_pct5y']<70 else '🔴贵')} | {x['code']} | {x['name']} | {x['pe_now']} | **{x['pe_pct5y']}%** | {x['n_days']} |")
    miss = [x for x in out if x["pe_pct5y"] is None]
    if miss:
        print("\n缺失: " + ", ".join(f"{x['name']}" for x in miss))


if __name__ == "__main__":
    main()
