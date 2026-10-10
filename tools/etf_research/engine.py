"""Single simulation pipeline; both ranking views share these runs."""
from pathlib import Path
import json, math, urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
from .research import BASE,HOLDINGS,VERSION,load_universe,select_window,latest_session,get_model
DEFAULT_INPUT=Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-broad-20260923')
DEFAULT_OUTPUT=Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-research')
WINDOWS=['full','early','late','recent20']
WEIGHTS={'idle_net_per_avg_cost_pct':.35,'full_cycle_net_per_avg_cost_pct':.20,'recent20_cycle_net_per_avg_cost_pct':.15,'worst_half_efficiency_pct':.15,'max_down_corr_to_base':-.15}
URL='https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale=5&ma=no&datalen=10000'
def clean(value):
    if isinstance(value,dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [clean(v) for v in value]
    if isinstance(value,np.generic):value=value.item()
    if isinstance(value,float) and not math.isfinite(value):return None
    return value
def dump(value):return json.dumps(clean(value),ensure_ascii=False,allow_nan=False)
def validate(frame):
    f=frame.copy();f.time=pd.to_datetime(f.time).dt.strftime('%Y-%m-%d %H:%M:%S')
    cols=['open','high','low','close','volume']
    f[cols]=f[cols].apply(pd.to_numeric,errors='raise')
    if f.empty or f.time.duplicated().any() or not f.time.is_monotonic_increasing:raise ValueError('empty/duplicate/unsorted bars')
    if not np.isfinite(f[cols]).all().all() or (f[cols[:4]]<=0).any().any() or (f.volume<0).any():raise ValueError('invalid numeric bars')
    if ((f.high<f[['open','close']].max(axis=1)) | (f.low>f[['open','close']].min(axis=1)) | (f.high<f.low)).any():raise ValueError('invalid OHLC')
    return f
def fetch_bars(code):
    last=None
    for _ in range(3):
        try:
            request=urllib.request.Request(URL.format(code=code),headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(request,timeout=30) as response:rows=json.load(response)
            if not isinstance(rows,list) or not rows:raise ValueError('Sina empty response')
            return validate(pd.DataFrame(rows).rename(columns={'day':'time'}))
        except Exception as exc:last=exc
    raise ValueError(f'Sina refresh failed: {last}')
def metrics(pool,runs,traces,returns):
    daily=pd.DataFrame(returns);base_days={e['time'][:10] for b in BASE for e in traces.get(b,[]) if e['side']=='sell'};rows=[]
    for row in pool.itertuples():
        c=row.code;x=dict(code=c,name=row.name,holding=c in HOLDINGS,has_all_four_windows=all((c,w) in runs for w in WINDOWS))
        for w in WINDOWS:
            for k,v in runs.get((c,w),{}).items():x[f'{w}_{k}']=v
        sells=[e for e in traces.get(c,[]) if e['side']=='sell' and not e['initial']];idle=[e for e in sells if e['time'][:10] not in base_days]
        x.update(idle_cycle_net=sum(e['pnl'] for e in idle),idle_cycles=len(idle),idle_cycle_days=len({e['time'][:10] for e in idle}))
        x['idle_net_per_avg_cost_pct']=x['idle_cycle_net']/x['full_avg_cost']*100 if x.get('full_avg_cost') else np.nan
        corrs=[];downs=[]
        for b in BASE:
            corr=down=np.nan
            if c==b:corr=down=1.
            elif c in daily and b in daily:
                pair=daily[[c,b]].dropna();sub=pair[pair[b]<0]
                if len(pair)>2 and pair[c].std()>0 and pair[b].std()>0:corr=pair[c].corr(pair[b])
                if len(sub)>2 and sub[c].std()>0 and sub[b].std()>0:down=sub[c].corr(sub[b])
            x[f'corr_{b}']=corr;x[f'down_corr_{b}']=down;corrs.append(corr);downs.append(down)
        x['max_corr_to_base']=max(corrs) if all(math.isfinite(v) for v in corrs) else np.nan
        x['max_down_corr_to_base']=max(downs) if all(math.isfinite(v) for v in downs) else np.nan
        x['worst_half_efficiency_pct']=min(x.get('early_cycle_net_per_avg_cost_pct',np.nan),x.get('late_cycle_net_per_avg_cost_pct',np.nan))
        x['qualification']=bool(x['has_all_four_windows'] and c not in HOLDINGS and x.get('full_cycles',0)>=10 and all(x.get(f'{w}_cycles',0)>=2 for w in WINDOWS[1:]) and x['idle_cycle_days']>=3 and x['max_corr_to_base']<.8 and x['max_down_corr_to_base']<.8)
        rows.append(x)
    rank=pd.DataFrame(rows)
    for col in WEIGHTS:
        if col not in rank:rank[col]=np.nan
    valid=rank.has_all_four_windows & ~rank.holding & rank[list(WEIGHTS)].notna().all(axis=1)
    rank['score']=np.nan;rank.loc[valid,'score']=0.
    for col,w in WEIGHTS.items():rank.loc[valid,'score']+=abs(w)*rank.loc[valid,col].rank(pct=True,ascending=w>0)
    return rank.sort_values(['qualification','score','code'],ascending=[False,False,True],na_position='last').reset_index(drop=True)
def run_research(input_path=DEFAULT_INPUT,output_path=None,asof=None,sessions=63,offline=False,limit=None,workers=8,bars_dir=None):
    if sessions<20:raise ValueError('sessions must be >=20')
    asof=asof or latest_session();inp=Path(input_path);pool=load_universe(inp/'eligibility.csv');universe=len(pool)
    import hashlib
    reference=DEFAULT_INPUT/'eligibility.csv'
    production_pool=reference.is_file() and hashlib.sha256((inp/'eligibility.csv').read_bytes()).digest()==hashlib.sha256(reference.read_bytes()).digest()
    production_scope=bool(production_pool and sessions==63 and not offline and limit is None and asof==latest_session())
    if limit is not None:
        if limit<0:raise ValueError('negative limit')
        pool=pool[pool.code.isin(HOLDINGS)|pool.code.isin(pool[~pool.code.isin(HOLDINGS)].head(limit).code)].reset_index(drop=True)
    out=Path(output_path) if output_path else DEFAULT_OUTPUT/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    if out.resolve()==inp.resolve() or inp.resolve() in out.resolve().parents:raise ValueError('output cannot overwrite historical input')
    out.mkdir(parents=True,exist_ok=True);(out/'bars').mkdir(exist_ok=True)
    run_id=datetime.now().isoformat();errors=[];checks=[];data={};runs={};traces={};returns={}
    def progress(record):
        with (out/'progress.jsonl').open('a',encoding='utf-8') as f:f.write(dump(dict(run_id=run_id,**record))+'\n');f.flush()
    def save_errors():(out/'errors.json').write_text(dump(errors),encoding='utf-8')
    def acquire(c):
        old=(Path(bars_dir) if bars_dir else inp/'bars')/f'{c}-m5.csv'
        if offline:return validate(pd.read_csv(old)),None
        fresh=fetch_bars(c);last=fresh.time.iloc[-1]
        if old.exists():
            cached=validate(pd.read_csv(old));overlap=cached.merge(fresh,on='time',suffixes=('_old','_new'))
            if len(overlap) and ((overlap.close_old/overlap.close_new-1).abs()>.005).any():raise ValueError('cache overlap price-basis mismatch/ex-rights')
            fresh=pd.concat([cached,fresh]).drop_duplicates('time',keep='last').sort_values('time').reset_index(drop=True)
        return fresh,last
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures={executor.submit(acquire,c):c for c in pool.code}
        for future in as_completed(futures):
            c=futures[future]
            try:
                frame,last=future.result();data[c]=frame;frame.to_csv(out/'bars'/f'{c}-m5.csv',index=False)
                check=dict(code=c,bars=len(frame),first=frame.time.iloc[0],last=frame.time.iloc[-1],endpoint_last=last);checks.append(check);progress(dict(stage='fetch',**check))
            except Exception as exc:errors.append(dict(code=c,stage='fetch',error=str(exc)));progress(errors[-1]);save_errors()
    (out/'data-checks.json').write_text(dump(checks),encoding='utf-8')
    try:dates=select_window(data,asof,sessions)
    except Exception as exc:progress(dict(stage='fatal',error=str(exc)));save_errors();raise ValueError(f'baseline/window failure: {exc}') from exc
    model=get_model()
    for row in pool.itertuples():
        c=row.code
        try:
            if c not in data:raise ValueError('fetch unavailable')
            if not offline:
                last=next(x['endpoint_last'] for x in checks if x['code']==c)
                if last[:10]<asof:raise ValueError(f'stale endpoint last={last}')
            frame=data[c];frame=frame[frame.time.str[:10].isin(dates)].reset_index(drop=True);groups=frame.groupby(frame.time.str[:10])
            if sorted(groups.groups)!=dates or any(not g.time.iloc[-1].endswith('15:00:00') for _,g in groups):raise ValueError('incomplete common window')
            if any(len(g)<40 for _,g in groups):raise ValueError('insufficient intraday coverage')
            closes=groups.close.last();opens=groups.open.first()
            if ((opens/closes.shift(1)-1).abs()>.11).any():raise ValueError('possible ex-rights/abnormal overnight jump >11%')
            returns[c]=closes.pct_change();split=dates[len(dates)//2]
            windows={'full':frame,'early':frame[frame.time.str[:10]<split],'late':frame[frame.time.str[:10]>=split],'recent20':frame[frame.time.str[:10]>=dates[-20]]}
        except Exception as exc:
            for w in WINDOWS:errors.append(dict(code=c,window=w,stage='simulate',error=str(exc)));progress(errors[-1])
            save_errors();continue
        for w,f in windows.items():
            try:
                result=model.simulate(f,gap=.02,t0=False,slip=.0005,trace=w=='full')
                if w=='full':traces[c]=result.pop('events');result.pop('equity_curve')
                if abs(result['identity_error'])>1e-6:raise ValueError('identity error')
                result['cycle_net_per_avg_cost_pct']=result['cycle_net']/result['avg_cost']*100;runs[(c,w)]=result;progress(dict(stage='simulate',code=c,window=w,result=result))
            except Exception as exc:errors.append(dict(code=c,window=w,stage='simulate',error=str(exc)));progress(errors[-1]);save_errors()
    save_errors();failed=sum(e['stage']=='simulate' for e in errors);assert len(runs)+failed==len(pool)*4
    if any((b,w) not in runs for b in BASE for w in WINDOWS):raise ValueError('baseline simulation failure; inspect errors.json')
    rank=metrics(pool,runs,traces,returns);rank.to_csv(out/'ranking.csv',index=False)
    pd.DataFrame([dict(code=c,window=w,**v) for (c,w),v in runs.items()]).to_csv(out/'runs.csv',index=False)
    pd.DataFrame(returns).to_csv(out/'daily-returns.csv')
    rotation=rank[rank.has_all_four_windows & ~rank.holding & (rank.full_cycles>runs[(BASE[0],'full')]['cycles'])].sort_values(['full_cycles','full_cycle_net','full_cycle_net_per_avg_cost_pct','code'],ascending=[False,False,False,True])
    records=clean(rank.to_dict('records'));holdings={c:next(x for x in records if x['code']==c) for c in HOLDINGS}
    summary=dict(version=VERSION,run_at=run_id,asof=asof,window_start=dates[0],window_end=dates[-1],sessions=sessions,fee_minimum=1,universe_count=universe,attempted_assets=len(pool),rank_rows=len(rank),attempted_runs=len(pool)*4,successful_runs=len(runs),failed_runs=failed,fetch_errors=sum(e['stage']=='fetch' for e in errors),offline=offline,smoke=limit is not None,latest_claim=False,full_pool=limit is None,qualified=int(rank.qualification.sum()),eligibility_snapshot='20260923 historical eligibility; not newly discovered listed universe',scoring_weights=WEIGHTS,output_path=str(out))
    model_excluded=sum(e['stage']=='simulate' and e['error'] in ('initial orders exceed 1% first bar volume','price too high for board lot') for e in errors)
    summary.update(data_failed_runs=failed-model_excluded,model_excluded_runs=model_excluded)
    summary.update(production_pool=production_pool,production_scope=production_scope,latest_claim=production_scope and summary['data_failed_runs']==0 and summary['fetch_errors']==0)
    summary.update(rankable_rows=int(rank.has_all_four_windows.sum()),successful_assets=int(rank.has_all_four_windows.sum()),failed_assets=int((~rank.has_all_four_windows).sum()))
    result=clean(dict(summary=summary,ranking=records,rotation_ranking=rotation.to_dict('records'),rotation_top10=rotation.head(10).to_dict('records'),leader=None if rotation.empty else rotation.iloc[0].to_dict(),holdings=holdings,errors=errors))
    (out/'summary.json').write_text(dump(summary),encoding='utf-8');(out/'result.json').write_text(dump(result),encoding='utf-8');progress(dict(stage='complete',summary=summary))
    return result
