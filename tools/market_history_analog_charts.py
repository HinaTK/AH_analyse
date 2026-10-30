#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""大A历史类比研究 · 图表生成器
输出:
  1. history_analog_1_drawdowns.png  —— 三段历史+本轮的回撤路径对比（自顶点归一）
  2. history_analog_2_similarity.png —— 因子相似度矩阵热力图
  3. history_analog_3_afterward.png  —— 三段历史"见底后12个月"的反弹路径
  4. history_analog_4_factors.png     —— 当前 vs 三段历史的因子雷达图
数据: westock 月线实拉 + 研究档案 tools/market_history_analog_20261030.md
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


def series_from(dmap, months):
    return [dmap.get(m) for m in months]


# ============ 数据 ============
sh, sh_months = monthly("sh000001")
cyb, _ = monthly("sz399006")

# 本轮: 2026-05(顶) 起; 上证顶=2026-05 月内高点4243(日线), 月线收盘用4112/4069序列
cur_months = [m for m in sh_months if m >= "2026-04"]
cur_sh = [sh[m] for m in cur_months]
cur_top = 4243.0  # 日线实拉年内顶(2026-05-13)

# 历史段: (名称, 顶月份, 顶值, 谷月份, 谷值, 顶后月序列月数)
segs = [
    ("2018去杠杆+贸易战", "2018-01", 3481, "2018-12", 2494, 14),
    ("2022-24慢熊", "2021-12", 3640, "2024-01", 2789, 14),
    ("本轮2026", None, cur_top, "2026-10", 3599, len(cur_months)),
]

# ---- 图1: 回撤路径(自顶点最大回撤序列, 月度) ----
fig, ax = plt.subplots(figsize=(11, 6))
for name, top_m, top_v, _, _, n in segs:
    if top_m is None:
        # 本轮: 用日线段近似月度路径: 4243顶起
        path = [(p / cur_top - 1) * 100 for p in cur_sh]
        xs = list(range(len(path)))
        ax.plot(xs, path, marker="o", lw=2.5, label=name)
        continue
    months = [m for m in sh_months if m >= top_m][:n]
    vals = [sh[m] for m in months]
    path = [(v / top_v - 1) * 100 for v in vals]
    ax.plot(range(len(path)), path, marker="o", lw=2, label=name)
    # 标注谷
    gi = int(np.argmin(path))
    ax.annotate(f"{path[gi]:.0f}%", (gi, path[gi]), textcoords="offset points",
                xytext=(0, -14), ha="center", fontsize=9)
ax.axhline(-20, color="red", ls="--", alpha=0.5, lw=1)
ax.text(0.1, -19.4, "技术性熊市线(-20%)", color="red", fontsize=9, alpha=0.8)
ax.set_title("大A四轮大级别回撤：自顶点跌幅路径（月度，上证指数）", fontsize=14, weight="bold")
ax.set_xlabel("自顶部起月数")
ax.set_ylabel("距顶部涨幅 %")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT + "history_analog_1_drawdowns.png", dpi=150)
plt.close(fig)

# ---- 图2: 因子相似度热力图 ----
factors = ["大盘跌幅", "成长跌幅", "下跌速度", "热门成长领跌", "杠杆高位",
           "政策托底", "利率低位", "盈利未崩", "外部冲击"]
cur = [0.50, 0.67, 0.40, 1.00, 1.00, 1.00, 1.00, 0.50, 0.50]
h2018 = [1.00, 0.78, 0.00, 0.50, 0.75, 1.00, 0.00, 0.00, 1.00]
h2224 = [0.77, 1.00, 0.00, 1.00, 0.87, 1.00, 0.24, 0.00, 1.00]
h2401 = [0.27, 0.44, 1.00, 1.00, 0.91, 1.00, 0.48, 0.00, 0.00]
M = np.array([[1 - abs(c - h) for c, h in zip(cur, col)] for col in (h2018, h2224, h2401)])

fig, ax = plt.subplots(figsize=(10, 4.5))
im = ax.imshow(M, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
ax.set_xticks(range(len(factors)), factors, rotation=30, ha="right")
ax.set_yticks(range(3), ["2018贸易战熊", "2022-24慢熊", "2024.1微盘踩踏"])
for i in range(3):
    for j in range(len(factors)):
        ax.text(j, i, f"{M[i,j]:.2f}", ha="center", va="center", fontsize=9,
                color="black" if 0.3 < M[i, j] < 0.85 else "white")
# 加权总分
w = np.array([1, 1, 1, 2, 1.5, 1, 1, 1.5, 1])
totals = (M * w).sum(axis=1) / w.sum()
for i, t in enumerate(totals):
    ax.text(len(factors) - 0.3, i, f"加权\n{t*100:.0f}%", fontsize=11, weight="bold", va="center")
ax.set_title("当前(2026.5-10) vs 三段历史：九因子相似度矩阵（绿=像，红=不像）", fontsize=13, weight="bold")
fig.colorbar(im, ax=ax, shrink=0.8)
fig.tight_layout()
fig.savefig(OUT + "history_analog_2_similarity.png", dpi=150)
plt.close(fig)

# ---- 图3: 历史见底后12个月反弹路径 ----
fig, ax = plt.subplots(figsize=(11, 6))
after = [
    ("2018熊: 底2019-01@2440", "2019-01", 2440, 13),
    ("2024.1踩踏: 底2024-02@2635", "2024-02", 2635, 13),
]
for name, bot_m, bot_v, n in after:
    months = [m for m in sh_months if m >= bot_m][:n]
    vals = [sh[m] for m in months]
    path = [(v / bot_v - 1) * 100 for v in vals]
    ax.plot(range(len(path)), path, marker="o", lw=2.2, label=name)
    ax.annotate(f"+{path[-1]:.0f}%", (len(path) - 1, path[-1]),
                textcoords="offset points", xytext=(4, 6), fontsize=10, weight="bold")
# 2022-24慢熊: 底后有二次探底, 用2024-02起
months = [m for m in sh_months if m >= "2024-02"][:13]
vals = [sh[m] for m in months]
path = [(v / 2635 - 1) * 100 for v in vals]
ax.plot(range(len(path)), path, marker="o", lw=2.2, ls="--", label="2024-02(924前夜)作对照")
ax.axhline(0, color="gray", lw=0.8)
ax.set_title("历史大底之后12个月：反弹幅度对比（上证，自谷底归一）", fontsize=14, weight="bold")
ax.set_xlabel("自底部起月数")
ax.set_ylabel("距底部涨幅 %")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT + "history_analog_3_afterward.png", dpi=150)
plt.close(fig)

# ---- 图4: 雷达图 ----
labels = factors
N = len(labels)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
angles += angles[:1]
fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
for arr, name, color in [(cur, "当前2026", "red"), (h2401, "2024.1踩踏", "tab:blue"),
                          (h2224, "2022-24慢熊", "tab:green"), (h2018, "2018贸易战熊", "tab:orange")]:
    v = arr + arr[:1]
    ax.plot(angles, v, color=color, lw=2, label=name)
    ax.fill(angles, v, color=color, alpha=0.06)
ax.set_xticks(angles[:-1])
ax.set_xticklabels(labels, fontsize=10)
ax.set_title("四轮时期因子指纹雷达图（0-1标准化）", fontsize=14, weight="bold", pad=24)
ax.legend(loc="upper right", bbox_to_anchor=(1.28, 1.1))
fig.tight_layout()
fig.savefig(OUT + "history_analog_4_factors.png", dpi=150)
plt.close(fig)

print("生成4图:")
for i, n in enumerate(["drawdowns", "similarity", "afterward", "factors"], 1):
    print(f"  history_analog_{i}_{n}.png")
print("加权相似度:", {n: f"{t*100:.0f}%" for n, t in zip(["2018熊", "2022-24慢熊", "2024.1踩踏"], totals)})
