# -*- coding: utf-8 -*-
"""按 etf-analysis skill 框架分析 159866 日经ETF工银（含同指数竞品比较）。"""
import sys, math
sys.path.insert(0, 'D:/Hermes Agent CN Desktop/data/hermes-home/skills/@user_5d56ad01/etf-grid-screener/scripts')
from grid_tool import fetch_kline, fetch_nav

# A股市场主要日经225 ETF（同指数竞品）
CANDIDATES = {
    '159866': '日经ETF工银',
    '513880': '日经225ETF华安',
    '513520': '日经ETF易方达',
    '513000': '日经225ETF景顺?'
}

print("=" * 70)
print("Step 1-2: 同指数ETF比较（规模代理=成交额, 溢价, 流动性）")
print("=" * 70)

rows = []
for code, name in CANDIDATES.items():
    r = fetch_kline(code, 60)
    if not r:
        print(f"  {code} {name}: 数据不可得，剔除")
        continue
    d, o, c, h, l, v = r
    nav, nav_date = fetch_nav(code)
    # 成交额（v是手数, *100 股）
    amt20 = sum(v[-20+i]*c[-20+i] for i in range(20)) * 100 / 20
    amt5 = sum(v[-5+i]*c[-5+i] for i in range(5)) * 100 / 5
    prem = (c[-1]/nav - 1)*100 if nav else None
    cur = c[-1]
    ma20 = sum(c[-20:])/20
    ma60 = sum(c[-60:])/60
    # 年化波动率
    rets = [(c[i]/c[i-1]-1) for i in range(1, len(c))]
    mu = sum(rets)/len(rets)
    sd = (sum((x-mu)**2 for x in rets)/(len(rets)-1))**0.5
    ann_vol = sd*math.sqrt(244)*100
    below = sum(1 for x in c[-20:] if x < ma20)
    rows.append(dict(code=code, name=name, cur=cur, amt5=amt5, amt20=amt20,
                     prem=prem, nav_date=nav_date, ma20=ma20, ma60=ma60,
                     vol=ann_vol, below20=below))

print()
for r in rows:
    prem_s = f"{r['prem']:+.2f}%" if r['prem'] is not None else "N/A"
    # skill §2.4 阈值: 行业ETF > 2000万合格
    liq = "优" if r['amt20'] > 100e6 else "合格" if r['amt20'] > 20e6 else "差"
    # skill §5.2 QDII溢价警戒线
    if r['prem'] is None: prem_risk = "N/A"
    elif r['prem'] < 2: prem_risk = "正常(<2%)"
    elif r['prem'] < 5: prem_risk = "谨慎(2-5%)"
    else: prem_risk = "高危(>5%)"
    print(f"{r['code']} {r['name']}")
    print(f"  现价 {r['cur']:.3f} | 20日均额 {r['amt20']/1e4:.0f}万 (5日 {r['amt5']/1e4:.0f}万) 流动性[{liq}]")
    print(f"  溢价 {prem_s} [{prem_risk}] (净值日 {r['nav_date']})")
    print(f"  MA20 {r['ma20']:.3f} / MA60 {r['ma60']:.3f} | 现价vs MA20 {(r['cur']/r['ma20']-1)*100:+.1f}% | 近20日 {r['below20']}天低于MA20")
    print(f"  年化波动率 {r['vol']:.0f}%")
    print()

print("=" * 70)
print("Step 3: 综合评分（skill §3.1 etf_score 简化版，可得数据口径）")
print("=" * 70)
print("评分维度: 规模代理(30) 费率(25,需官方数据) 跟踪误差(30,需净值序列) 流动性(15)")
print("注意: 费率与跟踪误差数据本次未取官方披露，以下只按可得维度打分并明示缺口")
print()
for r in rows:
    # 规模得分代理: 用20日均成交额, 1亿=满分30
    s_scale = min(30, r['amt20']/1e8*30)
    # 流动性得分: 2000万=满分15
    s_liq = min(15, r['amt20']/2e7*15)
    # 溢价惩罚: 溢价>2%扣分
    s_prem = 0 if r['prem'] is None else max(0, 10 - abs(r['prem'])*5)
    avail = s_scale + s_liq + s_prem
    print(f"  {r['code']} {r['name']}: 规模代理 {s_scale:.1f}/30 + 流动性 {s_liq:.1f}/15 + 溢价健康 {s_prem:.1f}/10 = {avail:.1f}/55 (费率25+跟踪误差30未计)")

print()
print("=" * 70)
print("Step 4: 入场时机判定（结合 skill §5.2 QDII考量 + 用户既定三档方案）")
print("=" * 70)
r866 = [x for x in rows if x['code']=='159866'][0]
print(f"  现价 {r866['cur']:.3f}, 溢价 {r866['prem']:+.2f}%")
print(f"  第一档触发区 1.59-1.60: {'已进入' if r866['cur']<=1.60 else f'差 {(r866['cur']/1.60-1)*100:+.1f}%'}")
print(f"  提前触发区 1.60-1.62 (溢价<=0 条件{'满足' if r866['prem']<=0 else '不满足'}): {'在区内' if 1.60<=r866['cur']<=1.62 else '不在区内'}")
print(f"  趋势: 现价低于MA20 {(r866['cur']/r866['ma20']-1)*100:.1f}%, 近20日中 {r866['below20']} 天低于MA20 → 仍在下行通道")
