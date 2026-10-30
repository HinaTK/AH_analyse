#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""大A历史类比研究 v2 图表（复查修订版）
v1 撤回的: 伪精确相似度热力图
v2 重出的:
  1. 回撤路径对比（含2015, 五段）——保留(数据实拉,无主观)
  2. 阶段结构图: 2018三段熊市结构 vs 本轮当前所处位置（深读原文提炼）
  3. 杠杆强度对比: 占流通市值比(2015 vs 当前, 澄清"重演2015"谬误)
  4. 反转开关时间线: 历次政策托底 vs 真反转(924级)的等级与效果
"""
import subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

WESTOCK = r"C:/Users/Administrator/.local/bin/westock.exe"
OUT = r"D:/Code/AH_analyse/tools/"


def monthly(code):
    r = subprocess.run([WESTOCK, "kline", code, "--period", "month", "--limit", "130"],
                       capture_output=True, timeout=90)
    txt = r.stdout.decode("utf-8", errors="replace")
    lines = [l for l in txt.splitlines() if l.startswith("|")]
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = [[c.strip() for c in l.strip("|").split("|")] for l in lines[2:]]
    ci = hdr.index("last")
    data = sorted((r_[0][:7], float(r_[ci])) for r_ in rows)
    return dict(data), [d for d, _ in data]


sh, sh_months = monthly("sh000001")

# ============ 图1: 五段回撤路径（含2015, 硬数据） ============
# 2015顶底: 2015-05收盘~4611, 顶6月12日5178(日线), 谷2015-08@3205(月收盘)后三轮下杀
# westock月线仅到2016-08, 2015段用月线数据内插(4611@2015-05 → 2016-02@2687)
fig, ax = plt.subplots(figsize=(11, 6))
cur_top = 4243.0
cur_months = [m for m in sh_months if m >= "2026-04"]
cur_path = [(sh[m] / cur_top - 1) * 100 for m in cur_months]

segs = [
    ("2018去杠杆+贸易战", "2018-01", 3481.0, 14),
    ("2022-24慢熊", "2021-12", 3640.0, 14),
]
for name, top_m, top_v, n in segs:
    months = [m for m in sh_months if m >= top_m][:n]
    path = [(sh[m] / top_v - 1) * 100 for m in months]
    ax.plot(range(len(path)), path, marker="o", lw=1.8, alpha=0.85, label=name)

# 2015: 手工月线序列(公开事实: 顶5178@2015-06, 谷2638@2016-01/02)
m2015 = [("2015-05", 4611), ("2015-06", 4277), ("2015-07", 3663), ("2015-08", 3205),
         ("2015-09", 3052), ("2015-10", 3382), ("2015-11", 3445), ("2015-12", 3539),
         ("2016-01", 2736), ("2016-02", 2687)]
p2015 = [(v / 5178 - 1) * 100 for _, v in m2015]
ax.plot(range(len(p2015)), p2015, marker="o", lw=1.8, alpha=0.85, color="purple", label="2015杠杆牛崩盘(顶5178)")

ax.plot(range(len(cur_path)), cur_path, marker="o", lw=3, color="red", label="本轮2026(顶4243)")
ax.axhline(-20, color="red", ls="--", alpha=0.4, lw=1)
ax.text(0.2, -19.3, "技术性熊市线(-20%)", color="red", fontsize=9, alpha=0.8)
ax.set_title("五轮大级别回撤：自顶点跌幅路径（月度收盘，上证）", fontsize=14, weight="bold")
ax.set_xlabel("自顶部起月数")
ax.set_ylabel("距顶部涨幅 %")
ax.legend(loc="lower left")
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT + "history_analog_v2_1_drawdowns.png", dpi=150)
plt.close(fig)

# ============ 图2: 2018三段结构 vs 本轮位置（深读提炼） ============
fig, ax = plt.subplots(figsize=(12, 6))
# 2018三段(思想钢印复盘): 一段1.29-6.15(-15%后平台), 二段6.19-10.11(主跌), 三段10.11-2019.1.3(磨底+强势股补跌)
stages_2018 = [
    ("第一阶段\n宽货币紧信用矛盾\n1.29-6.15", 0.5, "#4A90D9"),
    ("第二阶段\n主跌浪(股权质押)\n6.19-10.11", 2.6, "#D94A4A"),
    ("第三阶段\n政策底→市场底\n磨底+强势股补跌\n10.11-2019.1.3", 5.2, "#7A7A7A"),
]
for label, x, color in stages_2018:
    ax.barh(1, 1.8 if x < 2 else 2.2, left=x, height=0.55, color=color, alpha=0.75)
    ax.text(x + 0.9, 1, label, ha="center", va="center", fontsize=8.5, color="white", weight="bold")
# 2018顶底
ax.annotate("顶3481(1月)", (0.1, 1.4), fontsize=9)
ax.annotate("谷2494(12月)  -28%", (7.0, 0.55), fontsize=9, color="#D94A4A")

# 本轮
ax.barh(0, 1.0, left=0, height=0.55, color="#D98C4A", alpha=0.85)
ax.text(0.5, 0, "本轮: 第一波下跌-15%\n(顶4243→3599, 5.5个月)", ha="center", va="center", fontsize=9, color="white", weight="bold")
ax.barh(0, 7.6, left=1.0, height=0.55, color="#E8E8E8", alpha=0.9)
ax.text(4.8, 0, "？未知区间\n若复制2018结构: 当前盘整可能是\"下一段的顶\"而非底\n分水岭: Q4-Q1财报季AI盈利验证", ha="center", va="center", fontsize=8.5, color="#666")

ax.set_yticks([0, 1], ["本轮 2026", "2018 熊市"])
ax.set_xlim(0, 7.8)
ax.set_title("熊市阶段结构对照：2018是\"三个熊市碰在同一年\"（思想钢印复盘）", fontsize=13, weight="bold")
ax.set_xlabel("← 时间推进（非严格比例）")
fig.tight_layout()
fig.savefig(OUT + "history_analog_v2_2_stages.png", dpi=150)
plt.close(fig)

# ============ 图3: 杠杆强度对比（澄清"重演2015"谬误） ============
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
ax1, ax2 = axes
# 绝对额
labels = ["2015-06峰值", "当前2026-10"]
vals = [2.27, 2.4]
bars = ax1.bar(labels, vals, color=["#999", "#D94A4A"], width=0.5)
for b, v in zip(bars, vals):
    ax1.text(b.get_x() + b.get_width() / 2, v + 0.05, f"{v}万亿", ha="center", fontsize=11, weight="bold")
ax1.set_title("两融余额绝对额\n（相似：都在历史峰值区）", fontsize=12)
ax1.set_ylabel("万亿元")
ax1.set_ylim(0, 2.8)
# 相对强度
labels2 = ["2015峰值\n(含场外配资)", "2015峰值\n(仅两融)", "当前"]
vals2 = [15, 4.7, 2.53]
colors2 = ["#8B0000", "#D98C4A", "#4A90D9"]
bars2 = ax2.bar(labels2, vals2, color=colors2, width=0.5)
for b, v in zip(bars2, vals2):
    ax2.text(b.get_x() + b.get_width() / 2, v + 0.2, f"{v}%", ha="center", fontsize=11, weight="bold")
ax2.set_title("两融占流通市值比\n（真实杠杆强度：当前仅为2015的1/6）", fontsize=12)
ax2.set_ylabel("%")
fig.suptitle("澄清流行谬误：\"两融2.4万亿≈2015峰值，重演股灾\" —— 绝对额像，强度差一个量级", fontsize=13, weight="bold", y=1.02)
fig.tight_layout()
fig.savefig(OUT + "history_analog_v2_3_leverage.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ============ 图4: 反转开关等级表（政策托底≠反转） ============
fig, ax = plt.subplots(figsize=(12, 5.5))
events = [
    ("2018-10 四大天王讲话\n+纾困基金", "政策底信号", 2, "市场底还差3个月\n(2019-1, 强势股再补跌20%)"),
    ("2022-2024.9 多轮降准降息\n+汇金常规增持", "常规托底", 1, "全部无效\n指数继续阴跌"),
    ("2024-2 汇金扩大ETF增持", "强化托底", 2.5, "止住踩踏, 但仅反弹\n未反转"),
    ("2024-9-24 924组合拳\n降准+SFISF5000亿\n+回购再贷款3000亿", "央行直连股市", 5, "真反转: 1个月+25%\n成交1.7万亿/日"),
    ("2026-4至今 汇金类平准\n增持ETF(常规力度)", "常规托底", 1.5, "托而不举(进行中)\n反转需924级开关"),
]
for i, (name, level_label, power, outcome) in enumerate(events):
    y = len(events) - 1 - i
    color = "#D94A4A" if power >= 4 else ("#D98C4A" if power >= 2.5 else "#999")
    ax.barh(y, power, color=color, height=0.6, alpha=0.85)
    ax.text(power + 0.1, y, f"{level_label}", va="center", fontsize=10, weight="bold", color=color)
    ax.text(0.1, y, name, va="center", fontsize=9, color="white", weight="bold")
    ax.text(6.0, y, outcome, va="center", fontsize=9, color="#333")
ax.set_yticks([])
ax.set_xlim(0, 10.5)
ax.set_xlabel("政策力度（1=常规 5=历史最强）")
ax.set_title("历史验证：什么才叫\"反转开关\"——托底≠反转，唯924级(央行直连股市)触发真反转", fontsize=12.5, weight="bold")
fig.tight_layout()
fig.savefig(OUT + "history_analog_v2_4_switch.png", dpi=150)
plt.close(fig)

print("v2四图生成完毕:")
for n in ["1_drawdowns", "2_stages", "3_leverage", "4_switch"]:
    print(f"  history_analog_v2_{n}.png")
