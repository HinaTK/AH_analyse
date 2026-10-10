import importlib
import pandas as pd
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

def bars(days):
    rows=[]
    for day in days:
        for hour in pd.date_range('2000-01-01 09:35','2000-01-01 11:30',freq='5min').strftime('%H:%M:%S').tolist()+pd.date_range('2000-01-01 13:05','2000-01-01 15:00',freq='5min').strftime('%H:%M:%S').tolist():
            rows.append(dict(time=f'{day} {hour}',open=1.,high=1.,low=1.,close=1.,volume=1e8))
    return pd.DataFrame(rows)

def test_closed_common_window_rejects_stale_baselines():
    r=module()
    data={c:bars(['2026-10-08','2026-10-09']) for c in r.BASE}
    assert r.select_window(data,'2026-10-09',2)==['2026-10-08','2026-10-09']
    with pytest.raises(ValueError,match='stale'):
        r.select_window(data,'2026-10-12',2)
    with pytest.raises(ValueError,match='insufficient'):
        r.select_window(data,'2026-10-09',63)
    assert r.latest_session(datetime(2026,10,10,12,tzinfo=ZoneInfo('Asia/Shanghai')))=='2026-10-09'


def test_model_preserves_constraints_and_changes_only_fee():
    r=module()
    model=r.get_model()
    assert model.fee(5000)==1
    assert model.fee(20000)==2
    d=bars(['2026-10-08','2026-10-09'])
    result=model.simulate(d,trace=True)
    assert abs(result['identity_error'])<1e-6
    assert result['t0'] is False
    assert result['min_cash']>=50000
    assert all(e['qty']%100==0 for e in result['events'])
    d.volume=100
    with pytest.raises(ValueError,match='volume'):
        model.simulate(d)

def test_offline_research_runs_four_windows_and_accounts_for_errors(tmp_path,monkeypatch):
    r=module()
    inp=tmp_path/'synthetic-input';inp.mkdir();(inp/'bars').mkdir()
    pd.DataFrame([dict(code=c,name=c,eligible=True) for c in [*r.HOLDINGS,'sh510050','sh510100']]).to_csv(inp/'eligibility.csv',index=False)
    days=pd.bdate_range('2026-06-30',periods=63).strftime('%Y-%m-%d').tolist()
    for code in [*r.HOLDINGS,'sh510050']:
        frame=bars(days)
        frame.to_csv(inp/'bars'/f'{code}-m5.csv',index=False)
    out=tmp_path/'synthetic-output'
    result=r.run_research(input_path=inp,output_path=out,offline=True,asof=days[-1])
    assert result['summary']['universe_count']==5
    assert result['summary']['attempted_runs']==20
    assert result['summary']['successful_runs']+result['summary']['failed_runs']==20
    assert result['summary']['rankable_rows']==4
    assert result['summary']['failed_assets']==1
    assert result['summary']['successful_assets']==4
    alt=r.run_research(input_path=inp,bars_dir=inp/'bars',output_path=tmp_path/'synthetic-alt',offline=True,asof=days[-1])
    assert alt['summary']['successful_assets']==4
    assert len(result['ranking'])==5
    assert set(result['holdings'])==set(r.HOLDINGS)
    assert result['summary']['latest_claim'] is False
    import json
    text=(out/'summary.json').read_text(encoding='utf-8')
    json.loads(text,parse_constant=lambda x: pytest.fail('invalid JSON constant'))
    assert len((out/'progress.jsonl').read_text().splitlines())>=5
    assert result['summary']['production_pool'] is False
    assert result['summary']['production_scope'] is False
    engine=importlib.import_module('tools.etf_research.engine')
    reference=tmp_path/'production-input';reference.mkdir()
    monkeypatch.setattr(engine,'DEFAULT_INPUT',reference)
    monkeypatch.setattr(engine,'latest_session',lambda:days[-1])
    # Online branches exercise the real engine with local bars, never network.
    def local_fetch(code):
        return engine.validate(pd.read_csv(inp/'bars'/f'{code}-m5.csv'))
    monkeypatch.setattr(engine,'fetch_bars',local_fetch)
    def online(label,**kwargs):
        return r.run_research(input_path=inp,output_path=tmp_path/label,asof=days[-1],**kwargs)['summary']
    missing=online('missing-reference')
    assert missing['full_pool'] and not missing['production_pool']
    assert not missing['production_scope'] and not missing['latest_claim']
    (reference/'eligibility.csv').write_bytes((inp/'eligibility.csv').read_bytes())
    failed=online('data-failed')
    assert failed['production_pool'] and failed['production_scope']
    assert failed['data_failed_runs']>0 and not failed['latest_claim']
    pd.DataFrame([dict(code=c,name=c,eligible=True) for c in [*r.HOLDINGS,'sh510050']]).to_csv(inp/'eligibility.csv',index=False)
    custom=online('custom-pool')
    assert custom['full_pool'] and not custom['production_pool']
    assert not custom['production_scope'] and not custom['latest_claim']
    (reference/'eligibility.csv').write_bytes((inp/'eligibility.csv').read_bytes())
    current=online('production-current')
    assert current['production_scope'] and current['latest_claim']
    short=online('short-window',sessions=20)
    assert not short['production_scope'] and not short['latest_claim']
    smoke=online('smoke',limit=1)
    assert not smoke['production_scope'] and not smoke['latest_claim']
    monkeypatch.setattr(engine,'latest_session',lambda:'2026-10-09')
    historical=online('historical')
    assert not historical['production_scope'] and not historical['latest_claim']


def test_weekly_single_call_versioned_streak_and_no_same_week_double_count(tmp_path):
    try: weekly=importlib.import_module('tools.etf_research.weekly')
    except ModuleNotFoundError: pytest.fail('weekly thin entry missing')
    r=module();calls=[]
    result={'summary':{'version':r.VERSION,'asof':'2026-10-09','full_pool':True,'offline':False,'production_scope':True,'window_start':'2026-07-01','window_end':'2026-10-09','successful_runs':1284,'failed_runs':0,'attempted_assets':321},'leader':{'code':'sh510050','full_cycles':30},'holdings':{c:{'full_cycles':10} for c in r.HOLDINGS},'ranking':[],'errors':[]}
    def runner(**kwargs):calls.append(kwargs);return result
    path=tmp_path/'state.json';path.write_text('{"version":"old-daily","consecutive_weeks":50}')
    one=weekly.run_weekly(state_path=path,research_runner=runner)
    assert len(calls)==1 and one['state']['consecutive_weeks']==1
    assert set(r.HOLDINGS).issubset(set(one['holdings']))
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['consecutive_weeks']==1
    result['summary']['asof']='2026-10-16'
    two=weekly.run_weekly(state_path=path,research_runner=runner)
    assert two['state']['review_due'] and two['state']['consecutive_weeks']==2
    assert two['state']['executable'] is False
    previous=path.read_text()
    # Validation cannot inherit a production streak, in either week.
    for offline,full_pool,scope in ((True,True,False),(False,False,False),(True,False,False),(False,True,False),(False,True,None)):
        for asof in ('2026-10-16','2026-10-23'):
            result['summary'].update(offline=offline,full_pool=full_pool,asof=asof)
            result['summary'].pop('production_scope',None)
            if scope is not None:result['summary']['production_scope']=scope
            validation=weekly.run_weekly(state_path=path,research_runner=runner)
            assert validation['state']['consecutive_weeks']==1
            assert validation['state']['review_due'] is False
            assert path.read_text()==previous
            assert '仅验证' in validation['report']
            assert '达到两周人工复核门槛。' not in validation['report']
    result['summary'].update(offline=False,full_pool=True,production_scope=True,asof='2026-10-23',failed_runs=4)
    degraded_two=weekly.run_weekly(state_path=path,research_runner=runner)
    assert degraded_two['state']['consecutive_weeks']>=2
    assert degraded_two['state']['review_due'] is False
    assert '达到两周人工复核门槛。' not in degraded_two['report']
    assert path.read_text()==previous
    result['summary']['failed_runs']=0
    result['summary']['asof']='2026-10-30'
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['consecutive_weeks']==1
    previous=path.read_text()
    result['summary']['failed_runs']=4;result['summary']['failed_assets']=1
    degraded=weekly.run_weekly(state_path=path,research_runner=runner)
    assert path.read_text()==previous
    assert not degraded['state']['review_due']
    assert '降级' in degraded['report']
    result['holdings'][r.BASE[0]]['full_cycle_net']=4038.9000000000005
    assert '4,038.90' in weekly.run_weekly(state_path=path,research_runner=runner)['report']

def test_window_does_not_skip_missing_baseline_session():
    r=module();days=['2026-10-08','2026-10-09','2026-10-13']
    with pytest.raises(ValueError,match='missing'):
        r.select_window({c:bars(days) for c in r.BASE},'2026-10-13',3)

def test_offline_intraday_gaps_are_rejected(tmp_path):
    r=module();inp=tmp_path/'synthetic-input';inp.mkdir();(inp/'bars').mkdir()
    pd.DataFrame([dict(code=c,name=c,eligible=True) for c in r.HOLDINGS]).to_csv(inp/'eligibility.csv',index=False)
    days=pd.bdate_range('2026-06-30',periods=63).strftime('%Y-%m-%d').tolist()
    for c in r.HOLDINGS:
        f=bars(days);f=f[f.time.str.endswith('15:00:00')];f.to_csv(inp/'bars'/f'{c}-m5.csv',index=False)
    with pytest.raises(ValueError,match='baseline simulation'):
        r.run_research(input_path=inp,output_path=tmp_path/'synthetic-output',offline=True,asof=days[-1])

def test_weekly_cli_weekend_guard():
    weekly=importlib.import_module('tools.etf_research.weekly')
    text=weekly.main([],now=datetime(2026,10,10,16,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert '休市' in text

def test_weekly_model_exclusions_allow_streak_only_on_same_coverage(tmp_path):
    weekly=importlib.import_module('tools.etf_research.weekly');r=module()
    result={'summary':{'version':r.VERSION,'asof':'2026-10-09','full_pool':True,'offline':False,'production_scope':True,'window_start':'2026-07-07','window_end':'2026-10-09','successful_runs':1185,'failed_runs':95,'data_failed_runs':0,'model_excluded_runs':95,'fetch_errors':0,'attempted_assets':321},'leader':{'code':'sh589120','full_cycles':38},'holdings':{c:{} for c in r.HOLDINGS},'ranking':[{'code':'sh589120','has_all_four_windows':True}],'errors':[]}
    def runner(**kwargs):return result
    path=tmp_path/'state.json'
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['consecutive_weeks']==1
    result['summary']['asof']='2026-10-16'
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['review_due']
    result['summary']['asof']='2026-10-23';result['ranking'].append({'code':'sh510050','has_all_four_windows':True})
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['consecutive_weeks']==1

def module():
    try:
        return importlib.import_module('tools.etf_research.research')
    except ModuleNotFoundError:
        raise AssertionError('versioned research entry is missing')

def test_universe_keeps_all_eligible_and_all_holdings(tmp_path):
    p=tmp_path/'eligibility.csv'
    pd.DataFrame([{'code':'sh510050','name':'ETF','eligible':True},{'code':'sz159992','name':'holding','eligible':False}]).to_csv(p,index=False)
    r=module()
    pool=r.load_universe(p)
    assert set(pool.code)=={'sh510050',*r.HOLDINGS}
    assert not pool.code.duplicated().any()
