#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""利率点火/熄火监控 v2（2026-10-29）。

数据方案（实测可用性排序）:
  1. westock 拉债券ETF K线（价格与收益率严格反向，数据稳定可用）
     - sh511090 30年国债ETF（久期~20年）→ 30年收益率代理
     - sh511010 10年国债ETF（久期~5.5年）→ 10年收益率代理
  2. 当前收益率绝对值用人工校准锚（定期更新）: 10Y=1.63% / 30Y=2.04% @2026-10-27
     收益率变化 ≈ -价格变化% × (100/久期)

信号定义（ETF价格口径, 全部可机器验证）:
  🔥点火: 30年收益率>=2.30% ⇒ 511090 较校准锚价格下跌 (2.30-2.04)%×20 ≈ -5.2% ⇒ <=115.14
  🚨熄火: 10年收益率<=1.50% ⇒ 511010 较锚下跌 (1.63-1.50)%×5.5 ≈ -0.7% ⇒ 对应阈值
  先行观察: 30年收益率60日新低(=511090价格60日新高) 且未点火 → "利率仍下行,磨底继续"

CPI/PPI: 读 macro_cpi_ppi_cache.json（月度手动/任务维护），缺失显示待更新。
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WESTOCK = r"C:/Users/Administrator/.local/bin/westock.exe"
STATE_PATH = Path("D:/Code/AH_analyse/tools/rate_ignition_state.json")
MACRO_CACHE = Path("D:/Code/AH_analyse/tools/macro_cpi_ppi_cache.json")

# ==== 校准锚（收益率% ↔ ETF价格，定期人工更新）====
ANCHOR = {
    "sh511090": {"name": "30年国债ETF", "yield": 2.04, "duration": 20.0,
                 "ignite_yield": 2.30, "px_ref": 121.462},   # 2026-10-28收盘@收益率2.04%
    "sh511010": {"name": "10年国债ETF", "yield": 1.63, "duration": 5.5,
                 "flameout_yield": 1.50, "px_ref": 141.216},  # 2026-10-28收盘@收益率1.63%（实测校准）
}
IGNITE_PX = ANCHOR["sh511090"]["px_ref"] * (1 - (ANCHOR["sh511090"]["ignite_yield"] - ANCHOR["sh511090"]["yield"]) / 100 * ANCHOR["sh511090"]["duration"])


def westock(*args):
    r = subprocess.run([WESTOCK, *args], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace")


def kline_closes(code, limit=250):
    out = westock("kline", code, "--period", "day", "--limit", str(limit))
    lines = [l for l in out.splitlines() if l.startswith("|")]
    if len(lines) < 5:
        return None, None
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = [[c.strip() for c in l.strip("|").split("|")] for l in lines[2:]]
    try:
        ci = hdr.index("last")
        closes = [float(r[ci]) for r in rows]
        return closes, rows[0][0]
    except (ValueError, KeyError, IndexError):
        return None, None


def est_yield(code, px):
    a = ANCHOR[code]
    return a["yield"] + (a["px_ref"] - px) / a["px_ref"] * 100 / a["duration"] * 1.0


def load_macro():
    if not MACRO_CACHE.exists():
        return None
    try:
        return json.loads(MACRO_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def check(c30, d30, c10, d10, macro):
    sigs = []
    today = datetime.now().strftime("%Y-%m-%d")

    # ① 30年点火: 估算收益率 >= 2.30
    if c30:
        px = c30[0]
        y30 = est_yield("sh511090", px)
        lo60, hi60 = min(c30[:60]), max(c30[:60])
        price_pct = (px - lo60) / (hi60 - lo60) * 100 if hi60 > lo60 else 50
        if y30 >= ANCHOR["sh511090"]["ignite_yield"]:
            state, detail = "🔥点火", f"估算30Y {y30:.2f}% ≥ 2.30%（ETF {px:.2f}）"
        else:
            state = "未触发"
            # 60日新高=利率60日新低 → 下行中
            trend = "利率60日新低（下行未止）" if px >= hi60 * 0.999 else (
                    "利率60日新高（回升中）" if px <= lo60 * 1.001 else "利率60日区间震荡")
            detail = f"估算30Y {y30:.2f}%（线2.30%），{trend}，ETF价格60日分位{price_pct:.0f}%（高=利率低）"
        sigs.append(("ignite30", "30年国债≥2.30%点火", state, detail, d30))
    else:
        sigs.append(("ignite30", "30年国债≥2.30%点火", "数据缺失", "511090 K线拉取失败", d30))

    # ② 10年熄火警报
    if c10:
        px = c10[0]
        y10 = est_yield("sh511010", px)
        if y10 <= ANCHOR["sh511010"]["flameout_yield"]:
            state, detail = "🚨熄火", f"估算10Y {y10:.2f}% ≤ 1.50%，资产荒恶化，保险4%假设承压"
        else:
            state, detail = "正常", f"估算10Y {y10:.2f}%（警戒1.50%）"
        sigs.append(("flameout10", "10年国债≤1.50%警报", state, detail, d10))
    else:
        sigs.append(("flameout10", "10年国债≤1.50%警报", "数据缺失", "511010 K线拉取失败", d10))

    # ③ PPI先行
    if macro and macro.get("ppi"):
        ppi = macro["ppi"][-2:]
        if len(ppi) >= 2 and all(p["value"] > 0 for p in ppi):
            state, detail = "✅先行", f"近2月 {[p['value'] for p in ppi]} 均>0"
        else:
            v = ppi[-1]["value"] if ppi else None
            state, detail = "未触发", f"最新 {v}%（线 0%）"
    else:
        state, detail = "待更新", "macro_cpi_ppi_cache.json 缺失或无 ppi 序列"
    sigs.append(("ppi_lead", "PPI连续2月>0%（先行）", state, detail, ""))

    # ④ CPI起步
    if macro and macro.get("cpi"):
        cpi = macro["cpi"][-3:]
        if len(cpi) >= 3 and all(c["value"] >= 1.5 for c in cpi):
            state, detail = "✅起步", f"近3月 {[c['value'] for c in cpi]} 均≥1.5%"
        else:
            v = cpi[-1]["value"] if cpi else None
            state, detail = "未触发", f"最新 {v}%（线 1.5%）"
    else:
        state, detail = "待更新", "macro_cpi_ppi_cache.json 缺失或无 cpi 序列"
    sigs.append(("cpi_start", "CPI连续3月≥1.5%", state, detail, ""))

    return sigs


def dedup(sigs):
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_state()
    out = []
    for key, label, st, detail, d in sigs:
        prev = state.get(key, {})
        bell = ""
        if st in ("🔥点火", "✅先行", "✅起步", "🚨熄火") and (prev.get("state") != st):
            bell = " 🔔"
        state[key] = {"state": st, "date": today}
        out.append((key, label, st, detail, bell))
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def render(sigs, y30, y10, d30):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append(f"### 📡 利率点火监控（保险周期）@ {now}")
    lines.append("")
    lines.append("| 信号 | 触发线 | 状态 | 读数 |")
    lines.append("| --- | --- | --- | --- |")
    for key, label, st, detail, bell in sigs:
        lines.append(f"| {label} | {'≥2.30%' if '点火' in key else ('≤1.50%' if 'flame' in key else ('>0%' if 'ppi' in key else '≥1.5%'))} | {st}{bell} | {detail} |")
    lines.append("")
    lines.append(f"30年国债≈**{y30:.2f}%**（ETF代理估算，校准锚2.04%@10-28）｜ 10年国债≈**{y10:.2f}%**")
    lines.append("")
    lines.append("读法：🔥点火=保险修复路径启动可加仓；🚨熄火=重新评估平安磨底逻辑；PPI领先利率拐点2-4季度。")
    lines.append("口径：债券ETF价格与收益率反向，久期换算；锚定期人工更新（当前锚 10Y 1.63%/30Y 2.04%）。")
    return "\n".join(lines)


def main():
    as_json = "--json" in sys.argv
    c30, d30 = kline_closes("sh511090")
    time.sleep(0.5)
    c10, d10 = kline_closes("sh511010")
    macro = load_macro()
    sigs = check(c30, d30, c10, d10, macro)
    sigs = dedup(sigs)
    y30 = est_yield("sh511090", c30[0]) if c30 else float("nan")
    y10 = est_yield("sh511010", c10[0]) if c10 else float("nan")
    if as_json:
        print(json.dumps({"y30_est": None if c30 is None else round(y30, 3),
                          "y10_est": None if c10 is None else round(y10, 3),
                          "date30": d30, "date10": d10,
                          "signals": [{"key": k, "state": s, "detail": d} for k, l, s, d, b in sigs]},
                         ensure_ascii=False))
    else:
        print(render(sigs, y30, y10, d30))


if __name__ == "__main__":
    main()
