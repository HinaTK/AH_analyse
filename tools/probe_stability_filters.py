# -*- coding: utf-8 -*-
"""全池检验: ADX斜率 / 量能确认 能否判别"全破→站回5日线"事件的真假站稳。

事件定义 (与此前一致): 前一日五线全破、当日收盘站回5日线。
事件结果: 后5日内收盘再次全破 = 假站稳; 否则 = 真站稳。
两个候选变量的取值 (事件日当日收盘可观察, 无前视):
  adx_slope2 = ADX(t) - ADX(t-2)   [2日斜率]
  adx_slope3 = ADX(t) - ADX(t-3)   [3日斜率]
  vol_ratio  = 当日成交量 / 前5日均量(不含当日)
判定方案:
  A2: adx_slope2 < 0 (动能衰竭) → 判真
  A3: adx_slope3 < 0 → 判真
  V1: vol_ratio > 1.0 (放量) → 判真
  V2: vol_ratio > 1.2 → 判真
  基准: 无条件 (全部判真) = 现行规则
对每个方案输出: 覆盖率(判真的比例)、真站稳召回、假站稳过滤率、延迟成本。
"""
import sys
from pathlib import Path
import json

sys.path.insert(0, 'D:/Code/AH_analyse')
sys.path.insert(0, 'D:/Code/AH_analyse/tools')
import pandas as pd
from tools.etf_research.entry_timing import prepare
from tools.market_phase_check import wilder_adx

BASE = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-research/20261026-200137-313253/bars')
result_j = json.load(open(BASE.parent / 'result.json', encoding='utf-8'))
covered = {x['code'] for x in result_j['ranking'] if x.get('has_all_four_windows')}


def adx_series_fast(daily, n=14):
    """一次性算整条 ADX 序列 (Wilder 递推, 与 wilder_adx 同算法但向量化推进)。"""
    h = daily['high'].to_numpy(float); l = daily['low'].to_numpy(float); c = daily['close'].to_numpy(float)
    m = len(daily)
    tr = [0.0]*m; pdm = [0.0]*m; ndm = [0.0]*m
    tr[0] = h[0]-l[0]
    for i in range(1, m):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        up = h[i]-h[i-1]; dn = l[i-1]-l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
    if m <= 2*n+2:
        return [None]*m
    atr = [0.0]*m; ps = [0.0]*m; ns = [0.0]*m
    atr[n] = sum(tr[1:n+1]); ps[n] = sum(pdm[1:n+1]); ns[n] = sum(ndm[1:n+1])
    for i in range(n+1, m):
        atr[i] = atr[i-1] - atr[i-1]/n + tr[i]
        ps[i] = ps[i-1] - ps[i-1]/n + pdm[i]
        ns[i] = ns[i-1] - ns[i-1]/n + ndm[i]
    dx = [0.0]*m
    for i in range(n, m):
        pv = 100*ps[i]/atr[i] if atr[i] else 0.0
        nv = 100*ns[i]/atr[i] if atr[i] else 0.0
        dx[i] = 100*abs(pv-nv)/(pv+nv) if (pv+nv) else 0.0
    adx = [None]*m
    first = 2*n
    if m > first:
        adx[first] = sum(dx[n:first+1])/(first+1-n)
        for i in range(first+1, m):
            adx[i] = (adx[i-1]*(n-1)+dx[i])/n
    return adx


records = []
for f in sorted(BASE.glob('*-m5.csv')):
    code = f.stem.replace('-m5', '')
    if code not in covered:
        continue
    df = pd.read_csv(f)
    df['date'] = df['time'].astype(str).str[:10]
    daily = df.groupby('date', as_index=False).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
        close=('close', 'last'), volume=('volume', 'sum'))
    if len(daily) < 90:
        continue
    daily = prepare(daily).reset_index(drop=True)
    # 均线
    for p in (5, 10, 20, 30, 60):
        daily[f'ma{p}'] = daily['close'].rolling(p).mean()
    daily['adx'] = adx_series_fast(daily)
    daily['vol5_prev'] = daily['volume'].rolling(5).mean().shift(1)

    dates = daily['date'].tolist()
    for i in range(70, len(daily)-6):
        row = daily.iloc[i]; prev = daily.iloc[i-1]
        if any(pd.isna(row[f'ma{p}']) or pd.isna(prev[f'ma{p}']) for p in (5, 10, 20, 30, 60)):
            continue
        bc_prev = sum(1 for p in (5, 10, 20, 30, 60) if prev['close'] < prev[f'ma{p}'])
        if bc_prev != 5:
            continue  # 前一日未全破
        if not row['close'] >= row['ma5']:
            continue  # 当日未站回5日线
        # 事件: 前1日全破, 当日站回。真假 = 后5日是否再全破
        future = daily.iloc[i+1:i+6]
        rebroke = False
        for j in range(len(future)):
            r = future.iloc[j]
            bc = sum(1 for p in (5, 10, 20, 30, 60) if r['close'] < r[f'ma{p}'])
            if bc == 5:
                rebroke = True
                break
        adx0 = row['adx']
        adx2 = daily.iloc[i-2]['adx'] if i >= 2 else None
        adx3 = daily.iloc[i-3]['adx'] if i >= 3 else None
        vr = row['volume']/row['vol5_prev'] if (row['vol5_prev'] and not pd.isna(row['vol5_prev']) and row['vol5_prev'] > 0) else None
        if adx0 is None or adx2 is None:
            continue
        records.append(dict(
            code=code, date=dates[i], true_stable=not rebroke,
            slope2=adx0-adx2, slope3=(adx0-adx3) if adx3 is not None else None,
            vol_ratio=vr,
        ))

rdf = pd.DataFrame(records)
n = len(rdf)
print(f"全池'前日全破→当日站回'事件: n={n}, 覆盖 {rdf['code'].nunique()} 只")
print(f"其中真站稳 {int(rdf['true_stable'].sum())} ({rdf['true_stable'].mean()*100:.0f}%), 假站稳 {int((~rdf['true_stable']).sum())} ({(~rdf['true_stable']).mean()*100:.0f}%)")
print()

def evaluate(mask_valid, mask_signal, name):
    """mask_signal=True 判真 (放行买入)。输出召回/过滤/覆盖。"""
    if mask_valid.sum() == 0:
        print(f"{name}: 无有效样本")
        return
    sub = rdf[mask_valid]
    sig = mask_signal[mask_valid]
    trues = sub['true_stable']
    recall = (sig & trues).sum() / trues.sum() if trues.sum() else float('nan')     # 真站稳里被放行的比例
    filter_fake = ((~sig) & (~trues)).sum() / (~trues).sum() if (~trues).sum() else float('nan')  # 假站稳里被拦的比例
    coverage = sig.mean()
    precision = trues[sig].mean() if sig.sum() else float('nan')  # 放行里真站稳比例
    print(f"{name:24s}: 放行率{coverage*100:5.1f}% | 真站稳召回{recall*100:5.1f}% | 假站稳过滤{(1-precision)*100:5.1f}% → 放行后假站稳占比 {(1-precision)*100:.1f}% (基准 { (~rdf['true_stable']).mean()*100:.1f}%)")

print("=== 方案2: ADX 斜率 (回落=衰竭→判真) ===")
evaluate(pd.Series([True]*n), rdf['slope2'] < 0, "A2: 2日斜率<0")
s3ok = rdf['slope3'].notna()
evaluate(s3ok, (rdf['slope3'] < 0).fillna(False), "A3: 3日斜率<0")
print()
print("=== 方案3: 量能确认 (放量→判真) ===")
vrok = rdf['vol_ratio'].notna()
evaluate(vrok, (rdf['vol_ratio'] > 1.0).fillna(False), "V1: 量比>1.0")
evaluate(vrok, (rdf['vol_ratio'] > 1.2).fillna(False), "V2: 量比>1.2")
evaluate(vrok, (rdf['vol_ratio'] > 1.5).fillna(False), "V3: 量比>1.5")
print()
print("=== 对照: 守前低 (道氏123条件②, 之前单票显示有判别力) ===")
# 需要当日low vs 前20日low — 重新算太贵, 用已有字段做不到; 留给专门跑
print("(另行全池跑)")
print()
print("=== 分桶看原始分布 (真/假站稳的变量分布是否分离) ===")
for col, label in [('slope2', 'ADX 2日斜率'), ('vol_ratio', '当日量/5日均量')]:
    t = rdf[rdf['true_stable']][col].dropna()
    f = rdf[~rdf['true_stable']][col].dropna()
    print(f"{label:16s}: 真站稳 均值{t.mean():+.2f} 中位{t.median():+.2f} | 假站稳 均值{f.mean():+.2f} 中位{f.median():+.2f} | 分离度(中位差/合并std) {(t.median()-f.median())/(pd.concat([t,f]).std()+1e-9):+.2f}")
