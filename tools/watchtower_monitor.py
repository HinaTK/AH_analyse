#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""四大观察哨监控（2026-10-30 历史类比研究的落地，源自 tools/market_history_analog_20261030.md）

哨① 量能地量: 上证5日均额/120日峰值 < 0.33 → 地量（卖压枯竭，右侧信号1/3）
哨② 两融出清: 全市场两融余额 跌破2.20万亿 → 出清加深确认；净偿还连续10日>500亿 → 加速出清
哨③ AI财报季: 财报窗口期标记（2026Q4-2027Q1, 创业板/科创板业绩预告1月底前强制披露）→ 窗口期提示验证临近
哨④ 924级政策: 政策事件型——脚本无法自动判定, 显示"人工盯守"状态 + 备忘清单(SFISF扩容/央行直连工具/化债级财政)

数据源:
  量能: westock kline sh000001 (amount)
  两融: 东财 RPTA_RZRQ_LSHJ (全市场历史序列, 实测可用)
输出: watchdog 模式——有触发/状态翻转才输出, 全部正常静默
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

WESTOCK = r"C:/Users/Administrator/.local/bin/westock.exe"
STATE_PATH = Path("D:/Code/AH_analyse/tools/watchtower_state.json")

# 阈值（研究档案口径）
TH_VOLRATIO = 0.33      # 地量线
TH_MARGIN_CLEAR = 22000.0  # 两融出清线(亿)
TH_MARGIN_ACCEL = 500.0    # 10日净偿还加速线(亿)
EARNINGS_WINDOW = ("2027-01-01", "2027-02-01")  # Q4业绩预告强制披露窗口(1月底前)


def westock(*args):
    r = subprocess.run([WESTOCK, *args], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace")


def volume_ratio():
    """上证: 5日均额/120日峰值。"""
    out = westock("kline", "sh000001", "--period", "day", "--limit", "130")
    lines = [l for l in out.splitlines() if l.startswith("|")]
    if len(lines) < 10:
        return None
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = [[c.strip() for c in l.strip("|").split("|")] for l in lines[2:]]
    try:
        ai = hdr.index("amount")
        amounts = [float(r[ai]) for r in rows]
    except (ValueError, KeyError, IndexError):
        return None
    if len(amounts) < 120:
        return None
    avg5 = sum(amounts[:5]) / 5
    peak = max(amounts[:120])
    return {"ratio": round(avg5 / peak, 3), "avg5_yi": round(avg5 / 1e8, 0),
            "peak_yi": round(peak / 1e8, 0), "date": rows[0][0]}


def margin_data():
    """东财全市场两融: 最新余额 + 10日净偿还。"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPTA_RZRQ_LSHJ&columns=DIM_DATE,RZYE,RZRQYE,RZYEZB,RZJME10D"
           "&pageSize=8&sortColumns=DIM_DATE&sortTypes=-1")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = json.loads(urllib.request.urlopen(req, timeout=20).read())
        data = ((raw.get("result") or {}).get("data")) or []
        if not data:
            return None
        d = data[0]
        return {
            "date": d["DIM_DATE"][:10],
            "rzye_yi": round(d["RZYE"] / 1e8, 0),        # 融资余额(亿)
            "rzrq_yi": round(d["RZRQYE"] / 1e8, 0),      # 两融余额(亿)
            "pct_ltsz": round(d["RZYEZB"], 2),           # 占流通市值%
            "jme10_yi": round(d["RZJME10D"] / 1e8, 0),   # 10日净偿还(亿, 负=净偿还)
        }
    except Exception as e:
        return {"error": str(e)}


def check_sentries():
    sigs = []
    # 哨① 地量
    v = volume_ratio()
    if v:
        if v["ratio"] < TH_VOLRATIO:
            st, note = "✅地量达成", f"量能比{v['ratio']} < {TH_VOLRATIO}，卖压枯竭信号"
        elif v["ratio"] < 0.40:
            st, note = "接近", f"量能比{v['ratio']}（线{TH_VOLRATIO}），趋近地量"
        else:
            st, note = "未到", f"量能比{v['ratio']}（线{TH_VOLRATIO}）"
        sigs.append(("vol_dry", "哨①量能地量(<0.33)", st, note, v["date"]))
    else:
        sigs.append(("vol_dry", "哨①量能地量", "数据缺失", "K线拉取失败", ""))

    # 哨② 两融出清
    m = margin_data()
    if m and "error" not in m:
        notes = []
        st = "未到"
        if m["rzrq_yi"] < TH_MARGIN_CLEAR:
            st = "✅出清加深"
            notes.append(f"两融{m['rzrq_yi']:.0f}亿 < {TH_MARGIN_CLEAR:.0f}亿线")
        else:
            notes.append(f"两融{m['rzrq_yi']:.0f}亿（线{TH_MARGIN_CLEAR:.0f}亿）")
        if abs(m["jme10_yi"]) > TH_MARGIN_ACCEL and m["jme10_yi"] < 0:
            notes.append(f"10日净偿还{abs(m['jme10_yi']):.0f}亿>加速线{TH_MARGIN_ACCEL:.0f}亿")
            if st == "未到":
                st = "⚡加速出清"
        notes.append(f"占流通市值{m['pct_ltsz']}%")
        sigs.append(("margin_clear", "哨②两融出清(<2.2万亿)", st, "；".join(notes), m["date"]))
    else:
        sigs.append(("margin_clear", "哨②两融出清", "数据缺失",
                     (m or {}).get("error", "东财接口失败")[:80], ""))

    # 哨③ AI财报季（日历驱动）
    today = datetime.now().strftime("%Y-%m-%d")
    if EARNINGS_WINDOW[0] <= today <= EARNINGS_WINDOW[1]:
        st, note = "⏰窗口开启", "Q4业绩预告强制披露期（1月底前）——AI盈利验证分水岭"
    else:
        days = (datetime.strptime(EARNINGS_WINDOW[0], "%Y-%m-%d") - datetime.now()).days
        if days > 0:
            st, note = "待窗口", f"距预告披露窗口还有{days}天（2027-01起）"
        else:
            st, note = "窗口已过", "验证已落地，按结果重估情景概率"
    sigs.append(("ai_earnings", "哨③AI财报季验证", st, note, ""))

    # 哨④ 924级政策（人工盯守清单）
    sigs.append(("policy_924", "哨④924级政策开关", "人工盯守",
                 "盯: SFISF扩容/回购增持再贷款加码/央行直连股市新工具/化债级财政——出现任意一项即推送人工判定", ""))
    return sigs


def render(sigs):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"### 🗼 观察哨（历史类比四哨）@ {now}", "",
             "| 哨 | 状态 | 读数 |", "| --- | --- | --- |"]
    for key, label, st, note, d in sigs:
        dd = f"（{d}）" if d else ""
        lines.append(f"| {label} | {st} | {note}{dd} |")
    lines += ["", "读法：哨①+哨②同时达成=出清末段（右侧三信号的地量件先满足）；哨③财报验证定2022/2021路径分岔；哨④任何一项出现=反转开关候选，需人工确认级别。"]
    return "\n".join(lines)


def main():
    as_json = "--json" in sys.argv
    sigs = check_sentries()
    # watchdog: 触发态或状态翻转才输出
    prev = {}
    if STATE_PATH.exists():
        try:
            prev = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}
    today = datetime.now().strftime("%Y-%m-%d")
    triggered = []
    for s in sigs:
        if any(t in s[2] for t in ("✅", "⚡", "⏰")):
            # 同日同状态不重复推（状态翻转日推一次）
            if prev.get(s[0], {}).get("state") != s[2] or prev.get(s[0], {}).get("date") != today:
                triggered.append(s)
    flipped = any(prev.get(s[0], {}).get("state") != s[2] for s in sigs if s[2] not in ("人工盯守",))
    if as_json:
        print(json.dumps({"sentries": [{"key": k, "state": s, "note": n, "date": d} for k, l, s, n, d in sigs]}, ensure_ascii=False))
        return
    if triggered or flipped or not prev:
        print(render(sigs))
    new_state = {s[0]: {"state": s[2], "date": today} for s in sigs}
    # 翻转检测须在写状态前完成——上面 flipped 已在写前计算
    STATE_PATH.write_text(json.dumps(new_state, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
