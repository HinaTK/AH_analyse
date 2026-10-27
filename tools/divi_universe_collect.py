#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三榜合一·高股息个股全面采集：TTM股息率 + 财务 + 技术 + 红旗 → JSON。

三表来源：
  表1 App"股息率前20名"（2026-10-27截图）
  表2 财知合一社"2026年9月股息率金字塔"（30只）
  表3 雨笠攒股日记"20只精选高分红龙头股"（2026-10-26，实际19行）
"""
import subprocess, sys, re, time, json, urllib.request
from datetime import datetime, timedelta

WESTOCK = r"C:/Users/Administrator/.local/bin/westock.exe"
TODAY = datetime.now().date()
CUTOFF = TODAY - timedelta(days=365)

# 合并去重名单：code, name, sector, 来源表(1/2/3)
POOL = [
    # 银行 (13)
    ("sh601398", "工商银行", "银行", "2,3"), ("sh601939", "建设银行", "银行", "2,3"),
    ("sh601288", "农业银行", "银行", "3"), ("sh601988", "中国银行", "银行", "3"),
    ("sh600036", "招商银行", "银行", "2,3"), ("sh601166", "兴业银行", "银行", "1"),
    ("sh600015", "华夏银行", "银行", "1"), ("sh601818", "光大银行", "银行", "1"),
    ("sh601838", "成都银行", "银行", "1"), ("sz000001", "平安银行", "银行", "1"),
    ("sh601229", "上海银行", "银行", "1"), ("sh601916", "浙商银行", "银行", "1"),
    ("sh600016", "民生银行", "银行", "1"),
    # 煤炭 (3)
    ("sh601088", "中国神华", "煤炭", "1,2,3"), ("sh601225", "陕西煤业", "煤炭", "1,2,3"),
    ("sh600188", "兖矿能源", "煤炭", "1,2"),
    # 石油 (3)
    ("sh601857", "中国石油", "石油", "2,3"), ("sh600028", "中国石化", "石油", "2,3"),
    ("sh600938", "中国海油", "石油", "2,3"),
    # 电力 (5)
    ("sh600011", "华能国际", "电力", "2,3"), ("sh600900", "长江电力", "电力", "2,3"),
    ("sh600886", "国投电力", "电力", "3"), ("sh600023", "浙能电力", "电力", "1"),
    ("sh601985", "中国核电", "电力", "2"),
    # 电信 (3)
    ("sh600941", "中国移动", "电信", "2,3"), ("sh601728", "中国电信", "电信", "2,3"),
    ("sh600050", "中国联通", "电信", "2"),
    # 白酒 (3)
    ("sh600519", "贵州茅台", "白酒", "2,3"), ("sz000858", "五粮液", "白酒", "2,3"),
    ("sh600809", "山西汾酒", "白酒", "2,3"),
    # 家电 (3)
    ("sz000651", "格力电器", "家电", "1,2,3"), ("sz000333", "美的集团", "家电", "1,2"),
    ("sh600690", "海尔智家", "家电", "2"),
    # 食品 (2)
    ("sz000895", "双汇发展", "食品", "1,3"), ("sh600887", "伊利股份", "食品", "3"),
    # 建筑/基建 (3)
    ("sh601668", "中国建筑", "建筑", "1,2"), ("sh601390", "中国中铁", "建筑", "2"),
    ("sh601800", "中国交建", "建筑", "2"),
    # 交通 (3)
    ("sh601006", "大秦铁路", "交通", "2"), ("sh601816", "京沪高铁", "交通", "2"),
    ("sh600018", "上港集团", "交通", "2"),
    # 其他 (7)
    ("sh601919", "中远海控", "航运", "1"), ("sz000538", "云南白药", "医药", "1"),
    ("sz000157", "中联重科", "机械", "1"), ("sh600803", "新奥股份", "燃气", "1"),
    ("sh601318", "中国平安", "保险", "2"), ("sh601601", "中国太保", "保险", "2"),
    ("sh601628", "中国人寿", "保险", "2"),
]


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


def retry_westock(*args, tries=3):
    for i in range(tries):
        out = westock(*args)
        if "|" in out:
            return out
        time.sleep(1.0 + i)
    return out


def ttm_dps(code):
    out = retry_westock("dividend", code)
    rows = parse_md(out)
    total, n, last_year = 0.0, 0, ""
    for r in rows:
        ex = (r.get("exDiviDate") or "").replace("-", "")
        if not (ex.isdigit() and len(ex) == 8):
            continue
        try:
            d = datetime.strptime(ex, "%Y%m%d").date()
        except ValueError:
            continue
        if d < CUTOFF or d > TODAY:
            continue
        dps = float(r.get("cashDiviRMB") or 0) / 10.0
        if dps > 0:
            total += dps
            n += 1
            last_year = r.get("reportEndDate", "")[:10]
    return round(total, 4), n, last_year


def prices(codes):
    res = {}
    for i in range(0, len(codes), 30):
        url = "https://qt.gtimg.cn/q=" + ",".join(codes[i:i+30])
        raw = urllib.request.urlopen(url, timeout=15).read().decode("gbk", errors="replace")
        for m in re.finditer(r'v_(\w+)="([^"]+)"', raw):
            f = m.group(2).split("~")
            if len(f) > 40:
                try:
                    res[m.group(1)] = {"price": float(f[3]), "pct": float(f[32]), "mktcap": f[45] if len(f) > 45 else ""}
                except (ValueError, IndexError):
                    pass
    return res


def finance_snapshot(code):
    """财务红旗快扫: 最新期净利增速/ROE/负债率 + PE分位锚EPS。"""
    out = retry_westock("finance", code, "--limit", "2")
    tabs = out.split("**")
    res = {}
    for i, t in enumerate(tabs):
        if t.strip() == "利润表" and i + 1 < len(tabs):
            rows = parse_md(tabs[i+1])
            if rows:
                r = rows[0]
                res["eps_ttm"] = r.get("EPSTTM") or r.get("BasicEPS")
                res["np_yoy"] = r.get("NPParentCompanyYOY")
                res["roe_ttm"] = r.get("ROETTM") or r.get("RoeWeighted")
    return res


def tech_snapshot(code):
    out = westock("technical", code)
    rows = parse_md(out)
    if not rows:
        return {}
    r = rows[0]
    return {"macd": r.get("MACD"), "kdj_j": r.get("KDJ_J"), "rsi6": r.get("RSI_6"),
            "ma20": r.get("MA_20"), "ma60": r.get("MA_60"), "ma250": r.get("MA_250"),
            "close": r.get("closePrice")}


def main():
    codes = [c for c, *_ in POOL]
    px = prices(codes)
    results, failed = [], []
    for code, name, sector, src in POOL:
        rec = {"code": code, "name": name, "sector": sector, "src": src}
        try:
            dps, n, lastyr = ttm_dps(code)
            rec["dps_ttm"], rec["div_n"], rec["last_div_period"] = dps, n, lastyr
            p = px.get(code, {})
            rec["price"] = p.get("price")
            rec["yield_ttm"] = round(dps / p["price"] * 100, 2) if dps and p.get("price") else None
            time.sleep(0.3)
            rec["fin"] = finance_snapshot(code)
            rec["tech"] = tech_snapshot(code)
            results.append(rec)
            y = rec["yield_ttm"]
            print(f"OK {code} {name}: DPS={dps} x{n} 股息率={y}%", flush=True)
        except Exception as e:
            failed.append(f"{code} {name}: {e}")
            print(f"FAIL {code} {name}: {e}", flush=True)
    out = {"date": str(TODAY), "results": results, "failed": failed}
    with open(r"D:/Code/AH_analyse/tools/divi_universe.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n完成 {len(results)}/{len(POOL)}，失败 {len(failed)}")


if __name__ == "__main__":
    main()
