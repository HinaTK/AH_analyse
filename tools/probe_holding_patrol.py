# -*- coding: utf-8 -*-
"""持仓巡检模型全池回测: ER + ATR收敛 + 前窗口破位 (用户架构, 2026-10-28)。

对比三方:
  A. 现行五线门控 (收盘<ma5/10/20/30/60 全破 → 停新格买入)
  B. 新巡检模型: 停新格买入 = NOT(ER<0.35 AND ATR5<=ATR20 AND 未破前窗口低点)
     - ER(10日) = |C今-C十日前| / Σ|日变动|  (Kaufman效率比)
     - ATR5/ATR20 用20日TR均值(前窗口, 不含近5日)
     - 前窗口低点 = 5日前的20日最低 (防滚动窗口吞掉创新低)
  C. B的宽松版: 只看ER+ATR (不看破位)

评估口径 (持仓巡检的真实业务问题):
  1. 日级判定质量: 在"未来5日下跌>5%"的日子 (网格挨打日), 哪个模型在暂停?
     → 漏报率 = 深跌日仍在放行买入的比例
  2. 在"未来5日在区间内往返>3次"的日子 (网格赚钱日), 哪个在放行?
     → 误报率 = 赚钱日被暂停的比例
  3. 总体: 暂停天数占比 (策略可用性)
"""
import sys
from pathlib import Path
import json

sys.path.insert(0, 'D:/Code/AH_analyse')
sys.path.insert(0, 'D:/Code/AH_analyse/tools')
import pandas as pd
from tools.etf_research.entry_timing import prepare

BASE = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-research/20261026-200137-313253/bars')
result_j = json.load(open(BASE.parent / 'result.json', encoding='utf-8'))
covered = {x['code'] for x in result_j['ranking'] if x.get('has_all_four_windows')}

ER_WIN = 10
ER_TH = 0.35
FWD = 5

stats = dict(
    days=0, bad_days=0, good_days=0, flat_days=0,
    # 漏报: 未来5日跌>5% (网格挨打) 但模型放行买入
    miss_A=0, miss_B=0, miss_C=0,
    # 误报: 未来5日往返好 (网格赚钱) 但模型暂停
    falseA=0, falseB=0, falseC=0,
    # 暂停总日占比
    pauseA=0, pauseB=0, pauseC=0,
)

for f in sorted(BASE.glob('*-m5.csv')):
    code = f.stem.replace('-m5', '')
    if code not in covered:
        continue
    df = pd.read_csv(f)
    df['date'] = df['time'].astype(str).str[:10]
    daily = df.groupby('date', as_index=False).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'))
    if len(daily) < 100:
        continue
    daily = prepare(daily).reset_index(drop=True)
    c = daily['close']; h = daily['high']; l = daily['low']
    # 均线 (现行五线)
    for p in (5, 10, 20, 30, 60):
        daily[f'ma{p}'] = c.rolling(p).mean()
    # ATR 序列 (20日滚动均值)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr20 = tr.rolling(20).mean()
    atr5 = tr.rolling(5).mean()
    # 前窗口20日低点: 5日前的rolling(20).min() → low.shift(5).rolling(20).min()
    prior_low = l.shift(5).rolling(20).min()
    # ER: 滚动10日 |净位移|/总行程
    net = (c - c.shift(ER_WIN)).abs()
    path = c.diff().abs().rolling(ER_WIN).sum()
    er = (net / path).fillna(0.0)

    for i in range(75, len(daily) - FWD):
        row = daily.iloc[i]
        if any(pd.isna(row[f'ma{p}']) for p in (5, 10, 20, 30, 60)):
            continue
        if pd.isna(atr20.iloc[i]) or pd.isna(prior_low.iloc[i]):
            continue
        # A. 现行五线
        breakA = sum(1 for p in (5, 10, 20, 30, 60) if row['close'] < row[f'ma{p}']) == 5
        # B. 巡检完整版: 需要三条件全满足才继续网格
        ok_er = er.iloc[i] < ER_TH
        ok_atr = atr5.iloc[i] <= atr20.iloc[i]
        ok_range = row['low'] > prior_low.iloc[i]   # 当日低点未破前窗口低点
        contB = ok_er and ok_atr and ok_range
        # C. 巡检宽松版: 只看 ER+ATR
        contC = ok_er and ok_atr

        # 未来5日结果分类
        fwd = daily.iloc[i + 1:i + 1 + FWD]
        fwd_ret = (fwd['close'].iloc[-1] / row['close'] - 1) if len(fwd) == FWD else None
        if fwd_ret is None:
            continue
        # 网格赚钱日: 未来5日收盘价与今日收盘做1.5%往返的次数
        cycles = 0
        anchor = row['close']
        up = False
        last_cross = row['close']
        for fc in fwd['close']:
            if not up and fc >= last_cross * 1.015:
                cycles += 1; up = True; last_cross = fc
            elif up and fc <= last_cross * 0.985:
                cycles += 1; up = False; last_cross = fc
        stats['days'] += 1
        if fwd_ret < -0.05:
            stats['bad_days'] += 1
            stats['miss_A'] += (not breakA)
            stats['miss_B'] += contB
            stats['miss_C'] += contC
        elif cycles >= 3:
            stats['good_days'] += 1
            stats['falseA'] += breakA
            stats['falseB'] += (not contB)
            stats['falseC'] += (not contC)
        else:
            stats['flat_days'] += 1
        stats['pauseA'] += breakA
        stats['pauseB'] += (not contB)
        stats['pauseC'] += (not contC)

n = stats['days']
print(f"全池逐日判定: n={n} 天 (深跌日 {stats['bad_days']}, 网格好日 {stats['good_days']}, 平日 {stats['flat_days']})")
print()
print(f"{'模型':28s}{'暂停占比':>9s}{'深跌日漏报率':>13s}{'好日误报率':>11s}")
print(f"{'A 现行五线全破':26s}{stats['pauseA']/n*100:8.1f}%{stats['miss_A']/max(1,stats['bad_days'])*100:12.1f}%{stats['falseA']/max(1,stats['good_days'])*100:10.1f}%")
print(f"{'B 巡检完整版(ER+ATR+破位)':26s}{stats['pauseB']/n*100:8.1f}%{stats['miss_B']/max(1,stats['bad_days'])*100:12.1f}%{stats['falseB']/max(1,stats['good_days'])*100:10.1f}%")
print(f"{'C 巡检宽松版(ER+ATR)':26s}{stats['pauseC']/n*100:8.1f}%{stats['miss_C']/max(1,stats['bad_days'])*100:12.1f}%{stats['falseC']/max(1,stats['good_days'])*100:10.1f}%")
