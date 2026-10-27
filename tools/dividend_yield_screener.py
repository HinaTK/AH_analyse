#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""高股息个股筛选器：候选池 × westock 分红历史 × 腾讯实时价 → TTM股息率榜。

用法: python dividend_yield_screener.py [--market a|hk|all] [--top N]
输出: markdown 表格（原样交付，禁止聊天层手改数字）。
口径: TTM每股派息 = 近365天内除息日(含特别股息)每股现金分红合计; 股息率 = TTM DPS / 实时价。
"""
import subprocess
import sys
import re
import urllib.request
from datetime import datetime, timedelta

WESTOCK = r"C:/Users/Administrator/.local/bin/westock.exe"
TODAY = datetime.now().date()
CUTOFF = TODAY - timedelta(days=365)

# 候选池: (code, name, sector)
POOL_A = [
    ("sh601398", "工商银行", "银行"), ("sh601939", "建设银行", "银行"),
    ("sh601288", "农业银行", "银行"), ("sh601328", "交通银行", "银行"),
    ("sh601658", "邮储银行", "银行"), ("sh600036", "招商银行", "银行"),
    ("sh601166", "兴业银行", "银行"), ("sh601998", "中信银行", "银行"),
    ("sh601818", "光大银行", "银行"), ("sh601169", "北京银行", "银行"),
    ("sh601009", "南京银行", "银行"), ("sh600919", "江苏银行", "银行"),
    ("sh601838", "成都银行", "银行"), ("sh601229", "上海银行", "银行"),
    ("sh600000", "浦发银行", "银行"),
    ("sh601088", "中国神华", "煤炭"), ("sh601225", "陕西煤业", "煤炭"),
    ("sh600188", "兖矿能源", "煤炭"), ("sh601898", "中煤能源", "煤炭"),
    ("sh601001", "晋控煤业", "煤炭"),
    ("sh601857", "中国石油", "石油"), ("sh600028", "中国石化", "石油"),
    ("sh600938", "中国海油", "石油"),
    ("sh600941", "中国移动", "电信"), ("sh601728", "中国电信", "电信"),
    ("sh600050", "中国联通", "电信"),
    ("sh600900", "长江电力", "电力"), ("sh600886", "国投电力", "电力"),
    ("sh600025", "华能水电", "电力"), ("sh601985", "中国核电", "电力"),
    ("sh601006", "大秦铁路", "铁路"), ("sz000429", "粤高速A", "公路"),
    ("sh600377", "宁沪高速", "公路"), ("sh600548", "深高速", "公路"),
    ("sh600012", "皖通高速", "公路"), ("sh600350", "山东高速", "公路"),
    ("sh600019", "宝钢股份", "钢铁"), ("sh600585", "海螺水泥", "建材"),
    ("sh601668", "中国建筑", "建筑"), ("sh601919", "中远海控", "航运"),
    ("sz000895", "双汇发展", "食品"),
]
POOL_HK = [
    ("hk00005", "汇丰控股", "银行"), ("hk01398", "工商银行H", "银行"),
    ("hk00939", "建设银行H", "银行"), ("hk01288", "农业银行H", "银行"),
    ("hk03988", "中国银行H", "银行"), ("hk03328", "交通银行H", "银行"),
    ("hk00857", "中国石油H", "石油"), ("hk00386", "中国石化H", "石油"),
    ("hk00883", "中国海油H", "石油"), ("hk00941", "中国移动H", "电信"),
    ("hk00728", "中国电信H", "电信"), ("hk01088", "中国神华H", "煤炭"),
]


def parse_md_table(text):
    """把 westock 输出的 markdown 表解析成 dict 列表。"""
    rows = []
    lines = [l for l in text.splitlines() if l.startswith("|")]
    if len(lines) < 3:
        return rows
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    for l in lines[2:]:
        cells = [c.strip() for c in l.strip("|").split("|")]
        if len(cells) == len(hdr):
            rows.append(dict(zip(hdr, cells)))
    return rows


def westock(*args):
    r = subprocess.run([WESTOCK, *args], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")


def ttm_dps(code):
    """近365天除息日对应的每股现金分红合计（A股: cashDiviRMB 为每10股派息）。"""
    out = westock("dividend", code)
    tables = re.split(r"\n#### ", out)
    rows = []
    for t in tables:
        rows.extend(parse_md_table(t))
    total, n = 0.0, 0
    for r in rows:
        ex = (r.get("exDiviDate") or "").replace("-", "").strip()
        if not (ex.isdigit() and len(ex) == 8):
            continue
        try:
            d = datetime.strptime(ex, "%Y%m%d").date()
        except ValueError:
            continue
        if d < CUTOFF or d > TODAY:
            continue
        if code.startswith("hk"):
            dps = float(r.get("cashDivPerShare") or 0) + float(r.get("specialDivPerShare") or 0)
        else:
            dps = float(r.get("cashDiviRMB") or 0) / 10.0
        if dps > 0:
            total += dps
            n += 1
    return total, n


def realtime_prices(codes):
    """腾讯批量实时报价: code -> (name, price)。"""
    prices = {}
    for i in range(0, len(codes), 30):
        chunk = codes[i:i + 30]
        url = "https://qt.gtimg.cn/q=" + ",".join(chunk)
        raw = urllib.request.urlopen(url, timeout=15).read().decode("gbk", errors="replace")
        for m in re.finditer(r'v_(\w+)="([^"]+)"', raw):
            f = m.group(2).split("~")
            if len(f) > 4:
                try:
                    prices[m.group(1)] = float(f[3])
                except ValueError:
                    pass
    return prices


def main():
    market = "all"
    top = 0
    args = sys.argv[1:]
    if "--market" in args:
        market = args[args.index("--market") + 1]
    if "--top" in args:
        top = int(args[args.index("--top") + 1])

    pool = []
    if market in ("a", "all"):
        pool += POOL_A
    if market in ("hk", "all"):
        pool += POOL_HK

    prices = realtime_prices([c for c, _, _ in pool])
    results = []
    for code, name, sector in pool:
        try:
            dps, n = ttm_dps(code)
            for _ in range(2):  # westock 偶发限流返回空表，重试
                if n > 0:
                    break
                dps, n = ttm_dps(code)
            px = prices.get(code)
            if dps > 0 and px:
                results.append({
                    "code": code, "name": name, "sector": sector,
                    "price": px, "dps": dps, "n": n,
                    "yield": dps / px * 100,
                })
        except Exception as e:
            print(f"<!-- {code} {name}: 取数失败 {e} -->", file=sys.stderr)
    results.sort(key=lambda r: -r["yield"])

    if top:
        results = results[:top]

    print(f"**高股息筛选**（候选{len(pool)}只，成功{len(results)}只）｜口径: 近365天除息日每股现金分红合计÷实时价｜数据: westock分红历史+腾讯实时 ｜生成: {TODAY}")
    print()
    print("| 代码 | 名称 | 板块 | 现价 | TTM每股派息(元) | 派息次数 | 股息率TTM |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for r in results:
        print(f"| {r['code']} | {r['name']} | {r['sector']} | {r['price']:.2f} | {r['dps']:.3f} | {r['n']} | **{r['yield']:.2f}%** |")


if __name__ == "__main__":
    main()
