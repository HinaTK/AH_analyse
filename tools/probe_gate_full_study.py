# -*- coding: utf-8 -*-
"""研究池全量 ADX 门控研究：321只ETF逐日回放 probe_only 状态，ADX梯度×后续收益。

设计（与 _probe_gate_study2 同口径，扩大样本）：
- 对每只ETF拉500根日K（东财主源+腾讯备用）
- 对每个交易日 i（70 <= i < n-10）：用截至当日数据跑 judge_entry
- 只统计 probe_only（收盘<60日线、破线1-4条）的样本日
- ADX 用生产 wilder_adx 截至当日值；记录破线数/方向/fwd5/fwd10
- 增量落盘：每完成一只 append 一行统计 + 全样本追加 CSV（断点可续）
输出 reports/_probe_gate_full.csv + 逐只进度日志
"""
import sys, json, time
sys.path.insert(0, '.')
sys.path.insert(0, 'tools')
from pathlib import Path
import pandas as pd
from tools.etf_research.entry_timing import judge_entry, prepare
from tools.etf_research.research import load_universe
import market_phase_check as mp

OUT = Path('reports/_probe_gate_full.csv')
STATE = Path('reports/_probe_gate_full_state.json')

def adx_at(hist_rows):
    try:
        r = mp.wilder_adx(hist_rows)
        return tuple(r) if r else (None, None, None)
    except Exception:
        return (None, None, None)

uni = json.loads(Path('reports/_universe_codes.json').read_text(encoding='utf-8'))
uni = [(c, n) for c, n in uni]
print(f'研究宇宙 {len(uni)} 只', flush=True)

# 断点续跑状态
done = set()
if STATE.exists():
    done = set(json.loads(STATE.read_text(encoding='utf-8')).get('done', []))

rows_all = []
if OUT.exists():
    rows_all = pd.read_csv(OUT, dtype={'code': str}).to_dict('records')

t0 = time.time()
for k, (code, name) in enumerate(uni):
    if code in done:
        continue
    secid = ('1.' if code.startswith('sh') else '0.') + code[-6:]
    try:
        raw = mp.fetch_kline(secid, lmt=500, klt='101')
        if len(raw) < 90:
            raise ValueError(f'bars {len(raw)} < 90')
    except Exception as e:
        print(f'[{k+1}/{len(uni)}] {code} {name} 取数失败 {type(e).__name__}', flush=True)
        done.add(code); STATE.write_text(json.dumps({'done': sorted(done)}), encoding='utf-8')
        continue
    df = prepare(pd.DataFrame(raw)).reset_index(drop=True)
    closes = df['close'].values
    n = len(df)
    got = 0
    # 每12根抽样一次判定（全量判定太慢：321只×430点×judge_entry(全序列prepare)不可行）
    # 抽样保持无前视，只是密度降低——统计口径不变
    for i in range(70, n - 10):
        if (i - 70) % 3 != 0:
            continue
        hist = df.iloc[:i + 1]
        try:
            judged = judge_entry(hist)
        except Exception:
            continue
        if judged['verdict'] != 'probe_only':
            continue
        ma = judged.get('ma') or {}
        below = sum(1 for p in (5, 10, 20, 30, 60) if closes[i] < ma.get(p, 1e9))
        adx_v, pdi_v, mdi_v = adx_at(hist[['high', 'low', 'close']].to_dict('records'))
        if adx_v is None:
            continue
        fwd5 = closes[min(i + 5, n - 1)] / closes[i] - 1
        fwd10 = closes[min(i + 10, n - 1)] / closes[i] - 1
        rows_all.append(dict(code=code, date=df['date'].iloc[i], below=below,
                             adx=round(adx_v, 2), down=mdi_v > pdi_v,
                             fwd5=round(fwd5 * 100, 3), fwd10=round(fwd10 * 100, 3)))
        got += 1
    done.add(code)
    STATE.write_text(json.dumps({'done': sorted(done)}), encoding='utf-8')
    pd.DataFrame(rows_all).to_csv(OUT, index=False, encoding='utf-8')
    if (k + 1) % 20 == 0 or k == len(uni) - 1:
        print(f'[{k+1}/{len(uni)}] {code} +{got} 累计{len(rows_all)} 用时{time.time()-t0:.0f}s', flush=True)

print(f'完成：{len(rows_all)} 个 probe_only 样本日，{len(done)} 只处理', flush=True)
