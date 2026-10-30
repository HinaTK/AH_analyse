#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""高股息决策引擎（TDD）：合并三源数据 → 四维交叉 → 明确动作。

数据源:
  divi_two_axis.json   两轴数据(价格/股息/盈利/红旗/趋势/52周分位)
  divi_pe_pctile.json  PE近5年分位(东财)
决策规则(全部门槛透明可审):
  RED   任一红旗(水源枯/分本金) → 回避
  BUY   股息率>=4.5% 且 盈利收益率>=7% 且 PE分位<50% 且 价格分位<60% 且 趋势非空头
  WAIT-CHEAP  PE分位<30%(估值便宜) 但 价格/趋势条件未齐 → 等回调价位
  WAIT-TREND  股息+盈利达标 但 PE分位>=70%(贵) → 等估值消化
  PASS  其余
"""


def decide(r, pe_pct):
    """r: 两轴dict; pe_pct: PE近5年分位(None=缺失,按50中位处理)。返回(动作, 理由, 买点价)。"""
    p = pe_pct if pe_pct is not None else 50.0
    grade = r.get("grade", "")
    price, yld = r.get("price"), r.get("yield_t") or 0
    ey = r.get("eyield") or 0
    trend = r.get("trend")
    pct52 = r.get("pct52") if r.get("pct52") is not None else 50
    year_line = r.get("year_line")
    np_yoy = r.get("np_yoy")
    red = "🚩" in grade

    if red:
        return ("回避", "红旗: 净利大幅下滑或派息超盈利, 分红水源不可持续", None)
    if yld >= 4.5 and ey >= 7 and p < 50 and pct52 < 60 and trend != "空头":
        # 边界带(2026-10-30固化): 净利YoY在-15%~-20%之间, 引擎买入但水源在恶化,
        # 不许裸输出"买入"——必须带⚠️并强制小仓提示, 防止人工警告被埋没
        if np_yoy is not None and -20 < np_yoy < -15:
            return ("买入⚠️边界", f"四维达标但净利YoY {np_yoy:+.1f}% 处边界带(-15%~-20%), "
                                 f"只许小仓试(≤总资金3%), 触-20%即转回避, 盯季报", None)
        return ("买入", f"股息{yld:.1f}%+盈利收益率{ey:.1f}%+PE分位{p:.0f}%+价格分位{pct52}%+{trend}", None)
    if p < 30 and (pct52 >= 60 or trend == "空头" or ey < 7):
        anchor = year_line if year_line else price
        return ("等回调", f"估值历史低位(PE分位{p:.0f}%)但价格/趋势未配合, 等回踩年线附近", anchor)
    if yld >= 4.5 and ey >= 7 and p >= 70:
        return ("等消化", f"两轴达标但PE分位{p:.0f}%(历史上{p:.0f}%时间之上), 估值已贵", None)
    if yld >= 4.5 and ey >= 7 and pct52 >= 85:
        return ("等回调", f"价格分位{pct52}%(一年高位), 等回撤", year_line)
    return ("观望", f"股息{yld:.1f}%/盈利收益率{ey:.1f}%, 两轴至少一轴不够硬", None)


def merge(two_axis_path, pe_path):
    import json
    with open(two_axis_path, encoding="utf-8") as f:
        rows = json.load(f)
    with open(pe_path, encoding="utf-8") as f:
        pe = {x["code"]: x for x in json.load(f)}
    out = []
    for r in rows:
        p = pe.get(r["code"], {})
        action, why, anchor = decide(r, p.get("pe_pct5y"))
        out.append({**r, "pe_now": p.get("pe_now"), "pe_pct5y": p.get("pe_pct5y"),
                    "action": action, "why": why, "buy_anchor": anchor})
    prio = {"买入": 0, "等回调": 1, "等消化": 2, "观望": 3, "回避": 4}
    out.sort(key=lambda x: (prio.get(x["action"], 9), -(x["yield_t"] or 0)))
    return out


def render(rows):
    lines = []
    lines.append(f"## 高股息决策表·48只 @ 2026-10-27（买入/等/回避，四维交叉）")
    lines.append("| 动作 | 代码 | 名称 | 现价 | 股息率 | 盈利收益率 | PE | PE分位 | 价格分位 | 趋势 | 买点锚 | 理由 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for x in rows:
        pe = f"{x['pe_now']}" if x.get("pe_now") else "—"
        pp = f"{x['pe_pct5y']:.0f}%" if x.get("pe_pct5y") is not None else "—"
        p52 = f"{x['pct52']}%" if x.get("pct52") is not None else "—"
        ey = f"{x['eyield']:.1f}%" if x.get("eyield") else "—"
        anchor = f"{x['buy_anchor']:.2f}" if x.get("buy_anchor") else "—"
        lines.append(f"| **{x['action']}** | {x['code']} | {x['name']} | {x['price']:.2f} | "
                     f"{x['yield_t']:.2f}% | {ey} | {pe} | {pp} | {p52} | {x['trend']} | {anchor} | {x['why']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    rows = merge(r"D:/Code/AH_analyse/tools/divi_two_axis.json",
                 r"D:/Code/AH_analyse/tools/divi_pe_pctile.json")
    print(render(rows))
    with open(r"D:/Code/AH_analyse/tools/divi_decision.json", "w", encoding="utf-8") as f:
        import json
        json.dump(rows, f, ensure_ascii=False, indent=1)
